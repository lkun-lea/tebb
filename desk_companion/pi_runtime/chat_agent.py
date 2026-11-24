"""Product compatibility facade; the official Pi Agent Core owns the tool loop."""
import json
import os
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
    stable_discovery=True

    def __init__(self, *, llm, tools, system_prompt, journal=None, max_steps=10, compact_threshold=None, tool_loading=None):
        tool_loading=tool_loading or os.environ.get('TEBB_TOOL_LOADING','demand')
        if tool_loading not in {'demand','eager'}:raise ValueError('工具加载策略无效。')
        self.tool_loading=tool_loading
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
        wire_tools=body.get('tools')
        from desk_companion.tasks.task_budgets import current
        from desk_companion.pi_runtime.tool_loading import CALL
        scope=current()
        can_finish=self.loading.stable and 'submit_deliverable' in self.loading.loaded
        from desk_companion.projects.project_workspace import READ_TOOLS
        messages = body['messages']
        if self.source_evidence:
            after_call = SimpleNamespace(**{**vars(self.context), 'step_count': self.context.step_count + 1})
            closing_turn = self.loading.catalog.keys() <= READ_TOOLS and self.terminator.should_stop(after_call)[0]
            if closing_turn:
                wire_tools = None
                note = '这是交付回合。直接用自然语言回答用户，引用已有回执并交代缺失依据。勿输出工具调用或调用标记。'
            else:
                note = ('根据原问题和已读材料核对主要职责：区分已有实现正文、仅见文档或调用点、与问题无关。'
                        '已定位但还未核实的核心职责，先定点补读相应实现；缺口补齐后立即引用回执作答。'
                        '架构概览可以一条真实路径说明。避免为旁支、例子或穷举目录继续读取。')
            messages = [*messages, dict(role='system', content=note)]
        if can_finish and scope and scope.phase()=='finish':
            from copy import deepcopy
            wire_tools=deepcopy(wire_tools)
            for entry in wire_tools or []:
                fn=entry['function']
                if fn['name']==CALL:
                    fn['parameters']['properties']['name']['enum']=['submit_deliverable']
        manager=self.llm.admitted_call(messages,wire_tools,options=ChatOptions(sampling=self.llm.sampling,stream=True))
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
        self.discovered_for_turn = frozenset(self.loading.loaded)
        for entry in call.tools or []:
            fn=entry['function']
            if fn['name']==CALL:
                allowed=fn['parameters']['properties']['name'].get('enum')
                if allowed is not None:
                    self.discovered_for_turn=self.discovered_for_turn.intersection(allowed)
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
            if data.get('is_error'):
                from desk_companion.observability.tool_monitor import ToolRequest
                with ToolRequest(data['name'],ident=f'{self.run_id}:{self.turn}:{data["call_id"]}') as request:
                    request.reject('sdk_validation')
        elif kind=='tool_definitions':
            from desk_companion.observability.usage_observer import _safe
            for name in data['names']:
                _safe(self.loading.store.event,'definition_effective',tool=name,**self.loading.owner,
                    definition_version=self.loading.catalog.get(name,{}).get('version'),position=data['position'],effective_turn=self.turn+1,state='effective',protocol='pi_public_tool_declaration')
        if self.llm.on_progress and kind in {'text_delta','thinking_delta','provider_frame'}:self.llm.on_progress()

    def _tool(self, name, arguments, call_id):
        from desk_companion.observability.tool_monitor import ToolRequest
        from desk_companion.pi_runtime.tool_loading import CALL
        via_search = self.loading.stable and name == CALL and name in self.allowed_tools
        if via_search:
            target = arguments.get('name')
            if isinstance(target,str) and target in self.discovered_for_turn:
                name,arguments = target,arguments['arguments']
            else:
                result=dict(ok=False,reason='tool_not_discovered',next_action='请先按需搜索该工具。')
                self.memory.add_tool(json.dumps(result,ensure_ascii=False),call_id)
                self.completed.add((self.turn,call_id))
                return result
        metadata={**self.loading.owner,'model':self.llm.model,'definition_version':self.loading.catalog.get(name,{}).get('version')}
        with ToolRequest(name,ident=f'{self.run_id}:{self.turn}:{call_id}',metadata=metadata) as request:
            return self._admitted_tool(name,arguments,call_id,request,via_search=via_search)

    def _admitted_tool(self, name, arguments, call_id, request, *, via_search=False):
        if self._cancelled():raise ChatCancelledError(dict(message={},usage=None,duration_ms=0))
        if (self.turn,call_id) in self.completed:raise RuntimeError('本轮工具调用编号重复，未重复执行。')
        if name not in self.allowed_tools and not via_search:
            request.reject('not_allowed')
            raise ValueError('该工具不在本轮模型请求的授权清单中。')
        from desk_companion.pi_runtime.tool_loading import SEARCH,LOAD
        if name in {SEARCH,LOAD}:
            from desk_companion.tasks.task_budgets import current
            if current():current().tool(True,name)
            before=set(self.loading.loaded)
            result=self.loading.execute(name,arguments,request.id)
            if current() and (name==LOAD or self.loading.stable):
                for loaded in self.loading.loaded:
                    if loaded not in before:current().progress('tool_definition',loaded,self.loading.catalog[loaded]['version'])
            self.completed.add((self.turn,call_id))
            self.memory.add_tool(json.dumps(result,ensure_ascii=False),call_id)
            return result
        tool=self.tools.get(name)
        from jsonschema import ValidationError
        try:
            tool.validate_input(arguments)
        except ValidationError as exc:
            if not via_search: raise
            request.reject('invalid_arguments')
            result=dict(ok=False,reason='invalid_arguments',tool=name,field=list(exc.absolute_path),
                        constraint=exc.validator,next_action='按搜索结果中的参数定义修正后重试。')
            self.completed.add((self.turn,call_id))
            self.memory.add_tool(json.dumps(result,ensure_ascii=False),call_id)
            return result
        from desk_companion.tasks.task_budgets import current
        scope=current()
        if scope is not None and not self.tool_budget_managed:scope.tool(tool.isReadOnly,name)
        step_id=f'pi:{self.turn}:{call_id}'
        self._emit('tool_before_call',step_id=step_id,tool_name=name,input=arguments)
        started=time.monotonic();status='success'
        root_listing = (self.loading.source_overview and name == 'workspace_list'
                        and arguments.get('path', '') in ('', '.'))
        root_id = arguments.get('root', 'main') if root_listing else None
        if not tool.isReadOnly:
            self.overview_root_receipts.clear()
        try:
            if root_listing and root_id in self.overview_root_receipts:
                result = dict(ok=True, reused_call=self.overview_root_receipts[root_id],
                              next_action='本轮任务已列出该根目录，请复用先前回执。可直接按路径读取 README.md。')
            else:
                result = self.tools.execute(name, arguments)
                if root_listing and isinstance(result, dict) and result.get('ok') and 'entries' in result:
                    self.overview_root_receipts[root_id] = call_id
        except Exception as exc:
            status='failed';result=dict(ok=False,reason='adapter_error',error='工具执行未完成（'+type(exc).__name__+'），请核对原操作回执。')
            from desk_companion.projects.project_workspace import READ_TOOLS
            if name in READ_TOOLS and isinstance(exc,(OSError,ValueError)):
                from desk_companion.projects.workspace_feedback import read_error
                result.update(read_error(exc))
        if (name=='workspace_read' and self.loading.prefer_workspace and isinstance(result,dict)
                and 'workspace_read_symbol' in self.loading.catalog):
            from desk_companion.projects.workspace_source import discovery_preview
            result=discovery_preview(result)
        if name=='workspace_read_symbol' and self.loading.prefer_workspace and isinstance(result,dict):
            from desk_companion.projects.workspace_source import excerpt_for_question
            explicit_range = 'start_line' in arguments and 'end_line' in arguments
            if not (self.loading.source_overview and explicit_range):
                result = excerpt_for_question(result)
            if (self.loading.source_overview and result.get('closing_excerpt')
                    and result['end_line'] >= result['closing_excerpt']['end_line']):
                loops = result['closing_excerpt'].get('enclosing_loops')
                result = {k: v for k, v in result.items() if k != 'closing_excerpt'}
                if loops:
                    result['enclosing_loops'] = loops
        if self.loading.source_overview:
            from desk_companion.projects.workspace_source import overview_receipt
            result = overview_receipt(name, arguments, result, self.seen_source_locations,
                                      implementation=self.loading.implementation_overview)
            if isinstance(result, dict) and result.get('ok'):
                if (name in {'workspace_read', 'workspace_read_symbol'}
                        and (result.get('numbered_text') or result.get('text'))
                        and result.get('path') and not result['path'].lower().endswith(('.md', '.rst', '.txt'))):
                    self.source_evidence = True
        if result is None or isinstance(result,str) and not result.strip():
            result = dict(ok=False, state='unknown', reason='missing_receipt',
                          next_action='未收到执行回执；先核对操作状态，勿重复提交写入。')
        from desk_companion.observability.tool_monitor import tool_result_state
        if tool_result_state(result)in{'failed','unknown','timed_out','cancelled','rejected'}:status='failed'
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
        self.source_evidence = False
        self.seen_source_locations=set()
        self.overview_root_receipts = {}
        self.partial=dict(message=dict(role='assistant',content=None),usage=None,duration_ms=0)
        self.usage_by_run[self.run_id]=dict(input_tokens=0,output_tokens=0)
        self.memory.add_user(user_input)
        self.last_result=SimpleNamespace(status='running')
        sampling=self.llm.sampling or {}
        client=self.llm.client
        item=dict(id=self.llm.context_model_id,model=self.llm.model,api_key=client.api_key,base_url=str(client.base_url))
        payload=payload_for(item,sampling)
        from desk_companion.pi_runtime.tool_loading import ToolLoading
        from desk_companion.observability.usage_observer import _metadata
        from desk_companion.observability.agent_debug import metadata
        owner=_metadata()
        self.loading=ToolLoading(self.tools.to_openai_tools(),session=metadata().get('session') or self.run_id,
            root=owner.get('root',''),task=owner.get('task',''),user_input=user_input,
            stable=self.tool_loading=='demand' and self.stable_discovery)
        if self.tool_loading=='eager' and self.loading.catalog:
            names=list(self.loading.catalog)
            for offset in range(0,len(names),20):self.loading.execute('tebb_tools_load',dict(names=names[offset:offset+20]),'eager_baseline')
        payload.update(stable_discovery=self.loading.stable,product_gate=True,messages=self.memory.messages,
            tools=self.loading.specs(all_tools=True),initial_tools=[t['name']for t in self.loading.specs()],
            thinking_level=sampling.get('reasoning_effort','low'),call_timeout_ms=round((client.timeout.read or 90)*1000))
        from desk_companion.pi_runtime.tool_loading import SEARCH
        payload.update(base_tools=[t['name']for t in self.loading.specs()]if self.tool_loading=='eager'else[SEARCH],
            tool_versions={n:d['version']for n,d in self.loading.catalog.items()})
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
