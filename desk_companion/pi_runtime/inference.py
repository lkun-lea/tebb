"""Tool-free Pi inference under the existing product admission/accounting policy."""
from __future__ import annotations

import copy
import json
import time
from types import SimpleNamespace

from atlas.llm import ChatCallbacks, ChatOptions, ChatCancelledError, IncompleteResponseError
from desk_companion.collaboration.execution_context import ExecutionLLM, ContextAdmissionError, configuration_revision
from desk_companion.models import model_capacity
from desk_companion.models.model_generation import apply_chat_parameters
from desk_companion.pi_runtime.model_mapping import payload_for
from desk_companion.observability.pi_observer import PiObserver
from desk_companion.pi_runtime.bridge import PiBridge, PiProcessError, PiCancelled, PiTimeout


class PiInference(ExecutionLLM):
    """Reuse product policies; the borrowed route object never sends HTTPX requests.

    Atlas contracts/base initialization are temporary until all callers migrate.
    The model request and response assembly here execute only in official Pi AI.
    """
    def __init__(self, item, *, timeout=90, on_context=None):
        self.item = copy.deepcopy(item)
        self.timeout = timeout
        super().__init__(model=item['model'], client=SimpleNamespace(base_url=item['base_url']),
                         context_model_id=item.get('id', ''), on_context=on_context)

    def _transport_chat(self, messages, tools, on_delta, *, options, callbacks):
        if tools or not messages or any(row.get('role') not in {'system', 'user'} for row in messages) or any(
                not isinstance(row.get('content'), str) for row in messages):
            raise ValueError('当前 Pi 单次推理只接收系统提示与用户材料，不接受工具或会话历史。')
        options = options or ChatOptions(sampling=self.sampling)
        callbacks = callbacks or ChatCallbacks(on_delta=on_delta)
        sampling = dict(options.sampling or {})
        endpoint = self.item['base_url'].rstrip('/')+'/chat/completions'
        capacity = model_capacity.for_call(self.context_model_id, self.model, endpoint)
        revision = configuration_revision(self.item)
        payload = payload_for(self.item,sampling)
        payload['wire_options'].update(dict(options.extra_body or {}))
        payload['wire_options']['messages'] = messages
        payload['context'] = dict(systemPrompt='\n'.join(row['content'] for row in messages if row['role']=='system'),
            messages=[dict(role='user',content=row['content'],timestamp=0) for row in messages if row['role']=='user'])
        started = time.monotonic()
        observer = PiObserver(endpoint)
        usage = None
        pieces = []

        def before_model(data):
            if configuration_revision(self.item) != revision:
                raise ValueError('模型容量或输出绑定已变化，未发送，请重新检查后执行。')
            actual = data['payload']
            if actual.get('model') != self.model or actual.get('messages') != messages or actual.get('tools'):
                raise ContextAdmissionError('Pi 映射改变了已准入材料，未发送。', self.last_context)
            from desk_companion.collaboration.execution_context import prepare_request
            apply_chat_parameters(actual, self.item['base_url'])
            _, check = prepare_request(actual, capacity)
            if check['input_tokens'] != self.last_context['input_tokens'] or check['compacted']:
                raise ContextAdmissionError('实际发送材料与已准入计数不一致，未发送。', check)
            if options.should_cancel and options.should_cancel():
                raise ChatCancelledError(partial())
            observer.sending(actual)
            return dict(payload=actual)

        def event(kind, data):
            nonlocal usage
            observer.event(kind, data)
            if kind == 'provider_usage':
                usage = data['usage']
            elif kind == 'text_delta':
                pieces.append(data)
                if callbacks.on_delta: callbacks.on_delta(data)
            elif kind == 'thinking_delta' and callbacks.on_reasoning:
                callbacks.on_reasoning(data)
            if callbacks.on_progress and kind in {'text_delta','thinking_delta','provider_frame'}:
                callbacks.on_progress()

        def partial(data=None):
            result = (data or {}).get('message') or {}
            text = ''.join(block.get('text','') for block in result.get('content',[]) if block.get('type') == 'text')
            message = dict(role='assistant', content=text or ''.join(pieces) or None)
            calls = [dict(id=block['id'],type='function',function=dict(name=block['name'],arguments=json.dumps(block['arguments'])))
                     for block in result.get('content',[]) if block.get('type') == 'toolCall']
            if calls: message['tool_calls'] = calls
            return dict(message=message, usage=usage or (data or {}).get('provider_usage'), duration_ms=round((time.monotonic()-started)*1000),
                        finish_reason=result.get('stopReason'))

        error = None
        try:
            with PiBridge() as bridge:
                try:
                    data = bridge.call('complete', payload, before_model=before_model,
                        should_cancel=options.should_cancel, on_event=event, timeout=self.timeout)
                except PiCancelled as exc:
                    raise ChatCancelledError(partial(exc.partial)) from None
                except PiTimeout as exc:
                    failure = TimeoutError('Pi 模型调用超时，已保留片段与原调用记录。')
                    failure.partial = partial(exc.partial)
                    raise failure from None
                except PiProcessError as exc:
                    raise IncompleteResponseError(exc.finish_reason or 'error', partial(exc.partial)) from None
            return partial(data)
        except BaseException as exc:
            error = exc
            raise
        finally:
            observer.finish(error)
