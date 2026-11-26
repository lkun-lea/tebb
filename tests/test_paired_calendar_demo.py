"""在独立账号目录验证手机日程写入，覆盖中转、撤权及回执丢失后的重试。"""
import os
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from desk_companion.local_api.paired_workspace import apply_request, create_calendar_entry, seal, unseal
from desk_companion.planning.scheduling import SchedulingService
from desk_companion.planning.work_board import WorkBoardService
from tests.schedule_fixture import END, START, TimeCalendar



class PairedCalendarDemo(unittest.TestCase):
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
