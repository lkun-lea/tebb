import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from tests import test_http_api as http_fixture
from desk_companion.evaluation.self_test import catalog


class SelfTestHttpTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=http_fixture.HttpApiTests.asyncSetUp
    asyncTearDown=http_fixture.HttpApiTests.asyncTearDown

    async def rpc(self,operation,payload=None,**extra):
        response=await self.client.post('/rpc',json=dict(method='agent_self_test',args=dict(operation=operation,payload=payload or {},**extra)))
        self.assertEqual(response.status_code,200,response.text)
        result=response.json();self.assertTrue(result['ok'],result)
        return result['result']

    async def test_cli_rpc_and_model_tool_catalog_share_contract_and_preview_is_denied(self):
        self.assertEqual(await self.rpc('catalog'),catalog())
        with patch('desk_companion.collaboration.collaboration_access.preview_allowed',return_value=True):
            response=await self.client.post('/rpc',json=dict(method='agent_self_test',args=dict(operation='catalog')),headers={'Authorization':'Bearer preview'})
        self.assertEqual(response.status_code,403)
        denied=await self.client.post('/rpc',json=dict(method='agent_self_test',args=dict(operation='catalog')),headers={'Authorization':'Bearer wrong'})
        self.assertEqual(denied.status_code,401)

    async def test_real_authenticated_fixture_batch_and_cli_report_reuse_original_records(self):
        from desk_companion.pi_runtime.bridge import PiBridge
        node=PiBridge().node
        if not node or not Path('desk_companion/evaluation/promptfoo/node_modules').is_dir():
            self.skipTest('Pinned Node/Pi/Promptfoo dependencies required')
        self.addCleanup(self.host.bridge.shutdown_evaluations)
        # Persisted versions, Promptfoo subprocess, product tasks and reports are real; model is local fixture only.
        started=await self.rpc('start',dict(capability='smoke',request_id='selftest-http-smoke'))
        ident=started['batch']['id']
        repeated=await self.rpc('start',dict(capability='smoke',request_id='selftest-http-smoke'))
        self.assertEqual(repeated['batch']['id'],ident);self.assertTrue(repeated['reused'])
        for _ in range(240):
            current=await self.rpc('get',dict(ident=ident))
            if current['batch']['state']not in {'queued','running','cancelling'}:break
            await asyncio.sleep(.5)
        report=await self.rpc('report',dict(ident=ident))
        self.assertTrue(report['passed'],report)
        self.assertEqual(len(report['results']),3)
        env={**os.environ,'DESK_COMPANION_API_URL':f'http://127.0.0.1:{self.port}','DESK_COMPANION_API_TOKEN':'http-test-token'}
        completed=await asyncio.to_thread(subprocess.run,[sys.executable,'scripts/agent_inspect.py','selftest','report','--payload',json.dumps(dict(ident=ident))],
            capture_output=True,text=True,encoding='utf-8',env=env,timeout=20)
        self.assertEqual(completed.returncode,0,completed.stderr)
        self.assertEqual(json.loads(completed.stdout)['result'],report)
        self.assertNotIn('http-test-token',completed.stdout)
        sample=report['results'][0]
        trace=await self.rpc('trace',dict(ident=ident,case_id=sample['case_id']))
        self.assertTrue(trace['ok'])
        cancelled=await self.rpc('cancel',dict(ident=ident))
        self.assertEqual(cancelled['batch']['state'],'completed')

    async def test_active_batch_cancels_through_original_evaluator_and_never_passes(self):
        self.addCleanup(self.host.bridge.shutdown_evaluations)
        started=await self.rpc('start',dict(capability='smoke',request_id='selftest-cancel-0001'))
        ident=started['batch']['id']
        await self.rpc('cancel',dict(ident=ident))
        for _ in range(100):
            current=await self.rpc('get',dict(ident=ident))
            if current['batch']['state']not in {'queued','running','cancelling'}:break
            await asyncio.sleep(.2)
        self.assertEqual(current['batch']['state'],'cancelled',current)
        self.assertFalse((await self.rpc('report',dict(ident=ident)))['passed'])
