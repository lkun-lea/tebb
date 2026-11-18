"""Product compatibility facade; the official Pi Agent Core owns the tool loop."""
import json
import time
import uuid
from types import SimpleNamespace

from atlas.core.plugin import PluginManager
from atlas.core.terminator import make_default_terminator
from atlas.memory.base import Memory
from atlas.journal import InMemoryJournal
from atlas.llm import ChatOptions, ChatCancelledError, IncompleteResponseError

from desk_companion.observability.pi_observer import PiObserver
from desk_companion.pi_runtime.bridge import PiBridge, PiCancelled, PiTimeout, PiProcessError
from desk_companion.pi_runtime.model_mapping import payload_for


def legacy_message(message):
    result=dict(role='assistant',content=''.join(b.get('text','')for b in message.get('content',[])if b['type']=='text')or None)
    thinking=''.join(b.get('thinking','')for b in message.get('content',[])if b['type']=='thinking')
    if thinking:result['reasoning_content']=thinking
    calls=[dict(id=b['id'],type='function',function=dict(name=b['name'],arguments=json.dumps(b['arguments'],ensure_ascii=False)))
           for b in message.get('content',[])if b['type']=='toolCall']
    if calls:result['tool_calls']=calls
    return result


class PiAgentLimit(RuntimeError):
    public_message='Agent 达到步骤或时间上限。已保留进度，请查看任务时间线。'


