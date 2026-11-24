"""Real loopback HTTP, SSE, SQLite tasks and child processes; no remote writes."""
import asyncio
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import uvicorn

from desk_companion.local_api import server
from desk_companion.local_api.http_api import create_app
from desk_companion.local_api.host import HeadlessApp
from desk_companion.tasks.manager import TaskManager


class HttpApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = patch.dict(os.environ, DESK_COMPANION_DATA_DIR=self.temp.name)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.host = HeadlessApp()
        self.host._tasks = TaskManager(command=[sys.executable, '-u', '-m', 'tests.http_worker_fixture'])
        self.addCleanup(self.host._tasks.shutdown)
        patcher = patch.object(server, 'HOST', self.host)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.backend = SimpleNamespace(HOST=self.host, TOKEN='http-test-token', SHUTDOWN=asyncio.Event(),
            _dispatch=server._dispatch, _pet_asset=server._pet_asset, _news_cover=server._news_cover)
        sock = socket.socket()
        sock.bind(('127.0.0.1', 0))
        self.port = sock.getsockname()[1]
        self.service = uvicorn.Server(uvicorn.Config(create_app(self.backend), log_level='error', lifespan='off',
                                                   timeout_graceful_shutdown=1))
        self.thread = threading.Thread(target=lambda: self.service.run(sockets=[sock]), daemon=True)
        self.thread.start()
        for _ in range(200):
            if self.service.started:
                break
            await asyncio.sleep(.02)
        self.assertTrue(self.service.started)
        self.client = httpx.AsyncClient(base_url=f'http://127.0.0.1:{self.port}', trust_env=False,
            headers={'Authorization': 'Bearer http-test-token'}, timeout=15)

    async def asyncTearDown(self):
        await self.client.aclose()
        self.service.should_exit = True
        await asyncio.to_thread(self.thread.join, 5)
        self.assertFalse(self.thread.is_alive())

    def command(self, request_id='request-0001', **extra):
        return dict(request_id=request_id, text='fixture', sampling=dict(reasoning_effort='low', temperature=.5, top_p=1), **extra)

    async def submit(self, **extra):
        response = await self.client.post('/v1/runs', json=self.command(**extra))
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()['run_id']

    async def wait(self, ident):
        return await asyncio.to_thread(self.host.tasks.wait, ident)

    async def test_auth_whitelist_origin_and_preview_scope(self):
        self.assertEqual((await self.client.get('/health')).text, 'ok\n')
        for path in ['/rpc', '/v1/runs']:
            denied = await self.client.post(path, json={'method': 'account_session'} if path == '/rpc' else self.command(),
                headers={'Authorization': 'Bearer wrong'})
            self.assertEqual(denied.status_code, 401)
        result = await self.client.post('/rpc', json=dict(method='account_session'))
        self.assertTrue(result.json()['ok'])
        denied = await self.client.post('/rpc', json=dict(method='__getattribute__', args={'name': 'state'}))
        self.assertFalse(denied.json()['ok'])
        cors = await self.client.options('/rpc', headers={'Origin': 'https://evil.invalid', 'Access-Control-Request-Method': 'POST'})
        self.assertEqual(cors.status_code, 400)
        with patch('desk_companion.collaboration.collaboration_access.preview_allowed', return_value=True):
            denied = await self.client.post('/rpc', json=dict(method='account_session'), headers={'Authorization': 'Bearer preview'})
            self.assertEqual(denied.status_code, 403)
            denied = await self.client.post('/v1/runs', json=self.command(), headers={'Authorization': 'Bearer preview'})
            self.assertEqual(denied.status_code, 401)

    async def test_cloud_chat_owner_receipt_and_reconnect(self):
        subject = '298f6350-ef97-4880-92aa-ec278adbb532'
        body = dict(request_id='9e721147-2cf4-48d3-af79-c6ff013a2f59', text='fixture')
        with patch.dict(os.environ, TEBB_CHAT_OWNER=subject, TEBB_CLOUD_URL='https://test.invalid',
                        TEBB_CLOUD_PUBLISHABLE_KEY='sb_publishable_' + 'a'*20), patch(
                'desk_companion.accounts.personalization_cloud.PersonalizationCloud.verify_session') as verify:
            verify.return_value = 'other'
            self.assertEqual((await self.client.post('/cloud/v1/messages', json=body)).status_code, 403)
            verify.return_value = subject
            receipts = [await self.client.post('/cloud/v1/messages', json=body) for _ in range(2)]
            self.assertEqual(receipts[0].status_code, 200, receipts[0].text)
            self.assertEqual(receipts[0].json(), receipts[1].json())
            run = receipts[0].json()['run_id']
            self.assertEqual((await self.client.post('/cloud/v1/messages', json={**body,'text':'other'})).status_code,409)
            await self.wait(run)
            from desk_companion.local_api.cloud_chat import recent
            self.assertEqual(recent(self.host.tasks, subject, 'different-chat'), [])
            self.assertTrue((await self.client.get('/cloud/v1/tools')).json()['tools'])
            for _ in range(2):
                async with self.client.stream('GET','/cloud/v1/events') as response:
                    async for line in response.aiter_lines():
                        if line.startswith('data: ') and (event := json.loads(line[6:]))['type'] == 'turn':
                            self.assertEqual(event['data']['id'], run)
                            self.assertEqual(event['data']['answer'], '隔离片段完成')
                            break
                    else:
                        self.fail('缺少持久化回复')
            with patch('desk_companion.local_api.desktop_cloud_chat.ORIGIN', f'http://127.0.0.1:{self.port}'), patch.object(
                    self.host.accounts, 'cloud_client') as lease:
                lease.return_value.__enter__.return_value.chat_authorization.return_value = {'Authorization':'Bearer test-user'}
                relay = await self.client.post('/desktop/cloud/messages', json=body)
                self.assertEqual(relay.json(), receipts[0].json())
                async with self.client.stream('GET','/desktop/cloud/events') as response:
                    self.assertEqual(response.status_code, 200)
                    async for line in response.aiter_lines():
                        if line.startswith('data: ') and (event := json.loads(line[6:]))['type'] == 'turn':
                            self.assertEqual(event['data']['answer'], '隔离片段完成')
                            break
                    else:
                        self.fail('PC 未收到云端回复')
            verify.return_value = 'other'
            self.assertEqual((await self.client.get('/cloud/v1/events')).status_code, 403)

    async def test_atomic_dedup_conflict_replay_and_snapshot_watermark(self):
        ids = await asyncio.gather(*[self.submit() for _ in range(5)])
        self.assertEqual(len(set(ids)), 1)
        ident = ids[0]
        # Changed sampling/model/docs must conflict, even with identical text.
        for field in [dict(model_id='other'), dict(knowledge=True), dict(chips={'skills': ['changed']})]:
            conflict = await self.client.post('/v1/runs', json=self.command(**field))
            self.assertEqual(conflict.status_code, 409)
        await self.wait(ident)
        events = await self.client.get(f'/v1/runs/{ident}/events')
        rows = [json.loads(line[6:]) for line in events.text.splitlines() if line.startswith('data: ')]
        self.assertEqual(rows[-1]['type'], 'settled')
        self.assertEqual(rows[-1]['data']['task']['state'], 'succeeded')
        seqs = [int(line[4:]) for line in events.text.splitlines() if line.startswith('id: ')]
        self.assertEqual(seqs, sorted(set(seqs)))
        tail = await self.client.get(f'/v1/runs/{ident}/events', headers={'Last-Event-ID': str(seqs[-1])})
        self.assertNotIn('id: ', tail.text)
        for i in range(515):
            self.host.tasks.event(ident, 'status', f'fixture-{i}')
        expired = await self.client.get(f'/v1/runs/{ident}/events?after=1')
        self.assertIn('"type": "snapshot"', expired.text)
        snap = json.loads(next(line[6:] for line in expired.text.splitlines() if line.startswith('data: ')))['data']
        self.assertEqual(snap['task']['answer'], '隔离片段完成')
        self.assertEqual(snap['cursor'], snap['events'][-1]['seq'])
        # A lost response retried after switching selection still finds the same run.
        self.host.state.session_id = 'other-selection'
        self.assertEqual(await self.submit(), ident)
        previous = self.host.tasks
        previous.shutdown()
        self.host._tasks = TaskManager(path=previous.path, command=previous.command)
        self.addCleanup(self.host._tasks.shutdown)
        self.assertEqual(await self.submit(), ident)
        with self.host.tasks.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM tasks').fetchone()[0], 1)
        self.host.tasks.event(ident, 'answer_reset', True)
        pending = self.host.tasks.event_snapshot(ident, 1)
        self.assertTrue(pending['replace_pending'])
        self.assertEqual(pending['task']['answer'], '隔离片段完成')
        self.host.tasks.event(ident, 'token', 'replacement', replace_answer=True)
        replaced = self.host.tasks.event_snapshot(ident, 1)
        self.assertFalse(replaced['replace_pending'])
        self.assertEqual(replaced['task']['answer'], 'replacement')

    async def test_disconnect_does_not_cancel_explicit_cancel_cleans_worker(self):
        command = self.command(request_id='cancel-request')
        command['text'] = 'wait'
        response = await self.client.post('/v1/runs', json=command)
        ident = response.json()['run_id']
        async with self.client.stream('GET', f'/v1/runs/{ident}/events') as stream:
            async for line in stream.aiter_lines():
                if '隔离片段' in line:
                    break
        self.assertIn(self.host.tasks.get(ident)['state'], {'queued', 'running'})
        stopped = await self.client.post(f'/v1/runs/{ident}/cancel')
        self.assertTrue(stopped.json()['ok'])
        result = await self.wait(ident)
        self.assertEqual(result['state'], 'cancelled')
        self.assertEqual(result['answer'], '隔离片段')
        self.assertFalse(any(event['kind'] == 'think' for event in result['events']))
        for _ in range(100):
            if ident not in self.host.tasks.active:
                break
            await asyncio.sleep(.05)
        self.assertNotIn(ident, self.host.tasks.active)

    async def test_notebook_lost_ack_uses_same_task_and_saves_question_once(self):
        from desk_companion.knowledge import notebook
        book = notebook.new_notebook()
        session = book['session_id']
        ident = await self.submit(kind='notebook', session_id=session, doc_ids=[])
        self.assertEqual(await self.submit(kind='notebook', session_id=session, doc_ids=[]), ident)
        result = await self.wait(ident)
        self.assertEqual(result['state'], 'succeeded', result)
        events = await self.client.get(f'/v1/runs/{ident}/events')
        self.assertIn('HTTP笔记完整回答', events.text)
        page = notebook.load_notebook()
        turns = next(row['turns'] for row in page['sessions'] if row['id'] == session)
        self.assertEqual(len(turns), 2)
        self.assertEqual(turns[0]['text'], 'fixture')
        self.assertEqual(turns[1]['text'], 'HTTP笔记完整回答。')

    async def test_parent_worker_http_preserves_terminal_arguments(self):
        from desk_companion.local_api.worker_rpc import request
        received = []
        def dispatch(method, args, preview=False):
            received.append((method, args, preview))
            return dict(ok=True, result=dict(offset=args['offset'], data='YWJj', job={'state': 'running'}))
        self.backend._dispatch = dispatch
        value = await asyncio.to_thread(request, self.port, 'http-test-token', 'terminal_read', {'job_id': 'original', 'offset': 42})
        self.assertEqual(value['offset'], 42)
        self.assertEqual(received, [('terminal_read', {'job_id': 'original', 'offset': 42}, False)])

    async def test_preview_subscription_revoked_before_next_frame_and_unsubscribed(self):
        callbacks, removed = [], []
        valid = [True]
        def subscribe(callback):
            callbacks.append(callback)
            return lambda: removed.append(True)
        self.host._collaboration = SimpleNamespace(subscribe_stream=subscribe)
        with patch('desk_companion.collaboration.collaboration_access.preview_allowed', side_effect=lambda *_:valid[0]):
            async with self.client.stream('GET', '/v1/notifications',
                    headers={'Authorization':'Bearer preview','Origin':'http://localhost:5180'}) as response:
                self.assertEqual(response.status_code, 200)
                callbacks[0]('original-run', 'visible', 1, 1)
                lines = response.aiter_lines()
                while True:
                    if 'visible' in await anext(lines):
                        break
                valid[0] = False
                callbacks[0]('original-run', 'forbidden-after-expiry', 1, 2)
                remaining = [line async for line in lines]
                self.assertFalse(any('forbidden' in line for line in remaining))
        self.assertEqual(removed, [True])

    async def test_terminal_http_calls_reuse_real_service_records_and_controls(self):
        import base64
        from desk_companion.projects import terminal
        manager = terminal.TerminalManager()
        self.addCleanup(manager.shutdown)
        ident = 'b' * 32
        folder = terminal.root() / 'jobs' / ident
        folder.mkdir(parents=True)
        (folder / 'output.bin').write_bytes('中文 output'.encode())
        (folder / 'input.jsonl').touch()
        manager.jobs[ident] = dict(id=ident,state='running',session='fixture',created=1,output_bytes=13)
        with patch('desk_companion.projects.terminal.manager', return_value=manager):
            async def rpc(method, **args):
                result = (await self.client.post('/rpc', json=dict(method=method,args=args))).json()
                self.assertTrue(result['ok'], result)
                return result['result']
            data = await rpc('terminal_read', job_id=ident, offset=3)
            self.assertEqual(base64.b64decode(data['data']), '中文 output'.encode()[3:])
            self.assertEqual(data['offset'], len('中文 output'.encode()))
            self.assertTrue((await rpc('terminal_input', job_id=ident,text='echo fixture\n'))['ok'])
            self.assertTrue((await rpc('terminal_input', job_id=ident,cols=100,rows=30))['ok'])
            controls = [json.loads(row) for row in (folder/'input.jsonl').read_text().splitlines()]
            self.assertEqual(base64.b64decode(controls[0]['data']), b'echo fixture\n')
            self.assertEqual(controls[1]['size'], [100,30])
            self.assertEqual((await rpc('terminal_cancel', job_id=ident))['job']['state'], 'stopping')
            self.assertTrue((folder/'stop').exists())

    async def test_partner_board_change_refreshes_real_sse_and_releases_listener(self):
        created = self.host.work_board.change(dict(type='create',request_id='partner-board-create',fields=dict(title='partner item')))
        item = created['items'][0]
        async with self.client.stream('GET', '/v1/notifications?topic=board') as response:
            lines = response.aiter_lines()
            while 'work_board_changed' not in await anext(lines):
                pass
            changed = self.host.work_board.change(dict(type='move',request_id='partner-board-move',id=item['id'],
                version=item['version'],state='review'), project_id='')
            self.assertTrue(changed['ok'])
            while 'work_board_changed' not in await anext(lines):
                pass
            page = (await self.client.post('/rpc',json=dict(method='load_work_board'))).json()['result']
            self.assertEqual(page['items'][0]['state'], 'review')
        for _ in range(100):
            if not self.host.work_board._change_listeners:
                break
            await asyncio.sleep(.01)
        self.assertFalse(self.host.work_board._change_listeners)
        self.assertIsNone(self.host._collaboration, 'Board-only subscriptions must not construct collaboration managers')
