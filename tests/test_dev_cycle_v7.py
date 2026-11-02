"""Real process validation of outbox, bounded maintenance and frozen release use."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts import dev_cycle as cycle
from scripts.dev_cycle_feedback import supplement_delta,check_plan
from scripts import dev_cycle_improvement as improvement
from scripts import dev_cycle_runtime as runtime
from tests import test_dev_cycle as fixtures


class AtomicReceiptTests(unittest.TestCase):
    def test_transient_windows_denial_retries_same_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'state.json';cycle.write(path,dict(status='before'))
            replace=runtime.os.replace;calls=[]
            def sharing(source,target):
                calls.append((Path(source),Path(source).read_bytes()))
                if len(calls)<3:
                    error=PermissionError('transient Windows sharing denial');error.winerror=5;raise error
                return replace(source,target)
            with patch.object(runtime.os,'replace',side_effect=sharing),patch.object(runtime.time,'sleep') as sleep:
                cycle.write(path,dict(status='after',text='原始证据'))
            self.assertEqual(cycle.read(path)['status'],'after')
            self.assertEqual(len(set(calls)),1)
            self.assertEqual(sleep.call_count,2)
            self.assertFalse(list(Path(folder).glob('*.tmp')))

    def test_permanent_denial_preserves_old_receipt_and_raises(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'state.json';cycle.write(path,dict(status='before'))
            error=PermissionError('persistent denial');error.winerror=5
            with patch.object(runtime.os,'replace',side_effect=error) as replace,patch.object(runtime.time,'sleep'):
                with self.assertRaises(PermissionError):cycle.write(path,dict(status='after'))
            self.assertEqual(replace.call_count,5)
            self.assertEqual(cycle.read(path)['status'],'before')
            self.assertEqual(len(list(Path(folder).glob('*.tmp'))),1)


class FeedbackTests(unittest.TestCase):
    setUp=fixtures.DevCycleTests.setUp
    init=fixtures.DevCycleTests.init
    run_cycle=fixtures.DevCycleTests.run_cycle

    def test_valid_scores_unchanged_when_209_extra_opinions_removed(self):
        contract=dict(criteria=[dict(id='AC-'+str(n))for n in range(1,4)])
        legal=[dict(criterion_id='AC-'+str(n),status='unknown'if n==2 else'pass',failure_type='evaluator'if n==2 else'none')for n in range(1,4)]
        old=dict(checks=legal+[dict(criterion_id='OM-'+str(n),status='pass',failure_type='none')for n in range(1,5)])
        delta=supplement_delta(contract,old,dict(checks=legal))
        self.assertFalse(delta['valid_score_changes']);self.assertEqual(len(delta['extra_opinions']),4)
        changed=json.loads(json.dumps(legal));changed[1].update(status='pass',failure_type='none')
        self.assertEqual(supplement_delta(contract,old,dict(checks=changed))['valid_score_changes'][0]['criterion_id'],'AC-2')
        ambiguous=dict(checks=legal+[dict(legal[0],status='fail',failure_type='implementation')])
        self.assertEqual(supplement_delta(contract,ambiguous,dict(checks=legal))['conflicting_scores'],['AC-1'])
        identical=dict(checks=legal+[dict(legal[1])])
        self.assertTrue(supplement_delta(contract,identical,dict(checks=changed))['valid_score_changes'])

    def test_invalid_extra_id_is_repaired_without_development_rework(self):
        base=fixtures.Agents()
        def actor(**kw):
            value=base(**kw)
            if kw['stage']=='verify':value['checks'].append(dict(value['checks'][0],criterion_id='OM-1'))
            return value
        state,_=self.run_cycle(actor)
        self.assertEqual(state['status'],'accepted',state)
        self.assertEqual(base.calls.count('develop'),1)
        self.assertEqual(base.calls.count('supplement'),1)
        delta=state['rounds'][0]['supplement_delta']
        self.assertFalse(delta['valid_score_changes']);self.assertEqual(delta['extra_opinions'][0]['criterion_id'],'OM-1')

    def test_runtime_is_pinned_and_detects_changes(self):
        self.init()
        target=improvement.runtime_target(self.task)
        self.assertNotEqual(target,Path(cycle.__file__).resolve())
        target.write_text('# changed','utf-8')
        with self.assertRaisesRegex(ValueError,'发生变化'):improvement.runtime_target(self.task)

    def test_plan_rejects_wrong_source_and_invented_contract_ids(self):
        draft=dict(criteria=[dict(id='AC-1')]);review=dict(criteria=[],omissions=[dict(criterion_id='OM-1')])
        plan=dict(draft_sha256=cycle.digest(draft),source_review_sha256=cycle.digest(review),items=[dict(opinion_id='OM-1',criterion_ids=['OM-1'])])
        with self.assertRaisesRegex(ValueError,'绑定现有'):check_plan(draft,review,plan)
        plan['draft_sha256']='wrong'
        with self.assertRaisesRegex(ValueError,'来源'):check_plan(draft,review,plan)

    def test_replayed_observations_do_not_fabricate_new_model_usage(self):
        self.init();runner=cycle.Cycle(self.task)
        runner.state['attempts']=[dict(stage='verify',round=0,directory='historic',status='completed',replayed=True)]
        self.assertEqual(runner.event_summary()['stages'][0]['status'],'historical_replay')
        self.assertIsNone(cycle.measure(runner.state)['reported_tokens'])
        self.assertEqual(cycle.measure(runner.state)['missing_usage_attempts'],[])

    def test_task_feedback_runs_plan_owner_without_resetting_budget(self):
        base=fixtures.Agents()
        def actor(**kw):
            value=base(**kw);stage=kw['stage'];payload=cycle.read(kw['record']/'packet.json')
            if stage=='verification_plan':
                if base.calls.count(stage)==2:
                    self.assertEqual(payload['source_review']['reason'],'Pending plan was rejected; use an observable result')
                    self.assertEqual(payload['previous_plans'][0]['items'][0]['expected'],'pending')
                    self.assertEqual(payload['reflection_followup']['action']['action'],'Replace pending with the concrete expected result')
                value['items'][0]['expected']='pending'if base.calls.count(stage)==1 else'answer is 1'
            if stage=='scope_review':
                plans=payload['verification_plan']
                if not plans:value.update(decision='revise',reason='Write a concrete expected result')
                elif plans[-1]['items'][0]['expected']=='pending':value.update(decision='revise',reason='Pending plan was rejected; use an observable result')
            if stage=='reflect'and base.calls.count(stage)==1:
                known=cycle.read(kw['record'].parent/'observation-index.json')['observations']
                value['proposals']=[dict(kind='task',owner='verification_plan',observation_ids=[known[0]['id']],action='Replace pending with the concrete expected result',expected_result='Plan can be independently reviewed',regression='Pending plan must be rejected')]
            return value
        contract=dict(status='ready',summary='answer',scope=['answer'],non_goals=[],constraints=[],questions=[],
            criteria=[dict(id='AC-01',requirement='answer is correct',verification='read')])
        result,_=self.run_cycle(actor,confirmed_contract=contract)
        self.assertEqual(result['status'],'accepted',result)
        self.assertEqual(result['reflection_followups'],1)
        self.assertEqual(base.calls.count('verification_plan'),2)
        self.assertEqual(result['launches'],len(base.calls))
        self.assertEqual(result['max_launches'],20)
        self.assertEqual(result['contract'],contract)

    def test_verifier_receives_prior_candidate_and_exact_evidence(self):
        base=fixtures.Agents(failures=1)
        result,_=self.run_cycle(base)
        reports=[payload for stage,payload,_ in base.payloads if stage=='verify']
        self.assertEqual(result['status'],'accepted',result)
        self.assertEqual(reports[0]['previous_verification'],[])
        previous=reports[1]['previous_verification']
        self.assertEqual(len(previous),1)
        self.assertNotEqual(previous[0]['candidate_sha'],reports[1]['candidate_sha'])
        self.assertTrue(Path(previous[0]['report_path']).is_file())
        self.assertEqual(previous[0]['checks'][0]['status'],'fail')
        self.assertTrue(Path(previous[0]['checks'][0]['evidence'][0]['path']).is_file())

    def test_missing_previous_report_is_a_handoff_fact(self):
        self.init();runner=cycle.Cycle(self.task)
        runner.state['rounds']=[dict(candidate_sha='prior',verification='missing-report')]
        handoff=runner.verification_handoff()
        self.assertTrue(handoff[0]['unavailable'])
        self.assertEqual(handoff[0]['candidate_sha'],'prior')
        self.assertIn('missing-report',handoff[0]['report_path'])

    def test_task_followup_skips_ineligible_owner_and_forwards_verify_action(self):
        base=fixtures.Agents(malicious='environment')
        action='Use the corrected isolated fixture and retain prior unknown evidence'
        def actor(**kw):
            value=base(**kw);stage=kw['stage'];payload=cycle.read(kw['record']/'packet.json')
            if stage=='reflect' and base.calls.count(stage)==1:
                known=cycle.read(kw['record'].parent/'observation-index.json')['observations']
                value['proposals']=[dict(kind='task',owner=owner,observation_ids=[known[0]['id']],
                    action=action,expected_result='Collect independent observations',regression='Preserve the original unknown report')
                    for owner in ['verification_plan','verify']]
            if stage=='verify' and base.calls.count(stage)==2:
                self.assertEqual(payload['reflection_followup']['owner'],'verify')
                self.assertEqual(payload['reflection_followup']['action']['action'],action)
                self.assertEqual(len(payload['reflection_followup']['task_actions']),2)
                self.assertEqual(payload['previous_verification'][0]['checks'][0]['status'],'unknown')
                value['checks'][0].update(status='pass',failure_type='none')
            return value
        result,_=self.run_cycle(actor)
        self.assertEqual(result['status'],'accepted',result)
        self.assertEqual(base.calls.count('develop'),1)
        self.assertEqual(base.calls.count('verify'),2)


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.bundle=self.root/'bundle';self.bundle.mkdir();(self.bundle/'scripts').mkdir();(self.bundle/'scripts/dev_cycle.py').write_text('VALUE=0\n','utf-8')
        self.env=self.root/'environment';self.env.mkdir()
        self.task=self.root/'task';self.task.mkdir()
        cycle.write(self.task/'state.json',dict(status='blocked'))
        self.raw=self.task/'raw.json';cycle.write(self.raw,dict(unchanged=True))
        self.initial=self.raw.read_bytes()
        self.validator=self.root/'validate.py'
        self.validator.write_text("""import json,pathlib,runpy,sys,os
