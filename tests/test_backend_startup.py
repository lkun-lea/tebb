"""Backend readiness must not require optional network transports."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request


class BackendStartupTests(unittest.TestCase):
    def test_local_backend_health_and_account_rpc_without_httpx(self):
        from websockets.sync.client import connect

        # A fresh interpreter catches eager imports even when the test runner
        # has already loaded HTTPX for network-contract tests.
        script = '''
import importlib.abc, runpy, sys
class NoNetworkStack(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'httpx' or fullname.startswith('httpx.'):
            raise AssertionError('HTTPX loaded before any network operation')
sys.meta_path.insert(0, NoNetworkStack())
runpy.run_module('desk_companion.bootstrap.account_server', run_name='__main__')
'''
        with tempfile.TemporaryDirectory() as directory:
            with socket.socket() as listener:
                listener.bind(('127.0.0.1', 0))
                port = listener.getsockname()[1]
            env = dict(os.environ, DESK_COMPANION_DATA_DIR=directory,
                       DESK_COMPANION_HOME_DIR=directory,
                       DESK_COMPANION_ACCOUNT_BOOTSTRAP='1', PYTHONUTF8='1')
            token = 'isolated-startup-test'
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with (Path(directory) / 'backend.log').open('w+') as log:
                process = subprocess.Popen([sys.executable, '-c', script, '--port', str(port), '--token', token],
                                           cwd=Path(__file__).resolve().parents[1], env=env,
                                           stdout=log, stderr=log)
                try:
                    deadline = time.monotonic() + 30
                    while time.monotonic() < deadline:
                        try:
                            with opener.open(f'http://127.0.0.1:{port}/health', timeout=.2) as response:
                                self.assertEqual(response.read(), b'ok\n')
                            break
                        except OSError:
                            if process.poll() is not None:
                                log.seek(0)
                                self.fail(log.read())
                            time.sleep(.05)
                    else:
                        self.fail('Backend did not become ready')
                    with connect(f'ws://127.0.0.1:{port}/ws?token={token}') as ws:
                        ws.send(json.dumps(dict(type='rpc', id='account', method='account_session', args={})))
                        result = json.loads(ws.recv(timeout=10))['result']
                        self.assertTrue(result['ok'], result)
                        self.assertEqual(result['result']['runtime']['key'], 'local')
                    request = urllib.request.Request(f'http://127.0.0.1:{port}/shutdown',
                                                     headers={'Authorization': 'Bearer ' + token})
                    with opener.open(request, timeout=3) as response:
                        self.assertEqual(response.status, 200)
                    self.assertEqual(process.wait(timeout=15), 0)
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.wait(timeout=5)

    def test_first_model_client_installs_trace_with_backend_metadata(self):
        script = "\nimport sys\nfrom desk_companion.observability import agent_debug; from desk_companion.models import model_network\nagent_debug.configure_process({'channel': 'backend'})\nassert 'httpx' not in sys.modules\nwith model_network.http_client(policy={'mode': 'system'}) as client:\n    assert client.send._desk_debug\nassert agent_debug.metadata()['channel'] == 'backend'\n"
        result = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True,
                                cwd=Path(__file__).resolve().parents[1], timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
