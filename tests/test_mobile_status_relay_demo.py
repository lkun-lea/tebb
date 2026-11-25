"""Isolated #322 demo: Windows projection -> opaque relay -> independent reader."""
import json
import unittest

import httpx
from cryptography.fernet import Fernet, InvalidToken
from tests import test_execution_flow as fixtures


class MobileStatusRelayDemo(unittest.TestCase):
    def test_disconnected_writer_replay_and_resolved_card(self):
        flow = fixtures.ExecutionFlowTests()
        flow.setUp()
        self.addCleanup(flow.tearDown)
        root = flow.send()
        flow.finish(root['id'], [flow.control('request_clarification', question='评审需要多长时间？')])
        question, = flow.service.mobile_questions()

        # A pre-paired key for this fixture only. The relay never receives it.
        cipher = Fernet(Fernet.generate_key())
        mailbox = {}

        def relay(request):
            if request.method == 'PUT':
                mailbox['latest'] = request.content
                return httpx.Response(204)
            return httpx.Response(200, content=mailbox['latest'])

        transport = httpx.MockTransport(relay)
        def publish():
            payload = json.dumps(flow.service.mobile_questions(), ensure_ascii=False).encode()
            with httpx.Client(transport=transport) as windows:
                windows.put('https://fixture.invalid/status', content=cipher.encrypt(payload)).raise_for_status()

        def read(phone):
            reply = phone.get('https://fixture.invalid/status')
            reply.raise_for_status()
            return json.loads(cipher.decrypt(reply.content))

        publish()
        self.assertNotIn(question['prompt'].encode(), mailbox['latest'])
        with self.assertRaises(InvalidToken):
            Fernet(Fernet.generate_key()).decrypt(mailbox['latest'])
        with httpx.Client(transport=transport) as phone:
            # The producer connection has closed; both reads show the same card.
            self.assertEqual(read(phone), [question])
            self.assertEqual(read(phone), [question])
            flow.service.action(dict(type='send', conversation=question['conversation'], run=question['run'],
                                     question_version=question['version'], text='45 分钟', request_id='relay-demo-answer'))
            publish()
            self.assertEqual(read(phone), [])

    def test_same_name_items_after_a_month_remain_independent(self):
        from desk_companion.collaboration.store import transaction
        from desk_companion.planning.work_items import apply_change
        import time
        flow = fixtures.ExecutionFlowTests()
        flow.setUp()
        self.addCleanup(flow.tearDown)
        roots = []
        for _ in range(2):
            run = flow.send('评审方案')
            flow.finish(run['id'], [flow.control('request_clarification', question='何时评审？')])
            roots.append(run['id'])
        with transaction(flow.service.path) as (state, _):
            for run in state['runs']:
                run['created'] -= 30 * 86400
            for run_id in roots:
                item = apply_change(state, dict(type='create', fields=dict(title='评审方案',due='2026-12-01')))
                apply_change(state, dict(type='link', id=item['id'], version=item['version'], run_id=run_id))
        first, second = flow.service.mobile_questions()
        self.assertNotEqual(first['items'][0]['id'], second['items'][0]['id'])
        self.assertLess(first['created'], time.time() - 29 * 86400)
        flow.service.defer_question(first['conversation'],first['run'],first['version'],int(time.time())+3600)
        self.assertEqual(flow.service.mobile_questions(), [second])
        with transaction(flow.service.path) as (state, _):
            item = state['work_items'][1]
            apply_change(state,dict(type='move',id=item['id'],version=item['version'],state='done'))
        self.assertEqual(flow.service.mobile_questions(),[])
        with self.assertRaises(ValueError):
            flow.service.action(dict(type='send',conversation=second['conversation'],run=second['run'],
                                     question_version=second['version'],text='迟到回复',request_id='stale-reply-test'))
