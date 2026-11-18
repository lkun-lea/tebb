"""One run per child process. TaskManager remains the owner of task state/cancellation."""
from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import threading
import time
import uuid

from desk_companion.tasks.task_process import ProcessTree


class PiProcessError(RuntimeError):
    pass


class PiCancelled(PiProcessError):
    pass


class PiTimeout(PiProcessError):
    pass


class PiBridge:
    def __init__(self, node=None):
        self.node = str(node or os.environ.get('TEBB_PI_NODE') or shutil.which('node') or '')
        self.process = None
        self.tree = None
        self.events = queue.Queue(maxsize=4096)
        self.closed = threading.Event()
        self.used = False

    def _read(self):
        try:
            for line in self.process.stdout:
                if len(line) > 4_000_000:
                    raise PiProcessError('Pi 事件过大。')
                value = json.loads(line)
                if value.get('v') != 1:
                    raise PiProcessError('Pi 进程协议不匹配。')
                while not self.closed.is_set():
                    try:
                        self.events.put(value, timeout=.1)
                        break
                    except queue.Full:
                        continue
        except Exception:
            pass  # The caller receives EOF, without raw provider content or credentials.
        finally:
            while not self.closed.is_set():
                try:
                    self.events.put(None, timeout=.1)
                    break
                except queue.Full:
                    continue

    def _send(self, value):
        self.process.stdin.write(json.dumps({'v': 1, **value}, ensure_ascii=False) + '\n')
        self.process.stdin.flush()

    def __enter__(self):
        if not self.node:
            raise PiProcessError('缺少固定 Node 24.22.3，请安装已验证的运行时。')
        try:
            self.process = subprocess.Popen([self.node, str(Path(__file__).with_name('worker.mjs'))],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, encoding='utf-8', bufsize=1,
                env={key: value for key, value in os.environ.items()
                     if key not in {'DESK_TERMINAL_PORT', 'DESK_TERMINAL_TOKEN'}},
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            self.tree = ProcessTree(self.process)
            self.reader = threading.Thread(target=self._read, daemon=True)
            self.reader.start()
            ready = self.events.get(timeout=15)
            if not ready or ready['type'] != 'ready' or ready['data'] != dict(node='v24.22.3', pi='1.5.2', protocol=1):
                raise PiProcessError('Pi 运行时或依赖不匹配，请核对固定版本和 npm ci。')
            return self
        except Exception:
            self.close()
            raise PiProcessError('Pi 启动失败，请核对 Node 24.22.3 和固定依赖。') from None

    def call(self, kind, payload, *, before_model, tool=None, cancel=None, on_event=lambda kind, data: None, timeout=90):
        if kind not in {'complete', 'agent'} or not 0 < timeout <= 300:
            raise ValueError('Pi 调用类型或时限无效。')
        if self.used:
            raise PiProcessError('每个 Pi 进程只接纳一个运行。')
        self.used = True
        ident = uuid.uuid4().hex
        self._send(dict(id=ident, type=kind, data={**payload, 'timeout_ms': round(timeout * 1000)}))
        deadline = time.monotonic() + timeout
        cancellation = False
        timed_out = False
        while True:
            if not cancellation and ((cancel and cancel.is_set()) or time.monotonic() >= deadline):
                cancellation = True
                timed_out = not (cancel and cancel.is_set())
                self._send(dict(id=ident, type='cancel'))
                deadline = time.monotonic() + 2
            if cancellation and time.monotonic() >= deadline:
                self.close()
                if timed_out:
                    raise PiTimeout('Pi 调用超时，已停止所属进程。')
                raise PiCancelled('Pi 调用已取消，已停止所属进程。')
            try:
                event = self.events.get(timeout=.05)
            except queue.Empty:
                continue
            if event is None:
                raise PiProcessError('Pi 进程已退出，请核对原任务与工具回执，不要重复执行。')
            if event['id'] != ident:
                raise PiProcessError('Pi 返回了其他调用的事件。')
            event_type, data = event['type'], event.get('data')
            if event_type in {'before_model', 'tool_call'}:
                if cancel and cancel.is_set():
                    cancellation = True
                    self._send(dict(id=ident, type='cancel'))
                    deadline = time.monotonic() + 2
                if cancellation:
                    continue
                try:
                    if event_type == 'before_model':
                        before_model(data)
                        result = dict(ok=True)
                    else:
                        declared = {value['name'] for value in payload.get('tools', [])}
                        if data['name'] not in declared or tool is None:
                            raise PiProcessError('此工具未获授权。')
                        result = dict(ok=True, result=tool(data['name'], data['arguments'], data['call_id']))
                except Exception:
                    # Deny at the existing product gate. Never convert denial to permission.
                    self._send(dict(id=ident, type='reply', ticket=data['ticket'], data=dict(ok=False)))
                    raise
                self._send(dict(id=ident, type='reply', ticket=data['ticket'], data=result))
            elif event_type in {'result', 'error'}:
                if cancellation or (cancel and cancel.is_set()) or data.get('cancelled'):
                    if timed_out or (data.get('cancelled') and not (cancel and cancel.is_set()) and not cancellation):
                        raise PiTimeout('Pi 调用超时，部分输出和原工具回执可核对。')
                    raise PiCancelled('Pi 调用已取消，部分输出和原工具回执可核对。')
                if event_type == 'error':
                    raise PiProcessError('Pi 调用未完成，请检查模型配置、网络和原任务回执。')
                message = data.get('message') or {}
                if message.get('stopReason') != 'stop':
                    raise PiProcessError('Pi 返回不完整结果（' + str(message.get('stopReason')) + '），未接纳为完整交付。')
                return data
            else:
                if not cancellation and not (cancel and cancel.is_set()):
                    on_event(event_type, data)

    def close(self):
        self.closed.set()
        if self.process is not None:
            try:
                self.process.stdin.close()
                self.process.wait(timeout=1)
            except (OSError, subprocess.TimeoutExpired):
                pass
            if self.tree is not None:
                self.tree.close()
            elif self.process.poll() is None:
                self.process.kill()
                self.process.wait(timeout=3)
            self.process.stdout.close()
        if hasattr(self, 'reader'):
            self.reader.join(timeout=2)

    def __exit__(self, *args):
        self.close()
