"""Progress supervision and Python provenance for the external development cycle."""
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import uuid

import psutil

if __package__:
    from .dev_cycle_environment import python_environment, verify_imports
else:
    from dev_cycle_environment import python_environment, verify_imports


def write_json(path, value, *, ensure_ascii=True):
    path = Path(path)
    temporary = path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=ensure_ascii, indent=2), 'utf-8')
    delays = (.02, .05, .1, .2)
    for attempt in range(len(delays)+1):
        try:
            os.replace(temporary, path)
            return
        except PermissionError as exc:
            # Windows readers can briefly hold the destination without delete
            # sharing. Retry these same bytes, never the model or task stage.
            if getattr(exc, 'winerror', None) not in {5, 32, 33} or attempt == len(delays):
                raise
            time.sleep(delays[attempt])


class CycleCancelled(Exception):
    pass


def cancelled(folder):
    return (Path(folder)/'cancel-request.json').exists()


class ProgressMonitor:
    def __init__(self, record, cwd, pid, created, *, check_seconds=120, silence_seconds=600, task_folder=None):
        self.record, self.cwd = Path(record), Path(cwd).resolve()
        self.evidence_dir = self.record/'evidence'
        self.task_folder = Path(task_folder) if task_folder is not None else self.record.parent
        self.pid, self.created = pid, created
        self.check_seconds, self.silence_seconds = check_seconds, silence_seconds
        self.started = time.time()
        self.offset = 0
        self.last_feedback = self.started
        self.last_progress = None
        self.checkpoint_digest = None
        self.active = {}
        self.last_message = ''
        self.notified = False

    def read_events(self, now):
        path = self.record/'events.jsonl'
        if not path.exists():
            return
        with path.open('rb') as stream:
            stream.seek(self.offset)
            while True:
                line = stream.readline()
                if not line.endswith(b'\n'):
                    break  # Retry a partial JSONL line at the next check.
                self.offset = stream.tell()
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                item = event.get('item', {}) if isinstance(event, dict) else {}
                if not isinstance(item, dict):
                    continue
                kind = item.get('type')
                if kind == 'command_execution':
                    if event.get('type') == 'item.started':
                        self.active[item.get('id', '?')] = dict(started=now)
                        self.last_feedback = now
                    elif event.get('type') == 'item.completed':
                        self.active.pop(item.get('id', '?'), None)
                        self.last_feedback = now
                elif event.get('type') == 'item.completed' and kind == 'file_change':
                    self.last_feedback = self.last_progress = now
                elif kind == 'agent_message':
                    self.last_message = str(item.get('text', ''))[:600]
                    # Free-form reassurances alone are not evidence of progress.

    def checkpoint(self, now):
        path = self.evidence_dir/'progress.json'
        if not path.exists():
            return None
        try:
            value = json.loads(path.read_text('utf-8'))
            if not isinstance(value, dict) or not isinstance(value.get('completed'), list) or not isinstance(value.get('current'), str) or not isinstance(value.get('next'), str):
                raise ValueError('进展需要completed/current/next字段')
            if not value['current'].strip():
                raise ValueError('current不能为空')
            verified = []
            roots = (self.cwd, self.record.resolve(), self.evidence_dir.resolve())
            for name in value.get('evidence', []):
                evidence = Path(name).resolve()
                if not any(root in evidence.parents for root in roots) or not evidence.is_file():
                    raise ValueError('进展证据必须在本阶段源码或产物目录内')
                verified.append(dict(path=str(evidence), sha256=hashlib.sha256(evidence.read_bytes()).hexdigest()))
            # A timestamp or repeated claim cannot manufacture new progress.
            fingerprint = hashlib.sha256(json.dumps(verified, sort_keys=True).encode()).hexdigest()
            if fingerprint != self.checkpoint_digest:
                self.checkpoint_digest = fingerprint
                if verified:
                    self.last_feedback = self.last_progress = now
            return dict(current=value['current'][:600], completed=value['completed'][:12], next=value['next'][:600],
                        blocker=value.get('blocker'), evidence=verified, verified=bool(verified))
        except (OSError, ValueError, TypeError, KeyError) as exc:
            return dict(error=str(exc)[:300], verified=False)

    def sample(self, *, now=None, exited=False):
        now = time.time() if now is None else now
        self.read_events(now)
        checkpoint = self.checkpoint(now)
        alive, children = False, []
        try:
            process = psutil.Process(self.pid)
            alive = process.create_time() == self.created and process.is_running()
            if alive:
                children = [p.pid for p in process.children(recursive=True) if p.is_running()]
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        stale = now-self.last_feedback >= self.silence_seconds
        if exited:
            state = 'exited'
        elif checkpoint and checkpoint.get('blocker'):
            state = 'blocked_reported'
        elif stale:
            state = 'needs_check'
        elif self.active:
            state = 'executing'
        elif self.last_progress:
            state = 'progress_observed'
        else:
            state = 'waiting_for_feedback'
        result = dict(state=state, observed_at=now, started=self.started, pid=self.pid, pid_created=self.created,
                      process_alive=alive, child_pids=children, last_feedback_at=self.last_feedback,
                      last_progress_at=self.last_progress, active_commands=len(self.active),
                      checkpoint=checkpoint, last_message=self.last_message,
                      check_seconds=self.check_seconds, silence_seconds=self.silence_seconds,
                      interpretation='Process liveness and model statements do not prove delivery or continued progress.')
        write_json(self.record/'monitor.json', result)
        if state in {'needs_check', 'blocked_reported'}:
            write_json(self.evidence_dir/'progress-request.json', dict(requested_at=now,
                       question='请更新progress.json：具体成果、当前操作、下一步、阻塞和可核对证据。'))
            if not self.notified:
                notice = dict(type='needs_attention', time=now, state=state, attempt=self.record.name,
                              reason='缺少可核对的新反馈；已请求进展并核对进程，保留运行和现场，不自动判失败或终止。')
                with (self.task_folder/'notifications.jsonl').open('a', encoding='utf-8') as stream:
                    stream.write(json.dumps(notice, ensure_ascii=True)+'\n')
                print(json.dumps(notice, ensure_ascii=True), file=sys.stderr, flush=True)
                self.notified = True
        else:
            self.notified = False
        return result


