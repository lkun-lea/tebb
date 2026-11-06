"""One transactional owner for confirmed cloud records and local sync intent."""
from contextlib import closing, contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import threading
from uuid import UUID, uuid4

from desk_companion.accounts.account_store import AccountRuntime, LOCAL, account_key, profile_root
from desk_companion.accounts.personalization_cloud import CloudError

KINDS = {'profile', 'preference', 'memory'}
CATEGORIES = {'communication', 'knowledge', 'goal', 'project', 'other'}
SCOPES = {'user', 'project', 'companion'}
OPEN = {'queued', 'calling', 'unconfirmed'}


def identifier(value):
    try:
        return str(UUID(value))
    except (ValueError, TypeError, AttributeError):
        raise CloudError('invalid_id', '资料或操作编号无效。') from None


def stamp():
    return datetime.now(timezone.utc).isoformat()


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def checked_payload(value):
    if not isinstance(value, dict) or set(value) - {'kind', 'category', 'text', 'scope', 'scope_id', 'source_device_id', 'source_ref'}:
        raise CloudError('invalid_record', '个人资料字段无效。')
    result = deepcopy(value)
    result.setdefault('scope', 'user'); result.setdefault('scope_id', '')
    if (not isinstance(result.get('kind'),str) or result['kind'] not in KINDS
            or not isinstance(result.get('category'),str) or result['category'] not in CATEGORIES
            or not isinstance(result.get('text'), str) or not 1 <= len(result['text'].strip()) <= 4000
            or not isinstance(result['scope'],str) or result['scope'] not in SCOPES or not isinstance(result['scope_id'], str)
            or len(result['scope_id']) > 128 or result['scope'] == 'user' and result['scope_id']
            or result['scope'] != 'user' and not result['scope_id'].strip()):
        raise CloudError('invalid_record', '请填写有效的类别、正文和使用范围。')
    result['text'] = result['text'].strip()
    if 'source_device_id' in result:
        result['source_device_id'] = identifier(result['source_device_id'])
    if 'source_ref' in result and (not isinstance(result['source_ref'], str) or not 1 <= len(result['source_ref']) <= 256):
        raise CloudError('invalid_record', '资料来源编号无效。')
    return result


def metadata(row):
    return {key: row[key] for key in ('kind', 'category', 'scope', 'scope_id')}


def scrub(row):
    return {**row, 'text': None, 'source_ref': None, 'source_device_id': None} if row else None


