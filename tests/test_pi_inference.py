"""Actual pinned Pi requests through the workflow's product policies, no paid calls."""
import json
import os
import tempfile
from unittest.mock import patch

from atlas.llm import ChatOptions, ChatCallbacks, ChatCancelledError, IncompleteResponseError
from desk_companion.collaboration.execution_context import ContextAdmissionError
from desk_companion.pi_runtime.inference import PiInference
from desk_companion.observability import agent_debug as debug
from desk_companion.observability.usage_store import UsageStore
from desk_companion.tasks.task_budgets import Ledger, installed, BudgetExceeded
from tests.test_pi_bridge import PiProviderFixture


class PiInferenceFixture(PiProviderFixture):
    def setUp(self):
        super().setUp()
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        env = patch.dict(os.environ, DESK_COMPANION_DATA_DIR=temp.name, TEBB_PI_NODE=self.node)
        env.start(); self.addCleanup(env.stop)
        import httpx
        self.addCleanup(setattr, httpx.Client, 'send', httpx.Client.send)
        self.addCleanup(setattr, debug, '_default', debug._default)
        debug.install(dict(task_id='workflow-task', session='isolated', channel='workflow'))
        self.ledger = Ledger(); self.root = self.ledger.create('workflow fixture')
        self.ledger.bind(self.root, 'ai-node')
        self.ledger.bind(self.root, 'root', root_member=True)
        for target, value in [
            ('desk_companion.models.model_network.load', dict(mode='direct')),
            ('desk_companion.models.model_capacity.for_call', dict(source='unknown')),
            ('desk_companion.models.model_tokenizer.count', dict(tokens=10, source='fixture_counter')),
            ('desk_companion.models.model_generation.binding', None)]:
            mock = patch(target, return_value=value); mock.start(); self.addCleanup(mock.stop)
        self.messages = [dict(role='system', content='Permission: no writes'), dict(role='user', content='固定材料')]

    def llm(self, scenario='normal'):
        return PiInference(dict(id='fixture', model=scenario, api_key='isolated-test-only',
            base_url=f'http://127.0.0.1:{self.http.server_port}/v1'), timeout=10)