def progress(folder):
    folder = Path(folder)
    state = json.loads((folder/'state.json').read_text('utf-8'))
    result = {k: state[k] for k in ('status', 'stage', 'round', 'launches', 'max_launches', 'max_rounds')}
    fingerprint=folder/'environment-fingerprint-progress.json'
    if fingerprint.is_file():
        try:result['dependency_fingerprint']=json.loads(fingerprint.read_text('utf-8'))
        except (OSError,ValueError)as exc:result['dependency_fingerprint']=dict(unavailable=type(exc).__name__)
    objective=state.get('active_objective')
    if objective:
        result['objective']=dict(objective)
        for name in ('progress.json','checks-progress.json'):
            path=Path(objective['record'])/name
            if path.is_file():
                try:result['objective'][name]=json.loads(path.read_text('utf-8'))
                except (OSError,ValueError)as exc:result['objective'][name]=dict(unavailable=type(exc).__name__)
    if state['attempts']:
        attempt = state['attempts'][-1]
        path = folder/attempt['directory']/'monitor.json'
        if path.exists():
            monitor = json.loads(path.read_text('utf-8'))
            if attempt['status'] == 'running':
                try:
                    process = psutil.Process(monitor['pid'])
                    alive = process.create_time() == monitor['pid_created'] and process.is_running()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    alive = False
                monitor['process_alive'] = alive
                if not alive or time.time()-monitor['observed_at'] > 2*monitor['check_seconds']:
                    monitor['state'] = 'monitor_stale_or_process_missing'
            result['monitor'] = monitor
    result['cancel_requested'] = cancelled(folder)
    result['improvements']=[json.loads(p.read_text('utf-8'))for p in sorted((folder/'improvement-jobs').glob('*.json'))]
    return result
