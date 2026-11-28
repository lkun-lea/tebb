import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import uuid

from desk_companion.collaboration.collaboration_worker import execute, PublicFailure
from desk_companion.integrations.web.web_sources import source_catalog


class ScriptedModel:
    def __init__(self,drafts,assessments=None):
        self.drafts=iter(drafts);self.assessments=iter(assessments or []);self.calls=[]

    def chat(self,messages,tools=None,on_delta=None):
        self.calls.append(dict(messages=copy.deepcopy(messages),tools=copy.deepcopy(tools)))
        if messages[0]['content'].startswith('反馈审阅协议'):
            rows=json.loads(messages[1]['content'])['materials']
            row=next((r for r in rows if r['level']=='body'),rows[0])
            status=next(self.assessments,'supported')
            value=dict(requirements=[dict(requirement='current requirement',dimension='claim_support'if row['level']=='body'else'task_acceptance',
                status=status,reason='controlled independent assessment',evidence=[row['excerpts'][0]['id']])])
            return dict(message=dict(content=json.dumps(value)),usage=dict(prompt_tokens=5,completion_tokens=3))
        value=next(self.drafts)
        if isinstance(value,str):value=dict(content=value)
        return dict(message=value,usage=dict(prompt_tokens=10,completion_tokens=4))


def delivery(text):
    return dict(tool_calls=[dict(id=uuid.uuid4().hex,function=dict(name='submit_deliverable',arguments=json.dumps(dict(report=text,complete=True,missing=[]))))])


