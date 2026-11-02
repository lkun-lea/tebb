"""Recovery, objective delivery gates, and honest workflow-cost accounting."""
import json
from pathlib import Path
import unittest

from scripts.dev_cycle import Cycle, digest, git, initialize, read
from scripts.dev_cycle_acceptance import fingerprint
from scripts.dev_cycle_metrics import measure
from tests import test_dev_cycle as fixtures

Agents = fixtures.Agents


class V5Tests(unittest.TestCase):
    setUp = fixtures.DevCycleTests.setUp
    init = fixtures.DevCycleTests.init
    run_cycle = fixtures.DevCycleTests.run_cycle

    def contract(self):
        return dict(status='ready', summary='answer', scope=['answer'], non_goals=[], constraints=[],
                    questions=[], criteria=[dict(id='AC-01', requirement='correct answer', verification='read')])

    def plan(self, body):
        script = self.root/'objective.py'
        script.write_text(body, 'utf-8')
        return dict(argv=['{python}', str(script), '{result}'], files={str(script): fingerprint(script)})

    def test_confirmed_contract_refines_verification_without_rewriting_product(self):
        agent = Agents()
        def executor(**kwargs):
            value = agent(**kwargs)
            if kwargs['stage'] == 'scope_review' and agent.calls.count('scope_review') == 1:
                value.update(decision='revise', reason='Add observable boundary assertion in verification plan')
            return value
        contract = self.contract()
        result, _ = self.run_cycle(executor, confirmed_contract=contract)
        self.assertEqual(result['status'], 'accepted', result)
        self.assertEqual(result['contract'], contract)
        self.assertEqual(result['contract_sha256'], digest(contract))
        self.assertEqual(len(result['verification_plan']), 1)
        self.assertEqual(agent.calls[:4], ['scope_review', 'verification_plan', 'scope_review', 'develop'])
        self.assertFalse(any(x == 'requirements' for x in agent.calls))

    def test_objective_failure_returns_to_development_before_any_acceptance(self):
        plan = self.plan("import json,sys,pathlib\np=pathlib.Path('answer.txt').read_text()=='2'\npathlib.Path(sys.argv[1]).write_text(json.dumps(dict(status='pass' if p else 'fail',failure_type='none' if p else 'implementation',checks=[dict(name='answer_is_two',passed=p,failure_type='none' if p else 'implementation',observed=True,criterion_ids=['AC-01'])])))\n")
        result, agent = self.run_cycle(acceptance_plan=plan)
        self.assertEqual(result['status'], 'accepted', result)
        self.assertEqual(agent.calls.count('develop'), 2)
        self.assertEqual(agent.calls.count('supervise'), 1)
        self.assertEqual(agent.calls.count('diagnose'), 1)
        self.assertLess(agent.calls.index('diagnose'),agent.calls.index('develop',agent.calls.index('develop')+1))
        self.assertEqual(result['rounds'][0]['objective']['status'], 'fail')
        self.assertEqual(result['rounds'][1]['objective']['status'], 'pass')
        index = read(self.task/'observation-index.json')
        self.assertTrue(any(row['kind'] == 'objective_failure' for row in index['observations']))
        self.assertEqual(read(self.task/'metrics.json')['objective_rejections'], 1)
        self.assertEqual(read(self.task/'metrics.json')['repair_submissions'], 1)

    def test_objective_mutation_is_not_silently_adopted(self):
        plan = self.plan("import json,sys,pathlib\npathlib.Path(sys.argv[1]).write_text(json.dumps(dict(status='pass',failure_type='none',checks=[dict(name='fixture',passed=True,failure_type='none',observed=True,criterion_ids=['AC-01'])])))\n")
        agent = Agents()
        def executor(**kwargs):
            value = agent(**kwargs)
            if kwargs['stage'] == 'develop':
                (self.root/'objective.py').write_text('tampered', 'utf-8')
            return value
        result, _ = self.run_cycle(executor, acceptance_plan=plan)
        self.assertEqual(result['status'], 'blocked')
        self.assertFalse((self.task/'accepted.patch').exists())

    def test_environment_assessment_can_route_to_diagnosis_and_same_candidate_recheck(self):
        agent = Agents()
        def executor(**kwargs):
            if kwargs['stage'] == 'diagnose':
                packet = read(kwargs['record']/'packet.json')
                evidence = self.task/packet['context']['report']/'result.json'
                return dict(action='verify', binding=packet['diagnosis_binding'],failure_type='environment',confirmed=True,affected_checks=['AC-01'],reason='Original evidence identifies a fixture issue',
                    next_action='Recheck fixture using the recorded input',
                    evidence=[dict(path=str(evidence), observation='raw failed assessment')])
            value = agent(**kwargs)
            if kwargs['stage'] == 'verify' and agent.calls.count('verify') == 1:
                value['checks'][0].update(status='unknown', failure_type='environment')
            return value
        result, _ = self.run_cycle(executor)
        self.assertEqual(result['status'], 'accepted', result)
        self.assertEqual(agent.calls.count('develop'), 1)
        self.assertEqual(agent.calls.count('verify'), 2)
        self.assertEqual(result['round'], 1)
        self.assertEqual(len(result['recoveries']), 1)
        self.assertTrue((self.task/'review-1').is_dir())
        self.assertFalse((self.task/'review-1-retry-1').exists())
        self.assertEqual(len(result['rounds'][0]['verification_history']), 1)

    def test_reflection_failure_keeps_candidate_but_does_not_export_accepted_patch(self):
        agent = Agents()
        def executor(**kwargs):
            if kwargs['stage'] == 'reflect':
                self.assertFalse((self.task/'accepted.patch').exists())
                self.assertEqual(read(self.task/'state.json')['status'], 'finalizing')
                raise RuntimeError('fixture reflection failure')
            value=agent(**kwargs)
            if kwargs['stage']=='supervise':value['process_review']=dict(status='unknown',summary='Need failure reflection',findings=[])
            return value
        result, _ = self.run_cycle(executor)
        self.assertEqual(result['status'], 'blocked')
        self.assertIsNotNone(result['candidate_sha'])
        self.assertFalse((self.task/'accepted.patch').exists())

    def test_metrics_do_not_invent_usage_or_double_count_cached_and_reasoning_tokens(self):
        state = self.init()
        empty = measure(state)
        self.assertIsNone(empty['reported_tokens'])
        self.assertFalse(empty['usage_complete'])
        state['attempts'] = [dict(stage='develop', directory='a', status='completed', started=1, ended=2,
            usage=[dict(input_tokens=100, cached_input_tokens=80, output_tokens=20, reasoning_output_tokens=9)]),
            dict(stage='verify', directory='b', status='failed', started=2, ended=3, usage=[])]
        result = measure(state)
        self.assertEqual(result['uncached_input_tokens'], 20)
        self.assertEqual(result['reported_tokens']['output_tokens'], 20)
        self.assertEqual(result['missing_usage_attempts'], ['b'])
        self.assertIsNone(result['fees'])

    def test_reflection_proposal_is_not_reported_as_validated_improvement(self):
        agent = Agents()
        def executor(**kwargs):
            value = agent(**kwargs)
            if kwargs['stage']=='supervise':value['process_review']=dict(status='unknown',summary='Need further assessment',findings=[])
            if kwargs['stage'] == 'reflect':
                value.update(proposals=[dict(kind='workflow',owner='maintenance',observation_ids=[],action='Improve evidence reading',expected_result='Read actual evidence',regression='Replay original failure')], validation_plan=['Replay original failure'])
            return value
        result, _ = self.run_cycle(executor)
        item = read(self.task/'improvement-candidates.json')['items'][0]
        self.assertEqual(result['status'], 'accepted')
        self.assertEqual(item['status'], 'proposed')
        self.assertIsNone(item['comparison'])
        self.assertTrue(item['evidence_index'][0]['sha256'])

    def test_read_only_transport_exit_is_diagnosed_and_retried_with_shared_budget(self):
        agent = Agents()
        def executor(**kwargs):
            if kwargs['stage'] == 'diagnose':
                packet=read(kwargs['record']/'packet.json');context = packet['context']
                return dict(action='retry',binding=packet['diagnosis_binding'],failure_type='environment',confirmed=True,affected_checks=[],reason='Fixture process ended; source is unchanged',
                    next_action='Retry the recorded read-only stage once', evidence=[dict(
                        path=str(self.task/context['report']/'stderr.log'), observation='original transport event')])
            value = agent(**kwargs)
            if kwargs['stage'] == 'requirements' and agent.calls.count('requirements') == 1:
                (kwargs['record']/'stderr.log').write_text('fixture stream ended', 'utf-8')
                raise RuntimeError('Codex exit 1; fixture transport')
            return value
        result, _ = self.run_cycle(executor)
        self.assertEqual(result['status'], 'accepted', result)
        self.assertEqual(agent.calls.count('requirements'), 2)
        self.assertEqual(result['launches'], 7)
        self.assertEqual(result['attempts'][0]['status'], 'failed')
        self.assertEqual(result['recoveries'][0]['action'], 'retry')

    def test_transport_retry_cannot_hide_read_only_source_mutation(self):
        agent = Agents()
        def executor(**kwargs):
            value = agent(**kwargs)
            if kwargs['stage'] == 'requirements':
                (kwargs['cwd']/'answer.txt').write_text('unexpected write', 'utf-8')
                raise RuntimeError('Codex exit 1; fixture transport')
            return value
        result, _ = self.run_cycle(executor)
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(result['recoveries'], [])
        self.assertFalse((self.task/'accepted.patch').exists())

    def test_new_record_paths_do_not_count_as_recovery_progress(self):
        agent = Agents()
        def executor(**kwargs):
            if kwargs['stage'] == 'diagnose':
                packet=read(kwargs['record']/'packet.json');context = packet['context']
                return dict(action='verify',binding=packet['diagnosis_binding'],failure_type='environment',confirmed=True,affected_checks=['AC-01'],reason='same fixture issue', next_action='same recheck',
                    evidence=[dict(path=str(self.task/context['report']/'result.json'), observation='new path, same state')])
            value = agent(**kwargs)
            if kwargs['stage'] == 'verify':
                value['checks'][0].update(status='unknown', failure_type='environment')
            if kwargs['stage'] == 'supervise':
                value.update(decision='recover')
            return value
        result, _ = self.run_cycle(executor)
        self.assertEqual(result['status'], 'exhausted', result)
        self.assertEqual(len(result['recoveries']), 1)
        self.assertEqual(agent.calls.count('develop'), 1)
        self.assertEqual(agent.calls.count('verify'), 2)

    def test_session_counters_are_not_summed_again_after_resume(self):
        state = self.init()
        state['attempts'] = [dict(stage='develop',directory='a',status='completed',session='same',
            usage=[dict(input_tokens=100,cached_input_tokens=80,output_tokens=20)]),
            dict(stage='develop',directory='b',status='completed',session='same',
            usage=[dict(input_tokens=150,cached_input_tokens=110,output_tokens=35)]),
            dict(stage='verify',directory='c',status='completed',session='fresh',
            usage=[dict(input_tokens=30,cached_input_tokens=10,output_tokens=5)])]
        result = measure(state)
        self.assertEqual(result['reported_tokens']['input_tokens'], 180)
        self.assertEqual(result['reported_tokens']['output_tokens'], 40)
        self.assertEqual(result['uncached_input_tokens'], 60)
        self.assertEqual(result['phases'][1]['tokens']['input_tokens'], 50)
        self.assertTrue(result['usage_complete'])

    def test_live_or_incomplete_counters_cannot_claim_complete_usage(self):
        state = self.init()
        state['attempts'] = [dict(stage='develop',directory='a',status='completed',session='s',
            usage=[dict(input_tokens=100,cached_input_tokens=80,output_tokens=20)]),
            dict(stage='verify',directory='b',status='running',usage=[])]
        self.assertFalse(measure(state)['usage_complete'])
        state['attempts'][1].update(status='completed',usage=[dict(input_tokens=12)])
        self.assertFalse(measure(state)['usage_complete'])
        self.assertEqual(measure(state)['counter_anomalies'][0]['reason'], 'incomplete_token_fields')


if __name__ == '__main__':
    unittest.main()