class PiInferenceTests(PiInferenceFixture):
    def test_actual_payload_usage_and_trace_with_verified_cap(self):
        deltas = []
        with installed('ai-node'), patch('desk_companion.models.model_generation.binding', return_value=dict(parameter='max_completion_tokens')):
            with self.llm() as llm:
                result = llm.chat(self.messages, options=ChatOptions(sampling=dict(temperature=.3, top_p=.8, reasoning_effort='max'),
                    extra_body=dict(max_completion_tokens=64)), callbacks=ChatCallbacks(on_delta=deltas.append))
        self.assertEqual(result['message']['content'], '40')
        self.assertEqual(''.join(deltas), '40')
        body = self.requests[0]
        self.assertEqual(body['messages'], self.messages)
        self.assertEqual(body['max_completion_tokens'], 64)
        self.assertNotIn('max_tokens', body); self.assertNotIn('tools', body)
        self.assertEqual((body['temperature'], body['top_p'], body['reasoning_effort']), (.3, .8, 'max'))
        view = self.ledger.view(self.root)
        self.assertEqual(view['consumed']['input_tokens'], 13)
        self.assertEqual(view['consumed']['output_tokens'], 7)
        rows = UsageStore().rows(); self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['usage']['total_tokens'], 20)
        self.assertIsNone(rows[0]['cost_cny'])
        self.assertEqual(rows[0]['network_attempts'][0]['status'], 200)
        detail = debug.detail(debug.listing()['items'][0]['id'])
        self.assertEqual(detail['request'], body)
        self.assertEqual(detail['response']['choices'][0]['message']['content'], '40')
        self.assertEqual(detail['call']['state'], 'complete')
        self.assertEqual(detail['call']['task_id'], 'workflow-task')
        self.assertNotIn('isolated-test-only', json.dumps(detail))
        self.assertEqual(detail['meta']['transport'], 'pi')
        self.assertEqual(detail['meta']['usage_call_id'], rows[0]['id'])
        self.assertIn('sources', detail['meta'])

    def test_unknown_binding_and_usage_stay_unknown_when_recording_paused(self):
        debug.configure(False)
        with installed('ai-node'), self.llm('missing-usage') as llm:
            result = llm.chat(self.messages)
        self.assertIsNone(result['usage'])
        self.assertNotIn('max_tokens', self.requests[0]); self.assertNotIn('max_completion_tokens', self.requests[0])
        self.assertEqual(self.ledger.view(self.root)['consumed']['output_unknown_calls'], 1)
        self.assertIsNone(UsageStore().rows()[0]['usage']['output_tokens'])
        self.assertEqual(debug.listing()['items'], [])

    def test_root_budget_denial_and_context_overflow_send_nothing(self):
        self.ledger.finish(self.root)
        with installed('ai-node'), self.llm() as llm:
            with self.assertRaises(BudgetExceeded): llm.chat(self.messages)
        with patch('desk_companion.models.model_capacity.for_call', return_value=dict(window=8, output_reserve=1)), self.llm() as llm:
            with self.assertRaises(ContextAdmissionError): llm.chat(self.messages)
        self.assertEqual(self.requests, [])

    def test_length_keeps_partial_usage_and_is_not_a_success(self):
        with installed('ai-node'), self.llm('length') as llm:
            with self.assertRaises(IncompleteResponseError) as caught: llm.chat(self.messages)
        self.assertEqual(caught.exception.partial['message']['content'], '40')
        self.assertEqual(caught.exception.finish_reason, 'length')
        self.assertEqual(self.ledger.view(self.root)['consumed']['output_tokens'], 7)
        self.assertEqual(debug.listing()['items'][0]['state'], 'failed')

    def test_unfinished_or_tool_response_cannot_become_complete_text(self):
        for scenario in ('no-finish', 'tool'):
            with self.subTest(scenario=scenario), self.llm(scenario) as llm:
                with self.assertRaises(IncompleteResponseError) as caught: llm.chat(self.messages)
            self.assertIsNotNone(caught.exception.partial['usage'])
        self.assertEqual(len(self.requests), 2)

    def test_empty_workflow_result_is_rejected_before_confirmation(self):
        from desk_companion.automation.workflow_nodes import execute
        with patch('desk_companion.models.model_catalog.require_active', return_value=self.llm('empty').item):
            with self.assertRaisesRegex(ValueError, '完整正文'):
                execute('ai',dict(model_id='',prompt='empty'), 'empty-receipt',lambda *_:None, dict(limits=dict(call_timeout=10)))

    def test_cancellation_callback_preserves_partial_and_stops_without_retry(self):
        cancelled = []
        with installed('ai-node'), self.llm('cancel') as llm:
            with self.assertRaises(ChatCancelledError) as caught:
                llm.chat(self.messages, options=ChatOptions(should_cancel=lambda: bool(cancelled)),
                    callbacks=ChatCallbacks(on_delta=cancelled.append))
        self.assertEqual(caught.exception.partial['message']['content'], '40')
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(debug.listing()['items'][0]['state'], 'cancelled')
        self.assertEqual(self.ledger.view(self.root)['consumed']['output_unknown_calls'], 1)

    def test_finish_phase_preserves_extra_system_message_exactly(self):
        with self.ledger.change(self.root) as root: root['no_progress'] = 3
        with installed('root'), self.llm() as llm: llm.chat(self.messages)
        self.assertEqual(self.requests[0]['messages'][:2], self.messages)
        self.assertIn('预算进入收尾', self.requests[0]['messages'][-1]['content'])
        self.assertEqual(len(self.messages), 2)

    def test_http_rejection_is_recorded_and_never_retried(self):
        with installed('ai-node'), self.llm('rejected') as llm:
            with self.assertRaises(IncompleteResponseError): llm.chat(self.messages)
        self.assertEqual(len(self.requests), 1)
        detail = debug.detail(debug.listing()['items'][0]['id'])
        self.assertEqual(detail['call']['status'], 429)
        self.assertIn('isolated rate limit', detail['response_raw'])
        self.assertEqual(UsageStore().rows()[0]['network_attempts'][0]['status'], 429)

    def test_workflow_node_uses_pi_and_does_not_write_zero_for_missing_usage(self):
        from desk_companion.automation.workflow_nodes import execute
        with patch('desk_companion.models.model_catalog.require_active', return_value=self.llm('missing-usage').item), \
                patch('desk_companion.observability.usage.append_usage') as append, installed('ai-node'):
            events = []
            result = execute('ai', dict(model_id='', prompt='处理固定材料'), 'receipt-original',
                lambda kind, data: events.append((kind,data)), dict(limits=dict(call_timeout=10)))
        self.assertEqual(result, dict(text='40'))
        self.assertIn(('usage', dict(input_tokens=None, output_tokens=None)), events)
        self.assertEqual(events[-1][0], 'llm_end')
        append.assert_not_called()

    def test_step_confirmed_ai_and_unknown_write_resume_without_replaying(self):
        from desk_companion.automation import workflow_nodes
        from desk_companion.automation.workflow_worker import execute
        from desk_companion.automation.workflows import WorkflowService
        from tests.test_workflows import FakeTasks, graph, node
        tasks = FakeTasks(); service = WorkflowService(lambda: tasks); store = service.store
        definition = store.save(dict(name='Pi step', graph=graph(node('trigger','trigger',text='old material'),
            node('ai','ai',prompt='{{trigger.text}}'),
            node('base','base',base_token='base',table_id='table',key_field='receipt',fields={'content':'{{ai.text}}'}))))
        run = service.operation('start',dict(id=definition['id'],version=definition['version'],request_id='same',mode='step'))['run']
        writes = []
        def adapter(kind, config, key, emit, request):
            if kind == 'base':
                writes.append(dict(key=key, fields=config['fields']))
                raise TimeoutError('Simulate committed remote write with lost receipt')
            return workflow_nodes.execute(kind, config, key, emit, request)
        def drive():
            execute(tasks.requests[-1], lambda *_:None, store=store, adapter=adapter, check_target=lambda *_:None)
            tasks.tasks[tasks.requests[-1]['task_id']]['state'] = 'succeeded'
        drive()
        self.assertTrue(service.operation('advance',dict(run_id=run['id']))['ok'])
        with patch('desk_companion.models.model_catalog.require_active', return_value=self.llm().item): drive()
        self.assertEqual(store.run(run['id'])['receipts']['ai']['output']['text'], '40')
        self.assertTrue(service.operation('advance',dict(run_id=run['id']))['ok']); drive()
        self.assertEqual(store.run(run['id'])['state'], 'waiting_approval'); self.assertEqual(writes, [])
        self.assertTrue(service.operation('advance',dict(run_id=run['id'],confirm_node='base'))['ok']); drive()
        self.assertEqual(store.run(run['id'])['state'], 'unknown')
        self.assertFalse(service.operation('advance',dict(run_id=run['id']))['ok'])
        with patch.object(workflow_nodes, 'reconcile', return_value=dict(record_id='original-record')) as check:
            self.assertTrue(service.operation('reconcile',dict(run_id=run['id'],node_id='base'))['ok'])
        self.assertEqual(check.call_args.args[2], writes[0]['key'])
        self.assertTrue(service.operation('advance',dict(run_id=run['id']))['ok']); drive()
        self.assertEqual(store.run(run['id'])['state'], 'completed')
        self.assertEqual(store.run(run['id'])['version'], definition['version'])
        self.assertEqual(len(self.requests), 1); self.assertEqual(len(writes), 1)
        self.assertEqual(writes[0]['fields'], {'content':'40'})

    def test_scheduled_saved_version_calls_pi_with_original_input(self):
        import copy
        from desk_companion.automation.automation_service import AutomationService
        from desk_companion.automation.workflow_worker import execute
        from tests.test_workflows import FakeTasks, graph, node
        tasks = FakeTasks(); service = AutomationService(tasks=lambda:tasks)
        self.addCleanup(service.stop, 3)
        store = service.workflows.store
        definition = store.save(dict(name='Pi schedule', graph=graph(node('trigger','trigger',text='saved original'),
            node('ai','ai',prompt='{{trigger.text}}'))))
        saved = service.save_automation_job(dict(name='fixed schedule',action='workflow',enabled=False,cadence='daily',
            weekdays=[],hour=9,minute=0,doc='',workflow_id=definition['id'],workflow_version=definition['version'],workflow_write_version=''))
        changed = copy.deepcopy(definition['graph']); changed['nodes'][0]['config']['text']='new unbound version'
        store.save(dict(id=definition['id'],revision=definition['revision'],name=definition['name'],graph=changed))
        with patch.object(service, '_kick'):
            execution = service.run_automation_job(saved['job_id'])['execution']
        service._start_workflow(saved['job_id'], execution)
        request = tasks.requests[-1]
        with patch('desk_companion.models.model_catalog.require_active', return_value=self.llm().item):
            execute(request, lambda *_:None, store=store)
        run = store.run(request['workflow_run'])
        self.assertEqual(run['state'], 'completed')
        self.assertEqual(run['version'], definition['version'])
        self.assertEqual(self.requests[0]['messages'][-1]['content'], 'saved original')
        self.assertEqual(run['receipts']['ai']['output'], dict(text='40'))
