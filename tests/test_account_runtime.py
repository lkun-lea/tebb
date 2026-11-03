import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

from desk_companion.account_store import AccountRuntime,AccountStore,WindowsAccountCipher,account_key,profile_root
from desk_companion.accounts import AccountService
from desk_companion.personalization_cloud import CloudError
from test_accounts import AuthFixture,TestCipher,A,B,URL,KEY


class AccountRuntimeTests(unittest.TestCase):
    def test_binding_uses_an_explicit_selection_without_copying_anonymous_data(self):
        from desk_companion.account_bootstrap import bind_runtime
        with tempfile.TemporaryDirectory() as folder:
            home=Path(folder).resolve();store=AccountStore(home,cipher=TestCipher())
            local=home/'memory';local.mkdir();(local/'facts.json').write_text('anonymous facts','utf-8')
            key=account_key(URL,A)
            with store.transaction() as state:
                state.update(config=dict(url=URL,publishable_key=KEY),selected=key)
                state['accounts'][key]=dict(url=URL,user_id=A,email='a@tebb.invalid',session=None,refresh_state='reauth_required')
            with patch.dict(os.environ,{},clear=True):
                selected,data=bind_runtime(home,store)
                self.assertEqual(selected,key);self.assertEqual(AccountRuntime.current().key,key)
                self.assertEqual(list(data.iterdir()),[]);self.assertEqual((local/'facts.json').read_text('utf-8'),'anonymous facts')

    def test_initialization_failure_is_sticky_so_sitecustomize_cannot_fall_through_to_another_space(self):
        from desk_companion import account_bootstrap as bootstrap
        with patch.object(bootstrap,'_initialized',False),patch.object(bootstrap,'_initialization_error',None), \
             patch.object(bootstrap,'_initialize',side_effect=CloudError('account_binding_mismatch','test failure')) as initialize:
            for _ in range(2):
                with self.assertRaises(CloudError):bootstrap.initialize_runtime()
            self.assertEqual(initialize.call_count,1)

    def test_packaged_startup_binds_before_extension_activation_and_workers_do_not_rebind(self):
        from scripts.prepare_runtime import write_sitecustomize
        from desk_companion import account_bootstrap as bootstrap
        observed=[]
        with tempfile.TemporaryDirectory() as folder:
            site=Path(folder);write_sitecustomize(site);source=(site/'sitecustomize.py').read_text('utf-8')
            def bind():os.environ['DESK_COMPANION_DATA_DIR']='TEST_ACCOUNT_A';os.environ.pop('DESK_COMPANION_ACCOUNT_BOOTSTRAP',None);bootstrap._initialized=True
            with patch.dict(os.environ,{'DESK_COMPANION_ACCOUNT_BOOTSTRAP':'1'}), \
                 patch.object(bootstrap,'_initialized',False),patch.object(bootstrap,'_initialization_error',None), \
                 patch.object(bootstrap,'_initialize',side_effect=bind) as initialized, \
                 patch('desk_companion.runtime_extensions.activate',side_effect=lambda:observed.append(os.environ.get('DESK_COMPANION_DATA_DIR'))):
                exec(compile(source,'sitecustomize.py','exec'),{})
                self.assertEqual(observed,['TEST_ACCOUNT_A']);self.assertEqual(initialized.call_count,1)
                bootstrap._initialized=False
                exec(compile(source,'sitecustomize.py','exec'),{})
                self.assertEqual(initialized.call_count,1);self.assertEqual(observed,['TEST_ACCOUNT_A','TEST_ACCOUNT_A'])

    @unittest.skipUnless(os.name=='nt','Windows DPAPI and native process ownership')
    def test_actual_processes_serialize_home_ownership_and_late_work_stays_in_its_original_account(self):
        with tempfile.TemporaryDirectory() as folder:
            home=Path(folder).resolve();store=AccountStore(home,cipher=WindowsAccountCipher());fixture=AuthFixture()
            service=AccountService(AccountRuntime(home,'local',home),store=store,auth=fixture.adapter(),env={})
            def act(kind,**args):
                result=service.action(dict(type=kind,request_id=str(uuid4()),version=service.status()['version'],**args))
                self.assertTrue(result['ok'],result);return result
            act('configure',url=URL,publishable_key=KEY)
            for email in ('a@tebb.invalid','b@tebb.invalid'):
                page=act('send_code',email=email);act('verify_code',challenge_id=page['challenge']['id'],code='123456')
            key_a,key_b=account_key(URL,A),account_key(URL,B)
            with store.transaction() as state:state['selected']=key_a
            ready=home/'ready.json';release=home/'release';second=home/'second.json';third=home/'third.json'
            code='''
import json,os,sys,time
from pathlib import Path
from desk_companion.account_bootstrap import initialize_runtime
from desk_companion.runtime_instance import InstanceInUse
from desk_companion.paths import data_root
report=Path(sys.argv[1])
try:initialize_runtime()
except InstanceInUse:
 report.write_text(json.dumps({'state':'in_use'}),'utf-8');raise SystemExit(73)
report.write_text(json.dumps({'state':'ready','root':str(data_root()),'bootstrap_marker':os.environ.get('DESK_COMPANION_ACCOUNT_BOOTSTRAP')}),'utf-8')
if len(sys.argv)>2:
 release=Path(sys.argv[2]);deadline=time.monotonic()+60
 while not release.exists() and time.monotonic()<deadline:time.sleep(.02)
 if not release.exists():raise SystemExit(2)
 (data_root()/'late-worker.txt').write_text('original account A','utf-8')
'''
            source=str(Path(__file__).resolve().parents[1])
            env={**os.environ,'PYTHONPATH':source+os.pathsep+os.environ.get('PYTHONPATH',''),
                 'DESK_COMPANION_DATA_DIR':str(home),'DESK_COMPANION_HOME_DIR':str(home),'DESK_COMPANION_ACCOUNT_BOOTSTRAP':'1'}
            env.pop('DESK_COMPANION_ACCOUNT_KEY',None)
            children=[]
            def start(report,*args):
                child=subprocess.Popen([sys.executable,'-c',code,str(report),*map(str,args)],env=env,
                    stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,creationflags=0x08000000)
                children.append(child);return child
            first=start(ready,release)
            try:
                deadline=time.monotonic()+30
                while not ready.exists() and first.poll() is None and time.monotonic()<deadline:time.sleep(.02)
                diagnostic=first.communicate(timeout=1)[1].decode('utf-8',errors='replace') if first.poll() is not None else 'process still starting'
                self.assertTrue(ready.exists(),f'first account process never became ready; exit={first.poll()}; {diagnostic}')
                self.assertIsNone(json.loads(ready.read_text('utf-8'))['bootstrap_marker'])
                with store.transaction() as state:state['selected']=key_b
                attempt=start(second);self.assertEqual(attempt.wait(30),73)
                self.assertEqual(json.loads(second.read_text('utf-8'))['state'],'in_use');self.assertFalse(profile_root(home,key_b).exists())
                release.write_text('finish','utf-8');self.assertEqual(first.wait(10),0)
                attempt=start(third);self.assertEqual(attempt.wait(30),0)
                self.assertEqual(Path(json.loads(third.read_text('utf-8'))['root']),profile_root(home,key_b))
                self.assertEqual((profile_root(home,key_a)/'late-worker.txt').read_text('utf-8'),'original account A')
                self.assertFalse((profile_root(home,key_b)/'late-worker.txt').exists())
            finally:
                release.touch()
                for child in children:
                    if child.poll() is None:child.kill();child.wait(10)
                    if child.stderr:child.stderr.close()


if __name__=='__main__':unittest.main()
