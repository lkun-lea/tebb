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
