"""Real Pi Agent Core loop and local provider, with existing product policies."""
from types import SimpleNamespace
from unittest.mock import patch

from atlas import Toolkit
from atlas.llm import IncompleteResponseError
from desk_companion.pi_runtime.chat_agent import PiChatAgent
from desk_companion.tasks.task_budgets import installed, BudgetExceeded
from desk_companion.observability.usage_store import UsageStore
from desk_companion.observability import agent_debug as debug
from tests.test_pi_inference import PiInferenceFixture


class PiChatTests(PiInferenceFixture):
    def test_luna_parameters_follow_final_tools_and_endpoint(self):
        from desk_companion.pi_runtime.model_mapping import apply_chat_parameters
        base = dict(model='gpt-6-luna', reasoning_effort='low', temperature=.5, top_p=.9,
                    thinking={'type':'enabled'}, max_completion_tokens=128)
        text = base.copy()
        apply_chat_parameters(text, 'https://api.openai.com/v1')
        self.assertEqual(text, dict(model='gpt-6-luna', reasoning_effort='low', max_completion_tokens=128))
        tool = dict(base, tools=[{'type':'function'}])
        apply_chat_parameters(tool, 'https://api.openai.com/v1/')
        self.assertNotIn('thinking', tool)
        self.assertEqual((tool['reasoning_effort'], tool['temperature']), ('none', .5))
        for model, url in [('deepseek-flash', 'https://api.openai.com/v1'),
                           ('gpt-6-luna', 'https://example.invalid/v1')]:
            other = dict(base, model=model)
            apply_chat_parameters(other, url)
            self.assertEqual(other, dict(base, model=model))

    def test_demand_loading_updates_actual_sdk_payload_before_execution(self):
        agent=self.agent('discover-tool');agent.tool_loading='demand'
        self.assertEqual(agent.run('Discover and use the calculator.'),'40')
        names=lambda r:[t['function']['name']for t in r.get('tools',[])]
        self.assertEqual(names(self.requests[0]),['tebb_tools_search'])
        self.assertEqual(names(self.requests[1]),['tebb_tools_search','tebb_tools_call'])
        self.assertEqual(self.requests[2]['tools'],self.requests[1]['tools'])
        messages=self.requests[1]['messages']
        self.assertEqual(self.requests[2]['messages'][:len(messages)],messages)
        self.assertEqual(self.writes,[dict(a=17,b=23)])
        self.assertEqual(len(self.requests),3)
        # A fresh run must discover again before executing, even with conversation history.
        self.assertEqual(agent.run('Use the established result.'),'40')
        self.assertEqual(names(self.requests[3]),['tebb_tools_search'])

    def agent(self, scenario='normal', *, max_steps=8):
        llm=self.llm(scenario)
        llm.client=SimpleNamespace(base_url=llm.item['base_url'],api_key='isolated-test-only',timeout=SimpleNamespace(read=10))
        tools=Toolkit();self.writes=[]
        def add(args):self.writes.append(args);return args['a']+args['b']
        tools.register(name='probe_add',description='Read-only fixture calculator',parameters=dict(type='object',
            properties=dict(a=dict(type='integer'),b=dict(type='integer')),required=['a','b']),func=add,isReadOnly=True)
        return PiChatAgent(llm=llm,tools=tools,system_prompt='Use the registered calculator. Return exactly 40.',max_steps=max_steps,tool_loading='eager')

    def test_overview_reuses_only_successful_listings_of_the_same_root(self):
        agent = self.agent()
        calls = []

        def list_root(args):
            calls.append(args)
            return dict(ok=len(calls) > 1, entries=[])

        agent.tools.register(name='workspace_list', description='List the workspace',
                             parameters=dict(type='object'), func=list_root, isReadOnly=True)
        agent.run('Return 40.')
        agent.loading.source_overview = True

        def execute(tool, args):
            return agent._admitted_tool(tool, args, str(len(agent.completed)), None, via_search=True)

        self.assertFalse(execute('workspace_list', {})['ok'])
        first = execute('workspace_list', {})
        self.assertTrue(first['ok'])
        self.assertIn('reused_call', execute('workspace_list', {'root': 'main', 'path': '.'}))
        self.assertNotIn('reused_call', execute('workspace_list', {'root': 'ref-0'}))
        self.assertNotIn('reused_call', execute('workspace_list', {'path': 'packages'}))
        self.assertEqual(len(calls), 4)

    def test_explicit_overview_range_keeps_loop_body_and_exit(self):
        agent = self.agent()
        lines = [f'line {n}\n' for n in range(1, 91)]
        receipt = dict(ok=True, path='loop.ts', start_line=1, end_line=90, text=''.join(lines),
                       closing_excerpt=dict(start_line=80, end_line=90, text=''.join(lines[79:])))
        agent.tools.register(name='workspace_read_symbol', description='Read source',
                             parameters=dict(type='object'), func=lambda _: receipt, isReadOnly=True)
        agent.run('Return 40.')
        agent.loading.source_overview = agent.loading.prefer_workspace = True
        args = dict(path='loop.ts', start_line=1, end_line=90)
        result = agent._admitted_tool('workspace_read_symbol', args, 'window', None, via_search=True)
        self.assertEqual(result['citation'], 'loop.ts:L1-L90')
        self.assertIn('90|line 90', result['numbered_text'])
        self.assertNotIn('closing_excerpt', result)
        self.assertIn('closing_excerpt', receipt)
        self.assertTrue(agent.source_evidence)
        agent.run('Return 40.')
        self.assertFalse(agent.source_evidence)

    def test_last_source_review_turn_reserves_the_answer_for_read_only_catalog(self):
        agent = self.agent(max_steps=1)
        tools = Toolkit()
        tools.register(name='workspace_list', description='List files',
                       parameters=dict(type='object'), func=lambda _: {}, isReadOnly=True)
        agent.tools = tools
        original = agent._model

        def after_evidence(data):
            if data['event'] != 'model_end':
                agent.source_evidence = True
            return original(data)

        with patch.object(agent, '_model', after_evidence):
            self.assertEqual(agent.run('解读项目架构'), '40')
        self.assertNotIn('tools', self.requests[-1])
        self.assertIn('交付回合', self.requests[-1]['messages'][-1]['content'])
        tools.register(name='submit_deliverable', description='Submit the result',
                       parameters=dict(type='object'), func=lambda _: {}, retry_max=0)
        with patch.object(agent, '_model', after_evidence):
            self.assertEqual(agent.run('解读项目架构'), '40')
        self.assertIn('submit_deliverable', [t['function']['name'] for t in self.requests[-1]['tools']])


    def test_official_loop_receipt_usage_and_actual_second_request(self):
        agent=self.agent('tool')
        with installed('ai-node'):
            self.assertEqual(agent.run('Compute 17 + 23.','chat-run'),'40')
        self.assertEqual(self.writes,[dict(a=17,b=23)])
        self.assertEqual(len(self.requests),2)
        self.assertEqual(self.requests[-1]['messages'][-1]['role'],'tool')
        self.assertEqual(self.requests[-1]['messages'][-1]['content'],'40')
        self.assertEqual(agent.usage_summary('chat-run'),dict(input_tokens=26,output_tokens=14))
        self.assertEqual(len([r for r in UsageStore().rows()if r['kind']=='model']),2)
        self.assertEqual(len(debug.listing()['items']),2)

    def test_history_sampling_and_multiple_turns(self):
        agent=self.agent()
        agent.memory.add_user('Earlier question')
        agent.memory.add_assistant(dict(role='assistant',content='Earlier answer'))
        for effort in ('low','high','max'):
            agent.llm.sampling=dict(reasoning_effort=effort,temperature=.3,top_p=.8)
            self.assertEqual(agent.run('Return 40.'),'40')
        self.assertEqual(self.requests[0]['messages'][1]['content'],'Earlier question')
        self.assertEqual(self.requests[0]['messages'][2]['content'],'Earlier answer')
        self.assertEqual([r['reasoning_effort']for r in self.requests],['low','high','max'])
        self.assertTrue(all(r['temperature']==.3 and r['top_p']==.8 for r in self.requests))
        self.assertTrue(all('max_tokens'not in r and'max_completion_tokens'not in r for r in self.requests))

    def test_length_prevents_tool_execution_and_settles_partial(self):
        agent=self.agent('length-tool')
        with installed('ai-node'):
            with self.assertRaises(IncompleteResponseError):agent.run('Return 40.')
        self.assertEqual(self.writes,[])
        self.assertEqual(self.ledger.view(self.root)['consumed']['output_tokens'],7)
        self.assertEqual(debug.listing()['items'][0]['state'],'failed')

    def test_limits_stop_before_next_request_without_repeating_tool(self):
        agent=self.agent('tool',max_steps=1)
        with self.assertRaisesRegex(RuntimeError,'步骤或时间'):agent.run('Compute 17 + 23.')
        self.assertEqual(len(self.requests),1);self.assertEqual(len(self.writes),1)

    def test_budget_denial_sends_nothing(self):
        agent=self.agent()
        self.ledger.finish(self.root)
        with installed('ai-node'),self.assertRaises(BudgetExceeded):agent.run('Return 40.')
        self.assertEqual(self.requests,[])

    def test_verified_output_binding_reaches_the_official_agent_request(self):
        agent=self.agent()
        with installed('ai-node'),patch('desk_companion.models.model_generation.binding',return_value=dict(parameter='max_tokens')):
            self.assertEqual(agent.run('Return 40.'),'40')
        self.assertEqual(self.requests[0]['max_tokens'],4096)
        self.assertNotIn('max_completion_tokens',self.requests[0])
        self.assertEqual(self.ledger.view(self.root)['output_mode'],'requested_hard')

    def test_finish_phase_keeps_the_system_note_and_removes_tool_options(self):
        agent=self.agent()
        with self.ledger.change(self.root)as root:root['no_progress']=3
        with installed('root'):self.assertEqual(agent.run('Finish from known material.'),'40')
        body=self.requests[0]
        self.assertNotIn('tools',body);self.assertNotIn('tool_choice',body)
        self.assertIn('预算进入收尾',body['messages'][-1]['content'])

    def test_local_library_disable_blocks_previously_registered_tool(self):
        from desk_companion.chat.tool_library import update
        agent=self.agent('tool')
        update('probe_add', {'disabled':True})
        with installed('root'),self.assertRaisesRegex(ValueError,'停用'):
            agent.run('Compute a sum.')
        self.assertEqual(self.writes,[])

    def test_finish_phase_rejects_tool_not_offered_in_actual_request(self):
        agent=self.agent('tool')
        with self.ledger.change(self.root)as root:root['no_progress']=3
        with installed('root'),self.assertRaisesRegex(ValueError,'授权清单'):agent.run('Finish only.')
        self.assertEqual(self.writes,[])
        self.assertNotIn('tools',self.requests[0])

    def test_missing_usage_remains_unknown(self):
        agent=self.agent('missing-usage')
        with installed('ai-node'):self.assertEqual(agent.run('Return 40.','unknown-run'),'40')
        self.assertEqual(agent.usage_summary('unknown-run'),dict(input_tokens=None,output_tokens=None))
        self.assertEqual(self.ledger.view(self.root)['consumed']['output_unknown_calls'],1)

    def test_glm_reasoning_survives_the_tool_round_trip(self):
        agent=self.agent('glm-5-fixture-tool');agent.llm.sampling=dict(reasoning_effort='max')
        self.assertEqual(agent.run('Compute 17 + 23.'),'40')
        body=self.requests[-1]
        assistant=next(m for m in body['messages']if m.get('tool_calls'))
        self.assertEqual(assistant['reasoning_content'],'fixture reasoning')
        self.assertEqual(body['thinking'],dict(type='enabled',clear_thinking=False))
        self.assertTrue(body['tool_stream'])

    def test_cancellation_keeps_partial_and_starts_no_tool(self):
        from atlas.llm import ChatCancelledError
        from desk_companion.desktop.stream_plugin import BubbleStreamPlugin
        agent=self.agent('cancel');pieces=[]
        def delta(text):
            pieces.append(text);self.ledger.finish(self.root)
        host=SimpleNamespace(ui=lambda f:f(),on_llm_delta=delta,on_stream_status=lambda _:None)
        agent.plugin_manager.register(BubbleStreamPlugin(host=host))
        with installed('ai-node'),self.assertRaises(ChatCancelledError):agent.run('Return 40.')
        self.assertEqual(''.join(pieces),'40');self.assertEqual(self.writes,[])
        self.assertEqual(debug.listing()['items'][0]['state'],'cancelled')
        self.assertEqual(len(self.requests),1)

    def test_sdk_rejects_invalid_arguments_before_python_tool(self):
        agent=self.agent('invalid-tool')
        self.assertEqual(agent.run('Compute 17 + 23.'),'40')
        self.assertEqual(self.writes,[])
        self.assertEqual(len(self.requests),2)

    def test_tool_ids_are_scoped_to_the_model_turn(self):
        agent=self.agent('reuse-id-tool')
        self.assertEqual(agent.run('Calculate twice.'),'40')
        self.assertEqual(self.writes,[dict(a=17,b=23),dict(a=18,b=22)])
        self.assertEqual(len(self.requests),3)

    def worker_task(self, scenario, channel='desktop'):
        import json
        import os
        import sys
        from pathlib import Path
        from desk_companion.models import model_catalog
        from desk_companion.tasks.manager import TaskManager
        model_catalog.upsert_entry(dict(base_url=self.llm(scenario).item['base_url'],model=scenario,api_key='isolated-only'))
        (Path(os.environ['DESK_COMPANION_DATA_DIR'])/'model-network.json').write_text(json.dumps(dict(mode='direct')))
        manager=TaskManager(command=[sys.executable,'-u','-m','tests.pi_chat_worker_fixture'])
        self.addCleanup(manager.shutdown)
        task=manager.submit('Compute fixture result.', 'pi-worker-session',channel)
        return manager,task

    def test_actual_worker_blocks_second_unknown_write_before_backend(self):
        import os
        from pathlib import Path
        manager,task=self.worker_task('repeat-write')
        row=manager.wait(task)
        self.assertEqual(row['state'],'failed')
        self.assertEqual((Path(os.environ['DESK_COMPANION_DATA_DIR'])/'write_count').read_text(),'1')
        self.assertEqual(len(self.requests),3)
        self.assertTrue(any(e['kind']=='unknown_operation_blocked'for e in row['events']))

    def test_feishu_channel_runs_the_same_real_pi_worker(self):
        import os
        from pathlib import Path
        manager,task=self.worker_task('tool','feishu')
        row=manager.wait(task)
        self.assertEqual(row['state'],'succeeded')
        self.assertEqual(row['answer'],'40')
        self.assertEqual((Path(os.environ['DESK_COMPANION_DATA_DIR'])/'read_called').read_text(),'1')
        self.assertEqual(len(self.requests),2)

    def test_task_manager_cancel_reaps_node_before_any_tool_and_rejects_late_success(self):
        import os
        import time
        from pathlib import Path
        import psutil
        manager,task=self.worker_task('cancel-tool')
        root=Path(os.environ['DESK_COMPANION_DATA_DIR'])
        deadline=time.monotonic()+20
        while time.monotonic()<deadline:
            if (root/'pi-chat.pid').exists() and manager.get(task)['answer']=='40':break
            time.sleep(.02)
        else:self.fail('Pi task did not reach cancellable partial output')
        pid=int((root/'pi-chat.pid').read_text())
        manager.cancel(task)
        row=manager.wait(task)
        deadline=time.monotonic()+5
        while time.monotonic()<deadline and psutil.pid_exists(pid):time.sleep(.02)
        self.assertFalse(psutil.pid_exists(pid))
        self.assertFalse((root/'read_called').exists())
        self.assertEqual(row['state'],'cancelled')
        self.assertEqual(row['answer'],'40')
