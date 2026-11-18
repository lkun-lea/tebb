import tempfile
from pathlib import Path
import unittest

from desk_companion.evaluation.golden_store import GoldenStore
from desk_companion.evaluation.batch_metrics import metrics,compare


class EvaluationCenterTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.store=GoldenStore(Path(temp.name)/'eval.sqlite3')

    def test_case_versions_and_frozen_standards(self):
        data=dict(id='failure_case',prompt='Return 7.',expected=7,split='development',source_failure='failed-call')
        a=self.store.save_case(data);b=self.store.save_case({**data,'expected':8})
        self.assertNotEqual(a['version'],b['version'])
        self.assertEqual(len([c for c in self.store.cases()if c['id']=='failure_case']),2)
        frozen=self.store.save_case({**data,'id':'frozen_case','split':'regression'})
        with self.assertRaises(ValueError):self.store.save_case({**data,'id':'frozen_case','split':'regression','expected':9})
        with self.assertRaises(ValueError):self.store.save_case({**data,'command':'send secrets'})
        self.assertEqual(frozen,self.store.save_case({**data,'id':'frozen_case','split':'regression'}))

    def test_mixed_outcomes_denominators_unknown_cost_and_comparison(self):
        outcomes=['success','false_success','failed','needs_input','skip','timed_out','cancelled','infrastructure_failure']
        planned=[dict(case_id=str(i),sample=1,weight=1)for i in range(9)]
        rows=[dict(case_id=str(i),sample=1,outcome=v,elapsed_ms=i*10,usage=None)for i,v in enumerate(outcomes)]
        summary=metrics(rows,planned)
        self.assertEqual(summary['success'],dict(numerator=1,denominator=9,rate=1/9))
        self.assertEqual(summary['attainment']['total_weight'],9)
        self.assertEqual(summary['false_success'],1)
        self.assertIsNone(summary['cost_cny']);self.assertIsNone(summary['latency']['p95_ms'])
        self.assertEqual(summary['usage']['input_tokens']['unknown_attempts'],9)
        a=dict(id='a',case_manifest_hash='frozen',judge_contract='fixed',planned=planned,results=rows)
        b=dict(id='b',case_manifest_hash='frozen',judge_contract='fixed',planned=planned,results=[{**r,'outcome':'success'}for r in rows])
        value=compare(a,b)
        self.assertEqual(value['changes'],dict(unchanged=2,improved=7))
        legacy={**a,'cases':[dict(criteria='reference_rubric')]}
        with self.assertRaises(ValueError):compare(legacy,{**b,'review_effort':'low'})
        self.assertEqual(compare(legacy,{**b,'review_effort':'provider_default'})['changes'],dict(unchanged=2,improved=7))
        with self.assertRaises(ValueError):compare(a,{**b,'case_manifest_hash':'changed-judge'})

    def test_original_batch_is_immutable_after_terminal_and_request_cannot_rebind(self):
        value=dict(id='batch',created=1,state='queued',manifest_hash='a',planned=[])
        self.assertTrue(self.store.create_batch(value,'request')[1])
        self.assertFalse(self.store.create_batch(value,'request')[1])
        with self.assertRaises(ValueError):self.store.create_batch({**value,'manifest_hash':'b'},'request')
        self.store.update('batch',state='completed',results=[])
        self.store.update('batch',state='running',results=[dict(outcome='success')])
        self.assertEqual(self.store.batch('batch')['state'],'completed')
        self.assertEqual(self.store.batch('batch')['results'],[])

    def test_reference_rubric_is_data_only_and_weighted_unknown_is_not_pass(self):
        value=self.store.save_case(dict(id='open_answer',prompt='Explain idempotence.',expected='Repeated execution has the same effect.',
            rubric=[dict(id='meaning',criterion='Explain the unchanged result.',weight=2)]))
        self.assertEqual(value['criteria'],'reference_rubric')
        from desk_companion.evaluation.agent_evals import evaluate
        self.assertEqual(evaluate(value['spec'],dict(state='succeeded',answer='anything',events=[]))[0],'incomplete')
        from desk_companion.evaluation.grading_contract import grading_contract
        self.assertNotEqual(grading_contract([value],{'id':'one'}),grading_contract([value],{'id':'two'}))
        self.assertNotEqual(grading_contract([value],{'id':'one'},review_effort='provider_default'),
                            grading_contract([value],{'id':'one'},review_effort='low'))
        calibration=next(c for c in self.store.cases()if c['criteria']=='reference_judge_calibration')
        self.assertEqual(grading_contract([calibration],review_effort='provider_default'),
                         grading_contract([calibration],review_effort='low'))
        plan=[dict(case_id='open_answer',sample=1,goals=value['spec']['rubric'])]
        unknown=metrics([dict(case_id='open_answer',sample=1,outcome='incomplete',goal_checks=[dict(id='meaning',passed=None)])],plan)
        self.assertEqual(unknown['attainment']['achieved_weight'],0)
        with self.assertRaises(ValueError):self.store.save_case(dict(id='bad_rubric',prompt='x',expected='x',rubric=[dict(id='x',criterion='x',weight=1,command='echo hi')]))

    def test_historical_first_output_is_not_relabelled_as_first_visible_text(self):
        result=metrics([dict(case_id='legacy',sample=1,outcome='success',model_observations=[dict(id='old',first_token_ms=10)])],[dict(case_id='legacy',sample=1)])
        self.assertIsNone(result['ttft']['p50_ms'])
        self.assertEqual(result['ttft']['unknown_model_calls'],1)

    def test_selected_model_policies_cover_candidate_and_judge_without_credentials(self):
        import json,sqlite3
        from contextlib import closing
        from unittest.mock import patch
        from desk_companion.evaluation.profile_snapshot import selected_policies,write_policies
        items=[dict(id=k,model=k,base_url='http://127.0.0.1:1',api_key='never-copy-me')for k in ('candidate','judge')]
        with patch('desk_companion.models.model_capacity.load',side_effect=lambda ident:dict(window=1000 if ident=='candidate'else 2000)),patch('desk_companion.models.model_generation.binding',return_value=dict(parameter='max_tokens')),patch('desk_companion.infrastructure.state.model_price_snapshot',return_value=dict(input_cny_per_mtok=1,output_cny_per_mtok=2)):
            snapshot=selected_policies(items)
        self.assertEqual(snapshot['capacities']['judge']['window'],2000)
        self.assertNotIn('never-copy-me',json.dumps(snapshot))
        write_policies(self.store.profile,snapshot)
        self.assertEqual(json.loads((self.store.profile/'model-capacity.json').read_text('utf-8')),snapshot['capacities'])
        with closing(sqlite3.connect(self.store.profile/'memory/model_generation.sqlite3'))as db:self.assertEqual(db.execute('SELECT count(*) FROM bindings').fetchone()[0],2)
