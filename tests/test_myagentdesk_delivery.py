import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from uuid import uuid4

import httpx

from desk_companion.integrations.myagentdesk_delivery import DesktopDelivery


class TestCipher:
    def seal(self, value):
        return value

    def open(self, value):
        return value


class ExitBeforeReturn(BaseException):
    pass


class DesktopDeliveryTest(TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.identifier, self.device = str(uuid4()), str(uuid4())
        self.source = {'id': self.identifier, 'title': '固定候选', 'source': 'https://example.com/issue/10',
                       'stage': 'development', 'input': {'commit': '2'*40, 'criteria': [], 'checks': []}}
        self.secret = 'f'*64
        self.starts = 0
        self.sent = []
        self.job = None
        self.offline = False
        self.lose_receipt = True
        self.unrecorded = False
        self.controller = self.boot()

    def transport(self, _device, method, path, body=None):
        if self.offline:
            raise httpx.ConnectError('offline')
        if path.endswith('/activate'):
            return {'label': '测试设备'}
        if path.endswith('/dispatches'):
            return {'dispatches': [self.source]}
        if path.endswith('/claim'):
            return {'input': self.source['input'], 'status': 'running'}
        if method == 'PUT':
            self.sent.append(body)
            if self.lose_receipt:
                self.lose_receipt = False
                raise httpx.ReadError('response lost')
            return {'status': body['status']}
        self.fail(f'Unexpected path {path}')

    def boot(self):
        return DesktopDelivery(self.root / 'data', self, lambda name: self.root / name,
                               transport=self.transport, cipher=TestCipher(),
                               snapshot=lambda *_: (b'patch', 'b'*64))

    def status(self):
        return {'ready': True, 'provider': 'test sandbox', 'distro': 'Ubuntu'}

    def start(self, cmd, session, *, timeout, request_id):
        self.starts += 1
        if not self.unrecorded:
            self.job = {'id': 'd'*32, 'request_id': request_id, 'state': 'succeeded',
                        'exit_code': 0, 'session': session, 'command': cmd}
        raise ExitBeforeReturn()

    def find_request(self, request_id):
        return self.job if self.job and self.job['request_id'] == request_id else None

    def read(self, identifier, offset):
        self.assertEqual(identifier, 'd'*32)
        return {'data': 'b2s=' if offset == 0 else '', 'offset': 2}

    def authorize(self):
        from unittest.mock import patch
        package = json.dumps({'origin': 'http://localhost:8000', 'id': self.device, 'code': self.secret})
        self.controller.operation(action='pair', package=package)
        self.controller.sync_once()
        self.assertEqual(self.controller.status()['queue'][0]['id'], self.identifier)
        self.controller.sync_once()
        self.assertEqual(self.starts, 0)
        with patch('desk_companion.integrations.myagentdesk_delivery.clean_root', return_value=self.root):
            self.controller.operation(action='approve', identifier=self.identifier, directory=str(self.root),
                                      recipe='{"implementation":["python3","-V"]}')
            self.controller.sync_once()
            self.controller.sync_once()
        with self.assertRaises(ExitBeforeReturn):
            self.controller.sync_once()

    def test_original_runtime_and_identical_outbox_after_restart(self):
        self.authorize()
        self.offline = True
        self.controller = self.boot()
        self.controller.sync_once()
        run = self.controller.status()['runs'][0]
        self.assertEqual((run['phase'], run['runs']), ('outbox', ['d'*32]))
        self.assertEqual(self.sent, [])
        self.offline = False
        self.controller.sync_once()
        self.assertEqual(self.controller.status()['runs'][0]['phase'], 'outbox')
        self.controller = self.boot()
        self.controller.sync_once()
        self.assertEqual(self.controller.status()['runs'][0]['phase'], 'uploaded')
        self.assertEqual(self.sent[0], self.sent[1])
        self.assertEqual(self.starts, 1)

    def test_unrecorded_start_waits_for_review(self):
        self.unrecorded = True
        self.authorize()
        self.controller = self.boot()
        for _ in range(4):
            self.controller.sync_once()
        run = self.controller.status()['runs'][0]
        self.assertEqual((run['phase'], run['receipt_status'], run['runs']), ('uploaded', 'needs_review', []))
        self.assertEqual(self.starts, 1)
