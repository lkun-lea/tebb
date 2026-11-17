"""User-owned work items; execution state and scheduling remain in their domains."""
from contextlib import closing, contextmanager, nullcontext
import hashlib
import json
import logging
from pathlib import Path
import re
import sqlite3
import threading

from desk_companion.planning import work_items
from desk_companion.planning.work_items import BoardRuleError
from desk_companion.infrastructure.resource_lock import ResourceLock


class WorkBoardService:
    def __init__(self, path=None):
        from desk_companion.collaboration.store import workspace_path
        self.path = Path(path or workspace_path())
        self._ready = False
        self._init_lock = threading.Lock()
        self._change_lock = threading.Lock()
        self._change_listeners = set()

    def _ensure(self):
        with self._init_lock:
            if self._ready:
                return
            from desk_companion.collaboration.service import initialize_workspace
            initialize_workspace(self.path)
            with closing(sqlite3.connect(self.path)) as db:
                db.execute('CREATE TABLE IF NOT EXISTS work_receipts '
                           '(id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, result TEXT NOT NULL)')
                db.commit()
            self._ready = True

    @staticmethod
    def validate_request_id(value):
        if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,100}', value):
            raise BoardRuleError('缺少有效的事项操作编号，请刷新后重试。')
        return value

    @contextmanager
    def workspace_transaction(self):
        """Shared short durable transaction; callers must keep network IO outside."""
        self._ensure()
        from desk_companion.collaboration.store import transaction
        with transaction(self.path) as result:
            yield result

    @contextmanager
    def hold_item(self, item_id):
        """Per-item admission, shared with scheduling across threads/processes."""
        lock = ResourceLock(f'work-item:{self.path.resolve()}:{item_id}')
        if not lock.acquire(blocking=False):
            raise BoardRuleError('此事项正在保存或安排时间，请稍后操作。')
        try:
            yield
        finally:
            lock.__exit__()

    def load(self, request_id=''):
        try:
            if request_id:
                self.validate_request_id(request_id)
            self._ensure()
            from desk_companion.collaboration.store import transaction
            with transaction(self.path) as (state, db):
                result = work_items.public_page(state)
                receipt = db.execute('SELECT result FROM work_receipts WHERE id=?', (request_id,)).fetchone() if request_id else None
                result['receipt'] = json.loads(receipt[0]) if receipt else None
            return result
        except Exception as exc:
            return dict(ok=False, error=f'事项读取失败：{exc}。请重新读取核对。', stage='read')

    def subscribe_changes(self, listener):
        with self._change_lock:
            self._change_listeners.add(listener)

        def unsubscribe():
            with self._change_lock:
                self._change_listeners.discard(listener)

        return unsubscribe

    def _notify_change(self):
        with self._change_lock:
            listeners = tuple(self._change_listeners)
        for listener in listeners:
            try:
                listener()
            except Exception:
                logging.getLogger(__name__).exception('事项已保存，通知订阅者失败。')

    @staticmethod
    def _status(item):
        return {key: item[key] for key in ('id', 'title', 'state', 'version', 'archived')}

    def query_status(self, project_id, *, query='', item_id='', request_id=''):
        """Read only fields needed to resolve an item and confirm its status."""
        if not all(isinstance(value, str) for value in (query, item_id, request_id)):
            raise BoardRuleError('事项查询须使用文本参数。')
        if request_id:
            self.validate_request_id(request_id)
        with self.workspace_transaction() as (state, db):
            items = [item for item in state.get('work_items', []) if item['project_id'] == project_id]
            if request_id:
                row = db.execute('SELECT result FROM work_receipts WHERE id=?', (request_id,)).fetchone()
                receipt = json.loads(row[0]) if row else None
                if receipt:
                    for item in items:
                        if item['id'] == receipt['item_id']:
                            return dict(ok=True, receipt=receipt, items=[self._status(item)], truncated=False)
                return dict(ok=True, receipt=None, items=[], truncated=False)
            query = query.strip().casefold()
            matches = [item for item in items if (not item_id or item['id'] == item_id)
                       and query in item['title'].casefold()]
        return dict(ok=True, items=[self._status(item) for item in matches[:50]], truncated=len(matches) > 50)

    def change(self, action, *, project_id=None):
        """A project scope supplied by the parent restricts the partner to status moves."""
        request_id = action.get('request_id', '') if isinstance(action, dict) else ''
        attempted, receipt = False, None
        try:
            self.validate_request_id(request_id)
            if not isinstance(action.get('type'), str):
                raise BoardRuleError('事项操作无效。')
            fingerprint = hashlib.sha256(json.dumps(action, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            self._ensure()
            from desk_companion.collaboration.store import transaction
            with (self.hold_item(action.get('id')) if action.get('type') != 'create' else nullcontext()), transaction(self.path) as (state, db):
                if project_id is not None:
                    item = next((row for row in state.get('work_items', []) if row['id'] == action.get('id')
                                 and row['project_id'] == project_id), None)
                    if not item or action['type'] != 'move':
                        raise BoardRuleError('当前会话范围内找不到可操作的事项。')
                row = db.execute('SELECT fingerprint,result FROM work_receipts WHERE id=?', (request_id,)).fetchone()
                if row:
                    if row[0] != fingerprint:
                        raise BoardRuleError('此操作编号已被其他事项操作使用。')
                    receipt = json.loads(row[1])
                else:
                    item = work_items.apply_change(state, action)
                    receipt = dict(request_id=request_id, item_id=item['id'], version=item['version'], operation=action['type'])
                    db.execute('INSERT INTO work_receipts VALUES(?,?,?)', (request_id, fingerprint, json.dumps(receipt)))
                attempted = True
        except BoardRuleError as exc:
            return dict(ok=False, error=str(exc), conflict=exc.conflict,
                        request_id=request_id, change_state='not_changed', stage='validate')
        except Exception as exc:
            return dict(ok=False, request_id=request_id, receipt=receipt,
                        change_state='unconfirmed' if attempted else 'not_changed', stage='save' if attempted else 'read',
                        error=(f'事项保存结果未确认：{exc}。请重新读取并核对操作编号，不要自动重发。' if attempted
                               else f'事项操作失败：{exc}。请重新读取。'))
        if project_id is not None:
            if row is None:
                self._notify_change()
            return dict(ok=True, receipt=receipt, item=self._status(item))
        page = self.load(request_id)
        if not page['ok']:
            return dict(ok=False, request_id=request_id, receipt=receipt, change_state='committed', stage='refresh',
                        error='事项操作已保存，但页面读取失败。请重新读取核对，不要重复提交。')
        return page
