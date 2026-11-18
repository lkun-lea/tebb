import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
from tests import test_http_api as fixture
from desk_companion.observability.tool_monitor import ToolMonitor


class ExecutionHttpTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=fixture.HttpApiTests.asyncSetUp
    asyncTearDown=fixture.HttpApiTests.asyncTearDown

    async def test_full_token_rpc_and_cli_share_tool_records_and_preview_is_denied(self):
        tools=ToolMonitor();tools.register([dict(name='web_fetch',description='Isolated fixture',parameters=dict(type='object',properties={}))])
        tools.event('intercept',ident='safe-failure',tool='web_fetch',root='task:fixture',error_kind='budget_denied',state='rejected')
        command=dict(method='execution_inspect',args=dict(operation='tools'))
        result=await self.client.post('/rpc',json=command)
        self.assertTrue(result.json()['ok']);self.assertEqual(result.json()['result']['items'][0]['id'],'safe-failure')
        with patch('desk_companion.collaboration.collaboration_access.preview_allowed',return_value=True):
            for method in ('execution_inspect','agent_evaluation'):
                denied=await self.client.post('/rpc',json=dict(method=method,args=dict(operation='list')),headers={'Authorization':'Bearer preview'})
                self.assertEqual(denied.status_code,403)
        env={**os.environ,'DESK_COMPANION_API_URL':f'http://127.0.0.1:{self.port}','DESK_COMPANION_API_TOKEN':'http-test-token'}
        completed=subprocess.run([sys.executable,'scripts/agent_inspect.py','execution','tools'],capture_output=True,text=True,encoding='utf-8',env=env,timeout=15)
        self.assertEqual(completed.returncode,0,completed.stderr)
        self.assertEqual(json.loads(completed.stdout),result.json())
        self.assertNotIn('http-test-token',completed.stdout)

    async def test_case_versions_are_same_through_authenticated_save_and_query(self):
        value=dict(id='http-golden',prompt='Return exactly JSON {"total":7}.',expected=dict(total=7),source_failure='safe-failure')
        result=await self.client.post('/rpc',json=dict(method='agent_evaluation',args=dict(operation='save_case',payload=dict(value=value))))
        self.assertTrue(result.json()['ok'],result.text)
        case=result.json()['result']['case']
        queried=await self.client.post('/rpc',json=dict(method='agent_evaluation',args=dict(operation='cases')))
        self.assertIn(case,queried.json()['result']['items'])
        unsafe=await self.client.post('/rpc',json=dict(method='agent_evaluation',args=dict(operation='save_case',payload=dict(value={**value,'python':'import os'}))))
        self.assertFalse(unsafe.json()['ok'])

    async def test_recorded_model_failure_can_become_data_only_draft(self):
        from desk_companion.observability.usage_store import UsageStore
        store=UsageStore();store.begin('model-failure','model',dict(root='operation:fixture',model='fixture'))
        store.update('model-failure',state='failed',error_kind='TimeoutError')
        response=await self.client.post('/rpc',json=dict(method='agent_evaluation',args=dict(operation='draft_failure',payload=dict(event_id='model-failure'))))
        self.assertTrue(response.json()['ok'],response.text)
        value=response.json()['result'];self.assertEqual(value['draft']['source_failure'],'model-failure')
        self.assertIsNone(value['draft']['expected']);self.assertFalse(value['ready'])

    async def test_evaluation_and_trace_exports_share_credential_redaction(self):
        value=dict(id='redacted-case',prompt='Synthetic Bearer private-fixture-token',expected='https://object.test/file?X-Goog-Signature=private-signature')
        response=await self.client.post('/rpc',json=dict(method='agent_evaluation',args=dict(operation='save_case',payload=dict(value=value))))
        self.assertTrue(response.json()['ok'],response.text)
        self.assertNotIn('private-fixture-token',response.text);self.assertNotIn('private-signature',response.text)
        tools=ToolMonitor();tools.register([dict(name='web_fixture',description='Bearer private-tool-token',parameters=dict(type='object',properties={}))])
        response=await self.client.post('/rpc',json=dict(method='execution_inspect',args=dict(operation='tools')))
        self.assertTrue(response.json()['ok']);self.assertNotIn('private-tool-token',response.text)
