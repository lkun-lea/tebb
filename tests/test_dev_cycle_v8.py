"""Failure attribution, independently reviewed oracle revisions and sealed evidence reuse."""
import json
import os
from pathlib import Path
import unittest

from scripts import dev_cycle as cycle
from scripts.dev_cycle_acceptance import fingerprint
from scripts.dev_cycle_acceptance import prepare_revision,revised_plan
from tests import test_dev_cycle as fixtures


RUNNER = '''import json,pathlib,sys
from oracle import linked
result=pathlib.Path(sys.argv[1]);counter=pathlib.Path(sys.argv[2])
counter.write_text(str(int(counter.read_text())+1)if counter.exists()else'1')
event={'local_id':'event-1'}
item={'id':'item-1','schedules':{'events':[event]}}
passed=bool(linked(event,item))
(result.parent/'observed.json').write_text(json.dumps(dict(event=event,item=item,linked=passed)))
result.write_text(json.dumps(dict(status='pass'if passed else'fail',failure_type='none'if passed else'implementation',
 checks=[dict(name='saved_event_link',passed=passed,observed=True,failure_type='none'if passed else'implementation',criterion_ids=['AC-01'])],summary='Association observed in the controlled fixture')))
'''

CALIBRATE = '''import json,pathlib,sys
from oracle import linked
event={'local_id':'event-1'}
values=dict(positive_linked=bool(linked(event,{'id':'item-1','schedules':{'events':[event]}})),
 negative_missing=not linked(event,{'id':'item-1','schedules':{'events':[]}}),
 negative_wrong=not linked(event,{'id':'other','schedules':{'events':[{'local_id':'event-2'}]}}))
passed=all(values.values());result=pathlib.Path(sys.argv[1])
(result.parent/'controls.json').write_text(json.dumps(values))
result.write_text(json.dumps(dict(status='pass'if passed else'fail',failure_type='none'if passed else'evaluator',
 checks=[dict(name=name,passed=bool(value),observed=True,failure_type='none'if value else'evaluator',criterion_ids=['AC-01'])for name,value in values.items()],summary='Frozen positive and missing/wrong-link negative controls')))
'''

CORRECT = "def linked(event,item):\n return any(row['local_id']==event['local_id']for row in item['schedules']['events'])\n"
WRONG = "def linked(event,item):\n return event.get('item_id')==item['id']\n"


class RevisionAgent(fixtures.Agents):
    def __init__(self, *, weak=False, mutate_control=False, review='pass', force_repair=False):
        super().__init__();self.weak=weak;self.mutate_control=mutate_control;self.review=review;self.force_repair=force_repair

    def __call__(self, **kw):
        stage=kw['stage'];payload=cycle.read(kw['record']/'packet.json')
        if stage in {'evaluator_repair','evaluator_review','diagnose'}:
            self.calls.append(stage);self.payloads.append((stage,payload,kw['cwd']))
            evidence=kw['record']/'evidence';evidence.mkdir()
            proof=evidence/'observation.txt';proof.write_text('Read the actual fixture data and frozen controls.','utf-8')
            rows=[dict(path=str(proof),observation='The event link exists in item.schedules; the old oracle reads an absent field')]
            if stage=='diagnose':
                failed_calibration=payload['context']['stage']=='evaluator_calibration'
                return dict(action='blocked'if failed_calibration else'repair'if self.force_repair else'revise_evaluator',
                    binding=payload['diagnosis_binding'],failure_type='implementation'if self.force_repair else'evaluator',
                    confirmed=True,affected_checks=['AC-01'],reason='Observed oracle mismatch',next_action='Correct the association predicate',evidence=rows)
            if stage=='evaluator_repair':
                (kw['cwd']/'oracle.py').write_text('def linked(event,item):\n return True\n'if self.weak else CORRECT,'utf-8')
                if self.mutate_control:(kw['cwd']/'calibrate.py').write_text('print("weakened")','utf-8')
                return dict(status='ready',summary='Predicate repaired',changes=['oracle.py'],tests=[],limitations=[])
            return dict(decision=self.review,reason='Original requirement retained; missing/wrong links remain rejected',defects=[],evidence=rows)
        result=super().__call__(**kw)
        if stage=='verify'and payload.get('controller_test_receipt',{}).get('status')!='pass':
            result['checks'][0].update(status='unknown',failure_type='evaluator')
        return result


