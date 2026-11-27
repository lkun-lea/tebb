from datetime import datetime, timedelta
import unittest

from desk_companion.collaboration.store import transaction
from desk_companion.planning.today import today_board
from tests import test_execution_flow as fixtures


class TodayBoardTests(unittest.TestCase):
    def setUp(self):
        self.flow = fixtures.ExecutionFlowTests()
        self.flow.setUp()
        self.addCleanup(self.flow.tearDown)
        self.service = self.flow.service
        self.start = datetime(2026, 11, 26, 6)

    def test_today_choices_match_versioned_chat_form_and_receipt(self):
        run = self.flow.send('确认会议时长')
        self.flow.finish(run['id'], [self.flow.control('request_clarification', question='安排多久？')])
        from desk_companion.collaboration.clarification import pause
        with transaction(self.service.path) as (state, _):
            pending = next(row for row in state['runs'] if row['id'] == run['id'])
            pause(pending, '安排多久？', [dict(id='duration', question='时长', options=[
                dict(id='short',label='15分钟',value='15'),dict(id='long',label='30分钟',value='30')])])
        q, = today_board(self.service)['questions']
        self.assertEqual(q['form'], self.service.execution_status(q['run'])['clarification_form'])
        action = dict(type='clarification_answer', id=q['run'], conversation=q['conversation'],
                      version=q['version'], answers={'duration': {'option_id': 'long'}})
        with self.assertRaises(ValueError):
            self.service.action(dict(action, version='stale', request_id='old-form'))
        self.service.action(dict(action, request_id='current-form'))
        after = today_board(self.service)
        self.assertEqual(after['questions'], [])
        self.assertEqual(after['receipt']['answer'], '补充信息：\n时长：30分钟')

    def test_reply_removes_both_projections_and_preserves_original_message(self):
        run = self.flow.send('今日隔离验收')
        self.flow.finish(run['id'], [self.flow.control('request_clarification', question='评审多久？')])
        with transaction(self.service.path) as (state, _):
            state['projects'].append(dict(id='project', name='项目'))
            next(c for c in state['conversations'] if c['id'] == 'dm-tebb')['project_id'] = 'project'
        config = today_board(self.service)['preferences']
        config['project'] = 'project'
        questions = today_board(self.service, config)['questions']
        self.assertEqual(questions, self.service.mobile_questions())
        q, = questions
        self.service.action(dict(type='send', conversation=q['conversation'], run=q['run'],
                                 question_version=q['version'], text='45min', request_id='today-test'))
        after = today_board(self.service)
        self.assertEqual(after['questions'], [])
        self.assertEqual(after['events'][0]['title'], '开始 · 今日隔离验收')
        receipt = after['receipt']
        self.assertEqual((receipt['run'], receipt['version'], receipt['title'], receipt['answer']),
                         (q['run'], q['version'], q['title'], '45min'))
        shared, = self.service.mobile_workspace([q['conversation']])['history']
        self.assertEqual(shared['today']['receipt'], dict(receipt, truncated=False))
        self.assertEqual(self.service.mobile_workspace([])['history'], [])
        next_day = datetime.fromtimestamp(receipt['accepted']) + timedelta(days=1)
        later = today_board(self.service, now=next_day)
        self.assertNotEqual(later['day'], later['receipt']['day'])
        history, = self.service.shared_history([q['conversation']])
        self.assertEqual(sum(row['text'] == '45min' for row in history['rows']), 1)

    def test_preference_scope_schedule_and_durable_same_day_reports(self):
        run = self.flow.send('可追溯的项目事件')
        with transaction(self.service.path) as (state, _):
            next(r for r in state['runs'] if r['id'] == run['id'])['created'] = self.start.timestamp()
            state['projects'].append(dict(id='p-demo', name='演示'))
            next(c for c in state['conversations'] if c['id']=='dm-tebb')['project_id']='p-demo'
        first = today_board(self.service, now=self.start)
        self.assertEqual(first['reports'], [])
        prefs = dict(first['preferences'], project='p-demo', morning=dict(time='07:00', focus='project'))
        board = today_board(self.service, prefs, now=self.start)
        self.assertEqual(board['events'][0]['source'], run['id'])
        with self.assertRaises(ValueError):
            today_board(self.service, prefs, now=self.start)
        due = self.start.replace(hour=8)
        today_board(self.service, scheduled=True, now=due)
        report = today_board(self.service, now=due)['reports'][0]
        self.assertEqual(report['rows'][0]['conversation'], 'dm-tebb')
        self.assertEqual(report, today_board(self.service, now=due+timedelta(seconds=5))['reports'][0])
        allowed = self.service.mobile_workspace(['dm-tebb'])['history'][0]
        self.assertEqual(allowed['today']['sections']['project'][0]['source'], run['id'])
        self.assertEqual(self.service.mobile_workspace([])['history'], [])
        self.assertNotIn('today_board', self.flow.state())


    def test_evening_keywords_and_empty_report(self):
        run = self.flow.send('项目讨论')
        self.flow.finish(run['id'], [self.flow.control('request_clarification', question='要准备几份材料？')])
        config = today_board(self.service, now=self.start)['preferences']
        config['morning'] = dict(time='07:00', focus='questions', keywords='场地')
        config['evening'] = dict(time='18:00', focus='both', keywords='材料 预算')
        today_board(self.service, config, now=self.start)
        evening = self.start.replace(hour=18)
        reports = today_board(self.service, now=evening)['reports']
        self.assertEqual(len(reports), 2)
        self.assertEqual(reports[0]['rows'], [])
        self.assertEqual([row['source'] for row in reports[1]['rows']], [run['id']])
        tomorrow = today_board(self.service, now=self.start + timedelta(days=1))
        self.assertEqual(tomorrow['reports'], [])

    def test_weekend_schedule_and_disabled_slot(self):
        config = today_board(self.service, now=self.start)['preferences']
        config['morning'].update(time='00:00', frequency='weekends')
        config['evening'].update(time='00:00', frequency='off')
        weekday = today_board(self.service, config, now=self.start)
        self.assertEqual(weekday['reports'], [])
        saturday = self.start + timedelta(days=2)
        self.assertEqual([r['slot'] for r in today_board(self.service, now=saturday)['reports']], ['morning'])
