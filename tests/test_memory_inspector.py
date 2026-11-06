import copy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import unittest
import uuid
from unittest.mock import Mock, patch

import httpx
from openai import OpenAI
from atlas.llm import ChatOptions

from desk_companion.memory import facts
from desk_companion.memory import memory_selection as memory
from desk_companion.memory import memory_inspector as desk
from desk_companion.observability import agent_debug
from desk_companion.collaboration.store import transaction
from desk_companion.collaboration.service import Collaboration
from desk_companion.memory.context_sources import Message, digest, manifest, at_boundary
from desk_companion.collaboration.execution_context import ExecutionLLM

MODEL=dict(id='fixture-model',model='fixture',base_url='https://model.invalid/v1',api_key='SECRET_CONNECTION')


class Queue:
    def __init__(self):
        self.settings={};self.requests=[]
    def submit(self,text,session,channel,**request):
        self.requests.append(dict(text=text,session_id=session,**request))
        return uuid.uuid4().hex
    def get(self,ident):
        return dict(id=ident,state='queued',events=[],answer='',error='')
    def shutdown(self):pass


class MemoryDeskTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        p=patch.dict(os.environ,DESK_COMPANION_DATA_DIR=str(self.root));p.start();self.addCleanup(p.stop)
        for name,value in [('require_item',MODEL),('require_active',MODEL)]:
            p=patch('desk_companion.models.model_catalog.'+name,return_value=value);p.start();self.addCleanup(p.stop)
        (self.root/'models.json').write_text(json.dumps(dict(active=MODEL['id'],items=[MODEL])),encoding='utf-8')
        self.chat=Queue();self.work=Queue()
        self.collab=Collaboration(start=False,managers=dict(chat=self.chat,work=self.work))
        self.addCleanup(self.collab.shutdown)
        state=desk.read_state(self.collab)
        self.cid=next(c['id'] for c in state['conversations'] if c['coordinator']=='tebb')
        self.scope=dict(conversation=self.cid,partner='tebb',project='project-one')

    def save(self,text='喜欢短回答',**kwargs):
        return facts.change(dict(type='save',operation=uuid.uuid4().hex,text=text,**kwargs))

    def sent(self,text='请解释你的表达偏好'):
        return dict(type='send',conversation=self.cid,text=text,request_id=uuid.uuid4().hex)

    def capture(self):
        item=self.save()
        action=self.sent();preview=desk.preview(self.collab,action)
        self.collab.action(action)
        run=desk.read_state(self.collab)['runs'][-1]
        payload=preview['request']
        request=httpx.Request('POST',MODEL['base_url']+'/chat/completions?key=QUERY_SECRET',json=payload,headers={'Authorization':'SECRET_HEADER'})
        with agent_debug.context(session='collab-'+run['id'],model_id=MODEL['id'],assembly=preview['sources']):
            call=agent_debug.begin(request,payload)
        (agent_debug.root()/(call+'.response.txt')).write_text('{}',encoding='utf-8')
        agent_debug.update(call,state='succeeded')
        return item,call,preview

    def test_scopes_share_one_store_and_exclude_unrelated_owners(self):
        self.save('全局')
        for kind in ('project','partner','conversation'):
            self.save(kind,scope=kind,owner=self.scope[kind])
            self.save(kind+'其他',scope=kind,owner='other')
        selected=memory.select(self.scope)
        self.assertEqual({i['text'] for i in selected['selected']},{'全局','project','partner','conversation'})
        self.assertEqual(len(selected['excluded']),3)
        self.assertTrue(all('不属于' in i['reason'] for i in selected['excluded']))
        with memory.bind_scope(**self.scope):
            self.assertIn('全局',facts.facts_prompt());self.assertNotIn('其他',facts.facts_prompt())

    def test_auto_extraction_is_candidate_and_explicit_remember_is_active_in_smallest_scope(self):
        with facts.bind_turn_user('我喜欢咖啡'),memory.bind_scope(**self.scope):
            result=facts.remember_fact(dict(text='喜欢咖啡',quote='喜欢咖啡'))
        self.assertIn('待确认',result);self.assertNotIn('已记下',result)
        item=facts.read_facts()[0]
        self.assertEqual((item['scope'],item['owner']),('conversation',self.cid))
        self.assertFalse(memory.select(self.scope)['selected'])
        facts.change(dict(type='confirm',id=item['id'],version=1,operation=uuid.uuid4().hex))
        self.assertEqual(len(memory.select(self.scope)['selected']),1)
        with facts.bind_turn_user('请记住我喜欢茶'),memory.bind_scope(**self.scope):
            self.assertIn('已记下',facts.remember_fact(dict(text='喜欢茶',quote='喜欢茶',scope='user')))
        self.assertEqual(facts.read_facts()[1]['scope'],'user')
        with facts.bind_turn_user('不要记住我喜欢水'),memory.bind_scope(**self.scope):
            self.assertNotIn('已记下',facts.remember_fact(dict(text='喜欢水',quote='喜欢水')))

    def test_version_conflict_expiry_disable_and_explicit_correction(self):
        first=self.save('Node 18',key='runtime')
        second=self.save('Node 20',key='runtime')
        selected=memory.select(self.scope)
        self.assertFalse(selected['selected']);self.assertEqual({i['state'] for i in selected['excluded']},{'conflict'})
        first=next(i for i in facts.read_facts() if i['id']==first['id'])
        corrected=self.save('Node 20',id=second['id'],version=second['version'],key='runtime',supersedes=[dict(id=first['id'],version=first['version'])])
        self.assertEqual(memory.select(self.scope)['selected'][0]['text'],'Node 20')
        facts.change(dict(type='disable',id=corrected['id'],version=corrected['version'],operation=uuid.uuid4().hex))
        self.save('expired',expires='2000-01-01T00:00:00+00:00')
        result=memory.select(self.scope)
        self.assertFalse(result['selected']);self.assertIn('已到期',[i['reason'] for i in result['excluded']])

    def test_edits_compare_versions_and_reconcile_same_operation_without_overwrite(self):
        original=self.save()
        action=dict(type='save',id=original['id'],version=1,operation=uuid.uuid4().hex,text='新偏好')
        updated=facts.change(action)
        self.assertEqual(facts.change(action),updated)
        with self.assertRaises(ValueError):facts.change(dict(action,text='不同的修改'))
        with self.assertRaises(ValueError):facts.change(dict(action,operation=uuid.uuid4().hex))
        self.assertEqual(updated['versions'][0]['text'],original['text'])

    def test_existing_original_rows_are_not_rewritten_when_read(self):
        facts.add_user_fact('原始用户数据')
        path=facts.facts_path();before=path.read_bytes()
        memory.select(self.scope)
        self.assertEqual(path.read_bytes(),before)

    def test_preview_uses_worker_assembly_without_model_task_or_business_write(self):
        self.save()
        before={str(p.relative_to(self.root)):p.read_bytes() for p in self.root.rglob('*') if p.is_file() and 'locks' not in p.parts}
        with patch('desk_companion.tasks.task_budgets.Ledger.create',side_effect=AssertionError('preview writes budget')):
            result=desk.preview(self.collab,self.sent())
        after={str(p.relative_to(self.root)):p.read_bytes() for p in self.root.rglob('*') if p.is_file() and 'locks' not in p.parts}
        self.assertEqual(before,after)
        self.assertEqual(len(result['sources']['selection']['selected']),1)
        self.assertIn('喜欢短回答',result['request']['messages'][0]['content'])
        self.assertFalse(self.chat.requests);self.assertFalse(self.work.requests)

    def test_preview_matches_actual_worker_and_sent_snapshot_stays_frozen(self):
        item=self.save()
        fixed=datetime(2026,11,1,20,0,tzinfo=timezone.utc)
        with patch('datetime.datetime') as clock:
            clock.now.return_value=fixed;clock.fromtimestamp.side_effect=datetime.fromtimestamp
            action=self.sent();prepared=desk.preview(self.collab,action)
            self.collab.action(dict(action,preview_revision=prepared['revision']))
            self.collab.tick()
            request=self.chat.requests[-1]
            from desk_companion.collaboration.collaboration_worker import _execute
            actual=_execute(request,lambda *_:None,Mock(),preview=True)
        self.assertEqual(json.dumps(prepared['request']['messages']),json.dumps(actual['messages']))
        self.assertEqual(prepared['request'].get('tools'),actual['tools'])
        self.save('修改后的偏好',id=item['id'],version=item['version'])
        self.assertEqual(request['memory_snapshot']['selected'][0]['text'],item['text'])

    def test_stale_preview_is_rejected_without_creating_tasks_or_budgets(self):
        item=self.save();action=self.sent();preview=desk.preview(self.collab,action)
        self.save('已修改',id=item['id'],version=1)
        before=desk.read_state(self.collab)
        with patch('desk_companion.tasks.task_budgets.Ledger.create',side_effect=AssertionError('stale preview side effect')):
            with self.assertRaisesRegex(ValueError,'变化'):
                self.collab.action(dict(action,preview_revision=preview['revision']))
        self.assertEqual(desk.read_state(self.collab),before)

    def test_confirmed_account_profile_reaches_actual_worker_and_is_frozen_before_delete(self):
        from desk_companion.accounts.account_store import AccountRuntime, account_key, profile_root
        from desk_companion.accounts.personalization_store import PersonalizationStore
        owner='a0000000-0000-4000-8000-000000000001'
        key=account_key('https://profile.invalid',owner)
        home=self.root.resolve();store=PersonalizationStore(AccountRuntime(home,key,profile_root(home,key)))
        page=store.mutate(dict(type='save',request_id=str(uuid.uuid4()),confirmed=True,
            payload=dict(kind='preference',category='communication',text='ACCOUNT_PROFILE_先给结论',scope='user')))
        row=page['records'][0]
        with patch('desk_companion.accounts.personalization.selected_items',store.selection_items):
            prepared=desk.preview(self.collab,self.sent())
            self.collab.action(self.sent());self.collab.tick()
            request=self.chat.requests[-1]
            from desk_companion.collaboration.collaboration_worker import _execute
            actual=_execute(request,lambda *_:None,Mock(),preview=True)
            self.assertIn('ACCOUNT_PROFILE_先给结论',actual['messages'][0]['content'])
            source=request['memory_snapshot']['selected'][0]['source']
            self.assertEqual(source['account'],key);self.assertEqual(source['record_id'],row['id'])
            store.mutate(dict(type='delete',request_id=str(uuid.uuid4()),confirmed=True,id=row['id'],version=row['version']))
            self.assertIn('ACCOUNT_PROFILE_先给结论',request['memory_snapshot']['selected'][0]['text'])
            self.assertNotIn('ACCOUNT_PROFILE_先给结论',desk.preview(self.collab,self.sent())['request']['messages'][0]['content'])
            self.assertIn('ACCOUNT_PROFILE_先给结论',prepared['request']['messages'][0]['content'])
        with self.assertRaisesRegex(ValueError,'个人资料'):
            desk.edit(self.collab,self.cid,dict(id='personalization:'+row['id']))
        with self.assertRaisesRegex(ValueError,'个人资料'):
            desk.cleanup_preview(self.collab,self.cid,'personalization:'+row['id'])

    def test_capture_records_exact_boundary_without_headers_or_current_memory_substitution(self):
        item,call,preview=self.capture()
        self.save('未来内容',id=item['id'],version=1)
        detail=agent_debug.detail(call)
        self.assertEqual(detail['request'],json.loads(json.dumps(preview['request'])))
        sources=detail['meta']['sources']
        self.assertEqual(sources['request_sha256'],digest(detail['request']))
        self.assertTrue(all(row['status']=='matched' for row in sources['messages']))
        self.assertEqual(sources['selection']['selected'][0]['text'],item['text'])
        self.assertNotIn('SECRET_HEADER',json.dumps(detail));self.assertNotIn('QUERY_SECRET',json.dumps(detail))

    def test_trial_can_override_only_verified_memory_and_never_replays_tools(self):
        item,call,_=self.capture()
        material=desk.trial_material(self.collab,self.cid,call,{item['id']:'试验覆盖'})
        self.assertNotIn('tools',material['request'])
        self.assertIn('试验覆盖',material['request']['messages'][0]['content'])
        self.assertEqual(facts.read_facts()[0]['text'],item['text'])
        with self.assertRaises(ValueError):desk.trial_material(self.collab,self.cid,call,{'unknown':'伪造'})
        self.assertFalse(material['request'].get('tools'))
        task=Mock();task.submit.return_value='new-trial'
        lazy=Mock(return_value=task)
        result=desk.operate(self.collab,lazy,self.cid,dict(type='trial_run',call_id=call,revision=material['revision'],overrides={item['id']:'试验覆盖'},operation=uuid.uuid4().hex))
        self.assertEqual(result['task_id'],'new-trial')
        kwargs=task.submit.call_args.kwargs
        self.assertEqual(kwargs['workflow'],'memory_trial');self.assertEqual(kwargs['kind'],'memory_trial');self.assertNotIn('tools',kwargs)
        self.assertEqual(kwargs['trial_messages'],material['request']['messages'])

    def test_missing_call_files_and_legacy_unknown_are_not_reconstructed(self):
        _,call,_=self.capture()
        (agent_debug.root()/(call+'.meta.json')).unlink()
        with self.assertRaises(ValueError):desk.trial_material(self.collab,self.cid,call,{'unknown':None})
        (agent_debug.root()/(call+'.request.json')).unlink()
        from desk_companion.memory.context_inspector import inspect
        result=inspect(self.collab,self.cid,call)
        self.assertTrue(result['detail']['missing']);self.assertIsNone(result['detail']['request'])

    def test_corrupt_source_metadata_does_not_hide_existing_original_request(self):
        _,call,_=self.capture()
        (agent_debug.root()/(call+'.meta.json')).write_text('{incomplete',encoding='utf-8')
        from desk_companion.memory.context_inspector import inspect
        result=inspect(self.collab,self.cid,call)
        self.assertIsNotNone(result['detail']['request'])
        self.assertEqual(result['detail']['meta']['sources']['status'],'unknown')
        self.assertTrue(result['detail']['meta']['metadata_error'])

    def test_transport_source_digest_is_checked_after_sdk_serialization(self):
        self.save()
        message=Message(dict(role='system',content='fixture'),'system')
        message.selection=memory.select(self.scope)
        memory.inject(message,message.selection)
        requests=[]
        def respond(request):
            requests.append(json.loads(request.content))
            return httpx.Response(200,json=dict(id='fixture',object='chat.completion',created=1,model='fixture',choices=[dict(index=0,message=dict(role='assistant',content='ok'),finish_reason='stop')],usage=dict(prompt_tokens=5,completion_tokens=1,total_tokens=6)))
        agent_debug.install()
        with httpx.Client(transport=httpx.MockTransport(respond)) as transport:
            sdk=OpenAI(base_url=MODEL['base_url'],api_key=MODEL['api_key'],http_client=transport,max_retries=0)
            with ExecutionLLM(model=MODEL['model'],client=sdk,context_model_id=MODEL['id']) as llm:
                llm.chat([message,Message(dict(role='user',content='fixture'),'current_input')],options=ChatOptions(stream=False))
        with agent_debug.database() as db:
            call=db.execute('SELECT id FROM calls').fetchone()[0]
        detail=agent_debug.detail(call)
        self.assertEqual(detail['request'],requests[0])
        self.assertEqual(detail['meta']['sources']['messages'][0]['status'],'matched')
        assembly=manifest([message],message.selection)
        changed=dict(model='fixture',messages=[dict(role='system',content='different')])
        self.assertEqual(at_boundary(changed,assembly)['messages'][0]['status'],'unknown')

    def test_catalog_never_creates_task_manager_and_foreign_scope_edit_is_rejected(self):
        lazy=Mock(side_effect=AssertionError('inspection starts workers'))
        result=desk.operate(self.collab,lazy,self.cid,dict(type='catalog'))
        self.assertEqual(result['scope']['conversation'],self.cid);lazy.assert_not_called()
        with self.assertRaises(ValueError):
            desk.edit(self.collab,self.cid,dict(type='save',text='x',scope='project',owner='foreign',operation=uuid.uuid4().hex))

    def test_trial_worker_has_one_call_no_tools_and_does_not_apply_results(self):
        item,call,_=self.capture();material=desk.trial_material(self.collab,self.cid,call)
        events=[]
        model=Mock();model.chat.return_value=dict(message=dict(content='短回答'),usage={})
        context=Mock();context.__enter__=Mock(return_value=model);context.__exit__=Mock(return_value=False)
        before=facts.read_facts()
        with patch('desk_companion.collaboration.collaboration_llm.CollaborationLLM',return_value=context):
            desk.execute_trial(dict(model_id=MODEL['id'],target_revision=digest({k:MODEL[k] for k in ('id','model','base_url')}),limits=dict(call_timeout=60),trial_messages=material['request']['messages'],original_call=call),lambda k,v:events.append((k,v)))
        self.assertEqual(model.chat.call_count,1);self.assertIsNone(model.chat.call_args.kwargs['tools'])
        self.assertEqual(facts.read_facts(),before)
        self.assertIn(('result','短回答'),events)
        self.assertEqual([k for k,_ in events].count('llm_start'),1)
        self.assertEqual([k for k,_ in events].count('llm_end'),1)
        events.clear();model.chat.side_effect=TimeoutError('synthetic timeout')
        with patch('desk_companion.collaboration.collaboration_llm.CollaborationLLM',return_value=context):
            with self.assertRaises(TimeoutError):
                desk.execute_trial(dict(model_id=MODEL['id'],target_revision=digest({k:MODEL[k] for k in ('id','model','base_url')}),limits=dict(call_timeout=60),trial_messages=material['request']['messages'],original_call=call),lambda k,v:events.append((k,v)))
        self.assertEqual([k for k,_ in events].count('llm_end'),1)
        self.assertFalse(any(k=='result' for k,_ in events))

    def test_partner_preferences_preserve_versions_and_stop_without_losing_text(self):
        self.collab.action(dict(type='partner_memory',conversation=self.cid,agent_id='tebb',memory='旧偏好',request_id=uuid.uuid4().hex))
        row=next(i for i in desk.catalog(self.collab,self.cid)['selection']['selected'] if i['id']=='partner:tebb')
        desk.edit(self.collab,self.cid,dict(type='disable',id=row['id'],version=row['version'],operation=uuid.uuid4().hex))
        selection=desk.catalog(self.collab,self.cid)['selection']
        stopped=next(i for i in selection['excluded'] if i['id']==row['id'])
        self.assertEqual(stopped['text'],'旧偏好');self.assertEqual(stopped['versions'][-1]['text'],'旧偏好')
        with self.assertRaises(ValueError):
            desk.edit(self.collab,self.cid,dict(type='save',id=row['id'],version=row['version'],text='过时覆盖',operation=uuid.uuid4().hex))
        desk.edit(self.collab,self.cid,dict(type='save',id=row['id'],version=stopped['version'],text='新偏好',operation=uuid.uuid4().hex))
        self.assertEqual(desk.catalog(self.collab,self.cid)['selection']['selected'][0]['text'],'新偏好')

    def test_cleanup_requires_explicit_known_artifacts_and_reports_remaining_copies(self):
        item,call,_=self.capture()
        preview=desk.cleanup_preview(self.collab,self.cid,item['id'])
        self.assertIn(call,preview['known_calls'])
        self.assertTrue(agent_debug.detail(call)['request'])
        with self.assertRaises(ValueError):
            desk.cleanup_apply(self.collab,self.cid,dict(id=item['id'],revision=preview['revision'],calls=['not-known']))
        result=desk.cleanup_apply(self.collab,self.cid,dict(id=item['id'],revision=preview['revision'],calls=[call],delete_source=True))
        self.assertTrue(any(r['state']=='failed' for r in result['results']))
        self.assertTrue(facts.read_facts())
        listing=agent_debug.listing()['items'][0]
        self.assertTrue(listing['files_missing'])
        self.assertIn('原聊天',result['note'])
        facts.change(dict(type='disable',id=item['id'],version=1,operation=uuid.uuid4().hex))
        preview=desk.cleanup_preview(self.collab,self.cid,item['id'])
        result=desk.cleanup_apply(self.collab,self.cid,dict(id=item['id'],revision=preview['revision'],calls=[],delete_source=True))
        self.assertEqual(result['results'][0]['part'],'source_and_versions')
        self.assertEqual(facts.read_facts(),[])

    def test_projection_preserves_ordinary_sources_and_unknown_boundaries_never_claim_memory_used(self):
        from desk_companion.memory.context_sources import carry
        from desk_companion.chat.assistant import build_system_message
        self.save()
        source=build_system_message('系统规则')
        projected=[dict(source)]
        carried=carry(projected,[source])
        self.assertTrue(carried[0].sources)
        assembly=manifest(carried,source.selection)
        boundary=at_boundary(dict(messages=[dict(role='system',content='SDK changed input')]),assembly)
        self.assertFalse(boundary['selection']['selected'])
        self.assertIn('未知',boundary['selection']['excluded'][0]['reason'])

    def test_model_stop_uses_identity_version_and_explicit_intent_without_erasing_history(self):
        item=self.save()
        with facts.bind_turn_user('你好'):
            self.assertIn('没有停止使用',facts.forget_fact(dict(id=item['id'],version=1)))
        with facts.bind_turn_user('请忘记这条记忆'):
            self.assertIn('没有停止使用',facts.forget_fact(dict(id=item['id'],version=2)))
            self.assertIn('已停止后续使用',facts.forget_fact(dict(id=item['id'],version=1)))
        self.assertEqual(facts.read_facts()[0]['versions'][0]['text'],item['text'])
        self.assertFalse(memory.select(self.scope)['selected'])

    def test_trial_source_offsets_survive_task_json_and_one_call_budget_has_no_finish_reserve(self):
        from desk_companion.memory.context_sources import restore
        from desk_companion.tasks.task_budgets import Ledger
        item,call,_=self.capture()
        material=desk.trial_material(self.collab,self.cid,call,{item['id']:'试验文字比原文更长，用来核对来源位置和临时版本。'})
        serialized=json.loads(json.dumps(material,ensure_ascii=False))
        messages=restore(serialized['request']['messages'],serialized['sources'])
        boundary=at_boundary(dict(messages=messages),manifest(messages,messages[0].selection))
        self.assertEqual(boundary['selection']['selected'][0]['text'],'试验文字比原文更长，用来核对来源位置和临时版本。')
        for source in boundary['messages'][0]['sources']:
            if source['category'].startswith('memory_'):
                fragment=messages[0]['content'][source['start']:source['end']]
                self.assertIn(source['source']['text'],fragment)
        ledger=Ledger();root=ledger.create('fixture-trial','memory_trial',90000)
        self.assertEqual(ledger.read(root)['finish_reserve']['model_calls'],0)

    def test_explicit_model_correction_retains_prior_version_and_current_quote(self):
        item=self.save('项目使用 Node 18')
        args=dict(text='项目使用 Node 20',quote='Node 20',corrects=dict(id=item['id'],version=1))
        with memory.bind_scope(**self.scope),facts.bind_turn_user('Node 20'):
            self.assertIn('没有写入',facts.remember_fact(args))
        with memory.bind_scope(**self.scope),facts.bind_turn_user('请将这条记忆更正为 Node 20'):
            self.assertIn('已记下更正',facts.remember_fact(args))
            self.assertIn('没有写入',facts.remember_fact(args))
        updated=facts.read_facts()[0]
        self.assertEqual(updated['id'],item['id']);self.assertEqual(updated['version'],2)
        self.assertEqual(updated['versions'][0]['text'],item['text'])
        self.assertEqual(updated['quote'],'Node 20')
        self.assertEqual(updated['source']['conversation'],self.cid)

    def test_preview_freezes_route_capacity_sampling_and_selected_materials(self):
        action=self.sent()
        action['model_id']=MODEL['id']
        action['sampling']=dict(reasoning_effort='high',temperature=.8,top_p=.9)
        prepared=desk.preview(self.collab,action)
        self.assertEqual(prepared['request']['temperature'],.8)
        self.assertEqual(prepared['request']['reasoning_effort'],'low')  # actual route policy
        from desk_companion.models import model_capacity
        model_capacity.save(MODEL['id'],10000,1000)
        with self.assertRaisesRegex(ValueError,'变化'):
            self.collab.action(dict(action,preview_revision=prepared['revision']))
        prepared=desk.preview(self.collab,action)
        changed=dict(action,sampling=dict(reasoning_effort='high',temperature=.1,top_p=.9),preview_revision=prepared['revision'])
        with self.assertRaisesRegex(ValueError,'变化'):self.collab.action(changed)
        with patch('desk_companion.models.model_catalog.require_item',return_value={**MODEL,'base_url':'https://other.invalid/v1'}):
            with self.assertRaisesRegex(ValueError,'变化'):
                self.collab.action(dict(action,preview_revision=prepared['revision']))

    def test_worker_refuses_changed_configuration_before_transport(self):
        from desk_companion.collaboration.execution_context import configuration_revision
        from desk_companion.collaboration.collaboration_llm import CollaborationLLM, ConfigurationChanged
        revision=configuration_revision(MODEL)
        client=Mock()
        llm=CollaborationLLM(MODEL,{},20,client=client,expected_configuration_revision=revision)
        with patch('desk_companion.models.model_catalog.require_item',return_value={**MODEL,'model':'changed-model'}):
            with self.assertRaises(ConfigurationChanged):llm.chat([dict(role='user',content='fixture')])
        self.assertIsNone(llm._llm);client.assert_not_called()

    def test_preview_reads_selected_skill_and_attachment_without_creating_a_task(self):
        from desk_companion.knowledge import local_sources
        folder=self.root/'skills';(folder/'fixture').mkdir(parents=True)
        (folder/'fixture'/'SKILL.md').write_text('---\nname: fixture\ndescription: synthetic selected skill\n---\n合成技能正文末尾。',encoding='utf-8')
        document=self.root/'synthetic.md';document.write_text('合成附件正文末尾。',encoding='utf-8')
        source=local_sources.stage([str(document)])['sources'][0]
        action=dict(self.sent(),skills=['fixture'],attachments=[source['id']])
        with patch('desk_companion.integrations.skill_catalog.SKILLS_DIR',folder):
            prepared=desk.preview(self.collab,action)
        content=json.dumps(prepared['request']['messages'],ensure_ascii=False)
        self.assertIn('合成技能正文末尾',content);self.assertIn('合成附件正文末尾',content)
        self.assertEqual(prepared['action']['attachments'],[source['id']])
        self.assertFalse(self.chat.requests);self.assertFalse(self.work.requests)
