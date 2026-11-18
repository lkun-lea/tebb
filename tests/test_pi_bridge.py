"""Pinned real Node/Pi processes against an isolated OpenAI-compatible HTTP fixture."""
import json
import os
from pathlib import Path
import shutil
import threading
import time
import unittest
import tempfile
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from desk_companion.pi_runtime.bridge import PiBridge, PiCancelled, PiProcessError, PiTimeout


class PiProviderFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.node = os.environ.get('TEBB_PI_NODE') or shutil.which('node')
        if not cls.node or not Path('desk_companion/pi_runtime/node_modules').is_dir():
            raise unittest.SkipTest('Install pinned Node/Pi dependencies to run private-process acceptance.')

    def setUp(self):
        self.requests = []
        requests = self.requests
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                requests.append(body)
                scenario = body['model']
                if scenario == 'rejected':
                    self.send_response(429)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(b'{"error":{"message":"isolated rate limit"}}')
                    return
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.end_headers()
                def frame(delta, finish=None):
                    value = dict(id='fixture', object='chat.completion.chunk', created=1, model=scenario,
                                 choices=[dict(index=0, delta=delta, finish_reason=finish)])
                    self.wfile.write(('data: ' + json.dumps(value) + '\n\n').encode())
                    self.wfile.flush()
                try:
                    frame(dict(reasoning_content='fixture reasoning'))
                    if scenario == 'tool' and not any(row['role'] == 'tool' for row in body['messages']):
                        frame(dict(tool_calls=[dict(index=0, id='call-1', type='function',
                            function=dict(name='probe_add', arguments='{"a":17,"b":23}'))]))
                        frame({}, 'tool_calls')
                    else:
                        if scenario != 'empty': frame(dict(content='40'))
                        if scenario == 'cancel':
                            time.sleep(3)
                        if scenario != 'no-finish': frame({}, 'length' if scenario == 'length' else 'stop')
                    if scenario != 'missing-usage':
                        self.wfile.write(('data: '+json.dumps(dict(choices=[],usage=dict(prompt_tokens=13, completion_tokens=7,total_tokens=20)))+'\n\n').encode())
                    self.wfile.write(b'data: [DONE]\n\n')
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    pass
        self.http = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.http.server_close)
        self.addCleanup(self.http.shutdown)

    def payload(self, scenario='normal'):
        return dict(model=dict(id=scenario,name=scenario,api='openai-completions',provider='tebb-test',
            baseUrl=f'http://127.0.0.1:{self.http.server_port}/v1',reasoning=True,input=['text'],
            contextWindow=8192,maxTokens=1024,cost=dict(input=0,output=0,cacheRead=0,cacheWrite=0),
            compat=dict(supportsDeveloperRole=False,supportsStore=False,maxTokensField='max_tokens')),
            api_key='isolated-test-only', network=dict(mode='direct'), context=dict(messages=[dict(role='user',content='40',timestamp=1)]),
            options=dict(maxTokens=1024,reasoningEffort='low'), prompt='Use probe_add exactly once to add 17 and 23, then return 40.')


