"""在独立账号目录验证手机日程写入，覆盖中转、撤权及回执丢失后的重试。"""
import os
import base64
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4
import httpx

from desk_companion.local_api.paired_workspace import apply_request, create_calendar_entry, exchange, seal, unseal
from desk_companion.planning.scheduling import SchedulingService
from desk_companion.planning.work_board import WorkBoardService
from tests.schedule_fixture import END, START, TimeCalendar



class PairedCalendarDemo(unittest.TestCase):
    def test_model_config_is_only_in_the_authorized_devices_encrypted_snapshot(self):
        device, key = uuid4().hex, os.urandom(32)
        item = dict(id='active', base_url='https://model.example/v1', model='demo', api_key='fixture-model-secret')
        snapshots = []
        def relay(request):
            if request.method == 'GET':
                return httpx.Response(200, json={'sealed': None})
            self.assertNotIn(item['api_key'].encode(), request.content)
            snapshots.append(unseal(key, device, 'windows', json.loads(request.content)['sealed']))
            return httpx.Response(200)
        client = httpx.Client
        with tempfile.TemporaryDirectory() as folder:
            record = Path(folder) / 'device.json'
            pair = SimpleNamespace(lock=threading.RLock(), account='demo', record=record, active=lambda:True,
                                   collaboration=lambda:SimpleNamespace(mobile_workspace=lambda shared:dict(questions=[])))
            with patch('httpx.Client', side_effect=lambda **kw:client(transport=httpx.MockTransport(relay), **kw)), \
                    patch('desk_companion.models.model_catalog.load_catalog', return_value=dict(active='active', items=[item])):
                for grants in ([], ['model.share'], []):
                    record.write_text(json.dumps(dict(id=device, account='demo', relay_key=base64.b64encode(key).decode(), write_grants=grants)))
                    exchange(pair, dict)
            self.assertNotIn('chat_model', snapshots[0])
            self.assertEqual(snapshots[1]['chat_model'], {k:item[k] for k in ('model','base_url','api_key')})
            self.assertNotIn('chat_model', snapshots[2])

    def test_exchange_publishes_calendar_ack_and_reuses_it(self):
        device, key = uuid4().hex, os.urandom(32)
        request = dict(id=str(uuid4()), time=int(time.time()), action='calendar.create', summary='评审', start=START, end=END)
        published = []
        def relay(http_request):
            if http_request.method == 'GET':
                return httpx.Response(200, json={'sealed': seal(key, device, 'phone', request)})
            published.append(unseal(key, device, 'windows', json.loads(http_request.content)['sealed']))
            return httpx.Response(200, json={'stored': True})
        client = httpx.Client
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, DESK_COMPANION_DATA_DIR=folder):
            path = Path(folder) / 'approved.json'
            path.write_text(json.dumps(dict(account='demo', id=device, relay_key=base64.b64encode(key).decode(),
                                            write_grants=['calendar.create'])), encoding='utf-8')
            pair = SimpleNamespace(lock=threading.RLock(), active=lambda:True, record=path, account='demo',
                                   calendar=SchedulingService(WorkBoardService(), TimeCalendar()).local,
                                   collaboration=lambda:SimpleNamespace(mobile_workspace=lambda shared:dict(questions=[])))
            with patch('httpx.Client', side_effect=lambda **kw:client(transport=httpx.MockTransport(relay), **kw)):
                exchange(pair, dict)
                exchange(pair, dict)
            self.assertEqual(published[0]['ack'], published[1]['ack'])
            self.assertTrue(published[0]['ack']['accepted'])
            self.assertEqual(published[0]['ack']['id'], request['id'])

    def test_revocation_retry_and_desktop_readback(self):
        device, key = uuid4().hex, os.urandom(32)
        request = dict(id=str(uuid4()), action='calendar.create', summary='设计评审', start=START, end=END)
        incoming = unseal(key, device, 'phone', seal(key, device, 'phone', request))
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, DESK_COMPANION_DATA_DIR=folder):
            board = WorkBoardService()
            calendar = SchedulingService(board, TimeCalendar()).local
            with self.assertRaises(PermissionError):
                create_calendar_entry(calendar, set(), device, incoming)
            grant = {'calendar.create'}
            ack = create_calendar_entry(calendar, grant, device, incoming)
            self.assertEqual(create_calendar_entry(calendar, grant, device, incoming), ack)
            with self.assertRaises(ValueError):
                create_calendar_entry(calendar, grant, device, dict(incoming, summary='另一场评审'))
            with self.assertRaises(ValueError):
                create_calendar_entry(calendar, grant, device, dict(incoming, local_id='other'))
            with board.workspace_transaction() as (state, _):
                rows = calendar.records(state)
                self.assertEqual(list(rows), [ack['event']])
                self.assertEqual(rows[ack['event']]['summary'], '设计评审')
            with self.assertRaises(PermissionError):
                create_calendar_entry(calendar, set(), device, incoming)
            options = dict(calendar=calendar, grants=grant)
            def dispatch(action, **fields):
                return apply_request(None, device, dict(action=action, time=100, id=str(uuid4()), **fields), 100, **options)
            row, = dispatch('calendar.list')['events']
            fields = dict(event=ack['event'], version=row['version'], start=START, end=END, summary='修改后的评审')
            self.assertEqual(dispatch('calendar.update', **fields)['version'], row['version']+1)
            with self.assertRaises(ValueError):
                dispatch('calendar.update', **fields)
            with self.assertRaises(ValueError):
                dispatch('calendar.update', **dict(fields, event='other-calendar'))
            foreign = apply_request(None, uuid4().hex, dict(action='calendar.list', time=100, id=str(uuid4())), 100, **options)
            self.assertEqual(foreign['events'], [])

    def test_note_replay_reads_original_handwritten_content(self):
        from desk_companion.knowledge.notebook import _read
        device = uuid4().hex
        request = dict(action='note.create', id=str(uuid4()), time=100, title='评审', body='下午三点复核')
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, DESK_COMPANION_DATA_DIR=folder):
            with self.assertRaises(PermissionError):
                apply_request(None, device, request, 100)
            args = dict(grants={'note.create'})
            ack = apply_request(None, device, request, 100, **args)
            self.assertEqual(apply_request(None, device, request, 100, **args), ack)
            note, = _read()['sessions'][0]['notes']
            self.assertEqual((note['id'], note['answer']), (ack['note'], request['body']))
            with self.assertRaises(ValueError):
                apply_request(None, device, dict(request, body='不同原文'), 100, **args)

    def test_workspace_reads_require_separate_grants_and_project_only_display_fields(self):
        device = uuid4().hex
        request = dict(id=str(uuid4()), time=100)
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, DESK_COMPANION_DATA_DIR=folder):
            apply_request(None, device, dict(request, action='note.create', title='评审', body='确认三十分钟'),
                          100, grants={'note.create'})
            for action in ('note.list', 'knowledge.list', 'automation.list'):
                with self.assertRaises(PermissionError):
                    apply_request(None, device, dict(request, action=action), 100, grants={'note.create'})
            def read(action):
                return apply_request(None, device, dict(request, action=action), 100, grants={action})['rows']
            self.assertEqual(read('note.list')[0]['detail'], '确认三十分钟')
            doc = dict(title='评审参考', source_version='3', updated='2026-11-28', url='private')
            with patch('desk_companion.knowledge.index.indexed_documents', return_value=[doc]):
                self.assertEqual(read('knowledge.list'), [dict(title='评审参考', detail='3', stamp='2026-11-28')])
            job = dict(name='早间简报', enabled=True, last_result='ok', schedule_text='每日 08:30', last_run_slot='08:30')
            with patch('desk_companion.automation.schedule.list_snapshot', return_value={'items':[job]}):
                self.assertEqual(read('automation.list')[0]['result'], '已完成')

    def test_agent_dispatch_requires_both_grants_and_preserves_original_conversation(self):
        from tests.test_execution_flow import ExecutionFlowTests
        flow = ExecutionFlowTests()
        flow.setUp()
        self.addCleanup(flow.tearDown)
        device = uuid4().hex
        request = dict(action='agent.request', id=str(uuid4()), time=100, conversation='dm-tebb', text='帮我整理项目安排')
        for grants, shared in [([], ['dm-tebb']), (['agent.request'], [])]:
            with self.assertRaises(PermissionError):
                apply_request(flow.service, device, request, 100, grants=grants, shared=shared)
        for _ in range(2):
            self.assertTrue(apply_request(flow.service, device, request, 100, grants=['agent.request'],
                                         shared=['dm-tebb'])['accepted'])
        run, = flow.service.snapshot()['state']['runs']
        self.assertEqual(run['conversation'], 'dm-tebb')
