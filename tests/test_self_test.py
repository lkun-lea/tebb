import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from desk_companion.evaluation.self_test import catalog, SelfTestService, execute
from desk_companion.evaluation.self_test_tools import specs
from desk_companion.evaluation.golden_store import GoldenStore, builtin_cases


class SelfTestTests(unittest.TestCase):
    def batch(self,service):
        return dict(id='a'*32,candidate=service.candidate,mode='fixture',state='completed',manifest_hash='frozen',code_version='code',
            planned=[dict(case_id='fixture',sample=1)],results=[dict(case_id='fixture',sample=1,outcome='success',
                call_ids=['call-fixture'],calls=[dict(id='call-fixture')],model_observations=[dict(debug_call='call-fixture')],
                call_evidence_complete=True,model_observations_complete=True)])

    def test_catalog_discovers_all_current_builtins_and_preserves_stored_versions(self):
        value=catalog();cases=builtin_cases()
        self.assertEqual({c['id']for a in value['capabilities']for c in a['cases']},{c['id']for c in cases})
        self.assertTrue(value['gaps']);self.assertTrue(value['limitations'])
        with tempfile.TemporaryDirectory()as directory:
            self.assertEqual({c['version']for c in cases},{c['version']for c in GoldenStore(Path(directory)/'eval.sqlite3').cases()})
        self.assertTrue((Path(__file__).parents[1]/value['guide']).is_file())

    def test_catalog_and_describe_need_no_authentication_or_evaluation_runtime(self):
        service=SelfTestService(None)
        self.assertEqual(service.operate('catalog'),catalog())
        self.assertEqual(service.operate('describe',dict(capability='smoke'))['capability']['id'],'smoke')
        result=subprocess.run([sys.executable,'scripts/agent_inspect.py','selftest','catalog'],env={k:v for k,v in os.environ.items()if not k.startswith('DESK_COMPANION_API_')},
            capture_output=True,text=True,encoding='utf-8',timeout=15)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout)['result'],catalog())

    def test_start_is_fixed_fixture_scoped_and_retry_uses_the_same_request(self):
        evaluator=Mock(return_value=dict(ok=True,batch=dict(id='batch')))
        service=SelfTestService(evaluator,'task:one');payload=dict(capability='smoke',request_id='stable-request')
        service.operate('start',payload);first=copy.deepcopy(evaluator.call_args.args)
        service.operate('start',payload);self.assertEqual(evaluator.call_args.args,first)
        operation,args=first;self.assertEqual(operation,'start');self.assertEqual(args['mode'],'fixture')
        self.assertEqual(args['samples'],1);self.assertEqual(args['timeout'],120)
        self.assertEqual(len(args['case_versions']),3)
        SelfTestService(evaluator,'task:other').operate('start',payload)
        self.assertNotEqual(first[1]['request_id'],evaluator.call_args.args[1]['request_id'])
        for extra in (dict(mode='live'),dict(live_authorized=True),dict(command='echo bad'),dict(profile='/private')):
            with self.assertRaises(ValueError):service.operate('start',{**payload,**extra})

    def test_owner_cannot_read_or_cancel_another_task_or_live_batch(self):
        evaluator=Mock();service=SelfTestService(evaluator,'task:one');batch=self.batch(service)
        evaluator.return_value=dict(ok=True,batch=batch)
        for altered in (dict(candidate='other'),dict(candidate=SelfTestService(None,'task:other').candidate),dict(mode='live')):
            evaluator.return_value=dict(ok=True,batch={**batch,**altered})
            for operation in ('get','report','cancel'):
                with self.assertRaises(ValueError):service.operate(operation,dict(ident=batch['id']))
        evaluator.return_value=dict(ok=True,batch=batch)
        self.assertEqual(SelfTestService(evaluator).operate('get',dict(ident=batch['id']))['batch'],batch)

    def test_report_does_not_pass_missing_duplicate_partial_or_unobserved_samples(self):
        batch=self.batch(SelfTestService(None));self.assertTrue(SelfTestService.report(batch)['passed'])
        for changes in (dict(state='running'),dict(state='cancelled'),dict(results=[]),dict(results=batch['results']*2),
                        dict(results=[{**batch['results'][0],'progress':True}]),
                        dict(results=[{**batch['results'][0],'outcome':'failed'}]),
                        dict(results=[{**batch['results'][0],'call_ids':[]}]),
                        dict(results=[{**batch['results'][0],'calls':[]}]),
                        dict(results=[{**batch['results'][0],'model_observations':[]}]),
                        dict(results=[{**batch['results'][0],'model_observations_complete':False}])):
            self.assertFalse(SelfTestService.report({**batch,**changes})['passed'])

    def test_tools_share_catalog_and_bind_runtime_identity_without_exposing_credentials(self):
        request=dict(task_id='actual-task',collab_run='actual-run')
        tools={s['function']['name']:s for s in specs(request)}
        self.assertEqual(tools['self_test_catalog']['implementation']({}),catalog())
        self.assertNotIn('token',json.dumps([s['function']for s in tools.values()]))
        with patch('desk_companion.evaluation.self_test_tools.call',return_value={'ok':True})as call:
            tools['self_test_start']['implementation'](dict(capability='smoke',request_id='stable-request'))
        self.assertEqual(call.call_args.args[1]['task_id'],'actual-task')
        self.assertEqual(call.call_args.args[1]['run_id'],'actual-run')
        with patch.dict(os.environ,TEBB_EVAL_CANCEL_FILE='fixture-cancel'):
            with self.assertRaises(ValueError):tools['self_test_start']['implementation'](dict(capability='smoke',request_id='stable-request'))
        with patch('desk_companion.tasks.task_budgets.current',return_value=SimpleNamespace(task='pi-task')),patch('desk_companion.evaluation.self_test_tools.call')as call:
            next(s for s in specs()if s['function']['name']=='self_test_cancel')['implementation'](dict(ident='a'*32))
            self.assertEqual(call.call_args.args[1]['task_id'],'pi-task')

    def test_parent_checks_physical_task_is_still_running(self):
        host=SimpleNamespace(tasks=SimpleNamespace(get=lambda _:dict(state='cancelled')))
        with self.assertRaises(ValueError):execute(host,None,'catalog',task_id='ended')

    def test_parent_checks_partner_run_stage_and_exact_physical_task(self):
        import threading
        from contextlib import nullcontext
        run=dict(id='run',task='physical',state='running',kind='task')
        host=SimpleNamespace(collaboration=SimpleNamespace(lock=threading.RLock(),path='unused'))
        with patch('desk_companion.collaboration.store.transaction',side_effect=lambda _:nullcontext((dict(runs=[run]),None))):
            self.assertEqual(execute(host,None,'catalog',task_id='physical',run_id='run'),catalog())
            for changes in (dict(task='another'),dict(state='cancelling'),dict(kind='route')):
                previous=run.copy();run.update(changes)
                with self.assertRaises(ValueError):execute(host,None,'catalog',task_id='physical',run_id='run')
                run.clear();run.update(previous)

    def test_evidence_operations_delegate_to_the_original_batch_and_default_sample(self):
        evaluator=Mock();service=SelfTestService(evaluator,'task:one');batch=self.batch(service)
        evaluator.return_value=dict(ok=True,batch=batch)
        for operation in ('cancel','diagnose','trace','debug_call'):
            payload=dict(ident=batch['id'])
            if operation in {'trace','debug_call'}:payload['case_id']='fixture'
            if operation=='debug_call':payload['call_id']='call-fixture'
            service.operate(operation,payload)
            forwarded={**payload,**({'sample':1}if operation in {'trace','debug_call'}else{})}
            evaluator.assert_called_with(operation,forwarded)
        with self.assertRaises(ValueError):service.operate('debug_call',dict(ident=batch['id'],case_id='fixture'))

    def test_partner_worker_offers_and_executes_the_real_catalog_tool(self):
        from tests import test_feedback_worker as fixture
        class CatalogObserved(Exception):pass
        for role in ('tebb','coder'):
            case=fixture.FeedbackWorkerTests()
            case.setUp()
            try:
                case.request['role']=dict(id=role,name=role,role='acceptance',tools=[])
                if role=='coder':
                    from desk_companion.projects.project_workspace import save
                    directory=Path(case.temp.name)/'project';directory.mkdir()
                    case.request['workspace']=save(str(directory),edit=True,commands=True,project_id='acceptance')['workspace']
                    case.request['role']['tools']=['工作区读取','文件编辑','终端']
                    case.request['development_task']=True
                case.request['budget']=3
                captured=[]
                class Model:
                    def chat(model,messages,tools=None,on_delta=None):
                        captured.append(copy.deepcopy(messages))
                        if len(captured)==1:
                            self.assertIn('self_test_catalog',{t['function']['name']for t in tools})
                            return dict(message=dict(tool_calls=[dict(id='catalog-call',function=dict(name='self_test_catalog',arguments='{}'))]),usage={})
                        self.assertTrue(any('agent_self_test'in str(m)for m in messages if m.get('role')=='tool'))
                        raise CatalogObserved()
                with self.assertRaises(CatalogObserved):case.run_model(Model())
            finally:case.doCleanups()

    def test_pi_catalog_search_and_load_can_discover_the_registered_self_test_tools(self):
        from atlas import Toolkit
        from desk_companion.pi_runtime.tool_loading import ToolLoading,SEARCH,LOAD
        from desk_companion.observability.tool_monitor import ToolMonitor
        with tempfile.TemporaryDirectory()as directory:
            toolkit=Toolkit()
            for spec in specs():toolkit.register(**spec['function'],func=spec['implementation'],isReadOnly=spec['read_only'],retry_max=0)
            loading=ToolLoading([s['function']for s in specs()],session='fixture',store=ToolMonitor(Path(directory)/'tools.sqlite3'))
            found=loading.execute(SEARCH,dict(query='自测'),'search')
            self.assertIn('self_test_catalog',{s['name']for s in found['tools']})
            loading.execute(LOAD,dict(names=['self_test_catalog','self_test_start']),'load')
            self.assertIn('self_test_start',{s['name']for s in loading.specs()})
