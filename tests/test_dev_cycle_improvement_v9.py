"""Maintenance trial selection, immutable receipts and duplicate observations."""
import copy
import hashlib
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from tests import test_dev_cycle_v7 as previous
from scripts import dev_cycle as cycle
from scripts import dev_cycle_improvement as improvement


class MaintenanceIntegrityTests(previous.MaintenanceTests):
    def adopted(self):
        outcomes=improvement.dispatch(self.task,self.policy,self.actor)
        self.assertEqual(outcomes[0]['status'],'adopted',outcomes)
        return cycle.read(Path(outcomes[0]['path']))

    def test_duplicate_observations_only_launch_one_job(self):
        report=cycle.read(self.task/'improvement-candidates.json')
        report['items'].append(dict(report['items'][0],id='I-alias',action='Same incident, other wording'))
        cycle.write(self.task/'improvement-candidates.json',report)
        def actor(**kw):
            if kw['stage']=='develop':self.assertIn('Same incident, other wording',kw['prompt'])
            return self.actor(**kw)
        result=improvement.dispatch(self.task,self.policy,actor)
        self.assertEqual([r['status']for r in result],['adopted','deduplicated'])
        self.assertEqual(self.calls,['develop','maintenance_review'])
        self.assertEqual(cycle.read(Path(result[0]['path']))['aliases'][0]['id'],'I-alias')
        cycle.write(self.task/'improvement-candidates.json',dict(items=[dict(report['items'][0],id='I-later')]))
        later=improvement.dispatch(self.task,self.policy,actor)
        self.assertEqual(later[0]['status'],'deduplicated')
        self.assertEqual(self.calls,['develop','maintenance_review'])

    def test_actual_canary_confirms_next_task_runtime(self):
        job=self.adopted();root=Path(self.policy['root'])
        self.assertEqual(cycle.read(root/'active-release.json')['status'],'trial')
        selected=improvement.selected_release(self.policy)
        self.assertEqual(selected,root/'releases'/job['release']['id']/'scripts/dev_cycle.py')
        confirmed=cycle.read(root/'active-release.json')
        self.assertEqual(confirmed['status'],'confirmed')
        self.assertTrue(confirmed['canary_seal'])
        self.assertEqual(improvement.selected_release(self.policy),selected)

    def test_unobserved_pass_cannot_adopt(self):
        fake=dict(status='pass',checks=[dict(name='baseline_red_candidate_green',passed=True,observed=False)])
        with patch.object(cycle,'execute_acceptance',return_value=fake):
            outcomes=improvement.dispatch(self.task,self.policy,self.actor)
        self.assertEqual(outcomes[0]['status'],'exhausted')
        self.assertNotIn('maintenance_review',self.calls)

    def test_review_receipt_tampering_is_rejected(self):
        job=self.adopted();review=Path(job['directory'])/'attempt-02-maintenance_review/result.json'
        data=cycle.read(review);data['decision']='blocked';cycle.write(review,data)
        with self.assertRaisesRegex(ValueError,'审查证据变化'):improvement.selected_release(self.policy)

    def test_foreign_policy_cannot_select_release(self):
        self.adopted();other=copy.deepcopy(self.policy);other['max_jobs']=2
        with self.assertRaisesRegex(ValueError,'策略身份'):improvement.selected_release(other)

    def test_source_evidence_tampering_is_rejected(self):
        self.adopted();self.raw.write_text('changed','utf-8')
        with self.assertRaisesRegex(ValueError,'审查证据变化'):improvement.selected_release(self.policy)

    def test_canary_failure_returns_baseline_and_preserves_adoption(self):
        canary=self.root/'canary-fail.py'
        canary.write_text("import json,pathlib,sys\npathlib.Path(sys.argv[1]).write_text(json.dumps(dict(status='fail',failure_type='implementation',checks=[dict(name='trial',passed=False,observed=True,failure_type='implementation',criterion_ids=['AC-01'])])))\n",'utf-8')
        self.policy['canary']=dict(plan=dict(argv=[sys.executable,str(canary),'{result}'],files={str(canary):hashlib.sha256(canary.read_bytes()).hexdigest()}),required_checks=['trial'])
        job=self.adopted();root=Path(self.policy['root'])
        self.assertIsNone(improvement.selected_release(self.policy))
        self.assertEqual(cycle.read(root/'active-release.json')['status'],'rolled_back')
        self.assertTrue((root/'adoptions'/(job['release']['id']+'.json')).exists())
        self.assertTrue((root/'release-events'/('rollback-'+job['release']['id']+'.json')).exists())
        self.assertIsNone(improvement.selected_release(self.policy))

    def test_modified_canary_receipt_invalidates_confirmation(self):
        job=self.adopted();improvement.selected_release(self.policy)
        receipt=Path(self.policy['root'])/'canary'/job['release']['id']/'result.json'
        receipt.write_text('{}','utf-8')
        with self.assertRaisesRegex(ValueError,'试用回执变化'):improvement.selected_release(self.policy)

    def test_validation_drops_inherited_source_namespace(self):
        with patch.dict(os.environ,{'DEV_CYCLE_SOURCE_ROOT':'old-source','DEV_CYCLE_IMPORT_LOG':'old-log','PYTHONHOME':'old-home','VIRTUAL_ENV':'old-venv'}):
            env=improvement.validation_environment(self.policy,self.bundle)
        self.assertEqual(env['DEV_CYCLE_SOURCE_ROOT'],str(self.bundle))
        self.assertEqual(env['PYTHONPATH'],str(self.bundle))
        for name in ['DEV_CYCLE_IMPORT_LOG','PYTHONHOME','VIRTUAL_ENV']:self.assertNotIn(name,env)

    def test_canary_cancellation_does_not_start_fallback(self):
        self.adopted()
        with patch.object(improvement,'execute_check',side_effect=InterruptedError('cancelled')):
            with self.assertRaises(InterruptedError):improvement.selected_release(self.policy)
        self.assertEqual(cycle.read(Path(self.policy['root'])/'active-release.json')['status'],'trial')

    def test_second_trial_regression_restores_prior_confirmed_release(self):
        validator=self.root/'version-check.py'
        validator.write_text("import json,pathlib,sys,runpy\nv=runpy.run_path('scripts/dev_cycle.py')['VALUE']\nok=v in (1,2) if sys.argv[2]=='regression' else v==1\npathlib.Path(sys.argv[1]).write_text(json.dumps(dict(status='pass'if ok else'fail',failure_type='none'if ok else'implementation',checks=[dict(name='version',passed=ok,observed=True,failure_type='none'if ok else'implementation',criterion_ids=['AC-01'])])))\n",'utf-8')
        digest=hashlib.sha256(validator.read_bytes()).hexdigest()
        for kind in ['regression','comparison','canary']:
            self.policy[kind]=dict(plan=dict(argv=[sys.executable,str(validator),'{result}','canary'if kind=='canary'else'regression'],files={str(validator):digest}),required_checks=['version'])
        self.policy['max_jobs']=2
        first=self.adopted();old=improvement.selected_release(self.policy)
        proposal=cycle.read(self.task/'improvement-candidates.json')['items'][0]
        cycle.write(self.task/'improvement-candidates.json',dict(items=[dict(proposal,id='I-second-version',observation_ids=['O-other'])]))
        def second_actor(**kw):
            result=self.actor(**kw)
            if kw['stage']=='develop':(kw['cwd']/'scripts/dev_cycle.py').write_text('VALUE=2\n','utf-8')
            return result
        outcome=improvement.dispatch(self.task,self.policy,second_actor)
        self.assertEqual(outcome[0]['status'],'adopted',outcome)
        self.assertEqual(improvement.selected_release(self.policy),old)
        active=cycle.read(Path(self.policy['root'])/'active-release.json')
        self.assertEqual(active['id'],first['release']['id'])
        self.assertEqual(active['status'],'confirmed')


if __name__=='__main__':unittest.main()