class PiChatAgent:
    pi_runtime=True

    def __init__(self, *, llm, tools, system_prompt, journal=None, max_steps=10, compact_threshold=None):
        self.llm,self.tools=llm,tools
        self.memory=Memory(system_prompt=system_prompt,compact_threshold=compact_threshold)
        self.plugin_manager=PluginManager()
        self.journal=journal or InMemoryJournal(save_full_payload=True)
        self.terminator=make_default_terminator(max_steps)
        self.last_result=None
        self.pending=None
        self.running=False
        self.tool_budget_managed=False
        self.usage_by_run={}

    def _emit(self, event, **values):
        values=dict(run_id=self.run_id,turn_idx=self.turn,**values)
        self.journal.append(self.journal.make_event(self.run_id,event,values))
        self.plugin_manager.emit(event,**values)

    def usage_summary(self, run_id):
        return self.usage_by_run[run_id].copy()

    def _cancelled(self):
        # MaxSteps is checked before the next model call, not between a response and its tools.
        check=SimpleNamespace(**{**vars(self.context),'step_count':0})
        return self.terminator.should_stop(check)[0] or bool(self.cancel_check and self.cancel_check())

    def _end(self, *, error=None, result=None):
        if self.pending is None:return
        manager,call,observer,started=self.pending
        self.pending=None
        try:
            if error:manager.__exit__(type(error),error,error.__traceback__)
            else:
                call.result=result
                manager.__exit__(None,None,None)
        except BaseException as exc:
            error=exc
            raise
        finally:
            observer.finish(error)
            hook=getattr(self.llm,'on_call_end',None)
            if hook:hook(round((time.monotonic()-started)*1000))

    def _model(self, data):
        if data['event']=='model_end':
            message=data['message'];reason=message['stopReason']
            value=dict(message=legacy_message(message),usage=data.get('provider_usage'),
                finish_reason='tool_calls'if reason=='toolUse'else reason,
                duration_ms=round((time.monotonic()-self.pending[3])*1000))
            if reason not in {'stop','toolUse'}:
                error=IncompleteResponseError(reason,value)
                self._end(error=error)
                raise error
            self._end(result=value)
            self.memory.add_assistant(value['message'])
            self.context.step_count+=1
            usage=value['usage'] or {}
            for target,source in [('input_tokens','prompt_tokens'),('output_tokens','completion_tokens')]:
                count=usage.get(source);prior=self.usage_by_run[self.run_id][target]
                self.usage_by_run[self.run_id][target]=prior+count if type(prior)is int and type(count)is int and count>=0 else None
            self._emit('llm_after_call',model=self.llm.model,response=value['message'],usage=value['usage'],duration_ms=value['duration_ms'])
            return
        if self.pending:raise RuntimeError('前次模型调用尚未结算。')
        if self.terminator.should_stop(self.context)[0] or self._cancelled():
            raise PiAgentLimit(PiAgentLimit.public_message)
        body=data['payload']
        if body.get('model')!=self.llm.model:raise ValueError('模型身份变化，未发送。')
        self.turn+=1
        hook=getattr(self.llm,'on_call_start',None)
        if hook:hook()
        started=time.monotonic()
        self.partial=dict(message=dict(role='assistant',content=None),usage=None,duration_ms=0)
        manager=self.llm.admitted_call(body['messages'],body.get('tools'),options=ChatOptions(sampling=self.llm.sampling,stream=True))
        try:call=manager.__enter__()
        except BaseException:
            hook=getattr(self.llm,'on_call_end',None)
            if hook:hook(round((time.monotonic()-started)*1000))
            raise
        observer=PiObserver(str(self.llm.client.base_url).rstrip('/')+'/chat/completions')
        self.pending=(manager,call,observer,started)
        self.cancel_check=call.options.should_cancel if call.options else None
        actual={**body,'messages':call.messages}
        actual.pop('tools',None)
        if call.tools:actual['tools']=call.tools
        else:
            actual.pop('tool_choice',None)
            actual.pop('parallel_tool_calls',None)
        self.allowed_tools={tool['function']['name']for tool in call.tools or []}
        if call.options:actual.update(call.options.extra_body or {})
        observer.sending(actual)
        self._emit('llm_before_call',model=self.llm.model,messages=call.messages,kwargs=dict(tools=call.tools))
        return dict(payload=actual)

    def _event(self, kind, data):
        if self.pending:self.pending[2].event(kind,data)
        if kind=='text_delta':
            self.partial['message']['content']=(self.partial['message']['content']or'')+data
            self._emit('llm_delta',delta=data)
        elif kind=='provider_usage':self.partial['usage']=data['usage']
        elif kind=='thinking_delta' and self.llm.on_reasoning:self.llm.on_reasoning(data)
        elif kind=='tool_result' and (self.turn,data['call_id']) not in self.completed:
            # SDK validation failures never started a Python tool or external write.
            result=data['result']
            text='\n'.join(b.get('text','')for b in result.get('content',[])if b.get('type')=='text')
            self.memory.add_tool(text,data['call_id'])
        if self.llm.on_progress and kind in {'text_delta','thinking_delta','provider_frame'}:self.llm.on_progress()

    def _tool(self, name, arguments, call_id):
        if self._cancelled():raise ChatCancelledError(dict(message={},usage=None,duration_ms=0))
        if (self.turn,call_id) in self.completed:raise RuntimeError('本轮工具调用编号重复，未重复执行。')
        tool=self.tools.get(name)
        if name not in self.allowed_tools:raise ValueError('该工具不在本轮模型请求的授权清单中。')
        tool.validate_input(arguments)
        from desk_companion.tasks.task_budgets import current
        scope=current()
        if scope is not None and not self.tool_budget_managed:scope.tool(tool.isReadOnly,name)
        step_id=f'pi:{self.turn}:{call_id}'
        self._emit('tool_before_call',step_id=step_id,tool_name=name,input=arguments)
        started=time.monotonic();status='success'
        try:result=self.tools.execute(name,arguments)
        except Exception as exc:
            status='failed';result=dict(ok=False,error='工具执行未完成（'+type(exc).__name__+'），请核对原操作回执。')
        self.completed.add((self.turn,call_id))
        text=result if isinstance(result,str)else json.dumps(result,ensure_ascii=False)
        self.memory.add_tool(text,call_id)
        self._emit('tool_after_call',step_id=step_id,tool_name=name,input=arguments,
            result=dict(output=result),status=status,duration_ms=round((time.monotonic()-started)*1000))
        return result

    def run(self, user_input, run_id=None):
        if self.running:raise RuntimeError('助手正在运行。')
        self.run_id=run_id or uuid.uuid4().hex;self.turn=0
        self.context=SimpleNamespace(step_count=0,start_time=time.time()*1000,total_tokens=0,cost_usd=0,recent_outputs=[])
        self.cancel_check=None;self.completed=set()
        self.partial=dict(message=dict(role='assistant',content=None),usage=None,duration_ms=0)
        self.usage_by_run[self.run_id]=dict(input_tokens=0,output_tokens=0)
        self.memory.add_user(user_input)
        self.last_result=SimpleNamespace(status='running')
        sampling=self.llm.sampling or {}
        client=self.llm.client
        item=dict(id=self.llm.context_model_id,model=self.llm.model,api_key=client.api_key,base_url=str(client.base_url))
        payload=payload_for(item,sampling)
        payload.update(product_gate=True,messages=self.memory.messages,
            tools=[spec['function']for spec in self.tools.to_openai_tools()],
            thinking_level=sampling.get('reasoning_effort','low'),call_timeout_ms=round((client.timeout.read or 90)*1000))
        error=None
        self.running=True
        try:
            with PiBridge() as bridge:
                try:
                    result=bridge.call('agent',payload,before_model=self._model,tool=self._tool,on_event=self._event,
                        should_cancel=self._cancelled,timeout=3600)
                except PiCancelled:raise ChatCancelledError(self.partial)from None
                except PiTimeout:
                    failure=TimeoutError('模型调用超时，原片段和回执已保留。');failure.partial=self.partial
                    raise failure from None
                except PiProcessError:raise IncompleteResponseError('error',self.partial)from None
            answer=legacy_message(result['message']).get('content') or ''
            self.last_result=SimpleNamespace(status='completed')
            return answer
        except BaseException as exc:
            error=exc
            self.last_result=SimpleNamespace(status='aborted')
            raise
        finally:
            try:self._end(error=error or RuntimeError('模型进程未交还完整结果。'))
            finally:self.running=False
