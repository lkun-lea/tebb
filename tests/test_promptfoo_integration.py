import importlib.util
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from desk_companion.evaluation.evaluation_center import EvaluationCenter


class PromptfooIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.package=Path('desk_companion/evaluation/promptfoo')
        if not (cls.package/'node_modules/promptfoo/package.json').is_file():raise unittest.SkipTest('Install pinned Promptfoo to run local framework integration.')

    def test_actual_framework_product_tasks_fixed_judge_and_restart_query(self):
        with tempfile.TemporaryDirectory()as folder,patch.dict(os.environ,DESK_COMPANION_DATA_DIR=folder):
            center=EvaluationCenter();catalog=center.store.cases()
            cases=[next(c['version']for c in catalog if c['id']==ident)for ident in ('extract_record','sort_unique','pi_tools_discovery')]
            batch=center.start('framework-product-001',cases,timeout=30)['batch']
            self.assertEqual(batch['metrics']['planned'],3)
            self.assertIn('success',batch['metrics'])
            reused=center.start('framework-product-001',cases,timeout=30)
            self.assertTrue(reused['reused']);self.assertEqual(reused['batch']['id'],batch['id'])
            deadline=time.monotonic()+90
            while True:
                result=center.get(batch['id'])['batch']
                if result['state']not in{'queued','running','cancelling'}:break
                if time.monotonic()>deadline:center.cancel(batch['id']);self.fail('Pinned evaluation did not settle.')
                time.sleep(.2)
            log=(center.directory/batch['id']/'framework.log').read_text('utf-8')
            self.assertEqual(result['state'],'completed',log)
            self.assertEqual(result['metrics']['success']['numerator'],3)
            self.assertTrue(all(r.get('task_id')and r.get('call_ids')and r['call_evidence_complete']for r in result['results']))
            framework=json.loads((center.directory/batch['id']/'framework.json').read_text('utf-8'))
            self.assertEqual(framework['stats']['successes'],3);self.assertEqual(framework['stats']['errors'],0)
            self.assertEqual(framework['tebb']['frameworkNetwork']['connected'],0)
            self.assertGreaterEqual(framework['tebb']['frameworkNetwork']['blocked_attempts'],1)
            self.assertTrue(all(r['gradingResult']['pass']for r in framework['results']))
            graph=center.trace(batch['id'],'pi_tools_discovery',1)
            self.assertGreater(len(graph['nodes']),3)
            tool=next(n for n in graph['nodes']if n.get('tool')=='project_fixture_check'and n['kind']=='tool')
            self.assertEqual(tool['state'],'returned')
            actual=next(r for r in result['results']if r['case_id']=='pi_tools_discovery')
            detail=center.debug_call(batch['id'],'pi_tools_discovery',1,actual['call_ids'][0])
            self.assertTrue(detail['redacted'])
            self.assertNotIn('github_fixture_unused',[t['function']['name']for t in detail['request'].get('tools',[])])
            with self.assertRaises(ValueError):center.debug_call(batch['id'],'pi_tools_discovery',1,'f'*32)
            restarted=EvaluationCenter().get(batch['id'])['batch']
            self.assertEqual(result['results'],restarted['results'])
            for profile in (center.directory/batch['id']).glob('attempt-*/private-profile'):
                self.assertFalse((profile/'models.json').exists())
                self.assertFalse((profile/'model-network.json').exists())

    def test_fixed_assertion_calibration_rejects_false_success_and_unknown(self):
        spec=importlib.util.spec_from_file_location('fixed_promptfoo_provider',self.package/'provider.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        for outcome in ('false_success','failed','unknown','timed_out','cancelled'):
            result=module.get_assert(json.dumps(dict(outcome=outcome)),{})
            self.assertFalse(result['pass']);self.assertEqual(result['score'],0)
        self.assertTrue(module.get_assert(json.dumps(dict(outcome='success')), {})['pass'])

    def test_reviewer_calibration_retains_real_operations_calls_and_expected_rejection(self):
        with tempfile.TemporaryDirectory()as folder,patch.dict(os.environ,DESK_COMPANION_DATA_DIR=folder):
            center=EvaluationCenter();catalog=center.store.cases()
            cases=[c['version']for c in catalog if c['criteria']=='reference_judge_calibration']
            self.assertEqual(len(cases),5)
            batch=center.start('reviewer-calibration-001',cases,timeout=30)['batch']
            deadline=time.monotonic()+100
            while True:
                result=center.get(batch['id'])['batch']
                if result['state']not in{'queued','running','cancelling'}:break
                if time.monotonic()>deadline:center.cancel(batch['id']);self.fail('Reviewer calibration did not settle.')
                time.sleep(.2)
            log=(center.directory/batch['id']/'framework.log').read_text('utf-8')
            self.assertEqual(result['state'],'completed',log)
            self.assertEqual(result['metrics']['success']['numerator'],5,result['results'])
            for row in result['results']:
                self.assertEqual(row['execution_kind'],'component_operation')
                self.assertEqual(row['task_budget']['status'],'finished')
                self.assertEqual(len(row['call_ids']),1)
                self.assertTrue(row['call_evidence_complete'])
                self.assertTrue(row['evidence']['verified'])
                self.assertNotIn('termination',row)
                graph=center.trace(batch['id'],row['case_id'])
                self.assertTrue(any(n['kind']=='model'for n in graph['nodes']))
                root=next(n for n in graph['nodes']if n['id']==graph['root'])
                self.assertEqual(root['kind'],'operation');self.assertEqual(root['state'],'unknown')
                detail=center.debug_call(batch['id'],row['case_id'],1,row['call_ids'][0])
                self.assertTrue(detail['redacted'])
            rejected=next(r for r in result['results']if r['case_id']=='judge_reject_wrong_total')
            self.assertFalse(rejected['evidence']['candidate_accepted'])
            for report in (center.directory/batch['id']).glob('attempt-*/report.json'):
                totals=json.loads(report.read_text('utf-8'))['totals']
                self.assertEqual(totals['tasks'],0);self.assertEqual(totals['component_operations'],1)
            self.assertFalse(list((center.directory/batch['id']).glob('attempt-*/private-profile/models.json')))

    def test_recorded_failure_to_frozen_reference_case_and_strategy_comparison(self):
        with tempfile.TemporaryDirectory()as folder,patch.dict(os.environ,DESK_COMPANION_DATA_DIR=folder):
            from desk_companion.observability.tool_monitor import ToolRequest,ToolMonitor
            from desk_companion.observability.usage_observer import invoke_tool
            with ToolRequest('project_fixture_check',metadata=dict(root='operation:source-failure',task='fixture')):
                invoke_tool('project_fixture_check',lambda:dict(ok=False,error='private fixture failure'))
            failure=next(e for e in ToolMonitor().events()if e['phase']=='outcome')
            center=EvaluationCenter();draft=center.operate('draft_failure',dict(event_id=failure['id']))['draft']
            case=center.store.save_case({**draft,'prompt':'Explain idempotence using only supplied data.','expected':'Repeated execution has the same effect.',
                'rubric':[dict(id='correct',criterion='Explain unchanged effect, allowing equivalent wording.',weight=2)],'split':'regression'})
            settled=[]
            for strategy in ('eager','demand'):
                batch=center.start('failure-closure-'+strategy,[case['version']],tool_loading=strategy,timeout=30)['batch']
                deadline=time.monotonic()+60
                while True:
                    result=center.get(batch['id'])['batch']
                    if result['state']not in{'queued','running','cancelling'}:break
                    if time.monotonic()>deadline:center.cancel(batch['id']);self.fail('Failure closure did not settle.')
                    time.sleep(.2)
                log=(center.directory/batch['id']/'framework.log').read_text('utf-8')
                self.assertEqual(result['state'],'completed',log)
                self.assertEqual(result['results'][0]['outcome'],'success',result['results'])
                row=result['results'][0];self.assertTrue(row['judge']['calls_budgeted']);self.assertFalse(row['judge']['tools_allowed'])
                self.assertEqual(row['judge']['model_id'],'eval-fixture')
                graph=center.trace(batch['id'],case['id'])
                self.assertTrue(any(e['relation']=='independent_evaluation'for e in graph['edges']))
                self.assertEqual(result['metrics']['attainment']['achieved_weight'],2)
                settled.append(result)
            compared=center.operate('compare',dict(baseline=settled[0]['id'],candidate=settled[1]['id']))
            self.assertEqual(compared['changes'],dict(unchanged=1))
            self.assertIn('tool_loading',compared['configuration_changes'])
            self.assertEqual(ToolMonitor().get_event(failure['id'])['state'],'failed')
            self.assertEqual(next(c for c in center.store.cases()if c['id']==case['id'])['source_evidence']['id'],failure['id'])

    def test_cancel_uses_product_owner_and_retains_unstarted_plan(self):
        with tempfile.TemporaryDirectory()as folder,patch.dict(os.environ,DESK_COMPANION_DATA_DIR=folder):
            center=EvaluationCenter();catalog=center.store.cases()
            cases=[next(c['version']for c in catalog if c['id']==ident)for ident in ('extract_record','sort_unique')]
            batch=center.start('framework-cancel-001',cases,timeout=30)['batch'];deadline=time.monotonic()+60
            while True:
                current=center.get(batch['id'])['batch']
                if any(r.get('task_id')for r in current['results']):break
                if current['state']not in{'queued','running'}or time.monotonic()>deadline:
                    center.cancel(batch['id']);self.fail('Product task did not reach observable progress.')
                time.sleep(.05)
            center.cancel(batch['id']);deadline=time.monotonic()+30
            while True:
                current=center.get(batch['id'])['batch']
                if current['state']not in{'running','cancelling','queued'}:break
                if time.monotonic()>deadline:self.fail('Cancellation did not settle.')
                time.sleep(.1)
            self.assertEqual(current['state'],'cancelled')
            self.assertEqual(current['metrics']['planned'],2)
            self.assertEqual(current['metrics']['success']['numerator'],0)
            self.assertGreaterEqual(current['metrics']['outcomes'].get('not_started',0),1)
            self.assertFalse(any(r.get('outcome')=='running'for r in current['results']))
            self.assertFalse(list((center.directory/batch['id']).glob('attempt-*/private-profile/models.json')))