class V8Tests(unittest.TestCase):
    setUp=fixtures.DevCycleTests.setUp
    init=fixtures.DevCycleTests.init
    run_cycle=fixtures.DevCycleTests.run_cycle

    def plan(self):
        root=self.root/'validator';root.mkdir()
        for name,text in [('oracle.py',WRONG),('runner.py',RUNNER),('calibrate.py',CALIBRATE)]:
            (root/name).write_text(text,'utf-8')
        return dict(argv=['{python}','{validator}/runner.py','{result}',str(self.root/'invocations.txt')],
            files={str(p):fingerprint(p)for p in root.iterdir()},revision_policy=dict(root=str(root),editable=['oracle.py'],
                calibration_argv=['{python}','{validator}/calibrate.py','{result}'],
                required_controls=['positive_linked','negative_missing','negative_wrong']))

    def test_192_dispute_revises_oracle_on_same_candidate_without_product_rework(self):
        plan=self.plan();old=Path(plan['revision_policy']['root'])/'oracle.py';old_bytes=old.read_bytes()
        result,agent=self.run_cycle(RevisionAgent(),acceptance_plan=plan)
        self.assertEqual(result['status'],'accepted',result)
        self.assertEqual(agent.calls.count('develop'),1)
        self.assertEqual(agent.calls.count('diagnose'),1)
        self.assertEqual(agent.calls.count('evaluator_repair'),1)
        self.assertEqual(agent.calls.count('evaluator_review'),1)
        self.assertEqual(result['round'],1);self.assertEqual(result['acceptance_revisions'],1)
        self.assertEqual(len(result['acceptance_history']),1);self.assertEqual(old.read_bytes(),old_bytes)
        history=result['rounds'][0]['objective_history']
        self.assertEqual([row['status']for row in history],['fail','pass'])
        self.assertTrue(Path(history[0]['report']).is_file())
        self.assertEqual((self.root/'invocations.txt').read_text(),'2')
        self.assertEqual(cycle.read(self.task/'contract.json'),result['contract'])
        self.assertEqual(result['launches'],len(agent.calls))

    def test_product_repair_cannot_be_authorized_by_diagnostic_relabeling(self):
        result,agent=self.run_cycle(RevisionAgent(force_repair=True),acceptance_plan=self.plan())
        self.assertEqual(result['status'],'blocked',result)
        self.assertEqual(agent.calls.count('develop'),1)
        self.assertIn('未被独立验收',result['reason'])
        self.assertFalse((self.task/'accepted.patch').exists())

    def test_weakened_oracle_fails_frozen_negative_controls(self):
        result,agent=self.run_cycle(RevisionAgent(weak=True),acceptance_plan=self.plan())
        self.assertEqual(result['status'],'blocked',result)
        self.assertFalse(result['acceptance_history']);self.assertEqual(agent.calls.count('develop'),1)
        self.assertEqual(agent.calls.count('evaluator_review'),0)
        report=cycle.read(self.task/'acceptance/revision-1/calibration/result.json')
        self.assertEqual(report['status'],'fail')
        self.assertEqual([row['name']for row in report['checks']if not row['passed']],['negative_missing','negative_wrong'])

    def test_frozen_controls_cannot_be_changed_by_oracle_author(self):
        result,agent=self.run_cycle(RevisionAgent(mutate_control=True),acceptance_plan=self.plan())
        self.assertEqual(result['status'],'blocked',result)
        self.assertFalse(result['acceptance_history']);self.assertEqual(agent.calls.count('evaluator_review'),0)
        self.assertIn('控制文件',result['reason'])

    def test_independent_review_can_reject_even_calibrated_revision(self):
        result,agent=self.run_cycle(RevisionAgent(review='blocked'),acceptance_plan=self.plan())
        self.assertNotEqual(result['status'],'accepted',result)
        self.assertFalse(result['acceptance_history']);self.assertEqual(agent.calls.count('develop'),1)
        self.assertLessEqual(result['acceptance_revisions'],result['max_acceptance_revisions'])

    def test_same_candidate_receipt_reused_only_while_environment_and_bytes_match(self):
        (self.repo/'.gitignore').write_text('node_modules\n','utf-8')
        cycle.git(self.repo,'add','.gitignore')
        cycle.git(self.repo,'-c','user.name=Fixture','-c','user.email=test@localhost','commit','--quiet','-m','ignore private dependencies')
        plan=self.plan();(Path(plan['revision_policy']['root'])/'oracle.py').write_text(CORRECT,'utf-8')
        plan['files']={p:fingerprint(p)for p in plan['files']}
        self.init(acceptance_plan=plan);agent=fixtures.Agents();runner=cycle.Cycle(self.task,agent)
        for stage in ['requirements','scope_review','develop']:runner.step(stage)
        review=runner.prepare_review();module=review/'client/node_modules/fixture/index.js';module.parent.mkdir(parents=True)
        module.write_text('old','utf-8');original=module.stat()
        runner.step('objective')
        self.assertEqual((self.root/'invocations.txt').read_text(),'1')
        runner.step('objective');self.assertEqual(runner.state['objective_cache_reuses'],1)
        self.assertEqual((self.root/'invocations.txt').read_text(),'1')
        module.write_text('new','utf-8');os.utime(module,ns=(original.st_atime_ns,original.st_mtime_ns))
        runner.step('objective')
        self.assertEqual((self.root/'invocations.txt').read_text(),'2')
        receipt=runner.state['rounds'][-1]['objective_receipt']
        Path(receipt['report']).write_text('tampered','utf-8')
        with self.assertRaisesRegex(ValueError,'证据发生变化'):runner.step('objective')

    def test_revision_rejects_hidden_executable_bytecode(self):
        plan=self.plan();draft=prepare_revision(plan,self.root/'draft')
        (draft/'oracle.py').write_text(CORRECT,'utf-8')
        cache=draft/'__pycache__';cache.mkdir();(cache/'oracle.cpython-311.pyc').write_bytes(b'not sealed executable input')
        with self.assertRaisesRegex(ValueError,'添加或删除'):revised_plan(plan,draft)

    def test_adoption_preserves_and_checks_independent_review_receipt(self):
        self.init(acceptance_plan=self.plan());runner=cycle.Cycle(self.task,RevisionAgent())
        for _ in range(12):
            if runner.state['acceptance_history']or runner.state['stage']=='done':break
            runner.run(one_stage=True)
        self.assertTrue(runner.state['acceptance_history'],runner.state['reason'])
        adoption=runner.state['acceptance_history'][0]
        review=self.task/adoption['review']/'result.json';value=cycle.read(review);value['decision']='blocked';cycle.write(review,value)
        state=runner.run()
        self.assertEqual(state['status'],'blocked')
        self.assertIn('采用链',state['reason'])
        self.assertFalse((self.task/'accepted.patch').exists())

    def test_diagnosis_binding_must_match_current_failure(self):
        base=fixtures.Agents(failures=1)
        def actor(**kw):
            value=base(**kw)
            if kw['stage']=='diagnose':value['binding']['candidate_sha']='old-candidate'
            return value
        result,_=self.run_cycle(actor)
        self.assertEqual(result['status'],'blocked',result)
        self.assertEqual(base.calls.count('develop'),1)
        self.assertIn('诊断不属于',result['reason'])

    def test_frozen_workspace_preparation_precedes_development_and_receipt_binding(self):
        (self.repo/'.gitignore').write_text('node_modules\n','utf-8');cycle.git(self.repo,'add','.gitignore')
        cycle.git(self.repo,'-c','user.name=Fixture','-c','user.email=test@localhost','commit','--quiet','-m','private environment')
        plan=self.plan();root=Path(plan['revision_policy']['root'])
        (root/'oracle.py').write_text(CORRECT,'utf-8')
        (root/'prepare.py').write_text("""import json,pathlib,sys
source=pathlib.Path.cwd();module=source/'client/node_modules/fixture/index.js';module.parent.mkdir(parents=True,exist_ok=True)
if not module.exists():module.write_text('private fixture implementation')
pathlib.Path(sys.argv[1]).write_text(json.dumps(dict(status='pass',failure_type='none',checks=[dict(name='prepared',passed=True,observed=True,failure_type='none',criterion_ids=['AC-01'])])))
""",'utf-8')
        plan['files']={str(p):fingerprint(p)for p in root.iterdir()}
        plan['prepare_argv']=['{python}','{validator}/prepare.py','{result}']
        base=fixtures.Agents()
        def actor(**kw):
            if kw['stage']=='develop':self.assertTrue((kw['cwd']/'client/node_modules/fixture/index.js').is_file())
            return base(**kw)
        state,_=self.run_cycle(actor,acceptance_plan=plan)
        self.assertEqual(state['status'],'accepted',state['reason'])
        self.assertEqual(base.calls.count('develop'),1);self.assertEqual(state['launches'],5)
        self.assertEqual(len(list((self.task/'environment').glob('workspace-*'))),2)
        self.assertEqual((self.root/'invocations.txt').read_text(),'1')