class PersonalizationStore:
    def __init__(self, runtime=None):
        self.runtime = runtime or AccountRuntime.current()
        if profile_root(self.runtime.home, self.runtime.key) != self.runtime.data.resolve():
            raise CloudError('account_binding_mismatch', '资料空间与当前账号不匹配。')
        self.path = self.runtime.data / 'memory' / 'personalization.sqlite3'
        if self.path.resolve() != self.path:
            raise CloudError('account_binding_mismatch', '个人资料目录不接受路径别名。')
        self._ready = False
        self._init_lock = threading.Lock()

    @property
    def available(self):
        return self.runtime.key != LOCAL

    def _ensure(self):
        if not self.available:
            raise CloudError('needs_login', '请先登录并切换到账号空间，再保存同步资料。')
        with self._init_lock:
            if self._ready:
                return
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(self.path, timeout=15)) as db:
                db.execute('PRAGMA journal_mode=WAL')
                db.executescript('''
                    CREATE TABLE IF NOT EXISTS profile_meta(id INTEGER PRIMARY KEY CHECK(id=1), data TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS profile_records(id TEXT PRIMARY KEY, data TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS profile_outbox(seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL,
                        record_id TEXT NOT NULL, phase TEXT NOT NULL, data TEXT NOT NULL);
                    CREATE INDEX IF NOT EXISTS profile_outbox_pending ON profile_outbox(phase,seq);
                    CREATE TABLE IF NOT EXISTS profile_receipts(id TEXT PRIMARY KEY, digest TEXT NOT NULL, data TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS profile_jobs(seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL, data TEXT NOT NULL);
                ''')
                db.execute('INSERT OR IGNORE INTO profile_meta VALUES(1,?)', (encoded(dict(
                    account=self.runtime.key, device_id=str(uuid4()), user_id=None, revision=0, cursor=0, head=0)),))
                db.commit()
                self._check_meta(json.loads(db.execute('SELECT data FROM profile_meta WHERE id=1').fetchone()[0]))
            self._ready = True

    def _check_meta(self, meta):
        if meta.get('account') != self.runtime.key:
            raise CloudError('account_binding_mismatch', '此个人资料副本属于其他账号，未读取或同步。')

    @contextmanager
    def _transaction(self):
        self._ensure()
        with closing(sqlite3.connect(self.path, timeout=15)) as db:
            db.execute('BEGIN IMMEDIATE')
            meta = json.loads(db.execute('SELECT data FROM profile_meta WHERE id=1').fetchone()[0])
            self._check_meta(meta)
            try:
                yield db, meta
                db.execute('UPDATE profile_meta SET data=? WHERE id=1', (encoded(meta),))
                db.commit()
            except BaseException:
                db.rollback()
                raise

    @staticmethod
    def _record(db, ident):
        row = db.execute('SELECT data FROM profile_records WHERE id=?', (ident,)).fetchone()
        return json.loads(row[0]) if row else None

    @staticmethod
    def _op(db, ident):
        row = db.execute('SELECT data FROM profile_outbox WHERE id=?', (ident,)).fetchone() if ident else None
        return json.loads(row[0]) if row else None

    @staticmethod
    def _save_record(db, record):
        db.execute('INSERT INTO profile_records VALUES(?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data',
                   (record['id'], encoded(record)))

    @staticmethod
    def _save_op(db, op):
        db.execute('INSERT INTO profile_outbox(id,record_id,phase,data) VALUES(?,?,?,?) '
                   'ON CONFLICT(id) DO UPDATE SET phase=excluded.phase,data=excluded.data',
                   (op['id'], op['record_id'], op['phase'], encoded(op)))

    def _purge_ops(self, db, ident):
        for (raw,) in db.execute('SELECT data FROM profile_outbox WHERE record_id=?', (ident,)).fetchall():
            op = json.loads(raw); op['payload'] = None
            if op['phase'] in OPEN:
                op['phase'] = 'retired'
            self._save_op(db, op)

    @staticmethod
    def _view(record):
        deleted = record['desired'] == 'deleted' or record.get('remote_deleted', False)
        content = {} if deleted else record.get('draft') or record.get('remote') or {}
        remote = record.get('remote')
        return dict(id=record['id'], version=record['local_version'], cloud_version=record['remote_version'],
            state=record['desired'], sync_state=record['sync_state'], text=content.get('text', ''),
            source_device_id=content.get('source_device_id'), source_ref=content.get('source_ref'),
            **record['info'], pending_id=record.get('pending_id'), updated=record['updated'],
            remote=({k: remote.get(k) for k in ('kind','category','text','scope','scope_id','state','version')}
                    if remote and record['sync_state'].startswith('conflict') and not deleted else None),
            can_resolve=bool(remote and remote.get('version') == record['remote_version']))

    def page(self, request_id='', job_id=''):
        if not self.available:
            return dict(ok=True, mode='local', records=[], counts={}, receipt=None, job=None, revision=0, device_id='')
        with self._transaction() as (db, meta):
            rows = [json.loads(r[0]) for r in db.execute('SELECT data FROM profile_records ORDER BY rowid DESC')]
            counts = {name: sum(r['sync_state'] == name for r in rows) for name in ('queued','syncing','unconfirmed','conflict','conflict_delete')}
            counts.update(total=len(rows), deleted=sum(r['desired'] == 'deleted' for r in rows))
            receipt = db.execute('SELECT data FROM profile_receipts WHERE id=?', (request_id,)).fetchone() if request_id else None
            job = (db.execute('SELECT data FROM profile_jobs WHERE id=?', (job_id,)).fetchone() if job_id else
                   db.execute('SELECT data FROM profile_jobs ORDER BY seq DESC LIMIT 1').fetchone())
            views = [self._view(r) for r in rows]
            for view in views:
                op = self._op(db, view['pending_id'])
                view['can_retry'] = bool(op and op['phase'] == 'unconfirmed' and op.get('checked_missing'))
                view['error'] = op.get('error','') if op else ''
            return dict(ok=True, mode='account', records=views, counts=counts,
                receipt=json.loads(receipt[0]) if receipt else None, job=json.loads(job[0]) if job else None,
                revision=meta['revision'], cursor=meta['cursor'], head=meta['head'], device_id=meta['device_id'])

    def mutate(self, action):
        if not isinstance(action, dict):
            raise CloudError('invalid_action', '资料操作须为对象。')
        request = identifier(action.get('request_id'))
        try:
            fingerprint = hashlib.sha256(encoded(action).encode()).hexdigest()
        except (ValueError,TypeError):
            raise CloudError('invalid_action', '资料操作必须为有效 JSON。') from None
        kind = action.get('type')
        if not isinstance(kind,str) or kind not in {'save','disable','delete','resolve_local','resolve_remote','retry'}:
            raise CloudError('invalid_action', '个人资料操作不存在。')
        with self._transaction() as (db, meta):
            prior = db.execute('SELECT digest FROM profile_receipts WHERE id=?', (request,)).fetchone()
            if prior:
                if prior[0] != fingerprint:
                    raise CloudError('operation_conflict', '原操作编号不能用于另一项修改。')
            else:
                ident = identifier(action.get('id') or request)
                record = self._record(db, ident)
                if record and (type(action.get('version')) is not int or action['version'] != record['local_version']):
                    raise CloudError('version_conflict', '资料已变化，请重新读取后再修改。')
                if not record and (kind != 'save' or action.get('id')):
                    raise CloudError('not_found', '资料已不存在。')
                if action.get('confirmed') is not True:
                    raise CloudError('needs_confirmation', '请明确确认这项资料修改。')
                if record is None:
                    record = dict(id=ident, local_version=0, remote_version=0, remote=None, draft=None,
                        remote_sequence=0, remote_deleted=False, desired='active', sync_state='queued', pending_id=None)
                op = self._op(db, record.get('pending_id'))
                if record.get('remote_deleted') or record['desired'] == 'deleted' and kind not in {'delete','retry'}:
                    raise CloudError('gone', '已删除的身份不能恢复；重新确认内容请新建资料。')
                if kind == 'retry':
                    if (not op or op['phase'] != 'unconfirmed' or not op.get('checked_missing')
                            or record['desired'] == 'deleted' and op['action'] != 'delete'
                            or op.get('payload') is None and op['action'] == 'put'):
                        raise CloudError('needs_reconcile', '请先核对原回执；已删除的正文不会重放。')
                    op.update(phase='queued', error=''); self._save_op(db, op)
                    record['sync_state'] = 'queued'
                elif kind == 'resolve_remote':
                    remote = record.get('remote')
                    if (not record['sync_state'].startswith('conflict') or not remote
                            or remote.get('version') != record['remote_version']):
                        raise CloudError('needs_pull', '请先同步读取当前云端版本。')
                    self._purge_ops(db, ident)
                    record.update(draft=None, desired=remote['state'], pending_id=None, sync_state='synced', info=metadata(remote))
                else:
                    if kind not in {'delete','disable'} and op and op['phase'] in OPEN and (op['phase'] != 'queued' or op['attempted']):
                        raise CloudError('needs_reconcile', '原请求结果尚未确认，请先核对；仍可停止本机使用并请求删除。')
                    if record['sync_state'].startswith('conflict') and kind not in {'resolve_local','delete','disable'}:
                        raise CloudError('conflict', '请明确选择本机或云端内容解决冲突。')
                    if kind == 'resolve_local' and (not record.get('remote') or record['remote'].get('version') != record['remote_version']):
                        raise CloudError('needs_pull', '请先读取云端版本再解决冲突。')
                    expected = record['remote_version']
                    if kind in {'delete','disable'} and op and op['attempted']:
                        expected = op['expected_version'] + 1
                    if kind in {'save','resolve_local'}:
                        payload = checked_payload(action.get('payload'))
                        payload.update(source_device_id=meta['device_id'], source_ref='manual:'+request)
                        record.update(draft=payload, info=metadata(payload), desired='active')
                        cloud_action = 'put'
                    elif kind == 'disable':
                        if not record.get('remote') and not record.get('draft'):
                            raise CloudError('not_found', '没有可停用的资料。')
                        record['desired'] = 'disabled'; payload = None; cloud_action = 'disable'
                        # A never-uploaded record can be stopped locally without sending its content.
                        if record['remote_version'] == 0 and not (op and op['attempted']):
                            self._purge_ops(db, ident)
                            record.update(pending_id=None, sync_state='local_disabled')
                            cloud_action = None
                    else:
                        payload = None; cloud_action = 'delete'
                        self._purge_ops(db, ident)
                        record.update(draft=None, remote=scrub(record.get('remote')), desired='deleted')
                    if cloud_action:
                        if op:
                            op.update(phase='retired' if op['attempted'] else 'superseded', payload=None)
                            self._save_op(db, op)
                        cloud_id = str(uuid4())
                        self._save_op(db, dict(id=cloud_id, record_id=ident, action=cloud_action,
                            expected_version=expected, payload=payload, phase='queued', attempted=False, error=''))
                        record.update(pending_id=cloud_id, sync_state='queued')
                record.update(local_version=record['local_version']+1, updated=stamp())
                self._save_record(db, record); meta['revision'] += 1
                receipt = dict(id=request, type=kind, record_id=ident, version=record['local_version'], state='saved')
                db.execute('INSERT INTO profile_receipts VALUES(?,?,?)', (request, fingerprint, encoded(receipt)))
        return self.page(request)

    def bind_cloud(self, url, user_id):
        user_id = identifier(user_id)
        if account_key(url, user_id) != self.runtime.key:
            raise CloudError('identity_mismatch', '同步会话不属于当前资料空间。')
        with self._transaction() as (_, meta):
            if meta['user_id'] and meta['user_id'] != user_id:
                raise CloudError('identity_mismatch', '资料副本身份不匹配。')
            meta['user_id'] = user_id

    def reserve(self, skip=()):
        with self._transaction() as (db, meta):
            rows = db.execute("SELECT data FROM profile_outbox WHERE phase IN ('queued','calling','unconfirmed') ORDER BY seq").fetchall()
            op = next((json.loads(raw) for (raw,) in rows if json.loads(raw)['id'] not in skip), None)
            if op is None:
                return None
            mode = 'apply' if op['phase'] == 'queued' else 'reconcile'
            op.update(phase='calling', attempted=True, error=''); self._save_op(db, op)
            record = self._record(db, op['record_id'])
            if record['pending_id'] == op['id']:
                record['sync_state'] = 'syncing'; self._save_record(db, record)
            meta['revision'] += 1
            return deepcopy(op), mode

    def unknown(self, operation_id, message, *, checked_missing=False):
        with self._transaction() as (db, meta):
            op = self._op(db, operation_id)
            if not op or op['phase'] in {'retired','superseded','done','conflict','gone'}:
                return
            op.update(phase='unconfirmed', error=message, checked_missing=checked_missing); self._save_op(db, op)
            record = self._record(db, op['record_id'])
            if record['pending_id'] == op['id']:
                record['sync_state'] = 'unconfirmed'; self._save_record(db, record)
            meta['revision'] += 1

    def finish(self, operation_id, receipt):
        with self._transaction() as (db, meta):
            op = self._op(db, operation_id)
            if not op or any(receipt.get(k) != expected for k, expected in (
                    ('operation_id', op['id']), ('record_id', op['record_id']), ('action', op['action']), ('user_id', meta['user_id']))):
                raise CloudError('identity_mismatch', '云回执与原资料操作不匹配，未采用。')
            if receipt.get('status') not in {'applied','conflict','gone','not_found'} or type(receipt.get('version')) is not int:
                raise CloudError('invalid_response', '资料回执无效。')
            record = self._record(db, op['record_id']); version = receipt['version']
            pending = record['pending_id'] == op['id']; status = receipt['status']
            if status == 'gone' or pending and status == 'applied' and op['action'] == 'delete':
                self._purge_ops(db, record['id'])
                record.update(remote_deleted=True, desired='deleted', draft=None, remote=scrub(record.get('remote')),
                    pending_id=None, sync_state='synced')
            elif pending and status == 'applied' and not record['remote_deleted']:
                if op['action'] == 'put':
                    remote = {**op['payload'], 'id': record['id'], 'state': 'active'}
                else:
                    remote = {**(record.get('remote') or record.get('draft') or {}), 'id': record['id'], 'state': 'disabled'}
                if version >= record['remote_version']:
                    remote.update(version=version, sequence=receipt['cursor'])
                    record.update(remote=remote, draft=None, desired=remote['state'], pending_id=None, sync_state='synced', info=metadata(remote))
            elif pending and status in {'conflict','not_found'}:
                record['sync_state'] = 'conflict_delete' if record['desired'] == 'deleted' else 'conflict'
            record['remote_version'] = max(record['remote_version'], version)
            if status == 'applied':
                record['remote_sequence'] = max(record['remote_sequence'], receipt['cursor'])
                meta['head'] = max(meta['head'], receipt['cursor'])
            record.update(local_version=record['local_version']+1, updated=stamp())
            self._save_record(db, record)
            op.update(phase='done' if status == 'applied' else 'gone' if status == 'gone' else 'conflict', receipt=receipt, payload=None)
            self._save_op(db, op); meta['revision'] += 1

    def receive_page(self, page, expected_cursor):
        with self._transaction() as (db, meta):
            if page.get('user_id') != meta['user_id']:
                raise CloudError('identity_mismatch', '同步页不属于当前账号。')
            if (expected_cursor != meta['cursor'] or type(page.get('cursor')) is not int or type(page.get('head')) is not int
                    or page['cursor'] < meta['cursor'] or page['head'] < max(meta['head'], page['cursor'])):
                raise CloudError('invalid_cursor', '同步页已过时，未覆盖当前资料或游标。')
            for row in page['records']:
                ident = identifier(row['id']); version = row['version']
                if type(version) is not int or version < 1:
                    raise CloudError('invalid_response', '云记录版本无效。')
                if row['state'] != 'deleted':
                    checked_payload({k: row[k] for k in ('kind','category','text','scope','scope_id')})
                elif any(row.get(k) is not None for k in ('text','source_ref','source_device_id')):
                    raise CloudError('invalid_response', '墓碑仍含正文，未采用。')
                record = self._record(db, ident)
                if record and (version < record['remote_version'] or record['remote_deleted'] and row['state'] != 'deleted'):
                    continue
                if record is None:
                    record = dict(id=ident, local_version=0, remote_version=0, remote_sequence=0, remote_deleted=False,
                        draft=None, desired=row['state'], pending_id=None, sync_state='synced', info=metadata(row))
                op = self._op(db, record.get('pending_id'))
                if row['state'] == 'deleted':
                    self._purge_ops(db, ident)
                    record.update(remote_deleted=True, desired='deleted', draft=None, pending_id=None, sync_state='synced')
                elif record['desired'] == 'deleted':
                    if not op or op['expected_version'] != version:
                        record['sync_state'] = 'conflict_delete'
                        if op and op['phase'] == 'queued':
                            op.update(phase='conflict', payload=None); self._save_op(db, op)
                elif op and op['phase'] in {'queued','conflict'} and op['expected_version'] != version:
                    op.update(phase='conflict', payload=None); self._save_op(db, op)
                    record['sync_state'] = 'conflict'
                elif not op or op['phase'] in {'done','gone','superseded','retired'}:
                    record.update(draft=None, desired=row['state'], sync_state='synced', pending_id=None)
                record.update(remote=scrub(row) if record['desired'] == 'deleted' else deepcopy(row), remote_version=version,
                    remote_sequence=row['sequence'], local_version=record['local_version']+1, updated=stamp())
                self._save_record(db, record)
            meta.update(cursor=page['cursor'], head=page['head'], revision=meta['revision']+1)

    def job(self, ident, **changes):
        ident = identifier(ident)
        with self._transaction() as (db, _):
            row = db.execute('SELECT data FROM profile_jobs WHERE id=?', (ident,)).fetchone()
            job = json.loads(row[0]) if row else dict(id=ident, state='queued', processed=0, error='', created=stamp())
            job.update(changes)
            db.execute('INSERT INTO profile_jobs(id,data) VALUES(?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data', (ident, encoded(job)))
            return deepcopy(job)

    def read_job(self, ident):
        with self._transaction() as (db, _):
            row = db.execute('SELECT data FROM profile_jobs WHERE id=?', (identifier(ident),)).fetchone()
            return json.loads(row[0]) if row else None

    def recover_jobs(self, current_job=''):
        """Only call after acquiring the account's exclusive sync lease."""
        with self._transaction() as (db, meta):
            for (raw,) in db.execute('SELECT data FROM profile_jobs').fetchall():
                job = json.loads(raw)
                if job['state'] in {'running','queued'} and job['id'] != current_job:
                    job.update(state='interrupted', error='原进程已结束；原资料操作仍按回执核对。')
                    db.execute('UPDATE profile_jobs SET data=? WHERE id=?', (encoded(job), job['id']))
            for (raw,) in db.execute("SELECT data FROM profile_outbox WHERE phase='calling'").fetchall():
                op = json.loads(raw); op['phase'] = 'unconfirmed'; self._save_op(db, op)
                record = self._record(db, op['record_id'])
                if record['pending_id'] == op['id']:
                    record['sync_state'] = 'unconfirmed'; self._save_record(db, record)
            meta['revision'] += 1

    def selection_items(self):
        if not self.available or not self.path.is_file():
            return []
        result = []
        # The memory inspector is read-only, including its first read in a worker.
        # Never initialize/migrate a store or refresh a session during selection.
        with closing(sqlite3.connect(self.path.as_uri()+'?mode=ro', uri=True, timeout=15)) as db:
            db.execute('BEGIN')
            meta = json.loads(db.execute('SELECT data FROM profile_meta WHERE id=1').fetchone()[0])
            self._check_meta(meta)
            rows = [self._view(json.loads(raw)) for (raw,) in db.execute('SELECT data FROM profile_records ORDER BY rowid DESC')]
        for row in rows:
            state = 'conflict' if row['sync_state'].startswith('conflict') and row['state'] != 'deleted' else row['state']
            scope = 'partner' if row['scope'] == 'companion' else row['scope']
            result.append(dict(id='personalization:'+row['id'], text=row['text'], version=row['version'], scope=scope,
                owner=row['scope_id'], state=state, writer='user', quote='', updated=row['updated'], versions=[], expires='', key='',
                source=dict(kind='personalization', record_id=row['id'], record_kind=row['kind'], category=row['category'],
                    account=self.runtime.key, device_id=row['source_device_id'], replica_id=meta['device_id'],
                    source_ref=row['source_ref'], cloud_version=row['cloud_version'], sync_state=row['sync_state'])))
        return result
