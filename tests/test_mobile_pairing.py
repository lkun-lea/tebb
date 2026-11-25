"""Exercise the same TLS enrollment and desktop decision used by Android."""
import base64
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from desk_companion.local_api.mobile_pairing import MobilePairing


class PairingTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.pair = MobilePairing(Path(tmp.name), 'account-A', lambda: True, lease=lambda: (bytes(32), time.time()+600))
        self.addCleanup(self.pair.close)
        with patch('desk_companion.local_api.mobile_pairing.lan_addresses', return_value=['127.0.0.1']):
            self.assertIn('qr', self.pair.desktop('start'))
        sock = self.pair.server.config.port
        self.http = httpx.Client(base_url=f'https://127.0.0.1:{sock}/mobile/v1', verify=False, trust_env=False)
        from desk_companion.local_api.mobile_discovery import proof
        self.sign = lambda request: request.headers.update({'x-tebb-account': proof(bytes(32), self.pair.pin + ':' + request.url.path)})
        self.http.event_hooks['request'].append(self.sign)
        self.addCleanup(self.http.close)
        key = ec.generate_private_key(ec.SECP256R1())
        public = key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
        signature = key.sign(('tebb-pair-v1:' + self.pair.token).encode(), ec.ECDSA(hashes.SHA256()))
        self.body = dict(token=self.pair.token, name='Test Android', public_key=base64.b64encode(public).decode(),
                         signature=base64.b64encode(signature).decode())

    def apply(self):
        reply = self.http.post('pairings', json=self.body)
        reply.raise_for_status()
        return reply.json()

    def test_only_matching_desktop_approval_registers(self):
        self.assertEqual(self.http.post('pairings', json={**self.body, 'signature': 'bad'}).status_code, 403)
        receipt = self.apply()
        self.assertEqual(receipt, self.apply())
        self.assertFalse(self.pair.record.exists())
        with self.assertRaises(ValueError):
            self.pair.desktop('approve', 'stale')
        path = 'pairings/' + receipt['id']
        self.assertEqual(self.http.get(path).status_code, 403)
        self.pair.desktop('approve', receipt['id'])
        headers = {'Authorization': 'Bearer ' + receipt['ticket']}
        self.assertEqual(self.http.get(path, headers=headers).json()['state'], 'approved')
        self.assertEqual(self.http.post('pairings', json=self.body).status_code, 409)
        self.assertTrue(self.pair.record.exists())
        self.pair.desktop('forget')
        self.assertFalse(self.pair.record.exists())

    def test_answer_resumes_original_run_and_retry_has_one_effect(self):
        from tests.test_execution_flow import ExecutionFlowTests
        flow = ExecutionFlowTests()
        flow.setUp()
        self.addCleanup(flow.tearDown)
        self.pair.collaboration = lambda: flow.service
        root = flow.send()
        run, _, _ = flow.finish(root['id'], [flow.control('request_clarification', question='要转换哪段文字？')])
        receipt = self.apply()
        ticket = {'Authorization': 'Bearer ' + receipt['ticket']}
        self.assertEqual(self.http.get('questions', headers=ticket).status_code, 403)
        self.pair.desktop('approve', receipt['id'])
        access = self.http.get('pairings/'+receipt['id'], headers=ticket).json()['access']
        headers = {'Authorization': 'Bearer '+access}
        question, = self.http.get('questions', headers=headers).json()['questions']
        self.assertEqual(question['run'], run['id'])
        body = {k:question[k] for k in ('conversation','version','run')}
        until = int(time.time()) + 3600
        defer = {**body, 'until': until}
        self.assertEqual(self.http.post('defer', json=defer).status_code, 403)
        self.assertEqual(self.http.post('defer', json={**defer, 'version':'old'}, headers=headers).status_code, 409)
        for _ in range(2):
            self.assertEqual(self.http.post('defer', json=defer, headers=headers).json()['until'], until)
        self.assertEqual(self.http.get('questions', headers=headers).json()['questions'], [])
        desktop = next(row for row in flow.service.snapshot()['state']['runs'] if row['id'] == run['id'])
        self.assertTrue(desktop['question_deferred'])
        with patch('desk_companion.collaboration.service.time.time', return_value=until + 1):
            self.assertEqual(flow.service.mobile_questions(), [question])
        body['text'] = '把 Hello 转成小写'
        for changes in ({'version':'stale'}, {'conversation':'dm-writer'}):
            self.assertEqual(self.http.post('answers', json={**body, **changes}, headers=headers).status_code, 409)
        self.assertEqual(self.http.post('answers', json=body).status_code, 403)
        for _ in range(2):
            ack = self.http.post('answers', json=body, headers=headers)
            self.assertTrue(ack.json()['accepted'])
        self.assertEqual(flow.service.execution_status(run['id'])['updates'], [body['text']])
        self.assertEqual(self.http.get('questions', headers=headers).json()['questions'], [])
        flow.finish(run['id'], [flow.control('start_background_task', instructions=body['text'], strategy='direct')])
        final, _, _ = flow.finish(run['id'], [dict(content='hello')])
        self.assertEqual((final['id'], final['state'], final['artifact']), (run['id'], 'succeeded', 'hello'))

    def test_relay_and_history_require_explicit_device_and_conversation_grants(self):
        import hashlib
        import json
        from tests.test_execution_flow import ExecutionFlowTests
        flow = ExecutionFlowTests()
        flow.setUp()
        self.addCleanup(flow.tearDown)
        self.pair.collaboration = lambda: flow.service
        run = flow.send('本地评审资料')
        receipt = self.apply()
        self.pair.desktop('approve_relay', receipt['id'])
        ticket = {'Authorization': 'Bearer ' + receipt['ticket']}
        approved = self.http.get('pairings/'+receipt['id'], headers=ticket).json()
        self.assertTrue(approved['relay'])
        stored = json.loads(self.pair.record.read_text('utf-8'))
        key = hashlib.sha256(('tebb-relay-v1:' + approved['access']).encode()).digest()
        self.assertEqual(base64.b64decode(stored['relay_key']),key)
        from desk_companion.collaboration.store import transaction
        with transaction(flow.service.path) as (state, _):
            state['messages'].append(dict(id='archived', conversation=run['conversation'],sender='user',
                                          text='夏天的旧方案',ts='2026-07-01T10:00:00+08:00'))
        self.assertEqual(flow.service.shared_history([]),[])
        view = self.pair.desktop('share_history',run['conversation'])
        shared, = flow.service.shared_history(view['shared_chats'])
        self.assertEqual(shared['id'],run['conversation'])
        self.assertEqual(shared['rows'][0]['source'], 'archived')
        self.assertGreater(shared['rows'][0]['time'], 0)
        self.assertIn('本地评审资料', [row['text'] for row in shared['rows']])
        with self.assertRaises(ValueError):
            self.pair.desktop('share_history','missing-conversation')
        view = self.pair.desktop('unshare_history',run['conversation'])
        self.assertEqual(flow.service.shared_history(view['shared_chats']),[])
        self.pair.desktop('forget')
        self.assertFalse(self.pair.record.exists())

    def test_approved_endpoint_survives_restart_and_checks_account(self):
        from unittest.mock import Mock
        service = Mock()
        service.mobile_questions.return_value = []
        receipt = self.apply()
        self.pair.desktop('approve', receipt['id'])
        ticket = {'Authorization': 'Bearer ' + receipt['ticket']}
        access = self.http.get('pairings/'+receipt['id'], headers=ticket).json()['access']
        headers = {'Authorization':'Bearer '+access}
        old = self.pair.server
        self.pair.close()
        for _ in range(100):
            if not old.started or old.servers and not old.servers[0].is_serving():
                break
            time.sleep(.03)
        fresh = MobilePairing(self.pair.directory, 'account-A', lambda:True, lambda:service, self.pair.lease)
        self.addCleanup(fresh.close)
        with patch('desk_companion.local_api.mobile_pairing.lan_addresses', return_value=['127.0.0.1']):
            fresh.restore()
        with httpx.Client(base_url=self.http.base_url, verify=False, trust_env=False) as client:
            client.event_hooks['request'].append(self.sign)
            self.assertEqual(client.get('questions', headers=headers).json(), {'questions':[]})
            fresh.active = lambda:False
            self.assertEqual(client.get('questions', headers=headers).status_code, 403)
            self.assertEqual(client.post('pairings', json=self.body).status_code, 403)

    def test_rejected_request_cannot_be_approved(self):
        receipt = self.apply()
        self.pair.desktop('reject', receipt['id'])
        with self.assertRaises(ValueError):
            self.pair.desktop('approve', receipt['id'])
        self.assertFalse(self.pair.record.exists())

    def test_other_account_cannot_discover_or_apply_even_with_qr(self):
        from desk_companion.local_api.mobile_discovery import proof
        nonce = '0' * 32
        self.assertIsNone(self.pair._offer(nonce, proof(b'x'*32, 'discover:'+nonce)))
        self.assertTrue(self.pair._offer(nonce, proof(bytes(32), 'discover:'+nonce)))
        self.http.event_hooks['request'].clear()
        self.assertEqual(self.http.post('pairings', json=self.body).status_code, 403)
        self.pair.account = 'local'
        with self.assertRaises(ValueError):
            self.pair._key()

    def test_other_account_cannot_use_approved_device_credentials(self):
        from desk_companion.local_api.mobile_discovery import proof
        receipt = self.apply()
        self.pair.desktop('approve', receipt['id'])
        self.http.event_hooks['request'].clear()
        def other_account(request):
            request.headers['x-tebb-account'] = proof(b'x'*32, self.pair.pin + ':' + request.url.path)
        self.http.event_hooks['request'].append(other_account)
        ticket = {'Authorization': 'Bearer ' + receipt['ticket']}
        access = {'Authorization': 'Bearer ' + self.pair.access}
        self.assertEqual(self.http.get('pairings/'+receipt['id'], headers=ticket).status_code, 403)
        self.assertEqual(self.http.get('questions', headers=access).status_code, 403)
        self.assertEqual(self.http.post('answers', json={}, headers=access).status_code, 403)

    def test_udp_reply_decrypts_only_for_original_challenge(self):
        import json
        import socket
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from cryptography.exceptions import InvalidTag
        from desk_companion.local_api.mobile_discovery import proof
        # 开发机上的真实桌面可能已在监听发现端口。使用系统分配的独立 UDP 端口。
        with patch('desk_companion.local_api.mobile_discovery.PORT', 0):
            self.pair.discovery.start()
        port = self.pair.discovery.sock.getsockname()[1]
        self.addCleanup(self.pair.discovery.close)
        nonce = 'a'*32
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(2)
            sig = proof(bytes(32), 'discover:'+nonce)
            sock.sendto(f'tebb2 {nonce} {sig}'.encode(), ('127.0.0.1', port))
            raw = base64.b64decode(sock.recv(2048))
        cipher = AESGCM(bytes(32))
        value = json.loads(cipher.decrypt(raw[:12], raw[12:], nonce.encode()))
        self.assertEqual(value['token'], self.pair.token)
        with self.assertRaises(InvalidTag):
            cipher.decrypt(raw[:12], raw[12:], b'another challenge')

    def test_expired_invite_cannot_enroll(self):
        self.pair.deadline = time.monotonic() - 1
        self.assertEqual(self.http.post('pairings', json=self.body).status_code, 409)
        self.assertEqual(self.pair.desktop()['state'], 'expired')
