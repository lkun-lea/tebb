"""Capability authoring, frozen graph instances and real node adapters."""
import copy
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

from desk_companion.workflows import WorkflowService
from desk_companion.workflow_graph import validate
from desk_companion.workflow_nodes import execute
from tests.test_workflows import FakeTasks,node,graph


class AuthoringTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.env=patch.dict(os.environ,DESK_COMPANION_DATA_DIR=temp.name);self.env.start();self.addCleanup(self.env.stop)
        self.tasks=FakeTasks();self.service=WorkflowService(lambda:self.tasks)

    def operation(self,op,/,**payload):
        value=self.service.operation(op,payload)
        self.assertTrue(value['ok'],value)
        return value

    def capability(self,**changes):
        payload=dict(name='提取行动项',kind='ai',template=dict(prompt='提取行动项：{{input.text}}',model_id=''),parameters=dict(text=''),operation=uuid.uuid4().hex)
        payload.update(changes)
        return payload,self.operation('capability_save',**payload)['capability']

    def test_capability_save_is_idempotent_and_rejects_reused_identity_and_stale_edits(self):
        payload,cap=self.capability()
        self.assertEqual(self.operation('capability_save',**payload)['capability'],cap)
        self.assertFalse(self.service.operation('capability_save',{**payload,'name':'changed'})['ok'])
        changed=self.operation('capability_save',**{**payload,'id':cap['id'],'revision':1,'operation':uuid.uuid4().hex,'template':dict(prompt='新版{{input.text}}',model_id='')})['capability']
        self.assertEqual(changed['revision'],2)
        self.assertFalse(self.service.operation('capability_save',{**payload,'id':cap['id'],'revision':1,'operation':uuid.uuid4().hex})['ok'])
        self.assertEqual(self.operation('capability_load',id=cap['id'],version=cap['version'])['capability'],cap)

    def test_instances_freeze_config_and_source_even_when_capability_is_edited(self):
        payload,cap=self.capability()
        instance=self.operation('capability_instantiate',id=cap['id'],version=cap['version'],node_id='extract',arguments=dict(text='{{trigger.text}}'))['node']
        self.assertEqual(instance['config']['prompt'],'提取行动项：{{trigger.text}}')
        definition=self.operation('save',name='实例',graph=graph(node('trigger','trigger'),instance))['definition']
        self.operation('capability_save',**{**payload,'id':cap['id'],'revision':1,'operation':uuid.uuid4().hex,'template':dict(prompt='changed',model_id='')})
        self.assertEqual(self.operation('load',id=definition['id'])['definition']['graph']['nodes'][1]['config']['prompt'],instance['config']['prompt'])
        self.assertEqual(instance['capability']['version'],cap['version'])
        forged=copy.deepcopy(definition['graph']);forged['nodes'][1]['capability']['version']='0'*64
        self.assertFalse(self.service.operation('save',dict(name='forged',graph=forged))['ok'])

    def test_capability_cannot_add_code_unknown_adapters_or_dynamic_external_targets(self):
        for changes in [dict(kind='python'),dict(template=dict(prompt='{{input.unknown}}')),dict(kind='message',template=dict(chat_id='{{input.text}}',text='hello',profile=''))]:
            with self.subTest(changes=changes):
                payload=dict(name='bad',kind='ai',template=dict(prompt='text'),parameters=dict(text=''),operation=uuid.uuid4().hex);payload.update(changes)
                self.assertFalse(self.service.operation('capability_save',payload)['ok'])
        self.assertEqual(self.service.store.definitions(),[]);self.assertEqual(self.tasks.requests,[])

    def test_graph_save_operation_receipt_does_not_duplicate_or_overwrite_later_edit(self):
        payload=dict(name='first',graph=graph(node('trigger','trigger')),operation_id=uuid.uuid4().hex,id='stable')
        first=self.operation('save',**payload)['definition']
        self.assertEqual(self.operation('save',**payload)['definition'],first)
        newer=self.operation('save',id='stable',revision=1,name='second',graph=payload['graph'])['definition']
        self.assertEqual(self.operation('save',**payload)['definition'],first)
        self.assertEqual(self.operation('load',id='stable')['definition'],newer)
        self.assertFalse(self.service.operation('save',{**payload,'name':'different'})['ok'])

    def test_saved_authoring_version_is_real_progress_only_once(self):
        from desk_companion.task_budgets import Ledger,installed,record_progress
        ledger=Ledger();root=ledger.create('fixture-authoring');ledger.bind(root,'fixture-task',root_member=True,purpose='task')
        payload,cap=self.capability()
        with installed('fixture-task'):
            record_progress('capability_save',payload,dict(ok=True,capability=cap))
            record_progress('capability_save',payload,dict(ok=True,capability=cap))
            record_progress('workflow_save',{},dict(ok=False,definition=dict(id='fake',version='0'*64)))
            record_progress('workflow_save',{},dict(ok=True,definition=dict(id='fake',version='not-a-version')))
        progress=ledger.read(root)['progress']
        self.assertEqual(len(progress),1);self.assertEqual(progress[0]['kind'],'authoring_artifact')

    def test_templates_are_editable_and_do_not_create_tasks_or_publish(self):
        templates=self.operation('templates')['templates']
        for item in templates:
            draft=copy.deepcopy(item['graph'])
            for n in draft['nodes']:
                if n['kind']=='message':n['config']['chat_id']='oc_fixture'
                if n['kind']=='base':n['config'].update(base_token='base_fixture',table_id='table_fixture',key_field='回执')
            validate(draft)
            self.operation('save',name=item['name'],graph=draft)
        self.assertEqual(self.tasks.requests,[])

    def test_video_uses_actual_subtitles_with_coverage_and_never_auto_archives(self):
        source=dict(source_id='fixture',url='https://www.youtube.com/watch?v=abcdefghijk',title='source',subtitle_status='available',segments=[dict(start=12,text='真实字幕')],truncated=False)
        with patch('desk_companion.video.read_video',return_value=dict(source_id='fixture')),patch('desk_companion.video.get_source',return_value=source),patch('desk_companion.video.export_summary') as export:
            value=execute('video',dict(url=source['url']),'receipt',lambda *args:None,{})
            self.assertIn('真实字幕',value['text']);self.assertIn('0:12',value['text']);self.assertTrue(value['complete']);export.assert_not_called()
            source['segments']=[]
            with self.assertRaises(ValueError):execute('video',dict(url=source['url']),'receipt',lambda *args:None,{})

    def test_news_reuses_five_item_validator_and_no_publisher(self):
        report=dict(lead='verified',candidate_count=5,items=[])
        with patch('desk_companion.news.summarize',return_value=report) as summarize:
            value=execute('news_report',dict(day='2026-11-02',candidates=json.dumps([{}]*5)),'receipt',lambda *args:None,{})
            self.assertEqual(summarize.call_args.args[1],dict(highlights=5));self.assertEqual(value['report'],report)

    def test_news_deduplicates_only_actual_confirmed_publications_not_drafts_or_unknown_writes(self):
        definition=self.operation('save',name='publication',graph=graph(node('trigger','trigger'),node('report','news_report',day='2026-11-01',candidates='[1,2,3,4,5]'),node('doc','document',title='报告',content='{{report.text}}')))['definition']
        run=self.service.store.create_run(definition['id'],definition['version'],'publication-test','full',{},True)
        report=dict(items=[dict(url='https://example.com/known',published='2026-11-01')])
        self.service.store.receipt(run['id'],definition['graph']['nodes'][1],'confirmed',inputs=dict(day='2026-11-01'),output=dict(text='内容',report=report))
        doc=definition['graph']['nodes'][2]
        for state in ('pending','unknown','failed'):
            self.service.store.receipt(run['id'],doc,state,inputs=dict(content='https://example.com/known'))
            self.assertEqual(self.service.store.published_news('2026-10-31','2026-11-02'),set())
        self.service.store.receipt(run['id'],doc,'confirmed',inputs=dict(content='https://example.com/different'))
        self.assertEqual(self.service.store.published_news('2026-10-31','2026-11-02'),set())
        self.service.store.receipt(run['id'],doc,'confirmed',inputs=dict(content='https://example.com/known'))
        self.assertEqual(self.service.store.published_news('2026-10-31','2026-11-02'),{('https://example.com/known','2026-11-01')})

    def test_parent_checks_role_and_active_run_before_authoring_and_blocks_execution(self):
        from desk_companion.collaboration import Collaboration,transaction
        from tests.test_collaboration import MODEL,Queue
        from desk_companion.workflow_tools import execute as author
        with patch('desk_companion.model_catalog.require_active',return_value=MODEL),patch('desk_companion.model_catalog.require_item',return_value=MODEL):
            class PhysicalQueue(Queue):
                def get(self,task,events=False):return super().get(task)
            work=PhysicalQueue()
            collaboration=Collaboration(managers=dict(work=work,chat=Queue()),start=False);self.addCleanup(collaboration.shutdown)
            host=SimpleNamespace(collaboration=collaboration,automation=SimpleNamespace(workflows=self.service))
            run=collaboration.action(dict(type='send',conversation='dm-tebb',text='搭建流程',mode='message',request_id=uuid.uuid4().hex))['state']['runs'][-1]
            task_id='physical-stage-1'
            work.items[task_id]=dict(id=task_id,state='running',channel='collaboration',session='collab-'+run['id'],answer='',error='',events=[])
            with transaction(collaboration.path) as (state,_):
                state['runs'][-1].update(kind='task',state='running',task=task_id)
            self.assertTrue(author(host,run['id'],'workflow_catalog',{},'',task_id)['ok'])
            payload=dict(name='伙伴草稿',graph=graph(node('trigger','trigger')))
            with self.assertRaises(ValueError):author(host,run['id'],'workflow_save',payload,'',task_id)
            with self.assertRaises(ValueError):author(host,run['id'],'workflow_save',payload,'call-1','old-stage')
            first=author(host,run['id'],'workflow_save',payload,'call-1',task_id)
            self.assertEqual(author(host,run['id'],'workflow_save',payload,'call-1',task_id),first)
            with self.assertRaises(ValueError):author(host,run['id'],'start',{},'call-1',task_id)
            work.items[task_id]['state']='cancelled'
            with self.assertRaises(ValueError):author(host,run['id'],'workflow_save',payload,'call-2',task_id)
            work.items[task_id]['state']='running'
            with transaction(collaboration.path) as (state,_):state['runs'][-1]['state']='cancelling'
            with self.assertRaises(ValueError):author(host,run['id'],'workflow_save',payload,'call-2',task_id)
            foreign=collaboration.action(dict(type='send',conversation='dm-writer',text='未授权伙伴',mode='message',request_id=uuid.uuid4().hex))['state']['runs'][-1]
            with transaction(collaboration.path) as (state,_):state['runs'][-1].update(kind='task',state='running',task='physical-stage-2')
            with self.assertRaisesRegex(ValueError,'未授予'):author(host,foreign['id'],'workflow_catalog',{},'call-2','physical-stage-2')
            self.assertEqual(self.tasks.requests,[])

    def test_legacy_agent_tools_cannot_enable_run_retype_or_delete_workflow_plans(self):
        from desk_companion.automation_service import AutomationService
        from desk_companion import automation
        definition=self.operation('save',name='界面确认版本',graph=graph(node('trigger','trigger'),node('doc','document',title='正文',content='{{trigger.text}}')))['definition']
        scheduler=AutomationService(tasks=lambda:self.tasks);self.addCleanup(lambda:scheduler.stop(0))
        payload=dict(name='已保存计划',action='workflow',enabled=False,cadence='daily',hour=9,minute=0,weekdays=[],doc='',workflow_id=definition['id'],workflow_version=definition['version'],workflow_write_version=definition['version'])
        saved=scheduler.save_automation_job(payload);self.assertTrue(saved['ok'],saved)
        before=automation.load_store()['jobs']
        for attack in ({**payload,'enabled':True},{**payload,'id':saved['job_id'],'action':'tebb_task','goal':'disguised'}):
            self.assertFalse(scheduler.save_automation_job(attack,_from_agent=True)['ok'])
        self.assertFalse(scheduler.run_automation_job(saved['job_id'],_from_agent=True)['ok'])
        self.assertFalse(scheduler.delete_automation_job(saved['job_id'],_from_agent=True)['ok'])
        self.assertEqual(automation.load_store()['jobs'],before);self.assertEqual(self.tasks.requests,[])

    def test_stale_advance_attempt_cannot_confirm_a_later_execution_phase(self):
        definition=self.operation('save',name='单步',graph=graph(node('trigger','trigger')))['definition']
        run=self.service.store.create_run(definition['id'],definition['version'],'stale-phase','step',{},False)
        with self.service.store.db(True) as db:db.execute("UPDATE runs SET state='paused',attempt=2 WHERE id=?",(run['id'],))
        result=self.service.operation('advance',dict(run_id=run['id'],expected_attempt=0))
        self.assertFalse(result['ok']);self.assertIn('阶段已变化',result['error']);self.assertEqual(self.tasks.requests,[])
