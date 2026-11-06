import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

import httpx

from desk_companion.accounts.account_auth import AccountAuth
from desk_companion.accounts.account_store import AccountStore, AccountRuntime, WindowsAccountCipher, account_key, profile_root
from desk_companion.accounts.service import AccountService
from desk_companion.accounts.personalization_cloud import CloudError

A='a0000000-0000-4000-8000-000000000001'
B='b0000000-0000-4000-8000-000000000002'
URL='https://accounts.example.invalid'
KEY='sb_publishable_'+'a'*24


class TestCipher:
    """Explicit test double, never selected by product code."""
    def seal(self, raw):return raw[::-1]
    def open(self, raw):return raw[::-1]


def user(subject=A):
    return dict(id=subject,email='a@tebb.invalid' if subject==A else 'b@tebb.invalid',aud='authenticated',
                app_metadata={},user_metadata={},created_at='2026-11-03T00:00:00Z')


def session(subject=A, suffix=''):
    return dict(access_token='ACCESS-'+subject+suffix,refresh_token='REFRESH-'+subject+suffix,
                expires_in=3600,expires_at=int(time.time())+3600,token_type='bearer',user=user(subject))


class AuthFixture:
    def __init__(self):
        self.calls=[];self.failure=None;self.refresh_owner=None;self.gate=None;self.entered=threading.Event()

    def __call__(self, request):
        body=json.loads(request.content or b'null')
        self.calls.append((request.method,request.url.path,body,dict(request.headers)))
        if self.gate:
            self.entered.set();self.gate.wait(5)
        if self.failure:
            return self.failure(request)
        path=request.url.path
        if path.endswith('/otp'):
            return httpx.Response(200,json={})
        if path.endswith('/verify'):
            if body['token']!='123456':return httpx.Response(403,json={'code':'otp_expired','error_code':'otp_expired','msg':'invalid OTP'})
            return httpx.Response(200,json=session(A if body['email']=='a@tebb.invalid' else B))
        if path.endswith('/token'):
            owner=self.refresh_owner or (A if A in body['refresh_token'] else B)
            return httpx.Response(200,json=session(owner,'-renewed'))
        if path.endswith('/user'):
            return httpx.Response(200,json=user(A if A in request.headers.get('authorization','') else B))
        if path.endswith('/logout'):
            return httpx.Response(204)
        return httpx.Response(404,json={})

    def adapter(self):
        return AccountAuth(lambda:httpx.Client(transport=httpx.MockTransport(self),follow_redirects=False))


class AccountTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.home=Path(self.temp.name).resolve();self.store=AccountStore(self.home,cipher=TestCipher())
        self.fixture=AuthFixture()
        self.service=AccountService(AccountRuntime(self.home,'local',self.home),store=self.store,auth=self.fixture.adapter(),env={})

    def act(self, kind, service=None, **args):
        service=service or self.service
        return service.action(dict(type=kind,request_id=str(uuid4()),version=service.status()['version'],**args))

    def configure(self):return self.act('configure',url=URL,publishable_key=KEY)

    def login(self, subject=A):
        if not self.service.status()['configured']:self.configure()
        email=user(subject)['email'];page=self.act('send_code',email=email)
        self.assertTrue(page['ok'],page)
        page=self.act('verify_code',challenge_id=page['challenge']['id'],code='123456')
        self.assertTrue(page['ok'],page)
        return account_key(URL,subject),page

    def bound(self, key):
        return AccountService(AccountRuntime(self.home,key,profile_root(self.home,key)),store=self.store,auth=self.fixture.adapter(),env={})

    def test_cloud_lease_reuses_sdk_refresh_and_blocks_parallel_account_actions(self):
        key,_=self.login();service=self.bound(key)
        with self.store.transaction() as state:state['accounts'][key]['session']['expires_at']=1
        cloud=type('Cloud',(),{'verify_session':lambda _:A,'close':lambda _:None})()
        tokens=[]
        service._cloud_factory=lambda config,token:(tokens.append(token) or cloud)
        with service.cloud_client() as current:
            self.assertIs(current,cloud);self.assertTrue(tokens[0].endswith('-renewed'))
            result=[]
            t=threading.Thread(target=lambda:result.append(self.act('logout',service)))
            t.start();t.join(3);self.assertEqual(result[0]['code'],'busy')
        self.assertEqual(sum(c[1].endswith('/token') for c in self.fixture.calls),1)
        self.assertEqual(service.status()['runtime']['key'],key)

    def test_cloud_identity_mismatch_invalidates_only_current_session_and_always_releases_lease(self):
        key,_=self.login();service=self.bound(key)
        cloud=type('Cloud',(),{'verify_session':lambda _:B,'close':lambda _:None})()
        service._cloud_factory=lambda *_:cloud
        with self.assertRaises(CloudError):
            with service.cloud_client():pass
        self.assertEqual(service.status()['accounts'][0]['state'],'reauth_required')
        self.assertIsNone(self.store.read()['accounts'][key]['session'])
        self.assertTrue(self.store.actions.acquire(False));self.store.actions.__exit__()

    def test_cloud_close_failure_cannot_leave_account_actions_locked(self):
        key,_=self.login();service=self.bound(key)
        def fail(_):raise RuntimeError('close failed')
        cloud=type('Cloud',(),{'verify_session':lambda _:A,'close':fail})()
        service._cloud_factory=lambda *_:cloud
        with self.assertRaises(RuntimeError):
            with service.cloud_client():pass
        result=[]
        def reserve():
            acquired=self.store.actions.acquire(False);result.append(acquired)
            if acquired:self.store.actions.__exit__()
        t=threading.Thread(target=reserve);t.start();t.join(3);self.assertEqual(result,[True])

    def test_no_project_is_an_explicit_local_space_without_network(self):
        page=self.service.status()
        self.assertEqual(page['runtime']['key'],'local');self.assertFalse(page['configured'])
        self.assertFalse(self.store.path.exists());self.assertEqual(self.fixture.calls,[])
        result=self.act('send_code',email='a@tebb.invalid')
        self.assertFalse(result['ok']);self.assertFalse(result['accepted']);self.assertEqual(result['code'],'needs_configuration')

    def test_configuration_is_encrypted_and_same_operation_is_not_reexecuted(self):
        payload=dict(type='configure',request_id=str(uuid4()),version=0,url=URL,publishable_key=KEY)
        first=self.service.action(payload);self.assertTrue(first['ok'])
        raw=self.store.path.read_text('utf-8');self.assertNotIn(KEY,raw);self.assertNotIn(URL,raw)
        second=self.service.action(payload);self.assertEqual(second['version'],first['version'])
        with self.assertRaises(CloudError):self.service.action(payload|{'url':'https://other.invalid'})

    def test_sdk_otp_does_not_create_users_and_server_verifies_identity(self):
        old=self.home/'memory'/'facts.json';old.parent.mkdir();old.write_text('old local facts','utf-8')
        key,page=self.login()
        self.assertEqual(self.fixture.calls[0][1],'/auth/v1/otp');self.assertIs(self.fixture.calls[0][2]['create_user'],False)
        self.assertEqual(self.fixture.calls[1][2]['type'],'email');self.assertEqual(self.fixture.calls[2][1],'/auth/v1/user')
        self.assertEqual(page['selected'],key);self.assertTrue(page['restart_required'])
        self.assertEqual(page['runtime']['key'],'local');self.assertFalse(profile_root(self.home,key).exists())
        self.assertEqual(old.read_text('utf-8'),'old local facts')
        public=json.dumps(page)
        for secret in ('ACCESS-','REFRESH-',KEY,'123456','publishable_key'):self.assertNotIn(secret,public)

    def test_request_replay_survives_a_new_service_without_sending_again(self):
        self.configure();payload=dict(type='send_code',email='a@tebb.invalid',request_id=str(uuid4()),version=self.service.status()['version'])
        self.assertTrue(self.service.action(payload)['ok']);count=len(self.fixture.calls)
        restored=AccountService(self.service.runtime,store=self.store,auth=self.fixture.adapter(),env={})
        self.assertTrue(restored.action(payload)['ok']);self.assertEqual(len(self.fixture.calls),count)
        self.assertEqual(self.act('send_code',email='a@tebb.invalid')['code'],'rate_limited')

    def test_stale_versions_invalid_keys_and_unknown_challenges_do_not_send(self):
        result=self.act('configure',url=URL,publishable_key='sb_secret_not_allowed')
        self.assertFalse(result['ok']);self.assertFalse(result['accepted'])
        self.configure()
        result=self.service.action(dict(type='send_code',email='a@tebb.invalid',version=0,request_id=str(uuid4())))
        self.assertEqual(result['code'],'version_conflict')
        result=self.act('verify_code',challenge_id='unknown',code='123456');self.assertFalse(result['accepted'])
        self.assertEqual(self.fixture.calls,[])

    def test_project_changes_retire_a_code_instead_of_sending_it_to_another_service(self):
        self.configure();page=self.act('send_code',email='a@tebb.invalid');challenge=page['challenge']['id']
        self.act('configure',url='https://another-project.invalid',publishable_key=KEY)
        count=len(self.fixture.calls);result=self.act('verify_code',challenge_id=challenge,code='123456')
        self.assertFalse(result['ok']);self.assertEqual(result['code'],'invalid_challenge');self.assertEqual(len(self.fixture.calls),count)

    def test_explicit_bad_otp_can_be_corrected_without_automatically_resending(self):
        self.configure();page=self.act('send_code',email='a@tebb.invalid');challenge=page['challenge']['id']
        wrong=self.act('verify_code',challenge_id=challenge,code='000000')
        self.assertFalse(wrong['ok']);self.assertEqual(wrong['code'],'invalid_otp')
        self.assertEqual(wrong['challenge']['id'],challenge)
        right=self.act('verify_code',challenge_id=challenge,code='123456');self.assertTrue(right['ok'])
        self.assertEqual(sum(path.endswith('/otp') for _,path,_,_ in self.fixture.calls),1)

    def test_activation_checks_valid_tokens_and_refreshes_expired_sessions_once(self):
        key,_=self.login();self.act('activate',account_id='local')
        count=len(self.fixture.calls);page=self.act('activate',account_id=key);self.assertTrue(page['ok'])
        self.assertEqual(self.fixture.calls[-1][1],'/auth/v1/user');self.assertEqual(len(self.fixture.calls),count+1)
        self.act('activate',account_id='local')
        with self.store.transaction() as state:state['accounts'][key]['session']['expires_at']=1
        page=self.act('activate',account_id=key);self.assertTrue(page['ok'])
        self.assertEqual([p for _,p,_,_ in self.fixture.calls[-2:]],['/auth/v1/token','/auth/v1/user'])
        self.assertTrue(self.store.read()['accounts'][key]['session']['refresh_token'].endswith('-renewed'))

    def test_refresh_identity_mismatch_cannot_move_or_replace_an_account(self):
        key,_=self.login();self.act('activate',account_id='local')
        with self.store.transaction() as state:state['accounts'][key]['session']['expires_at']=1
        self.fixture.refresh_owner=B
        result=self.act('activate',account_id=key)
        self.assertFalse(result['ok']);self.assertEqual(result['code'],'identity_mismatch')
        state=self.store.read();self.assertEqual(state['selected'],'local');self.assertIsNone(state['accounts'][key]['session'])
        self.assertNotIn(account_key(URL,B),state['accounts'])

    def test_failed_refresh_is_never_replayed_with_a_consumed_token(self):
        key,_=self.login();self.act('activate',account_id='local')
        with self.store.transaction() as state:state['accounts'][key]['session']['expires_at']=1
        self.fixture.failure=lambda request:(_ for _ in ()).throw(httpx.ReadTimeout('PRIVATE_TOKEN',request=request))
        result=self.act('activate',account_id=key);self.assertFalse(result['ok']);self.assertNotIn('PRIVATE_TOKEN',str(result))
        count=len(self.fixture.calls)
        self.assertEqual(self.act('activate',account_id=key)['code'],'needs_login');self.assertEqual(len(self.fixture.calls),count)

    def test_logout_uses_local_scope_and_keeps_remote_uncertainty_visible(self):
        key,_=self.login();bound=self.bound(key)
        self.fixture.failure=lambda _:httpx.Response(500,json={'msg':'PRIVATE_TOKEN'})
        page=self.act('logout',service=bound)
        self.assertTrue(page['ok']);self.assertEqual(page['operation']['remote_status'],'unconfirmed')
        self.assertIsNone(self.store.read()['accounts'][key]['session']);self.assertEqual(page['selected'],'local')
        self.assertEqual(page['runtime']['key'],key);self.assertNotIn('PRIVATE_TOKEN',str(page))
        self.assertTrue(page['restart_required'])

    def test_logout_and_return_to_local_work_even_when_environment_configuration_is_invalid(self):
        key,_=self.login()
        broken=AccountService(self.bound(key).runtime,store=self.store,auth=self.fixture.adapter(),env={'TEBB_CLOUD_URL':'bad'})
        result=self.act('logout',service=broken);self.assertTrue(result['ok']);self.assertEqual(result['selected'],'local')
        self.assertIsNone(self.store.read()['accounts'][key]['session'])

    def test_unknown_operation_can_be_retired_without_replaying_it(self):
        self.configure();payload=dict(type='send_code',email='a@tebb.invalid',request_id=str(uuid4()),version=self.service.status()['version'])
        digest=hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        with self.store.transaction() as state:state['operations'][payload['request_id']]=dict(id=payload['request_id'],type='send_code',digest=digest,state='pending')
        self.assertEqual(self.service.action(payload)['code'],'unconfirmed');self.assertEqual(self.fixture.calls,[])
        done=self.act('acknowledge',operation_id=payload['request_id']);self.assertTrue(done['ok'])
        self.assertFalse(self.service.action(payload)['ok']);self.assertEqual(self.fixture.calls,[])

    def test_retiring_not_yet_arrived_request_blocks_a_late_original_rpc(self):
        self.configure();op=str(uuid4());self.assertTrue(self.act('acknowledge',operation_id=op)['ok'])
        with self.assertRaises(CloudError):self.service.action(dict(type='send_code',request_id=op,version=0,email='a@tebb.invalid'))
        self.assertEqual(self.fixture.calls,[])

    def test_account_status_is_readable_during_a_network_request_and_other_mutations_are_rejected(self):
        self.configure();gate=threading.Event();self.fixture.gate=gate;result=[]
        thread=threading.Thread(target=lambda:result.append(self.act('send_code',email='a@tebb.invalid')));thread.start()
        self.addCleanup(gate.set);self.assertTrue(self.fixture.entered.wait(3))
        state=self.store.read();op=next(reversed(state['operations']))
        self.assertEqual(self.service.status(op)['operation']['state'],'pending')
        self.assertEqual(self.act('send_code',email='b@tebb.invalid')['code'],'busy')
        gate.set();thread.join(5);self.assertFalse(thread.is_alive());self.assertTrue(result[0]['ok'])

    def test_registry_corruption_and_save_failure_never_fall_back_to_other_data(self):
        self.store.directory.mkdir(exist_ok=True);self.store.path.write_text('{broken','utf-8')
        with self.assertRaises(CloudError):self.service.status()
        self.store.path.unlink()
        with patch.object(self.store.cipher,'seal',side_effect=OSError('PRIVATE_TOKEN')):
            result=self.act('configure',url=URL,publishable_key=KEY)
        self.assertFalse(result['ok']);self.assertNotIn('PRIVATE_TOKEN',str(result));self.assertFalse(self.store.path.exists())

    def test_account_paths_are_opaque_and_runtime_binding_is_validated(self):
        key,_=self.login();self.assertEqual(profile_root(self.home,key),self.home/'accounts'/key/'data')
        for key in ('../other',str(uuid4()),'A'*64):
            with self.assertRaises(CloudError):profile_root(self.home,key)
        with patch.dict(os.environ,{'DESK_COMPANION_HOME_DIR':str(self.home),'DESK_COMPANION_DATA_DIR':str(self.home),'DESK_COMPANION_ACCOUNT_KEY':'a'*64}):
            with self.assertRaises(CloudError):AccountRuntime.current()

    @unittest.skipUnless(os.name=='nt','Windows DPAPI')
    def test_real_windows_dpapi_encrypts_sessions_and_rejects_tampering(self):
        cipher=WindowsAccountCipher();raw=b'PRIVATE_REFRESH_TOKEN'
        encrypted=cipher.seal(raw);self.assertNotIn(raw,encrypted);self.assertEqual(cipher.open(encrypted),raw)
        with self.assertRaises(Exception):cipher.open(encrypted[:-2]+b'xx')


if __name__=='__main__':unittest.main()
