import base64
import json
import io
import os
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import httpx

from desk_companion.accounts.personalization_cloud import CloudConfig, CloudError, PersonalizationCloud, preflight

A='a0000000-0000-4000-8000-000000000001'
B='b0000000-0000-4000-8000-000000000002'
RECORD='c0000000-0000-4000-8000-000000000003'
OP='d0000000-0000-4000-8000-000000000004'
KEY='sb_publishable_'+'a'*24
TOKEN='TEST_USER_TOKEN_DO_NOT_LOG'
ENV={'TEBB_CLOUD_URL':'https://example.supabase.co','TEBB_CLOUD_PUBLISHABLE_KEY':KEY}


def receipt(**changes):
    return dict(user_id=A,operation_id=OP,record_id=RECORD,status='applied',version=1,cursor=1,action='put',**changes)


def row(**changes):
    value=dict(id=RECORD,text='简洁回答',kind='preference',category='communication',scope='user',scope_id='',state='active',version=1,sequence=1)
    return value | changes


def page(**changes):
    return dict(user_id=A,records=[row()],cursor=1,has_more=False,head=1) | changes


class CloudClientTests(unittest.TestCase):
    def client(self, responses=None, handler=None):
        seen=[]
        def serve(request):
            seen.append(request)
            if handler:return handler(request)
            if request.url.path=='/auth/v1/user':return httpx.Response(200,json={'id':A})
            if request.url.path=='/auth/v1/settings':return httpx.Response(200,json={'external':{'email':True}})
            method=request.url.path.rsplit('_',1)[1]
            defaults={'status':{'contract':'tebb.personalization.v2','user_id':A,'revision':1,'pgvector':True},
                      'pull':page(),'apply':receipt(),'operation':{'user_id':A,'found':True,'receipt':receipt()}}
            return httpx.Response(200,json=(responses or {}).get(method,defaults[method]))
        transport=httpx.Client(transport=httpx.MockTransport(serve))
        cloud=PersonalizationCloud(CloudConfig.from_env(ENV),TOKEN,client=transport)
        self.addCleanup(transport.close)
        return cloud,seen,transport

    def test_default_check_is_static_and_never_creates_a_network_client(self):
        with patch('httpx.Client',side_effect=AssertionError('network not authorized')):
            self.assertEqual(preflight(env=ENV),{'status':'configured','network_checked':False,'deployment_checked':False})

    def test_missing_and_placeholder_configuration_are_not_ready(self):
        for env in ({},{'TEBB_CLOUD_URL':ENV['TEBB_CLOUD_URL']},
                    ENV|{'TEBB_CLOUD_URL':'https://YOUR_PROJECT_REF.supabase.co'},
                    ENV|{'TEBB_CLOUD_PUBLISHABLE_KEY':'sb_publishable_REPLACE_ME'}):
            with self.subTest(env=list(env)),self.assertRaises(CloudError):preflight(env=env)

    def test_https_and_loopback_only_without_url_credentials_or_paths(self):
        for url in ('http://remote.example','file:///tmp/cloud','https://u:secret@example.com',
                    'https://example.com/path','https://example.com?token=private','https://example.com#fragment',
                    'https://example.com:bad','https://example.com:\n443','https://example.com:'):
            with self.subTest(url=url),self.assertRaises(CloudError):CloudConfig(url,KEY)
        for url in ('https://cloud.example/','http://127.0.0.1:54321','http://[::1]:54321','http://localhost:54321'):
            self.assertEqual(CloudConfig(url,KEY).url,url.rstrip('/'))

    def test_client_configuration_rejects_privileged_keys_and_accepts_legacy_anon(self):
        def jwt(role):
            payload=base64.urlsafe_b64encode(json.dumps({'role':role}).encode()).decode().rstrip('=')
            return 'e30.'+payload+'.signature'
        self.assertEqual(CloudConfig(ENV['TEBB_CLOUD_URL'],jwt('anon')).publishable_key,jwt('anon'))
        for key in ('sb_secret_'+'x'*30,jwt('service_role'),jwt('authenticated'),TOKEN,None):
            with self.subTest(key_type=type(key)),self.assertRaises(CloudError):CloudConfig(ENV['TEBB_CLOUD_URL'],key)
        self.assertNotIn(KEY,repr(CloudConfig.from_env(ENV)))

    def test_public_key_never_substitutes_for_user_login(self):
        cloud=PersonalizationCloud(CloudConfig.from_env(ENV))
        self.addCleanup(cloud.close)
        with self.assertRaises(CloudError) as error:cloud.verify_session()
        self.assertEqual(error.exception.code,'needs_login')

    def test_no_rpc_is_allowed_before_server_identity_verification(self):
        cloud,seen,_=self.client()
        with self.assertRaises(CloudError) as error:cloud.status()
        self.assertEqual(error.exception.code,'needs_verification');self.assertEqual(seen,[])
        self.assertEqual(cloud.verify_session(),A);self.assertEqual(cloud.status()['user_id'],A)
        self.assertEqual(seen[0].url.path,'/auth/v1/user');self.assertEqual(seen[0].headers['Authorization'],'Bearer '+TOKEN)
        self.assertNotIn('user_id',json.loads(seen[1].content))

    def test_preflight_without_a_session_checks_auth_only_without_sending_a_login_email(self):
        _,seen,transport=self.client()
        value=preflight(connect=True,env=ENV,client=transport)
        self.assertEqual(value['status'],'needs_login');self.assertFalse(value['deployment_checked'])
        self.assertEqual([(r.method,r.url.path) for r in seen],[('GET','/auth/v1/settings')])
        self.assertNotIn('Authorization',seen[0].headers)

    def test_read_only_connected_preflight_validates_auth_contract_and_sync_page(self):
        _,seen,transport=self.client()
        value=preflight(connect=True,env=ENV|{'TEBB_CLOUD_ACCESS_TOKEN':TOKEN},client=transport)
        self.assertEqual(value['status'],'ready');self.assertTrue(value['read_only'])
        self.assertEqual([r.url.path for r in seen],['/auth/v1/settings','/auth/v1/user',
                         '/rest/v1/rpc/tebb_personalization_status','/rest/v1/rpc/tebb_personalization_pull'])
        report=json.dumps(value);self.assertNotIn(TOKEN,report);self.assertNotIn(KEY,report);self.assertNotIn(A,report)

    def test_disabled_email_and_invalid_auth_endpoint_are_not_ready(self):
        for settings,code in [({'external':{'email':False}},'email_disabled'),({},'invalid_response')]:
            _,_,transport=self.client(handler=lambda _:httpx.Response(200,json=settings))
            with self.assertRaises(CloudError) as error:preflight(connect=True,env=ENV,client=transport)
            self.assertEqual(error.exception.code,code)

    def test_identity_mismatch_invalidates_the_client_before_any_more_requests(self):
        cloud,seen,_=self.client(responses={'status':{'user_id':B}});cloud.verify_session()
        with self.assertRaises(CloudError) as error:cloud.status()
        self.assertEqual(error.exception.code,'identity_mismatch');count=len(seen)
        with self.assertRaises(CloudError):cloud.pull()
        self.assertEqual(len(seen),count)

    def test_invalid_user_and_contract_responses_cannot_become_ready(self):
        for value in ({'contract':'old','user_id':A,'revision':0,'pgvector':True},
                      {'contract':'tebb.personalization.v2','user_id':A,'revision':True,'pgvector':True},
                      {'contract':'tebb.personalization.v2','user_id':A,'revision':0,'pgvector':False}):
            cloud,_,_=self.client(responses={'status':value});cloud.verify_session()
            with self.assertRaises(CloudError):cloud.status()
        cloud,_,_=self.client(handler=lambda _:httpx.Response(200,json={'id':'unverified-name'}))
        with self.assertRaises(CloudError):cloud.verify_session()

    def test_redirects_are_not_followed_and_error_bodies_never_leak_credentials(self):
        for code in (302,401,403,404,429,500):
            cloud,seen,_=self.client(handler=lambda _:httpx.Response(code,text=TOKEN+KEY,
                                               headers={'Location':'https://unexpected.example'}))
            with self.assertRaises(CloudError) as error:cloud.verify_session()
            self.assertNotIn(TOKEN,str(error.exception));self.assertNotIn(KEY,str(error.exception));self.assertEqual(len(seen),1)

    def test_expired_session_revokes_previously_verified_identity(self):
        def serve(request):
            return httpx.Response(200,json={'id':A}) if request.url.path=='/auth/v1/user' else httpx.Response(401)
        cloud,seen,_=self.client(handler=serve);cloud.verify_session()
        with self.assertRaises(CloudError):cloud.status()
        count=len(seen)
        with self.assertRaises(CloudError):cloud.pull()
        self.assertEqual(len(seen),count)

    def test_timeout_never_retries_a_write_and_caller_can_query_the_same_operation_id(self):
        def serve(request):
            if request.url.path.endswith('/user'):return httpx.Response(200,json={'id':A})
            if request.url.path.endswith('_apply'):raise httpx.ReadTimeout(TOKEN,request=request)
            return httpx.Response(200,json={'user_id':A,'found':True,'receipt':receipt()})
        cloud,seen,_=self.client(handler=serve);cloud.verify_session()
        with self.assertRaises(CloudError) as error:cloud.apply(OP,RECORD,0,'put',{'text':'confirmed'})
        self.assertEqual(error.exception.code,'connection_failed');self.assertNotIn(TOKEN,str(error.exception))
        self.assertEqual(sum(r.url.path.endswith('_apply') for r in seen),1)
        self.assertEqual(cloud.operation(OP)['receipt']['operation_id'],OP)

    def test_conflicts_remain_explicit_and_apply_preserves_original_operation_id(self):
        value=receipt();value.update(status='conflict',version=2)
        cloud,seen,_=self.client(responses={'apply':value});cloud.verify_session()
        self.assertEqual(cloud.apply(OP,RECORD,1,'put',{'text':'confirmed'})['status'],'conflict')
        self.assertEqual(json.loads(seen[-1].content)['p_operation_id'],OP)
        self.assertEqual(json.loads(seen[-1].content)['p_expected_version'],1)

    def test_missing_operation_is_a_query_result_and_malformed_receipts_are_not_success(self):
        cloud,_,_=self.client(responses={'operation':{'user_id':A,'found':False,'receipt':None}});cloud.verify_session()
        self.assertFalse(cloud.operation(OP)['found'])
        for changes in ({'status':'success'},{'record_id':B},{'operation_id':B},{'version':True},{'version':0},{'cursor':-1}):
            value=receipt();value.update(changes)
            cloud,_,_=self.client(responses={'apply':value});cloud.verify_session()
            with self.assertRaises(CloudError):cloud.apply(OP,RECORD,0,'put',{})

    def test_sync_page_validation_stops_bad_cursors_and_deleted_content(self):
        bad_pages=[page(cursor=-1),page(cursor=2),page(cursor=0,head=1),page(has_more=True,cursor=0),
                   page(records=[row(sequence=2)]),page(records=[row(),row()]),page(records=[row(version=True)]),
                   page(records=[row(state='deleted',text='must not remain')]),page(records='wrong'),
                   page(records=[row(text=None)]),page(records=[row(scope_id='another-project')]),
                   page(records=[],has_more=True,cursor=1,head=2),page(has_more=True,cursor=2,head=3)]
        for value in bad_pages:
            cloud,_,_=self.client(responses={'pull':value});cloud.verify_session()
            with self.subTest(value=value),self.assertRaises(CloudError):cloud.pull()
        cloud,_,_=self.client();cloud.verify_session();self.assertEqual(cloud.pull()['cursor'],1)

    def test_invalid_mutation_arguments_make_no_network_requests(self):
        cloud,seen,_=self.client();cloud.verify_session();count=len(seen)
        for args in [(OP,RECORD,-1,'put',{}),(OP,RECORD,False,'put',{}),(OP,RECORD,0,'unknown',{}),
                     (OP,RECORD,0,'delete',{}),('invalid',RECORD,0,'put',{})]:
            with self.assertRaises(CloudError):cloud.apply(*args)
        self.assertEqual(len(seen),count)

    def test_injected_transport_remains_owned_by_the_caller(self):
        cloud,_,transport=self.client()
        cloud.close();self.assertFalse(transport.is_closed)

    def test_acceptance_without_live_flag_or_test_project_never_connects(self):
        from scripts import eval_personalization_cloud as evaluation
        for argv in (['eval'],['eval','--live']):
            output=io.StringIO()
            with patch('sys.argv',argv),patch.dict(os.environ,{},clear=True),redirect_stdout(output), \
                 patch.object(evaluation,'PersonalizationCloud',side_effect=AssertionError('unexpected client')):
                self.assertEqual(evaluation.main(),2)
            self.assertEqual(json.loads(output.getvalue())['status'],'not_run')

    def test_acceptance_cannot_overwrite_an_existing_reconciliation_report(self):
        from scripts import eval_personalization_cloud as evaluation
        with tempfile.TemporaryDirectory() as folder:
            report=Path(folder)/'run.json';report.write_text('pending operation to reconcile','utf-8')
            with patch('sys.argv',['eval','--live','--report',str(report)]), \
                 patch.dict(os.environ,{'TEBB_CLOUD_TEST_PROJECT':'1'}),redirect_stdout(io.StringIO()), \
                 patch.object(evaluation,'PersonalizationCloud',side_effect=AssertionError('unexpected client')):
                self.assertEqual(evaluation.main(),2)
            self.assertEqual(report.read_text('utf-8'),'pending operation to reconcile')


if __name__=='__main__':unittest.main()
