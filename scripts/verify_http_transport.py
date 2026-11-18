"""Run the actual TypeScript transport and headless backend with an isolated fake worker."""
import argparse
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from desk_companion.tasks.task_process import ProcessTree


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--node', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True, help='A new evidence directory')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    report = dict(status='running', real_model=False, native_ui=False)
    try:
        with tempfile.TemporaryDirectory(prefix='tebb-http-client-') as profile:
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0))
                port = sock.getsockname()[1]
            token = secrets.token_urlsafe(32)
            env = {**os.environ, 'DESK_COMPANION_DATA_DIR': profile, 'PYTHONUTF8': '1'}
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with (args.output/'backend.log').open('w', encoding='utf-8') as log:
                server = subprocess.Popen([sys.executable, '-u', '-m', 'tests.headless_backend_fixture',
                    '--port', str(port), '--token', token], env=env, cwd=ROOT, stdout=log, stderr=log,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
                tree = ProcessTree(server)
                try:
                    for _ in range(600):
                        try:
                            with opener.open(f'http://127.0.0.1:{port}/health', timeout=.2):
                                break
                        except OSError:
                            if server.poll() is not None:
                                raise RuntimeError('Isolated HTTP parent exited')
                            time.sleep(.05)
                    else:
                        raise TimeoutError('HTTP readiness deadline')
                    result = subprocess.run([str(args.node.resolve()), str(ROOT/'scripts/verify_http_client.cjs')],
                        input=json.dumps(dict(port=port, token=token)), text=True, encoding='utf-8',
                        capture_output=True, timeout=45, cwd=ROOT,
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
                    if result.returncode:
                        raise RuntimeError(result.stderr)
                    report.update(json.loads(result.stdout))
                    assert (Path(profile)/'tool_called').read_text(encoding='utf-8') == '1'
                    report['actual_tool_marker_verified'] = True
                    command = urllib.request.Request(f'http://127.0.0.1:{port}/shutdown', headers={'Authorization': 'Bearer '+token})
                    with opener.open(command, timeout=5):
                        pass
                    report['backend_exit_code'] = server.wait(timeout=20)
                    assert report['backend_exit_code'] == 0
                finally:
                    tree.close()
    except Exception as exc:
        report.update(status='failed', error=str(exc))
        raise
    finally:
        (args.output/'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
