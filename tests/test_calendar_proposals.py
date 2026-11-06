import copy
from types import SimpleNamespace
import unittest
import os,tempfile
from unittest.mock import patch

from desk_companion.planning.calendar_proposals import build, validate, CalendarProposalService, tool_spec, task_event

FIELDS=dict(summary='核对项目启动',start='2040-01-02T09:00:00+08:00',end='2040-01-02T10:00:00+08:00',timezone='Asia/Shanghai',item_id='work-item-one')


class CalendarProposalTests(unittest.TestCase):
    def setUp(self):
        self.items=[dict(id='work-item-one',title='合成事项',archived=False)];self.calls=[]
        self.proposal=build(FIELDS,task_id='task-one',run_id='run-one',items=self.items)['proposal']
        self.task=dict(id='task-one',answer='模型自由正文不作为协议',events=[dict(kind='calendar_proposal',data=dict(proposal=copy.deepcopy(self.proposal),call_id='call-one'))])
        self.page=dict(ok=True,events=[],operation=None)
        self.service=CalendarProposalService(SimpleNamespace(load=lambda:dict(ok=True,items=self.items)),
            SimpleNamespace(local=SimpleNamespace(load=self.load)),lambda ident:self.task)
    def load(self,**args):self.calls.append(args);return copy.deepcopy(self.page)

    def test_normalized_fields_and_actual_source_determine_stable_proposal_and_save_ids(self):
        result=build({**FIELDS,'start':'2040-01-02T01:00:00+00:00'},task_id='task-one',run_id='run-one',items=self.items)['proposal']
        self.assertEqual(result,self.proposal);self.assertEqual(validate(result,task_id='task-one'),self.proposal)
        self.assertNotEqual(build(FIELDS,task_id='another-task',items=self.items)['proposal']['id'],result['id'])
        self.assertEqual(build(FIELDS,task_id='task-one',run_id='run-one',items=self.items)['change_state'],'not_changed')

    def test_invalid_time_zone_naive_times_source_items_or_tampered_fields_are_rejected(self):
        for change in[dict(timezone='UTC'),dict(start='2040-01-02T09:00'),dict(start='2040-01-02T09:00:30+08:00'),dict(item_id='missing'),dict(end=FIELDS['start'])]:
            with self.subTest(change=change),self.assertRaises(ValueError):build({**FIELDS,**change},task_id='task-one',items=self.items)
        with self.assertRaises(ValueError):validate({**self.proposal,'summary':'被替换'},task_id='task-one')
        with self.assertRaises(ValueError):validate(self.proposal,task_id='another-task')

    def test_repeated_open_only_reads_original_events_and_local_receipt(self):
        before=copy.deepcopy(self.task)
        for _ in range(2):self.assertEqual(self.service.read('task-one',self.proposal['id'])['state'],'proposed')
        self.assertEqual(self.task,before);self.assertEqual(self.calls,[dict(request_id=self.proposal['save_request_id'])]*2)

    def test_free_model_text_or_other_task_cannot_supply_a_proposal(self):
        self.task['events']=[];self.task['answer']=str(self.proposal)
        self.assertFalse(self.service.read('task-one',self.proposal['id'])['ok']);self.assertEqual(self.calls,[])
        self.task['id']='another-task';self.assertFalse(self.service.read('task-one',self.proposal['id'])['ok'])

    def test_saved_consumed_and_unconfirmed_states_never_recreate_a_calendar_event(self):
        self.page['events']=[dict(local_id=self.proposal['id'],summary='用户调整后的标题')]
        self.page['operation']=dict(id=self.proposal['save_request_id'],state='saved')
        self.assertEqual(self.service.read('task-one',self.proposal['id'])['state'],'saved')
        self.page['events']=[];self.page['operation']=dict(id=self.proposal['save_request_id'],state='saved')
        self.assertEqual(self.service.read('task-one',self.proposal['id'])['state'],'consumed')
        self.page=dict(ok=False,error='synthetic disconnected');self.assertEqual(self.service.read('task-one',self.proposal['id'])['state'],'unconfirmed')

    def test_archived_source_blocks_new_draft_but_does_not_hide_an_existing_saved_event(self):
        self.items[0]['archived']=True;self.assertFalse(self.service.read('task-one',self.proposal['id'])['ok'])
        self.page['events']=[dict(local_id=self.proposal['id'])];self.page['operation']=dict(id=self.proposal['save_request_id'],state='saved')
        self.assertEqual(self.service.read('task-one',self.proposal['id'])['state'],'saved')

    def test_event_without_confirmed_original_receipt_remains_unconfirmed(self):
        self.page['events']=[dict(local_id=self.proposal['id'])]
        for operation in(None,dict(state='calling'),dict(state='unconfirmed')):
            with self.subTest(operation=operation):
                self.page['operation']=operation;result=self.service.read('task-one',self.proposal['id'])
                self.assertFalse(result['ok']);self.assertEqual(result['state'],'unconfirmed')

    def test_current_tool_requires_task_context_and_emits_a_valid_source_bound_event(self):
        from desk_companion.observability.agent_debug import context
        from desk_companion.planning.work_board import WorkBoardService
        with tempfile.TemporaryDirectory()as folder,patch.dict(os.environ,DESK_COMPANION_DATA_DIR=folder):
            board=WorkBoardService();made=board.change(dict(type='create',request_id='proposal-setup-item',fields=dict(title='实际事项')))
            self.assertTrue(made['ok'],made);item=next(row for row in made['items']if row['title']=='实际事项')
            spec=tool_spec();self.assertTrue(spec['read_only'])
            with patch('desk_companion.observability.agent_debug.metadata',return_value={}):
                with self.assertRaises(ValueError):spec['implementation']({**FIELDS,'item_id':item['id']})
            with context(task_id='actual-task',collab_run='actual-run'):result=spec['implementation']({**FIELDS,'item_id':item['id']})
            event=task_event(result,'actual-task','actual-call');self.assertEqual(event['proposal']['source'],dict(task_id='actual-task',run_id='actual-run'))
            with self.assertRaises(ValueError):task_event(result,'different-task','actual-call')

    def test_executor_respects_the_selected_proposal_capability_even_for_tebb(self):
        from desk_companion.collaboration.collaboration_worker import execute
        from desk_companion.collaboration.service import initialize_workspace
        class Captured(Exception):pass
        observed=[]
        class Model:
            def chat(self,messages,tools,on_delta):
                observed.append({tool['function']['name']for tool in tools});raise Captured()
        with tempfile.TemporaryDirectory()as folder,patch.dict(os.environ,DESK_COMPANION_DATA_DIR=folder),patch('desk_companion.models.model_catalog.require_item',return_value=dict(id='fixture',model='fixture',api_key='fixture-only',base_url='https://example.invalid/v1')):
            initialize_workspace(folder+'/workspace.sqlite3')
            for enabled in(False,True):
                request=dict(task_id='actual-task',kind='task',role=dict(id='tebb',name='tebb',role='合成能力验收',tools=['日程提案']if enabled else[]),text='核对工具开关',context=[],workspace={},model_id='fixture',budget=6,collab_run='actual-run',collab_path=folder+'/workspace.sqlite3')
                with self.assertRaises(Captured):execute(request,lambda *args:None,Model())
                self.assertEqual('calendar_propose'in observed[-1],enabled)