class PiBridgeTests(PiProviderFixture):
    def test_complete_events_usage_and_pinned_process_handshake(self):
        events, admissions = [], []
        with patch.dict(os.environ, DESK_TERMINAL_TOKEN='parent-only-token', DESK_TERMINAL_PORT='12345'), PiBridge(self.node) as bridge:
            import psutil
            self.assertNotIn('DESK_TERMINAL_TOKEN', psutil.Process(bridge.process.pid).environ())
            self.assertNotIn('DESK_TERMINAL_PORT', psutil.Process(bridge.process.pid).environ())
            result = bridge.call('complete', self.payload(), before_model=admissions.append,
                                 on_event=lambda kind,data:events.append((kind,data)), timeout=10)
            self.assertIsNone(bridge.process.poll())
        self.assertIsNotNone(bridge.process.poll())
        self.assertEqual(result['message']['stopReason'], 'stop')
        self.assertEqual(result['message']['content'][-1]['text'], '40')
        self.assertTrue(result['usage_reported'])
        self.assertFalse(result['cost_known'])
        self.assertEqual(len(admissions), 1)
        self.assertEqual(admissions[0]['payload']['messages'][-1]['content'], '40')
        self.assertTrue(any(kind=='thinking_delta' for kind,data in events))
        self.assertTrue(any(kind=='provider_usage' for kind,data in events))

    def test_official_agent_tools_cross_the_product_gate_once(self):
        payload = self.payload('tool')
        payload['context'] = dict(messages=[])
        payload['tools'] = [dict(name='probe_add',description='Read-only calculator',parameters=dict(type='object',
            properties=dict(a=dict(type='integer'),b=dict(type='integer')),required=['a','b']))]
        tools, admissions = [], []
        def execute(name,args,call_id):
            tools.append((name,args,call_id))
            return args['a']+args['b']
        with PiBridge(self.node) as bridge:
            result = bridge.call('agent', payload, before_model=admissions.append, tool=execute, timeout=15)
        self.assertEqual(result['message']['content'][-1]['text'], '40')
        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0][1], dict(a=17,b=23))
        self.assertEqual(len(admissions), 2)
        self.assertEqual(len(self.requests), 2)

    def test_budget_denial_happens_before_network_send(self):
        def deny(data):
            raise ValueError('budget denied')
        with PiBridge(self.node) as bridge:
            with self.assertRaisesRegex(ValueError, 'budget denied'):
                bridge.call('complete', self.payload(), before_model=deny, timeout=10)
        self.assertEqual(self.requests, [])

    def test_length_rejected_and_missing_usage_is_explicit(self):
        with PiBridge(self.node) as bridge:
            with self.assertRaisesRegex(PiProcessError, 'length'):
                bridge.call('complete', self.payload('length'), before_model=lambda data:None, timeout=10)
        with PiBridge(self.node) as bridge:
            result = bridge.call('complete', self.payload('missing-usage'), before_model=lambda data:None, timeout=10)
        self.assertFalse(result['usage_reported'])

    def test_cancel_preserves_partial_and_process_is_reaped(self):
        cancel = threading.Event()
        events = []
        def receive(kind, data):
            events.append((kind,data))
            if kind == 'text_delta':
                cancel.set()
        with PiBridge(self.node) as bridge:
            with self.assertRaises(PiCancelled):
                bridge.call('complete', self.payload('cancel'), before_model=lambda data:None,
                            cancel=cancel, on_event=receive, timeout=10)
        self.assertIsNotNone(bridge.process.poll())
        self.assertIn(('text_delta', '40'), events)

    def test_deadline_is_timeout_and_never_retries(self):
        with PiBridge(self.node) as bridge:
            with self.assertRaises(PiTimeout):
                bridge.call('complete', self.payload('cancel'), before_model=lambda data:None, timeout=1)
        self.assertIsNotNone(bridge.process.poll())
        self.assertLessEqual(len(self.requests), 1)

    def test_existing_task_cancel_reaps_python_worker_and_node_descendant(self):
        import psutil
        from desk_companion.tasks.manager import TaskManager
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,
                DESK_COMPANION_DATA_DIR=directory, TEBB_PI_NODE=self.node):
            manager = TaskManager(command=[sys.executable, '-u', '-m', 'tests.pi_task_fixture'])
            try:
                ident = manager.submit('process bridge acceptance', 'isolated-pi-session', pi_payload=self.payload('cancel'))
                deadline = time.monotonic() + 15
                marker = Path(directory) / 'pi-child.pid'
                while time.monotonic() < deadline:
                    if marker.exists() and manager.get(ident)['answer'] == '40':
                        break
                    time.sleep(.02)
                else:
                    self.fail('Task-owned Pi process did not reach its partial-output checkpoint')
                pid = int(marker.read_text())
                self.assertTrue(psutil.pid_exists(pid))
                manager.cancel(ident)
                row = manager.wait(ident)
                self.assertEqual(row['state'], 'cancelled')
                for _ in range(150):
                    if not psutil.pid_exists(pid) and ident not in manager.active:
                        break
                    time.sleep(.02)
                self.assertFalse(psutil.pid_exists(pid))
                self.assertNotIn(ident, manager.active)
                self.assertEqual(row['answer'], '40')
            finally:
                manager.shutdown()
