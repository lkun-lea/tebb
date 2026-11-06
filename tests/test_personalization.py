from contextlib import closing, contextmanager
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch
from uuid import uuid4

from desk_companion.accounts.account_store import AccountRuntime, account_key, profile_root
from desk_companion.accounts.personalization_store import PersonalizationStore
from desk_companion.accounts.personalization import PersonalizationService
from desk_companion.accounts.personalization_cloud import CloudError
from desk_companion.memory import memory_selection

A='a0000000-0000-4000-8000-000000000001'
B='b0000000-0000-4000-8000-000000000002'
URL='https://profiles.example.invalid'
def uid(): return str(uuid4())
def payload(text='先给结论，再补依据', **kw):
    return dict(kind='preference', category='communication', text=text, scope='user', scope_id='') | kw


class Remote:
    """Deterministic fault fixture; the PostgreSQL suite verifies actual SQL/RLS."""
    def __init__(self, owner=A):
        self.user_id=owner; self.config=type('Config',(),{'url':URL})()
        self.rows={}; self.receipts={}; self.head=0; self.calls=[]; self.failure=None
        self.entered=threading.Event(); self.gate=None
    def status(self): return {'revision':self.head}
    def apply(self, op, ident, expected, action, body):
        self.calls.append(('apply',op,ident,action)); self.entered.set()
        if self.gate: self.gate.wait(5)
        if op in self.receipts: return deepcopy(self.receipts[op])
        row=self.rows.get(ident); version=row['version'] if row else 0
        state=('gone' if row and row['state']=='deleted' else
               'conflict' if (row or action!='delete') and version!=expected else
               'not_found' if not row and action=='disable' else 'applied')
        if state=='applied':
            self.head+=1; version+=1
            content=deepcopy(body if action=='put' else row or payload(''))
            if action=='delete': content.update(text=None,source_ref=None,source_device_id=None)
            content.update(id=ident,version=version,sequence=self.head,state={'put':'active','delete':'deleted','disable':'disabled'}[action])
            self.rows[ident]=content
        result=dict(user_id=self.user_id, operation_id=op, record_id=ident, action=action,
                    status=state, version=version, cursor=self.head)
        self.receipts[op]=result
        if self.failure: raise self.failure
        return deepcopy(result)
    def operation(self, op):
        self.calls.append(('operation',op))
        return dict(found=op in self.receipts,receipt=deepcopy(self.receipts.get(op)))
    def pull(self, after=0):
        self.calls.append(('pull',after))
        return dict(user_id=self.user_id,records=sorted([deepcopy(r) for r in self.rows.values() if r['sequence']>after],key=lambda r:r['sequence']),
                    cursor=self.head, head=self.head, has_more=False)


class RecordsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.home=Path(self.temp.name).resolve(); self.store=self.new_store(self.home)
        self.remote=Remote(); self.store.bind_cloud(URL,A)
    def new_store(self, home, owner=A):
        key=account_key(URL,owner)
        return PersonalizationStore(AccountRuntime(home,key,profile_root(home,key)))
    def act(self, kind='save', row=None, **kw):
        action=dict(type=kind,request_id=uid(),confirmed=True,**kw)
        if row: action.update(id=row['id'],version=row['version'])
        if kind in {'save','resolve_local'}: action.setdefault('payload',payload())
        return self.store.mutate(action)
    def first(self): return self.store.page()['records'][0]
    def send(self):
        op,mode=self.store.reserve(); self.assertEqual(mode,'apply')
        receipt=self.remote.apply(op['id'],op['record_id'],op['expected_version'],op['action'],op['payload'])
        self.store.finish(op['id'],receipt); return op
    def pull(self):
        cursor=self.store.page()['cursor']; self.store.receive_page(self.remote.pull(cursor),cursor)

    def test_local_mode_never_claims_or_creates_a_cloud_store(self):
        local=PersonalizationStore(AccountRuntime(self.home,'local',self.home))
        self.assertEqual(local.page()['mode'],'local'); self.assertEqual(local.selection_items(),[])
        with self.assertRaises(CloudError): local.mutate(dict(type='save',request_id=uid(),confirmed=True,payload=payload()))
        self.assertFalse(local.path.exists())

    def test_confirmation_and_local_version_are_required_and_mutation_is_idempotent(self):
        action=dict(type='save',request_id=uid(),payload=payload(),confirmed=False)
        with self.assertRaises(CloudError): self.store.mutate(action)
        action['confirmed']=True; first=self.store.mutate(action); second=self.store.mutate(action)
        self.assertEqual(first['receipt'],second['receipt']); self.assertEqual(len(second['records']),1)
        with self.assertRaises(CloudError): self.store.mutate(action|{'payload':payload('另一个请求')})
        with self.assertRaises(CloudError): self.act(row=self.first()|{'version':False})
        for field in ('kind','category','scope'):
            with self.assertRaises(CloudError):self.act(payload=payload(**{field:[]}))

    def test_queued_edits_coalesce_and_disabled_never_uploaded_text_stays_local(self):
        self.act(); row=self.first(); self.act(row=row,payload=payload('更正后的资料'))
        op=self.send(); self.assertEqual(op['expected_version'],0); self.assertEqual(len(self.remote.calls),1)
        self.assertEqual(self.first()['text'],'更正后的资料')
        self.act(payload=payload('仅留本机')); row=self.first(); self.act('disable',row)
        self.assertEqual(self.first()['state'],'disabled'); self.assertIsNone(self.store.reserve())

    def test_unknown_write_is_reconciled_before_explicit_same_id_retry(self):
        self.act(); op,_=self.store.reserve(); self.store.unknown(op['id'],'断连')
        with self.assertRaises(CloudError): self.act('retry',self.first())
        pending,mode=self.store.reserve(); self.assertEqual(mode,'reconcile'); self.assertEqual(pending['id'],op['id'])
        self.store.unknown(op['id'],'未查到',checked_missing=True); self.assertTrue(self.first()['can_retry'])
        self.act('retry',self.first()); retry,mode=self.store.reserve()
        self.assertEqual(mode,'apply'); self.assertEqual(retry['id'],op['id']); self.assertEqual(retry['payload'],op['payload'])

    def test_unknown_create_deleted_locally_never_restores_from_late_receipt_or_page(self):
        text='必须从当前资料逻辑存储清除的正文'
        self.act(payload=payload(text)); create,_=self.store.reserve()
        self.store.unknown(create['id'],'断连'); self.act('delete',self.first())
        self.assertEqual(self.first()['text'],''); self.assertEqual(self.first()['state'],'deleted')
        late=self.remote.apply(create['id'],create['record_id'],0,'put',create['payload'])
        self.store.finish(create['id'],late); self.pull()
        self.assertEqual(self.first()['text'],''); self.assertEqual(self.first()['state'],'deleted')
        delete=self.send(); self.assertEqual(delete['expected_version'],1); self.pull()
        self.assertEqual(self.first()['sync_state'],'synced')
        with closing(sqlite3.connect(self.store.path)) as db:
            for table in ['profile_records','profile_outbox','profile_receipts','profile_jobs']:
                self.assertNotIn(text,json.dumps(db.execute('SELECT * FROM '+table).fetchall(),ensure_ascii=False))

    def test_delete_reaches_server_before_unknown_create_and_installs_a_fence(self):
        self.act(); create,_=self.store.reserve(); self.store.unknown(create['id'],'断连')
        self.act('delete',self.first()); self.send()
        late=self.remote.apply(create['id'],create['record_id'],0,'put',create['payload'])
        self.assertEqual(late['status'],'gone'); self.store.finish(create['id'],late); self.pull()
        self.assertTrue(all(i['state']=='deleted' and not i['text'] for i in self.store.selection_items()))

    def test_missing_delete_receipt_can_retry_original_content_free_operation(self):
        self.act();self.send();self.act('delete',self.first());op,_=self.store.reserve()
        self.store.unknown(op['id'],'原删除未查到',checked_missing=True)
        self.act('retry',self.first());retry,mode=self.store.reserve()
        self.assertEqual(mode,'apply');self.assertEqual(retry['id'],op['id']);self.assertIsNone(retry['payload'])
        result=self.remote.apply(retry['id'],retry['record_id'],retry['expected_version'],'delete',None)
        self.store.finish(retry['id'],result);self.assertEqual(self.first()['sync_state'],'synced')

    def test_conflicts_require_a_fresh_remote_observation_and_explicit_resolution(self):
        self.act(); self.send(); self.pull(); self.act(row=self.first(),payload=payload('设备一'))
        ident=self.first()['id']; self.remote.apply(uid(),ident,1,'put',payload('设备二'))
        self.send(); self.assertEqual(self.first()['sync_state'],'conflict')
        with self.assertRaises(CloudError): self.act('resolve_local',self.first(),payload=payload('明确选择'))
        self.pull(); self.assertEqual(self.first()['remote']['text'],'设备二')
        self.assertEqual(memory_selection.select(items=self.store.selection_items())['selected'],[])
        self.act('resolve_remote',self.first()); self.assertEqual(self.first()['text'],'设备二')
        self.act(row=self.first(),payload=payload('下一版')); self.send(); self.pull()
        self.assertEqual(self.first()['cloud_version'],3)

    def test_remote_tombstone_cancels_offline_draft_and_old_pages_cannot_resurrect(self):
        self.act(); self.send(); self.pull(); old=self.remote.pull(0)
        self.act(row=self.first(),payload=payload('离线草稿'))
        self.remote.apply(uid(),self.first()['id'],1,'delete',None); self.pull()
        self.assertIsNone(self.store.reserve()); self.assertEqual(self.first()['state'],'deleted')
        with self.assertRaises(CloudError): self.store.receive_page(old,0)
        with self.assertRaises(CloudError): self.act(row=self.first())

    def test_bad_page_rolls_back_entire_batch_and_cursor(self):
        self.remote.apply(uid(),uid(),0,'put',payload('有效记录'))
        self.remote.apply(uid(),uid(),0,'put',payload('错误记录'))
        page=self.remote.pull(); page['records'][1]['version']=False
        with self.assertRaises(CloudError): self.store.receive_page(page,0)
        self.assertEqual(self.store.page()['records'],[]); self.assertEqual(self.store.page()['cursor'],0)

    def test_account_binding_rejects_copied_database_and_cross_user_pages(self):
        self.act(); other=self.new_store(self.home,B); other.path.parent.mkdir(parents=True)
        with closing(sqlite3.connect(self.store.path)) as source,closing(sqlite3.connect(other.path)) as dest: source.backup(dest)
        with self.assertRaises(CloudError): other.page()
        with self.assertRaises(CloudError): self.store.bind_cloud(URL,B)
        with self.assertRaises(CloudError): self.store.receive_page(Remote(B).pull(),0)

    def test_scope_selection_is_readonly_and_freezes_records_before_later_deletion(self):
        self.act(payload=payload('本次背景')); self.send(); self.pull()
        with patch('desk_companion.accounts.personalization.selected_items',self.store.selection_items),patch('desk_companion.memory.facts.read_facts',return_value=[]):
            selection=memory_selection.select({'project':'p'})
        original=deepcopy(selection); self.act('delete',self.first())
        from desk_companion.memory.context_sources import Message
        message=Message({'role':'system','content':''},'system'); memory_selection.inject(message,selection)
        self.assertIn('本次背景',message['content']); self.assertEqual(selection,original)
        self.assertEqual(selection['selected'][0]['source']['account'],self.store.runtime.key)
        self.assertEqual(memory_selection.select(items=self.store.selection_items())['selected'],[])
        with patch.object(self.store,'_ensure',side_effect=AssertionError('inspection must not migrate')):
            self.store.selection_items()

    def test_cloud_project_and_companion_scopes_reuse_the_actual_selection_policy(self):
        self.act(payload=payload('项目背景',scope='project',scope_id='p1'))
        self.act(payload=payload('伙伴偏好',scope='companion',scope_id='a1'))
        rows=self.store.selection_items()
        self.assertEqual({r['text'] for r in memory_selection.select(dict(project='p1',partner='a1'),items=rows)['selected']},{'项目背景','伙伴偏好'})
        self.assertEqual(memory_selection.select(dict(project='other',partner='other'),items=rows)['selected'],[])

    def service(self):
        store=self.store; remote=self.remote
        class Accounts:
            runtime=store.runtime
            def status(self): return dict(runtime=dict(key=store.runtime.key,mode='account',email='test@tebb.invalid'),configured=True,url=URL,
                selected=store.runtime.key,accounts=[dict(current=True,state='signed_in')])
            @contextmanager
            def cloud_client(self): yield remote
        service=PersonalizationService(Accounts(),store=store)
        self.addCleanup(service.shutdown)
        return service
    def wait(self,service):
        service._thread.join(6); self.assertFalse(service._thread.is_alive())
        return self.store.page()['job']

    def test_service_lost_response_queries_receipt_without_a_second_write(self):
        self.act(); self.remote.failure=CloudError('connection_failed','断连')
        service=self.service(); first=uid(); service.start(first); self.assertEqual(self.wait(service)['state'],'failed')
        self.remote.failure=None; service.start(uid()); self.assertEqual(self.wait(service)['state'],'complete')
        self.assertEqual(sum(c[0]=='apply' for c in self.remote.calls),1)
        self.assertTrue(any(c[0]=='operation' for c in self.remote.calls)); self.assertEqual(self.first()['sync_state'],'synced')
        service.start(first); self.assertEqual(sum(c[0]=='apply' for c in self.remote.calls),1)

    def test_service_cancel_and_process_recovery_preserve_original_operation(self):
        self.act(); self.remote.gate=threading.Event(); service=self.service(); service.start(uid())
        self.assertTrue(self.remote.entered.wait(3)); service.action(dict(type='cancel',job_id=self.store.page()['job']['id']))
        self.remote.gate.set(); self.assertEqual(self.wait(service)['state'],'cancelled')
        self.act(row=self.first()); op,_=self.store.reserve(); old=uid(); self.store.job(old,state='running')
        service.start(uid()); self.assertEqual(self.wait(service)['state'],'needs_confirmation')
        self.assertEqual(self.store.read_job(old)['state'],'interrupted')
        self.assertTrue(any(c[:2]==('operation',op['id']) for c in self.remote.calls))
        self.assertEqual(sum(c[0]=='apply' for c in self.remote.calls),1)

    def test_bounded_job_reports_pause_instead_of_false_completion(self):
        for i in range(26): self.act(payload=payload('记录'+str(i)))
        service=self.service(); service.start(uid()); self.assertEqual(self.wait(service)['state'],'paused')
        service.start(uid()); self.assertEqual(self.wait(service)['state'],'complete')
        self.assertEqual(sum(c[0]=='apply' for c in self.remote.calls),26)

    def test_late_cancel_is_bound_to_original_job_and_cannot_stop_a_new_job(self):
        service=self.service();old=uid();service.start(old);self.wait(service)
        self.act();self.remote.gate=threading.Event();service.start(uid())
        self.assertTrue(self.remote.entered.wait(3))
        result=service.action(dict(type='cancel',job_id=old))
        self.assertTrue(result['job']['cancel_requested']);self.assertFalse(service._cancel.is_set())
        self.remote.gate.set();self.assertEqual(self.wait(service)['state'],'complete')

    def test_host_ticks_resume_offline_queue_without_a_second_timer_or_blind_replay(self):
        self.act();service=self.service();service.tick(now=10);self.wait(service)
        self.assertEqual(sum(c[0]=='apply' for c in self.remote.calls),1)
        self.assertIsNone(service.tick(now=20));service.tick(now=70);self.wait(service)
        self.assertEqual(sum(c[0]=='apply' for c in self.remote.calls),1)
        job=self.store.page()['job']['id'];service.action(dict(type='cancel',job_id=job))
        self.assertIsNone(service.tick(now=200));self.assertTrue(service.status()['auto_paused'])
        service.start(uid());self.wait(service);self.assertFalse(service.status()['auto_paused'])


if __name__=='__main__': unittest.main()
