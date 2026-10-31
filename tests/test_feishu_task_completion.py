from contextlib import contextmanager
import copy
from datetime import datetime,timedelta
import json
from pathlib import Path
import tempfile
import unittest
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from desk_companion.calendar_time import TZ
from desk_companion.feishu_task_completion import FeishuTaskCompletionService
from desk_companion import board_data

GUID='b5e165af-3f0d-4708-89bc-c4fd3a69738d'
ACTOR=dict(identity='user',verified=True,app_id='app-one',brand='feishu',open_id='user-one',user_name='隔离用户')


class FakeBoard:
    def __init__(self):
        self.context=dict(date='2040-01-02',fetched_at='2040-01-02T09:00:00+08:00',task=dict(guid=GUID,summary='隔离任务',due_at='',url=''))
        self.saved=[];self.fail=False
    def visible_task_context(self,guid):
        if guid!=self.context['task']['guid']:raise RuntimeError('not visible')
        return copy.deepcopy(self.context)
    @contextmanager
    def calendar_operation(self):yield
    def cache_completed_task(self,context):
        if self.fail:raise OSError('synthetic cache failure')
        self.saved.append(copy.deepcopy(context));return dict(ok=True)


class TaskCompletionTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.path=Path(temp.name)/'receipts.json'
        self.now=datetime(2040,1,2,9,tzinfo=TZ);self.actor=copy.deepcopy(ACTOR);self.board=FakeBoard();self.calls=[];self.task_done=0
        self.reply=dict(status='done',completed_at='2200000000000',already_completed=False);self.write_error=None;self.after_write=None
        self.service=self.make_service()
    def make_service(self):return FeishuTaskCompletionService(path=self.path,clock=lambda:self.now,identity=lambda:copy.deepcopy(self.actor),cli=self.cli,board=self.board)
    def cli(self,args,timeout):
        self.calls.append((copy.deepcopy(args),timeout))
        if args[1:3]==['tasks','get']:
            return json.dumps(dict(ok=True,data=dict(task=dict(guid=GUID,summary='服务端核实标题',completed_at=str(self.task_done)))))
        self.assertEqual(args,['task','+complete','--task-id',GUID,'--as','user'])
        if self.after_write:self.after_write()
        if self.write_error:raise self.write_error
        return json.dumps(dict(ok=True,data=self.reply))
    def writes(self):return sum(args[1]=='+complete'for args,_ in self.calls)
    def prepare(self,key='request-number-0001'):
        result=self.service.prepare(GUID,key);self.assertTrue(result['ok'],result);self.assertEqual(result['state'],'prepared');return result

    def test_preparation_is_read_only_and_confirmation_uses_original_guid_once(self):
        result=self.prepare();self.assertEqual(result['summary'],'服务端核实标题');self.assertEqual(result['identity'],ACTOR);self.assertEqual(self.writes(),0)
        completed=self.service.complete(result['request_id']);self.assertTrue(completed['ok']);self.assertEqual(completed['remote_state'],'confirmed')
        self.assertEqual(completed['cache_state'],'confirmed');self.assertEqual(self.writes(),1);self.assertEqual(len(self.board.saved),1)
        self.assertEqual(len(self.calls),2,'confirmed shortcut needs no routine details GET')
        self.assertEqual(self.make_service().complete(result['request_id'])['state'],'confirmed');self.assertEqual(self.writes(),1)

    def test_display_id_and_nonvisible_guid_cannot_start_completion(self):
        self.assertFalse(self.service.prepare('t104121','request-number-0001')['ok'])
        self.assertFalse(self.service.prepare('6694f7b0-661e-42dc-9ec2-2428f119cb21','request-number-0002')['ok'])
        self.assertEqual(self.calls,[]);self.assertEqual(self.writes(),0)

    def test_account_change_stops_original_operation_before_any_write(self):
        self.prepare();self.actor['open_id']='different-user'
        result=self.service.complete('request-number-0001');self.assertFalse(result['ok']);self.assertEqual(result['stage'],'identity_changed');self.assertEqual(self.writes(),0)

    def test_account_change_during_prepare_does_not_offer_confirmation(self):
        identities=iter([ACTOR,{**ACTOR,'open_id':'different-user'}]);self.service.identity=lambda:copy.deepcopy(next(identities))
        result=self.service.prepare(GUID,'request-number-0001');self.assertFalse(result['ok']);self.assertEqual(result['state'],'not_started');self.assertEqual(self.writes(),0)

    def test_account_change_after_call_is_unknown_and_blocks_inspection_for_other_user(self):
        self.prepare();self.after_write=lambda:self.actor.update(open_id='different-user')
        result=self.service.complete('request-number-0001');self.assertEqual(result['state'],'unconfirmed');self.assertEqual(self.writes(),1)
        calls=len(self.calls);self.service.inspect('request-number-0001');self.assertEqual(len(self.calls),calls);self.assertEqual(self.board.saved,[])
        self.actor=copy.deepcopy(ACTOR);self.task_done=2200000000000;result=self.service.inspect('request-number-0001')
        self.assertEqual(result['state'],'observed_done');self.assertEqual(result['execution_result'],'unconfirmed');self.assertEqual(self.writes(),1)

    def test_disconnect_keeps_original_receipt_and_inspection_only_reads(self):
        self.prepare();self.write_error=TimeoutError('synthetic disconnect')
        unknown=self.service.complete('request-number-0001');self.assertEqual(unknown['state'],'unconfirmed');self.assertEqual(self.writes(),1)
        self.assertEqual(unknown['observed_state'],'unknown');self.assertEqual(unknown['observed_at'],'');self.assertEqual(unknown['completed_at'],'')
        self.service.complete('request-number-0001');second=self.service.prepare(GUID,'request-number-0002')
        self.assertEqual(second['request_id'],'request-number-0001');self.assertEqual(self.writes(),1)
        open_result=self.service.inspect('request-number-0001');self.assertEqual(open_result['state'],'unconfirmed');self.assertEqual(open_result['observed_state'],'open')
        self.task_done=2200000000000;done=self.make_service().inspect('request-number-0001');self.assertEqual(done['state'],'observed_done');self.assertEqual(done['execution_result'],'unconfirmed')
        self.assertEqual(self.writes(),1);self.assertEqual(len(self.board.saved),1)

    def test_missing_confirmation_fields_are_unknown_even_if_shortcut_says_ok(self):
        for field in('status','completed_at','already_completed'):
            with self.subTest(field=field):
                temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.service=FeishuTaskCompletionService(path=Path(temp.name)/'state.json',clock=lambda:self.now,identity=lambda:ACTOR,cli=self.cli,board=self.board)
                self.reply=dict(status='done',completed_at='2200000000000',already_completed=False);self.reply.pop(field);self.prepare()
                result=self.service.complete('request-number-0001');self.assertEqual(result['state'],'unconfirmed');self.assertTrue(result['receipt']['shortcut_ok'])
        self.assertEqual(self.board.saved,[])

    def test_already_completed_is_confirmed_without_an_extra_query(self):
        self.prepare();self.reply['already_completed']=True;result=self.service.complete('request-number-0001')
        self.assertTrue(result['already_completed']);self.assertEqual(result['state'],'confirmed');self.assertEqual(len(self.calls),2)

    def test_cache_failure_does_not_erase_remote_confirmation_or_allow_another_prepared_write(self):
        self.prepare();self.prepare('request-number-0002');self.board.fail=True
        result=self.service.complete('request-number-0001');self.assertEqual(result['remote_state'],'confirmed');self.assertEqual(result['cache_state'],'unconfirmed')
        again=self.service.complete('request-number-0002');self.assertEqual(again['request_id'],'request-number-0001');self.assertEqual(self.writes(),1)

    def test_cache_receipt_disk_failure_preserves_known_remote_confirmation(self):
        self.prepare();save=self.service._save
        def fail(key,**fields):
            if 'cache_state'in fields:raise OSError('synthetic receipt disk failure')
            return save(key,**fields)
        with patch.object(self.service,'_save',side_effect=fail):result=self.service.complete('request-number-0001')
        self.assertFalse(result['ok']);self.assertEqual(result['state'],'confirmed');self.assertEqual(result['execution_result'],'confirmed')
        self.assertEqual(result['remote_state'],'confirmed');self.assertEqual(result['receipt_state'],'unconfirmed')
        self.assertEqual(self.service.complete('request-number-0001')['state'],'confirmed');self.assertEqual(self.writes(),1)

    def test_expired_or_changed_visible_context_cannot_write(self):
        self.prepare();self.now+=timedelta(minutes=3);self.assertEqual(self.service.complete('request-number-0001')['stage'],'expired');self.assertEqual(self.writes(),0)
        self.prepare('request-number-0002');self.board.context['fetched_at']='changed'
        self.assertEqual(self.service.complete('request-number-0002')['stage'],'cache_changed');self.assertEqual(self.writes(),0)

    def test_a_reopened_task_needs_a_fresh_visible_snapshot_and_new_verified_confirmation(self):
        self.prepare();self.service.complete('request-number-0001');self.assertEqual(self.writes(),1)
        self.board.context['fetched_at']='2040-01-02T09:02:00+08:00'
        self.prepare('request-number-0002');self.assertEqual(self.writes(),1)
        result=self.service.complete('request-number-0002');self.assertEqual(result['state'],'confirmed');self.assertEqual(self.writes(),2)

    def test_interrupted_call_recovers_unknown_without_replaying(self):
        self.prepare();self.service._save('request-number-0001',state='calling',execution_result='unconfirmed',remote_state='unconfirmed')
        result=self.make_service().status('request-number-0001');self.assertEqual(result['state'],'unconfirmed');self.assertEqual(result['stage'],'interrupted')
        self.make_service().complete('request-number-0001');self.assertEqual(self.writes(),0)

    def test_failed_readonly_inspection_preserves_unknown_in_both_receipt_and_response(self):
        self.prepare();self.write_error=TimeoutError();self.service.complete('request-number-0001')
        self.service.identity=lambda:(_ for _ in()).throw(RuntimeError('synthetic disconnected identity'))
        result=self.service.inspect('request-number-0001');self.assertFalse(result['ok']);self.assertEqual(result['state'],'unconfirmed')
        self.assertEqual(self.service.status('request-number-0001')['state'],'unconfirmed');self.assertEqual(self.writes(),1)

    def test_concurrent_request_id_collision_cannot_rebind_another_visible_task(self):
        other='6694f7b0-661e-42dc-9ec2-2428f119cb21';barrier=threading.Barrier(2);original=self.service._record
        def read(key):
            value=original(key)
            if value is None:barrier.wait(5)
            return value
        self.service._record=read
        self.board.visible_task_context=lambda guid:{**self.board.context,'task':dict(guid=guid,summary=guid)}
        def cli(args,timeout):
            guid=json.loads(args[args.index('--params')+1])['task_guid'];return json.dumps(dict(ok=True,data=dict(task=dict(guid=guid,summary=guid,completed_at='0'))))
        self.service.cli=cli
        with ThreadPoolExecutor(max_workers=2)as pool:results=list(pool.map(lambda guid:self.service.prepare(guid,'shared-request-0001'),[GUID,other]))
        self.assertEqual(sum(result['ok']for result in results),1)
        saved=json.loads(self.path.read_text('utf-8'))['operations'];self.assertEqual(len(saved),1);row=saved['shared-request-0001']
        self.assertEqual(row['summary'],row['guid']);self.assertEqual(row['context']['task']['guid'],row['guid'])

    def test_request_id_cannot_be_rebound_and_corrupt_receipts_are_preserved(self):
        self.prepare();other=self.service.prepare('6694f7b0-661e-42dc-9ec2-2428f119cb21','request-number-0001')
        self.assertFalse(other['ok']);self.assertEqual(self.service.status('request-number-0001')['guid'],GUID)
        self.path.write_text('{broken',encoding='utf-8');self.assertFalse(self.service.status()['ok']);self.assertEqual(self.path.read_text('utf-8'),'{broken')


class CompletionBoardCacheTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.path=Path(temp.name)/'today.json'
        self.addCleanup(patch.stopall);patch.object(board_data,'today_path',return_value=self.path).start();patch.object(board_data,'today_date',return_value='2040-01-02').start()
        self.snapshot=dict(date='2040-01-02',fetched_at='2040-01-02T09:00:00+08:00',agenda=dict(ok=True,items=[]),
            tasks=dict(ok=True,items=[dict(guid=GUID,summary='隔离任务'),dict(guid='other',summary='其他任务')]),summary='',summary_at='',doc_url='')
        self.path.write_text(json.dumps(self.snapshot),encoding='utf-8')
    def test_completion_updates_only_the_original_visible_task_and_preserves_other_sections(self):
        context=board_data.visible_task_context(GUID)
        with board_data.calendar_operation():board_data.cache_completed_task(context)
        result=json.loads(self.path.read_text('utf-8'));self.assertEqual(result['tasks']['items'],[dict(guid='other',summary='其他任务')])
        for key in('agenda','summary','summary_at','doc_url'):self.assertEqual(result[key],self.snapshot[key])
    def test_changed_cache_or_cross_day_never_applies_old_confirmation(self):
        context=board_data.visible_task_context(GUID);self.snapshot['fetched_at']='new version';self.path.write_text(json.dumps(self.snapshot),encoding='utf-8');before=self.path.read_bytes()
        with self.assertRaises(RuntimeError):board_data.cache_completed_task(context)
        self.assertEqual(self.path.read_bytes(),before)
        with patch.object(board_data,'today_date',return_value='2040-01-03'),self.assertRaises(board_data.BoardChangeError):board_data.cache_completed_task(context)