class FeedbackWorkerTests(unittest.TestCase):
    def test_proposal_handoff_has_domain_contract_without_claiming_ui_observation(self):
        from desk_companion.planning.calendar_proposals import build
        from desk_companion.collaboration.delivery_feedback import assess
        proposal=build(dict(summary='合成提案',start='2040-01-02T09:00:00+08:00',end='2040-01-02T10:00:00+08:00'),task_id=self.request['task_id'])
        receipts=[dict(tool='calendar_propose',call_id='proposal-one',read_only=True,result=proposal)]
        _,checks,_=assess(self.request,'提案已生成，请打开草稿确认。',[],None,receipts)
        verified=next(c for c in checks if c['id']=='calendar_proposal_handoff')
        self.assertEqual(verified['status'],'pass')
        self.assertFalse(verified['delivery_contract']['ui_observed'])
        captured=[]
        from desk_companion.collaboration.feedback_review import review
        review('生成可打开的提案','提案已生成',[],receipts,lambda m:(captured.append(m)or dict(message=dict(content='{}'))),verified_checks=checks)
        self.assertEqual(json.loads(captured[0][1]['content'])['delivery_contract']['kind'],'calendar_proposal')
        proposal['proposal']['summary']='篡改提案'
        _,bad,_=assess(self.request,'已生成',[],None,receipts)
        self.assertEqual(next(c for c in bad if c['id']=='calendar_proposal_handoff')['status'],'fail')

    def test_local_file_body_satisfies_repository_check_through_handoff(self):
        from desk_companion.projects import project_workspace
        from desk_companion.collaboration.delivery_feedback import assess

        root = Path(self.temp.name) / 'test'
        root.mkdir()
        (root / 'test.py').write_text('print(42)', encoding='utf8')
        (root / 'README.md').touch()
        self.request.update(role=dict(id='coder', name='coder', role='read', tools=['工作区读取']),
                            workspace=project_workspace.save(str(root), project_id='test-project')['workspace'], required_sources=['repository'],
                            text='看看目录里有什么，正在做什么？', stage='collect', parent_run='parent')
        def call(tool, path):
            return dict(id=uuid.uuid4().hex, function=dict(name=tool, arguments=json.dumps(dict(root='main', path=path))))
        model = ScriptedModel([dict(tool_calls=[call('workspace_list', ''), call('workspace_read', 'README.md'),
                                                call('workspace_read', 'missing.py'), call('workspace_read', 'test.py')]),
                               'test.py 打印 42。'])
        self.run_model(model)
        evidence = [data for kind, data in self.events if kind == 'evidence']
        self.assertEqual([item['path'] for item in evidence], ['test.py'])
        self.assertEqual(self.events[-1][0], 'result')
        for inherited, expected in [(evidence, {'web'}), ([], {'web', 'repository'})]:
            request = dict(self.request, source_evidence=inherited, required_sources=['web', 'repository'])
            _, checks, _ = assess(request, 'test.py 打印 42。', [], None, [])
            self.assertEqual({c['id'].removeprefix('required_source_') for c in checks
                              if c['id'].startswith('required_source_') and c['status'] == 'fail'}, expected)

    def test_workspace_question_reads_without_review_but_execution_is_reviewed(self):
        from desk_companion.projects import project_workspace
        root = Path(self.temp.name) / 'test'
        root.mkdir()
        (root / 'src').mkdir()
        (root / 'test.py').write_text('print(42)', encoding='utf8')
        self.request.update(workspace=project_workspace.save(str(root), edit=True, commands=True,
                            project_id='test-project')['workspace'],
                            role=dict(id='coder', name='coder', role='code', tools=['工作区读取','文件编辑','终端','联网搜索']))
        action = dict(tool_calls=[dict(id='list', function=dict(name='workspace_list', arguments='{}'))])
        for mode, question in [('workspace_question','帮我看看test文件夹下有什么，正在做什么？'),
                               ('execution','运行测试，验证功能是否正常。')]:
            self.events.clear()
            self.request.update(task_type=mode,text=question)
            model = ScriptedModel([action, '目录有 test.py 和 src。'])
            self.run_model(model)
            self.assertEqual(sum(k == 'llm_start' and d.get('phase') == 'feedback_review'
                                 for k,d in self.events), int(mode == 'execution'))
            self.assertTrue(any(k == 'tool_end' and d['status'] == 'success' for k,d in self.events))
            if mode == 'workspace_question':
                self.assertEqual({t['function']['name'] for t in model.calls[0]['tools']}, project_workspace.READ_TOOLS)
                receipt = next(m for m in model.calls[1]['messages'] if m.get('role') == 'tool')
                directory = next(e for e in json.loads(receipt['content'])['entries'] if e['directory'])
                self.assertNotIn('size', directory)
        self.request.update(task_type='workspace_question',text='看看文件夹内容')
        with self.assertRaisesRegex(PublicFailure, '未取得成功的工作区读取回执'):
            self.run_model(ScriptedModel(['没有读取文件。', '没有读取文件。']))

    def test_oversized_read_batch_returns_every_receipt_without_resubmission(self):
        from desk_companion.projects import project_workspace

        root = Path(self.temp.name) / 'test'
        root.mkdir()
        files = [f'file{i}.py' for i in range(9)]
        for path in files:
            (root / path).write_text('print(42)', encoding='utf8')
        self.request.update(role=dict(id='coder', name='coder', role='read', tools=['工作区读取']),
                            workspace=project_workspace.save(str(root), project_id='test-project')['workspace'],
                            text='查看目录内容')
        def read(ident, path):
            return dict(id=ident, function=dict(name='workspace_read', arguments=json.dumps(dict(path=path))))
        calls = [read(str(i), path) for i, path in enumerate(files)]
        model = ScriptedModel([dict(tool_calls=calls), '已读九个文件。'])
        self.run_model(model)
        replies = [m for m in model.calls[1]['messages'] if m.get('role') == 'tool']
        self.assertEqual([m['tool_call_id'] for m in replies], [c['id'] for c in calls])
        self.assertEqual([json.loads(m['content'])['text'] for m in replies], ['print(42)'] * 9)
        self.assertEqual([d['path'] for k, d in self.events if k == 'tool_end'], files)
        self.assertEqual(self.events[-1][0], 'result')

        self.events.clear()
        self.request['role']['tools'].append('文件编辑')
        self.request['workspace'] = project_workspace.save(str(root), edit=True, project_id='test-project')['workspace']
        write = dict(id='write', function=dict(name='workspace_write', arguments=json.dumps(
            dict(path='unexpected.py', revision='new', text='unexpected'))))
        with self.assertRaisesRegex(PublicFailure, '本批全部未执行'):
            self.run_model(ScriptedModel([dict(tool_calls=[*calls[:8], write])]))
        self.assertFalse(any(kind == 'tool_start' for kind, _ in self.events))
        self.assertFalse((root / 'unexpected.py').exists())

    def test_delegated_snapshot_keeps_partial_answer_until_synthesis(self):
        from desk_companion.collaboration.execution_flow import chain_view
        parent = dict(id='root', kind='task', state='waiting', stage='deliver', answer='')
        child = dict(id='coder', parent='root', state='running', stage='collect', answer='目录内容')
        for root_state, child_state in [('waiting', 'running'), ('pending', 'succeeded'), ('cancelled', 'failed')]:
            parent['state'], child['state'] = root_state, child_state
            self.assertEqual(chain_view(parent, [parent, child])['answer'], '目录内容')
        parent.update(state='succeeded', answer='最终交付')
        self.assertEqual(chain_view(parent, [parent, child])['answer'], '最终交付')

    def test_explicit_resume_correction_only_offers_actual_control_actions(self):
        self.request.update(kind='route',require_execution=True,supplemented_at=123,
            text='补充7和11，最终只返回JSON。',budget=2)
        class ResumeModel(ScriptedModel):
            def chat(inner,messages,tools=None,on_delta=None):
                if inner.calls:
                    self.assertIn('final_output_stage',messages[0]['content'])
                    self.assertIn('task',messages[0]['content'])
                    correction=messages[-2]['content'] if messages[-1]['content'].startswith('整个目标') else messages[-1]['content']
                    self.assertNotIn('可直接按用户格式回答',correction)
                    self.assertIn('本轮只能',correction)
                return super().chat(messages,tools,on_delta)
        control=dict(tool_calls=[dict(id='resume-execution',function=dict(name='start_background_task',
            arguments=json.dumps(dict(instructions='计算7和11并返回JSON',strategy='direct',steps=[dict(action='计算',outcome='JSON',effect='read')]))))])
        self.run_model(ResumeModel(['{"total":18,"checked":true}',control]))
        result=json.loads(self.events[-1][1]);self.assertEqual(result['mode'],'task')

    def test_citation_submission_is_reviewed_before_display_compilation(self):
        source=dict(kind='page',level='body',url='https://example.org/source',text='Publication year 2020.',truncated=False)
        ident=source_catalog([source])[0]['id']
        candidate=json.dumps(dict(year=2020,citation=f'[{ident}]'))
        self.request.update(text='只返回JSON，citation提交时使用实际证据编号。',source_evidence=[source])
        class StageReview(ScriptedModel):
            def chat(inner,messages,tools=None,on_delta=None):
                result=super().chat(messages,tools,on_delta)
                if messages[0]['content'].startswith('反馈审阅协议'):
                    payload=json.loads(messages[1]['content'])
                    draft=''.join(e['text']for r in payload['materials']if r['id']=='draft'for e in r['excerpts'])
                    value=json.loads(result['message']['content'])
                    value['requirements'][0]['status']='supported'if f'[{ident}]'in draft else'contradicted'
                    result['message']['content']=json.dumps(value)
                return result
        model=StageReview([candidate,candidate])
        self.run_model(model)
        payload=json.loads(model.calls[1]['messages'][1]['content'])
        self.assertEqual(payload['candidate_stage'],'submitted_candidate')
        self.assertEqual(payload['rendered_delivery']['stage'],'after_citation_resolution')
        self.assertIn(source['url'],payload['rendered_delivery']['text'])
        self.assertIn(source['url'],json.loads(self.events[-1][1])['citation'])

    def test_clarification_form_identity_and_heading_are_generated_by_product(self):
        self.request.update(kind='route',text='两个数值缺失，请先询问。')
        payload=dict(questions=[dict(question='第一个数？',options=['1','2']),dict(question='第二个数？',options=['3','4'])])
        model=ScriptedModel([dict(tool_calls=[dict(id='ask',function=dict(name='request_clarification',arguments=json.dumps(payload)))])])
        self.run_model(model)
        schema = next(t['function']['parameters'] for t in model.calls[0]['tools']
                      if t['function']['name'] == 'request_clarification')
        self.assertEqual(schema['type'], 'object')
        self.assertTrue({'oneOf', 'anyOf', 'allOf', 'enum', 'const', 'not'}.isdisjoint(schema))
        value=json.loads(next(data for kind,data in self.events if kind=='result'))
        self.assertEqual(value['mode'],'clarify');self.assertEqual(value['text'],'第一个数？\n第二个数？')
        self.assertEqual([q['id']for q in value['questions']],['q1','q2'])
        self.assertEqual(value['questions'][1]['options'][0],dict(id='q2_o1',label='3',value='3'))

    def test_resumed_json_and_business_mode_are_data_without_output_contract(self):
        for answer in ['{"total":18,"checked":true}', '[7,11]', '{"mode":"active","count":2}']:
            with self.subTest(answer=answer):
                self.events=[]
                self.request.update(kind='route',text='补齐后返回结果。')
                self.run_model(ScriptedModel([answer]))
                result=json.loads(next(data for kind,data in self.events if kind=='result'))
                self.assertEqual(result,dict(mode='answer',text=answer))

    def test_business_json_cannot_replace_explicit_execution(self):
        self.request.update(kind='route',text='实际搜索公开资料。',require_execution=True,budget=2)
        with self.assertRaises(PublicFailure):
            self.run_model(ScriptedModel(['{"mode":"task","text":"已搜索"}']*2))
        self.assertFalse(any(kind=='result'for kind,_ in self.events))

    def test_explicit_delegation_reaches_actual_route_prompt_and_schema(self):
        self.request.update(kind='route',requested_strategy='delegate',require_execution=True,members=[dict(id='writer',name='writer',role='read',tools=[])])
        call=dict(tool_calls=[dict(id='actual-route',function=dict(name='start_background_task',arguments=json.dumps(dict(instructions='核对资料',strategy='direct',steps=[dict(action='核对资料',outcome='差异',effect='read')]))))])
        model=ScriptedModel([call]);self.run_model(model)
        tool=next(t for t in model.calls[0]['tools']if t['function']['name']=='start_background_task')
        self.assertEqual(tool['function']['parameters']['properties']['strategy']['enum'],['delegate'])
        self.assertIn('用户已明确选择协作',model.calls[0]['messages'][0]['content'])
        # Keep the raw model recommendation; the authoritative parent applies user intent.
        result=json.loads(next(data for kind,data in self.events if kind=='result'))
        self.assertEqual(result['strategy'],'direct')

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        for context in [patch.dict(os.environ,{'DESK_COMPANION_DATA_DIR':self.temp.name}),
                        patch('desk_companion.models.model_catalog.require_item',return_value=dict(id='fixture',api_key='test-only',base_url='https://example.invalid/v1',model='fake')),
                        patch('desk_companion.collaboration.collaboration_worker.updates',return_value=[]),
                        patch('desk_companion.collaboration.collaboration_worker.selected_materials',return_value={})]:
            context.start();self.addCleanup(context.stop)
        self.request=dict(kind='task',role=dict(id='writer',name='writer',role='write',tools=[]),text='只输出JSON。',
            collab_run=uuid.uuid4().hex,collab_path=str(Path(self.temp.name)/'workspace.sqlite3'),conversation='test',
            model_id='fixture',limits=dict(call_timeout=10,task_timeout=30),budget=6,context=[])
        self.request['task_id']=uuid.uuid4().hex
        self.events=[]

    def run_model(self,model):execute(self.request,lambda k,d:self.events.append((k,d)),llm=model)

    @unittest.skipUnless(os.name=='nt','first readonly runtime pilot requires Windows parent-exit protection')
    def test_atlas_collect_child_keeps_actual_body_and_independent_acceptance(self):
        from desk_companion.collaboration.readonly_research import ReadonlyLoop
        instances=[]
        class ObservedLoop(ReadonlyLoop):
            def __init__(loop,**kwargs):super().__init__(**kwargs);instances.append(loop)
        source=dict(kind='page',level='body',url='https://example.org/read',text='Actual controlled original sentence.',truncated=False)
        ident=source_catalog([source])[0]['id']
        self.request.update(parent_run='actual-parent',stage='collect',dependencies=[],execution_runtime='atlas_readonly',
            text='只输出JSON，含reading和citation，依据给定链接正文。',role=dict(id='research',name='research',role='read',tools=['网页读取']),
            context=[dict(sender='user',text=source['url'])])
        invocation=dict(tool_calls=[dict(id='actual-read',function=dict(name='web_fetch',arguments=json.dumps(dict(url=source['url']))))])
        model=ScriptedModel([invocation,json.dumps(dict(reading=True,citation=f'[{ident}]'))]);reads=[]
        with patch('desk_companion.collaboration.readonly_research.ReadonlyLoop',ObservedLoop):
            execute(self.request,lambda k,d:self.events.append((k,d)),llm=model,fetch=lambda url:(reads.append(url)or source))
        self.assertEqual(reads,[source['url']])
        self.assertTrue(any(kind=='execution_runtime'and data['name']=='atlas_readonly'for kind,data in self.events))
        self.assertTrue(next(data for kind,data in self.events if kind=='feedback_check')['ok'])
        result=json.loads(self.events[-1][1]);self.assertTrue(result['reading']);self.assertIn(source['url'],result['citation'])
        import dataclasses
        journal=[dataclasses.asdict(event)for event in instances[0].journal.get_events(instances[0].agent.last_result.run_id)]
        self.assertNotIn('test-only',json.dumps(journal,ensure_ascii=False))
        self.assertTrue(all(isinstance(event['payload'].get('model'),str)for event in journal if event['event_type']=='llm_before_call'))

    def test_atlas_failed_source_is_not_handed_off_as_model_success(self):
        self.request.update(parent_run='actual-parent',stage='collect',dependencies=[],execution_runtime='atlas_readonly',
            role=dict(id='research',name='research',role='read',tools=['网页读取']),context=[dict(sender='user',text='https://example.org/read')])
        call=dict(tool_calls=[dict(id='failed-read',function=dict(name='web_fetch',arguments=json.dumps(dict(url='https://example.org/read'))))])
        attempts=[];model=ScriptedModel([call,'{"read":true}'])
        def fetch(url):attempts.append(url);raise TimeoutError('controlled source timeout')
        with self.assertRaises(PublicFailure):execute(self.request,lambda k,d:self.events.append((k,d)),llm=model,fetch=fetch)
        self.assertEqual(attempts,['https://example.org/read'])
        self.assertFalse(any(kind=='result'for kind,_ in self.events))

    def test_runtime_hint_cannot_move_a_project_capability_into_readonly_driver(self):
        self.request.update(parent_run='actual-parent',stage='collect',dependencies=[],execution_runtime='atlas_readonly',
            role=dict(id='research',name='research',role='read',tools=['项目环境']))
        self.run_model(ScriptedModel(['{"provided":true}']))
        runtimes=[data for kind,data in self.events if kind=='execution_runtime']
        self.assertEqual(runtimes[0]['name'],'legacy');self.assertEqual(runtimes[0]['requested'],'atlas_readonly')

    def test_project_log_json_escapes_do_not_discard_receipt_or_block_review(self):
        self.request['role']['tools']=['项目环境']
        arguments=dict(environment='a'*32,operation='b'*32)
        invocation=dict(tool_calls=[dict(id='log-call',function=dict(name='project_log',arguments=json.dumps(arguments)))])
        model=ScriptedModel([invocation,'{"log_read":true}'])
        result=dict(ok=True,**arguments,text='Running on http://172.17.0.57:5000\n\x1b[33mPress CTRL+C\x1b[0m\n')
        with patch('desk_companion.projects.project_tools.call',return_value=result):self.run_model(model)
        ends=[data for kind,data in self.events if kind=='tool_end'and data['tool']=='project_log']
        self.assertEqual(ends[0]['status'],'success')
        self.assertTrue(any(kind=='feedback_check'for kind,_ in self.events))
        for call in model.calls:
            for row in call['messages']:
                if row.get('role')=='tool'and row.get('tool_call_id')=='log-call':
                    self.assertEqual(json.loads(row['content'])['text'],result['text'])
        self.assertFalse(any(kind=='evidence'and any(s.get('level')=='body'for s in data.get('sources',[]))for kind,data in self.events))

    def test_trusted_root_can_finish_after_old_twelve_call_phase_boundary(self):
        import hashlib
        from desk_companion.tasks.task_budgets import Ledger, installed, current
        ledger=Ledger();root=ledger.create('root-stage','coding');ledger.bind(root,self.request['task_id'],root_member=True)
        self.request.update(budget=12,role=dict(id='writer',name='writer',role='write',tools=['项目环境']))
        calls=[dict(tool_calls=[dict(id='read-'+str(i),function=dict(name='project_read',arguments=json.dumps(
            dict(environment='a'*32,path='source-'+str(i)))) )])for i in range(13)]
        task=self.request['task_id']
        class BudgetedModel(ScriptedModel):
            def chat(model,*args,**kwargs):
                call,_=ledger.reserve_call(task,10,phase=current().phase())
                result=super().chat(*args,**kwargs);ledger.settle(task,call,result['usage']);return result
        model=BudgetedModel([*calls,'{"read":13}'])
        def read(method,payload):
            text=payload['path'];return dict(ok=True,text=text,sha256=hashlib.sha256(text.encode()).hexdigest())
        with installed(task),patch('desk_companion.projects.project_tools.call',side_effect=read):self.run_model(model)
        self.assertEqual(len(model.calls),15)  # 13 actual reads, final candidate, independent review.
        self.assertEqual(ledger.view(root)['consumed']['model_calls'],15)
        self.assertEqual(ledger.view(root)['limits']['model_calls'],24)
        self.assertEqual(ledger.view(root)['extensions'],[])
        report=next(data for kind,data in self.events if kind=='feedback_check')
        self.assertFalse(any(row['id']=='review_unavailable'for row in report['checks']))

    def test_structured_citation_and_real_review_have_separate_checks(self):
        source=dict(kind='page',level='body',url='https://example.org/source',text='Launch was in 2020.')
        self.request.update(text='只输出JSON对象，含year和citation来源。',source_evidence=[source])
        ident=source_catalog([source])[0]['id']
        self.run_model(ScriptedModel([json.dumps(dict(year=2020,citation=f'[{ident}]'))]))
        result=json.loads(self.events[-1][1]);self.assertEqual(set(result),{'year','citation'})
        report=next(d for k,d in self.events if k=='feedback_check')
        self.assertEqual(report['completion'],'assessed')
        self.assertTrue(any(c['dimension']=='source_url'and c['basis']=='deterministic'for c in report['checks']))
        self.assertTrue(any(c['dimension']=='claim_support'and c['basis']=='model_assessment'for c in report['checks']))

    def test_parent_format_repair_keeps_only_json_and_counts_review_call(self):
        from desk_companion.evaluation.agent_evals import CASES
        self.request.update(stage='deliver',objective=next(c['prompt']for c in CASES if c['id']=='delegate_deliver'))
        model=ScriptedModel([delivery('# 报告\n{"total":18,"checked":true}'),delivery('{"total":18,"checked":true}')])
        self.run_model(model)
        self.assertEqual(json.loads(self.events[-1][1]),dict(total=18,checked=True))
        self.assertEqual(len(model.calls),3)
        self.assertEqual(sum(k=='llm_start'for k,d in self.events),3)
        self.assertEqual([tool['function']['name']for tool in model.calls[-1]['tools']],['submit_feedback_review'])

    def test_unsupported_claim_can_only_receive_one_correction(self):
        source=dict(kind='page',level='body',url='https://example.org/source',text='Launch was in 2020.')
        self.request.update(text='报告启动年份并引用来源。',source_evidence=[source])
        model=ScriptedModel(['2019年启动 [来源](https://example.org/source)','2020年启动 [来源](https://example.org/source)'],['contradicted','supported'])
        self.run_model(model)
        self.assertEqual(len(model.calls),4)
        reports=[d for k,d in self.events if k=='feedback_check']
        self.assertEqual([r['ok']for r in reports],[False,True])

    def test_review_uses_existing_call_budget_and_preserves_partial_answer(self):
        self.request.update(stage='deliver',budget=1)
        model=ScriptedModel([delivery('{"done":true}')])
        with self.assertRaises(PublicFailure):self.run_model(model)
        self.assertEqual(len(model.calls),1)
        self.assertTrue(any(k=='token'and v=='{"done":true}'for k,v in self.events))
        self.assertEqual(next(d for k,d in self.events if k=='feedback_check')['completion'],'unverified')

    def test_user_json_data_is_not_mistaken_for_route_control(self):
        self.request.update(kind='route',text='只输出JSON：total=18。')
        self.run_model(ScriptedModel(['{"total":18}']))
        result=json.loads(self.events[-1][1])
        self.assertEqual(result,dict(mode='answer',text='{"total":18}'))

    def test_unknown_create_is_not_replayed_during_correction(self):
        self.request.update(text='准备公开项目。只输出JSON。',role=dict(id='writer',name='writer',role='write',tools=['项目环境']),budget=8)
        def prepare(ident):return dict(tool_calls=[dict(id=ident,function=dict(name='project_prepare',arguments=json.dumps(dict(repository='https://github.com/example/project'))))])
        model=ScriptedModel([prepare('first'),'{"ready":true}',prepare('repeat'),'{"ready":false}'],['contradicted','unverified'])
        unknown=dict(ok=False,operation=dict(id='original-operation',state='unknown'),environment=dict(id='original-environment',state='unknown'),log_id='original-log')
        with patch('desk_companion.projects.project_tools.call',return_value=unknown)as rpc:
            with self.assertRaises(PublicFailure):self.run_model(model)
        self.assertEqual(rpc.call_count,1)
        self.assertTrue(any(k=='repair_tool_blocked'and d['tool']=='project_prepare'for k,d in self.events))
        reports=[d for k,d in self.events if k=='feedback_check']
        self.assertTrue(all(r['unknown_operations'][0]['operation_id']=='original-operation'for r in reports))

    def test_execution_capable_task_cannot_skip_review_by_omitting_tools(self):
        self.request.update(role=dict(id='writer',name='writer',role='write',tools=['项目环境']))
        model=ScriptedModel(['{"ready":true}','{"ready":true}'],['unverified','unverified'])
        with self.assertRaises(PublicFailure):self.run_model(model)
        self.assertEqual(len(model.calls),4)

    def test_update_during_review_invalidates_old_approval_and_format(self):
        self.request.update(stage='deliver',text='计算7和11的总和。',objective='计算7和11的总和。')
        received=[]
        class UpdatingModel(ScriptedModel):
            def chat(inner,messages,tools=None,on_delta=None):
                value=super().chat(messages,tools,on_delta)
                if messages[0]['content'].startswith('反馈审阅协议')and not received:received.append('最终只返回JSON。')
                return value
        model=UpdatingModel([delivery('总和是18。'),delivery('{"total":18}')])
        with patch('desk_companion.collaboration.collaboration_worker.updates',side_effect=lambda *_:received.copy()):self.run_model(model)
        self.assertTrue(any(k=='feedback_invalidated'for k,d in self.events))
        self.assertEqual(json.loads(self.events[-1][1]),dict(total=18));self.assertEqual(len(model.calls),4)

    def test_failed_repair_generation_retains_prior_candidate_without_success(self):
        self.request.update(stage='deliver')
        class BrokenRepair(ScriptedModel):
            def chat(inner,messages,tools=None,on_delta=None):
                if len(inner.calls)==2:raise RuntimeError('controlled provider failure')
                return super().chat(messages,tools,on_delta)
        model=BrokenRepair([delivery('{"total":19}')],['contradicted'])
        with self.assertRaisesRegex(RuntimeError,'controlled'):self.run_model(model)
        self.assertFalse(any(k=='result'for k,d in self.events))
        self.assertEqual(self.events[-1],('token','{"total":19}'))

    def test_invalid_review_quote_repairs_reviewer_without_regenerating_candidate(self):
        source=dict(kind='page',level='body',url='https://example.org/source',text='Launch was in 2020.')
        self.request.update(text='只输出JSON对象，含year和citation来源。',source_evidence=[source],budget=3)
        candidate=json.dumps(dict(year=2020,citation='[source](https://example.org/source)'))
        class RepairingReview(ScriptedModel):
            reviewed=0
            def chat(inner,messages,tools=None,on_delta=None):
                value=super().chat(messages,tools,on_delta)
                if messages[0]['content'].startswith('反馈审阅协议'):
                    inner.reviewed+=1
                    if inner.reviewed==1:
                        raw=json.loads(value['message']['content']);raw['requirements'][0]['evidence'][0]='not_an_actual_excerpt'
                        value['message']['content']=json.dumps(raw)
                return value
        model=RepairingReview([candidate])
        self.run_model(model)
        self.assertEqual(len(model.calls),3);self.assertEqual(model.reviewed,2)
        self.assertEqual(json.loads(self.events[-1][1]),json.loads(candidate))
        self.assertTrue(any(k=='feedback_review_repair'for k,d in self.events))
        self.assertTrue(json.loads(model.calls[-1]['messages'][1]['content'])['previous_protocol_issues'])

    def test_protocol_repair_after_candidate_repair_uses_workspace_snapshot(self):
        workspace = dict(primary=self.temp.name, commands=False, edit=False, revision='private-field')
        self.request.update(text='说明工作目录，以及是否能运行命令。', workspace=workspace,
                            role=dict(id='coder', name='coder', role='read', tools=['工作区读取']), budget=5)
        class Reviewer(ScriptedModel):
            reviews = 0
            def chat(inner, messages, tools=None, on_delta=None):
                response = super().chat(messages, tools, on_delta)
                if messages[0]['content'].startswith('反馈审阅协议'):
                    inner.reviews += 1
                    payload = json.loads(messages[1]['content'])
                    source = next(row for row in payload['materials'] if row['id'] == 'workspace')
                    excerpt = source['excerpts'][0]
                    self.assertEqual(json.loads(excerpt['text']), dict(primary=self.temp.name, commands=False, edit=False))
                    result = json.loads(response['message']['content'])
                    item = result['requirements'][0]
                    item['evidence'] = [excerpt['id']]
                    if inner.reviews == 2:
                        result['requirements'] = [item] * 7
                    elif inner.reviews == 3:
                        self.assertEqual(payload['previous_protocol_issues'][0]['protocol_errors'][0]['constraint'], 6)
                    response['message']['content'] = json.dumps(result)
                return response
        model = Reviewer(['原稿', '已修订'], ['unverified', 'supported', 'supported'])
        self.run_model(model)
        self.assertEqual(self.events[-1], ('result', '已修订'))
        self.assertEqual([d['answer'] for k,d in self.events if k == 'feedback_draft'], ['原稿', '已修订'])
        self.assertEqual(model.reviews, 3)
        self.assertFalse(any(k == 'tool_start' for k,d in self.events))

    def test_repeated_review_format_error_preserves_draft_and_explains_limit(self):
        self.request.update(text='给出答复', require_execution=True, budget=6)
        class InvalidReviewer(ScriptedModel):
            def chat(inner, messages, tools=None, on_delta=None):
                response = super().chat(messages, tools, on_delta)
                if messages[0]['content'].startswith('反馈审阅协议'):
                    value = json.loads(response['message']['content'])
                    value['requirements'] *= 7
                    response['message']['content'] = json.dumps(value)
                return response
        model = InvalidReviewer(['原稿'])
        with self.assertRaisesRegex(PublicFailure, '7项核验结论，协议最多接受6项'):
            self.run_model(model)
        self.assertEqual(len(model.calls), 3)
        self.assertEqual(self.events[-1], ('token', '原稿'))

    def test_review_timeout_retains_candidate_without_reexecuting_tools_or_rewriting(self):
        from desk_companion.collaboration.review_limits import ReviewTimeout
        self.request.update(text='核对给定来源。',source_evidence=[dict(kind='page',level='body',url='https://example.org/a',text='Actual fact.')])
        class ExpiredReview(ScriptedModel):
            def chat(inner,messages,tools=None,on_delta=None):
                if messages[0]['content'].startswith('反馈审阅协议'):
                    inner.calls.append(dict(messages=messages,tools=tools))
                    raise ReviewTimeout('controlled expiry')
                return super().chat(messages,tools,on_delta)
        model=ExpiredReview(['Actual fact. [source](https://example.org/a)'])
        with self.assertRaises(PublicFailure):self.run_model(model)
        self.assertEqual(len(model.calls),2)
        self.assertIn('Actual fact.',self.events[-1][1])
        self.assertFalse(any(kind=='result'for kind,_ in self.events))
        report=next(data for kind,data in self.events if kind=='feedback_check')
        self.assertTrue(any(c['id']=='review_unavailable'and c['status']=='unknown'for c in report['checks']))

    def test_correct_raw_child_candidate_is_reviewed_for_current_duty(self):
        text='计算7与11的和。只输出JSON对象。'
        self.request.update(text=text,objective='必须委派写作者并整体汇总。只返回JSON。',parent_run='actual-parent',stage='deliver',budget=2)
        candidate='{"total":18,"checked":true}';model=ScriptedModel([candidate,candidate]);self.run_model(model)
        self.assertEqual(json.loads(self.events[-1][1]),dict(total=18,checked=True));self.assertEqual(len(model.calls),2)
        self.assertEqual(json.loads(model.calls[-1]['messages'][1]['content'])['materials'][0]['excerpts'][0]['text'],text)
        materials=json.loads(model.calls[-1]['messages'][1]['content'])['materials']
        self.assertEqual(next(m for m in materials if m['id']=='global_goal')['excerpts'][0]['text'],self.request['objective'])
        self.assertEqual(json.loads(next(m for m in materials if m['id']=='assignment')['excerpts'][0]['text'])['parent_run'],'actual-parent')
        self.assertIn('actual-parent',model.calls[0]['messages'][0]['content'])
        delivery_check=next(d for k,d in self.events if k=='delivery_check')
        self.assertTrue(delivery_check['ok']);self.assertEqual(delivery_check['missing'],[])
        self.assertEqual(delivery_check['candidate_origin'],'final_answer')

    def test_raw_candidate_still_needs_review_and_explicit_missing_still_blocks(self):
        self.request.update(stage='deliver',budget=1)
        with self.assertRaises(PublicFailure):self.run_model(ScriptedModel(['{"total":18}']))
        self.assertFalse(any(k=='result'for k,d in self.events))
        self.events=[];self.request['budget']=2
        incomplete=dict(tool_calls=[dict(id='incomplete',function=dict(name='submit_deliverable',arguments=json.dumps(dict(report='{"total":18}',complete=False,missing=['actual core requirement missing']))))])
        with self.assertRaises(PublicFailure):self.run_model(ScriptedModel([incomplete,incomplete]))
        self.assertTrue(any(k=='feedback_check'and any(c['id']=='delivery_declaration'and c['status']=='fail'for c in d['checks'])for k,d in self.events))
        self.events=[]
        with self.assertRaises(PublicFailure):self.run_model(ScriptedModel([incomplete,'{"total":18}']))
        last=next(d for k,d in reversed(self.events)if k=='delivery_check')
        self.assertFalse(last['ok']);self.assertEqual(last['declaration_origin'],'retained')
        self.assertEqual(last['missing'],['actual core requirement missing'])

    def test_unknown_create_blocks_another_create_before_any_final_draft(self):
        self.request.update(text='准备公开项目。只输出JSON。',role=dict(id='writer',name='writer',role='write',tools=['项目环境']),budget=8)
        def prepare(ident):return dict(tool_calls=[dict(id=ident,function=dict(name='project_prepare',arguments=json.dumps(dict(repository='https://github.com/example/project'))))])
        model=ScriptedModel([prepare('first'),prepare('repeat'),'{"ready":false}','{"ready":false}'])
        unknown=dict(ok=False,operation=dict(id='original-operation',state='unknown'),environment=dict(id='original-environment',state='unknown'))
        with patch('desk_companion.projects.project_tools.call',return_value=unknown)as rpc:
            with self.assertRaises(PublicFailure):self.run_model(model)
        self.assertEqual(rpc.call_count,1)
        self.assertTrue(any(k=='unknown_operation_blocked'for k,d in self.events))


if __name__=='__main__':unittest.main()