candidate=pathlib.Path.cwd()
old=runpy.run_path(str(pathlib.Path(os.environ['DEV_CYCLE_BASELINE'])/'scripts/dev_cycle.py'))['VALUE']
new=runpy.run_path(str(candidate/'scripts/dev_cycle.py'))['VALUE']
pathlib.Path(sys.argv[1]).write_text(json.dumps(dict(status='pass'if old==0 and new==1 else'fail',failure_type='none'if old==0 and new==1 else'implementation',checks=[dict(name='baseline_red_candidate_green',passed=old==0 and new==1,failure_type='none'if old==0 and new==1 else'implementation',observed=True,criterion_ids=['AC-01'])])),encoding='utf-8')
""",'utf-8')
        plan=dict(argv=[sys.executable,str(self.validator),'{result}'],files={str(self.validator):hashlib.sha256(self.validator.read_bytes()).hexdigest()})
        self.policy=dict(root=str(self.root/'maintenance'),source_bundle=str(self.bundle),source_files=improvement.files(self.bundle),
            environment=str(self.env),max_jobs=1,max_revisions=2,max_cli=4,allowed_paths=['scripts/dev_cycle.py'],
            regression=dict(plan=plan,required_checks=['baseline_red_candidate_green']),comparison=dict(plan=plan,required_checks=['baseline_red_candidate_green']),
            canary=dict(plan=plan,required_checks=['baseline_red_candidate_green']))
        cycle.write(self.task/'improvement-candidates.json',dict(items=[dict(id='I-test',kind='workflow',owner='maintenance',
            observation_ids=['O-real'],action='Fix future workflow behavior',expected_result='VALUE=1',regression='baseline red',
            evidence_valid=True,evidence_index=[dict(path=str(self.raw),sha256=hashlib.sha256(self.initial).hexdigest())])]))
        self.calls=[]

    def actor(self,*,stage,cwd,record,**kwargs):
        self.calls.append(stage)
        (record/'events.jsonl').write_text(json.dumps(dict(type='thread.started',thread_id=stage))+ '\n'+json.dumps(dict(type='turn.completed',usage=dict(input_tokens=20,cached_input_tokens=5,output_tokens=2)))+'\n','utf-8')
        if stage=='develop':
            (cwd/'scripts/dev_cycle.py').write_text('VALUE=1\n','utf-8')
            return dict(status='ready',summary='fixed',changes=['scripts/dev_cycle.py'],tests=['host validates'],limitations=[])
        jobroot=record.parent
        proof=jobroot/'validation-1/regression/result.json'
        return dict(decision='pass',reason='real process red/green receipts',defects=[],evidence=[dict(path=str(proof),observation='passed')])

    def test_outbox_executes_validates_reviews_and_adopts_without_touching_task(self):
        before=(self.task/'state.json').read_bytes()
        result=improvement.dispatch(self.task,self.policy,self.actor)
        self.assertEqual(result[0]['status'],'adopted',result)
        self.assertEqual(self.calls,['develop','maintenance_review'])
        job=cycle.read(Path(result[0]['path']))
        self.assertTrue(Path(job['release']['validation']).is_dir())
        self.assertEqual(improvement.files(self.bundle),self.policy['source_files'])
        self.assertEqual(self.raw.read_bytes(),self.initial)
        self.assertEqual((self.task/'state.json').read_bytes(),before)
        improvement.dispatch(self.task,self.policy,self.actor)
        self.assertEqual(len(self.calls),2)
        metrics=cycle.read(Path(job['directory'])/'metrics.json')
        self.assertEqual(metrics['reported_tokens']['input_tokens'],40)

    def test_out_of_scope_change_never_adopts(self):
        def actor(**kw):
            result=self.actor(**kw)
            if kw['stage']=='develop':(kw['cwd']/'bypass.py').write_text('pass','utf-8')
            return result
        result=improvement.dispatch(self.task,self.policy,actor)
        self.assertEqual(result[0]['status'],'blocked')
        self.assertFalse((Path(self.policy['root'])/'active-release.json').exists())

    def test_failed_or_missing_comparison_cannot_adopt(self):
        self.policy['comparison']['required_checks']=['never_reported']
        result=improvement.dispatch(self.task,self.policy,self.actor)
        self.assertEqual(result[0]['status'],'exhausted')
        self.assertNotIn('maintenance_review',self.calls)
        self.assertFalse((Path(self.policy['root'])/'active-release.json').exists())

    def test_policy_change_cannot_refund_maintenance_quota(self):
        original=cycle.read(self.task/'improvement-candidates.json')['items'][0]
        improvement.dispatch(self.task,self.policy,self.actor)
        cycle.write(self.task/'improvement-candidates.json',dict(items=[dict(original,id='I-second',observation_ids=['O-second'])]))
        result=improvement.dispatch(self.task,self.policy,self.actor)
        self.assertEqual(result[0]['status'],'exhausted')
        self.assertEqual(len(self.calls),2)

    def test_no_evidence_never_launches_maintenance(self):
        data=cycle.read(self.task/'improvement-candidates.json');data['items'][0]['evidence_valid']=False;cycle.write(self.task/'improvement-candidates.json',data)
        result=improvement.dispatch(self.task,self.policy,self.actor)
        self.assertEqual(result[0]['status'],'needs_evidence');self.assertFalse(self.calls)


if __name__=='__main__':unittest.main()
