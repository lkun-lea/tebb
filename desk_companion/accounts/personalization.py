"""Confirmed record commands and bounded, observable cloud synchronization."""
import threading
import time
from uuid import NAMESPACE_URL, uuid4, uuid5

from desk_companion.accounts.personalization_cloud import CloudError
from desk_companion.accounts.personalization_store import PersonalizationStore, identifier
from desk_companion.infrastructure.resource_lock import ResourceLock


class PersonalizationService:
    def __init__(self, accounts, *, store=None, scopes=None):
        self.accounts = accounts
        self.store = store or PersonalizationStore(accounts.runtime)
        self._scopes = scopes or (lambda: [])
        self._lock = threading.Lock()
        self._thread = None
        self._job_id = ''
        self._cancel = threading.Event()
        self._closed = False
        self._next_sync = 0
        self._auto_paused = False
        # Coordination belongs with the account registry. Avoid adding a 64-char
        # lock name below the already hashed account data path on Windows.
        self._lease = ResourceLock('personalization-sync:'+accounts.runtime.key,
                                   directory=accounts.runtime.home/'account-control'/'locks')

    def status(self, request_id='', job_id='', include_scopes=False):
        page = self.store.page(request_id, job_id)
        account = self.accounts.status()
        page.update(account=account['runtime'], configured=account['configured'], cloud_url=account['url'], auto_paused=self._auto_paused)
        if include_scopes:
            page['scopes'] = [dict(scope='user', id='', label='所有对话'), *self._scopes()]
        return page

    def action(self, payload):
        try:
            if not isinstance(payload, dict):
                raise CloudError('invalid_action', '个人资料操作须为对象。')
            if payload.get('type') == 'sync':
                return self.start(payload.get('request_id'))
            if payload.get('type') == 'cancel':
                ident = identifier(payload.get('job_id'))
                if self.store.read_job(ident) is None:
                    raise CloudError('not_found', '原同步任务不存在，未取消其他任务。')
                with self._lock:
                    if self._job_id == ident:
                        self._cancel.set()
                        self._auto_paused = True
                    self.store.job(ident, cancel_requested=True)
                return self.status(job_id=ident)
            self.store.mutate(payload)
            job_id = str(uuid5(NAMESPACE_URL, 'tebb-profile-sync:'+identifier(payload['request_id'])))
            try:
                self.start(job_id)
                return self.status(payload['request_id'])
            except CloudError as exc:
                page = self.status(payload['request_id'])
                return {**page, 'notice': '资料已保存；同步暂未启动。'+str(exc)}
        except CloudError as exc:
            page = self.status(payload.get('request_id','') if isinstance(payload, dict) else '')
            return {**page, 'ok': False, 'code': exc.code, 'error': str(exc), 'accepted': page.get('receipt') is not None}

    def tick(self, now=None):
        """Reuse the host scheduler; no separate timer or network on memory reads."""
        instant = time.monotonic() if now is None else now
        with self._lock:
            if (not self.store.available or self._closed or self._auto_paused or instant < self._next_sync
                    or self._thread and self._thread.is_alive()):
                return
            self._next_sync = instant + 60
        account = self.accounts.status()
        if (not account['configured'] or account.get('selected') != self.accounts.runtime.key
                or not any(a['current'] and a['state'] in {'signed_in','expired'} for a in account.get('accounts',[]))):
            return
        return self.start(automatic=True)

    def start(self, request_id=None, *, automatic=False):
        ident = identifier(request_id or str(uuid4()))
        if not self.store.available:
            raise CloudError('needs_login', '请先登录并切换到账号空间。')
        with self._lock:
            old = self.store.read_job(ident)
            if old:
                return self.status(job_id=ident)
            if self._closed:
                raise CloudError('closed', '当前后台正在收尾，资料已留在原账号空间。')
            if self._thread and self._thread.is_alive():
                return {**self.status(), 'ok': False, 'code': 'busy', 'accepted': False, 'error': '已有同步正在进行。'}
            if automatic and self._auto_paused:
                return self.status()
            if not automatic:
                self._auto_paused = False
            self._cancel.clear()
            self._job_id = ident
            self.store.job(ident)
            self._thread = threading.Thread(target=self._run, args=(ident,), daemon=True, name='profile-sync')
            self._thread.start()
        return self.status(job_id=ident)

    def _run(self, job_id):
        acquired = False
        pending = None
        try:
            acquired = self._lease.acquire(blocking=False)
            if not acquired:
                raise CloudError('busy', '此账号已有其他同步进程，未重复执行。')
            self.store.recover_jobs(job_id)
            self.store.job(job_id, state='running', phase='identity')
            processed, skipped = 0, set()
            with self.accounts.cloud_client() as cloud:
                self.store.bind_cloud(cloud.config.url, cloud.user_id)
                cloud.status()
                while processed < 25 and not self._cancel.is_set():
                    reserved = self.store.reserve(skipped)
                    if reserved is None:
                        break
                    pending, mode = reserved
                    self.store.job(job_id, phase='reconcile' if mode == 'reconcile' else 'publish', operation_id=pending['id'])
                    if self._cancel.is_set():
                        self.store.unknown(pending['id'], '同步已取消，原操作需核对。')
                        break
                    if mode == 'reconcile':
                        result = cloud.operation(pending['id'])
                        if result['found']:
                            self.store.finish(pending['id'], result['receipt'])
                        else:
                            self.store.unknown(pending['id'], '云端未查到原回执；可以明确重试原编号，不会自动重放正文。', checked_missing=True)
                            skipped.add(pending['id'])
                    else:
                        receipt = cloud.apply(pending['id'], pending['record_id'], pending['expected_version'],
                                              pending['action'], pending['payload'])
                        self.store.finish(pending['id'], receipt)
                    pending = None
                    processed += 1
                    self.store.job(job_id, processed=processed)
                if not self._cancel.is_set():
                    self.store.job(job_id, phase='pull')
                    for _ in range(5):
                        if self._cancel.is_set():
                            break
                        cursor = self.store.page()['cursor']
                        page = cloud.pull(cursor)
                        self.store.receive_page(page, cursor)
                        if not page['has_more']:
                            break
            counts = self.store.page()['counts']
            current = self.store.page()
            state = ('cancelled' if self._cancel.is_set() else 'needs_confirmation' if
                     any(counts.get(k) for k in ('unconfirmed','conflict','conflict_delete')) else
                     'paused' if counts.get('queued') or current['cursor'] < current['head'] else 'complete')
            self.store.job(job_id, state=state, phase='done', processed=processed, error='')
        except Exception as exc:
            error = str(exc) if isinstance(exc, CloudError) else '同步未确认，请核对原操作；未自动重放。'
            if pending is not None:
                self.store.unknown(pending['id'], error)
            self.store.job(job_id, state='failed', error=error, code=exc.code if isinstance(exc, CloudError) else 'sync_failed',
                           failure_type=type(exc).__name__, os_error=getattr(exc,'winerror',None))
        finally:
            if acquired:
                self._lease.__exit__()

    def request_stop(self):
        with self._lock:
            self._closed = True
            self._cancel.set()

    def wait(self, timeout=25):
        """Bounded CLI/acceptance entry; normal UI observes status without waiting."""
        with self._lock:
            thread = self._thread
        if thread:
            thread.join(timeout)
        return dict(complete=not thread or not thread.is_alive(), **self.status())

    def shutdown(self, timeout=25):
        self.request_stop()
        with self._lock:
            thread = self._thread
        if thread:
            thread.join(timeout)
        return dict(complete=not thread or not thread.is_alive())


def selected_items():
    """Local-only selection; never obtains credentials or starts synchronization."""
    return PersonalizationStore().selection_items()
