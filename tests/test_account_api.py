import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from websockets.asyncio.client import connect
from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

from desk_companion.account_store import AccountRuntime,AccountStore
from desk_companion.accounts import AccountService
from desk_companion.personalization import PersonalizationService
from desk_companion.bridge import Bridge
from desk_companion.local_api import server
from test_accounts import TestCipher,AuthFixture


class AccountApiTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        home=Path(self.temp.name).resolve()
        self.service=AccountService(AccountRuntime(home,'local',home),store=AccountStore(home,cipher=TestCipher()),auth=AuthFixture().adapter(),env={})
        self.host=SimpleNamespace(accounts=self.service,state=SimpleNamespace(session_id='isolated'),turn_lock=threading.RLock())
        self.host.personalization=PersonalizationService(self.service)
        self.addCleanup(self.host.personalization.shutdown)
        self.host.bridge=Bridge(self.host)

    async def test_authenticated_account_rpc_returns_public_state_while_model_turn_is_locked(self):
        with patch.object(server,'HOST',self.host),ThreadPoolExecutor(max_workers=1) as executor:
            self.host.turn_lock.acquire()
            try:
                value=executor.submit(server._dispatch,'account_session',{}).result(3)
            finally:self.host.turn_lock.release()
        self.assertTrue(value['ok']);self.assertEqual(value['result']['runtime']['key'],'local')
        self.assertNotIn('access_token',json.dumps(value))

    async def test_real_websocket_keeps_local_process_authentication(self):
        with patch.object(server,'HOST',self.host),patch.object(server,'TOKEN','account-test-token'):
            async with serve(server._handler,'127.0.0.1',0) as running:
                port=running.sockets[0].getsockname()[1]
                async with connect(f'ws://127.0.0.1:{port}/ws?token=wrong') as ws:
                    with self.assertRaises(ConnectionClosed):await ws.recv()
                    self.assertEqual(ws.close_code,4401)
                async with connect(f'ws://127.0.0.1:{port}/ws?token=account-test-token') as ws:
                    await ws.send(json.dumps(dict(type='rpc',id='request',method='account_session')))
                    reply=json.loads(await ws.recv());self.assertTrue(reply['result']['ok'])
                    self.assertEqual(reply['result']['result']['runtime']['key'],'local')

    async def test_browser_collaboration_capability_cannot_query_or_mutate_accounts(self):
        with patch.object(server,'HOST',self.host),patch('desk_companion.collaboration_access.preview_allowed',return_value=True):
            async with serve(server._handler,'127.0.0.1',0) as running:
                port=running.sockets[0].getsockname()[1]
                async with connect(f'ws://127.0.0.1:{port}/collaboration?token=preview-only') as ws:
                    for method in ('account_session','account_action','personalization_status','personalization_action'):
                        await ws.send(json.dumps(dict(type='rpc',id=method,method=method,args={})))
                        reply=json.loads(await ws.recv());self.assertEqual(reply['type'],'error')
                        self.assertNotIn('accounts',reply)
        self.assertEqual(self.service.status()['version'],0)

    async def test_profile_rpc_is_authenticated_observable_and_does_not_wait_for_model_turn(self):
        with patch.object(server,'HOST',self.host),ThreadPoolExecutor(max_workers=1) as executor:
            self.host.turn_lock.acquire()
            try:value=executor.submit(server._dispatch,'personalization_status',{}).result(3)
            finally:self.host.turn_lock.release()
        self.assertTrue(value['result']['ok']);self.assertEqual(value['result']['mode'],'local')
        with patch.object(server,'HOST',self.host),patch.object(server,'TOKEN','profile-test-token'):
            async with serve(server._handler,'127.0.0.1',0) as running:
                port=running.sockets[0].getsockname()[1]
                async with connect(f'ws://127.0.0.1:{port}/ws?token=profile-test-token') as ws:
                    await ws.send(json.dumps(dict(type='rpc',id='profile-status',method='personalization_status')))
                    reply=json.loads(await ws.recv())
                    self.assertEqual(reply['result']['result']['records'],[])
                    await ws.send(json.dumps(dict(type='rpc',id='profile-write',method='personalization_action',
                        args=dict(payload=dict(type='sync',request_id='a0000000-0000-4000-8000-000000000001')))))
                    reply=json.loads(await ws.recv());result=reply['result']['result']
                    self.assertFalse(result['ok']);self.assertEqual(result['code'],'needs_login')
                    self.assertFalse(result['accepted'])
