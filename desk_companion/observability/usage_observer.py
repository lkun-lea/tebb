"""Actual adapter attempts; never store prompts, arguments, outputs or credentials."""
from contextvars import ContextVar
import hashlib
import logging
import json
import time
import uuid

from desk_companion.observability.usage_store import UsageStore, estimate, normalized_usage

_MODEL=ContextVar('usage_model_attempt',default=None)
_LAST=ContextVar('usage_last_model_attempt',default=None)
log=logging.getLogger(__name__)


def _safe(function,*args,**kwargs):
    try:return function(*args,**kwargs)
    except Exception as exc:
        log.warning('Usage metadata unavailable (%s)',type(exc).__name__)
        return None


def _metadata():
    from desk_companion.tasks.task_budgets import current
    from desk_companion.observability.usage_sources import scope_metadata
    return scope_metadata(current())


class ModelAttempt:
    def __init__(self,model,model_id='',endpoint='',ident=None,*,source=None,store=None):
        self.id=ident or uuid.uuid4().hex;self.store=store or UsageStore();self.model=model;self.model_id=model_id
        self.endpoint=endpoint;self.source=source;self.network=[];self.finished=False;self.prices=None

    def __enter__(self):
        self.started=time.monotonic()
        from desk_companion.observability.agent_debug import install
        _safe(install)
        self.metadata=_safe(_metadata)or dict(root='',task='',project_id=None,channel='unknown',source='unknown')
        from desk_companion.observability.agent_debug import metadata
        context=metadata()
        self.metadata['session']=context.get('session','')
        self.metadata.update({key:context[key]for key in('agent','role','phase','configuration_version','code_version','skills_selection_version')if key in context})
        from desk_companion.infrastructure.code_identity import process_code_version
        self.metadata['code_version']=_safe(process_code_version)
        if not self.metadata.get('root'):
            self.metadata.update(root='operation:'+self.id,task=context.get('task_id',''))
        if self.source:self.metadata.update(source=self.source,channel='diagnostic')
        endpoint=self.endpoint.rstrip('/')
        for suffix in('/chat/completions','/responses'):
            if endpoint.endswith(suffix):endpoint=endpoint[:-len(suffix)];break
        route=hashlib.sha256(endpoint.encode()).hexdigest()
        self.metadata.update(model=self.model,model_id=self.model_id,route=route,
            model_key=(self.model_id or self.model)+':'+route[:16])
        from desk_companion.infrastructure.state import model_price_snapshot
        self.prices=_safe(model_price_snapshot,self.model)
        self.metadata['price_snapshot']=self.prices
        _safe(self.store.begin,self.id,'model',self.metadata)
        self.token=_MODEL.set(self)
        _LAST.set((self.metadata['root'],self.metadata['task'],self.id,self.model))
        return self

    def returned(self,usage,finish_reason=None):
        normalized=normalized_usage(usage)
        _safe(self.store.update,self.id,state='returned',ended=time.time(),usage=normalized,
            cost_cny=estimate(normalized,self.prices),finish_reason=finish_reason if isinstance(finish_reason,str)and len(finish_reason)<=64 else None)
        self.finished=True

    def observe(self,payload,debug_call=None):
        from desk_companion.observability.tool_monitor import fingerprint,ToolMonitor
        values=dict(prompt_version=fingerprint([m for m in payload.get('messages',[])if m.get('role')in{'system','developer'}]),
                    tools_version=fingerprint(payload.get('tools',[])),input_version=fingerprint(payload.get('messages',payload.get('input',[]))),
                    request_configuration_version=fingerprint({k:v for k,v in payload.items()if k not in{'messages','input','tools'}}))
        if debug_call:
            self.debug_calls=getattr(self,'debug_calls',[])
            if debug_call not in self.debug_calls:self.debug_calls.append(debug_call)
            values.update(debug_call=debug_call,debug_calls=self.debug_calls)
        _safe(self.store.update,self.id,**values)
        monitor=ToolMonitor();definitions=_safe(monitor.register,payload.get('tools',[]))or[]
        owner={k:self.metadata.get(k,'') for k in ('root','task','session')}
        for d in definitions:
            _safe(monitor.event,'offer',ident=self.id+':offer:'+d['name'],tool=d['name'],**owner,
                definition_version=d['version'],trigger_call=self.id,model=self.model,state='offered',
                protocol='actual_provider_payload')

    def text_received(self):
        if not getattr(self,'first_text_recorded',False):
            _safe(self.store.update,self.id,first_text_ms=round((time.monotonic()-self.started)*1000))
            self.first_text_recorded=True

    def output_received(self):
        if not getattr(self,'first_output_recorded',False):
            _safe(self.store.update,self.id,first_output_ms=round((time.monotonic()-self.started)*1000))
            self.first_output_recorded=True

    def __exit__(self,kind,exc,traceback):
        try:
            if not self.finished:
                partial=getattr(exc,'partial',None);usage=partial.get('usage')if isinstance(partial,dict)else None
                normalized=normalized_usage(usage)
                error=kind.__name__ if kind else ''
                state='cancelled'if error in{'ChatCancelledError','CancelledError','KeyboardInterrupt'}else'failed'if kind else'unknown'
                _safe(self.store.update,self.id,state=state,ended=time.time(),error_kind=error,
                    usage=normalized,cost_cny=estimate(normalized,self.prices))
        finally:_MODEL.reset(self.token)

    def sending(self):
        ordinal=len(self.network)+1
        self.network.append(dict(id=self.id+':'+str(ordinal),state='sending',status=None))
        _safe(self.store.update,self.id,network_attempts=self.network)
        return self,ordinal-1


def http_sending(request):
    current=_MODEL.get()
    if current and request.method=='POST'and request.url.path.endswith(('/chat/completions','/responses')):
        try:current.observe(json.loads(request.content))
        except (ValueError,TypeError):pass
        return current.sending()


def current_model_attempt():
    """Actual Node/provider adapters share the same attempt owner as HTTPX."""
    return _MODEL.get()


def http_returned(handle,status=None,error=None):
    if not handle:return
    attempt,index=handle
    attempt.network[index].update(state='failed'if error or status is not None and status>=400 else'headers',status=status)
    if error:attempt.network[index]['error_kind']=type(error).__name__
    _safe(attempt.store.update,attempt.id,network_attempts=attempt.network)


def invoke_tool(name,function,*args,**kwargs):
    """Wrap only the real adapter invocation, after guards/cache/locks."""
    from desk_companion.chat.tool_library import disabled
    if disabled(name):
        raise ValueError('此工具已在本机工具目录中停用。')
    store=UsageStore();ident=uuid.uuid4().hex;metadata=_safe(_metadata)or dict(root='',task='',project_id=None,channel='unknown',source='unknown')
    from desk_companion.observability.tool_monitor import ToolMonitor,current_request,tool_result_state
    from desk_companion.observability.agent_debug import metadata as debug_metadata
    request=current_request()
    metadata['session']=debug_metadata().get('session','')
    if request and request.metadata.get('root'):
        metadata.update({k:request.metadata[k]for k in('root','task','session')if k in request.metadata})
    if not metadata.get('root'):metadata['root']='operation:'+ident
    prior=_LAST.get();parent=prior[2]if prior and prior[:2]==(metadata['root'],metadata['task'])and metadata['root']else None
    if parent and len(prior)>3:metadata['model']=prior[3]
    _safe(store.begin,ident,'tool',{**metadata,'tool':name,'parent_call':parent})
    monitor=ToolMonitor()
    owner={k:metadata.get(k,'') for k in ('root','task')}
    if metadata.get('model'):owner['model']=metadata['model']
    if request:
        request.admitted=True
        request.emit('attempt',attempt_id=ident,parent_call=parent)
    else:_safe(monitor.event,'attempt',ident=ident+':attempt',tool=name,**owner,attempt_id=ident,parent_call=parent)
    started=time.monotonic()
    try:
        result=function(*args,**kwargs)
    except BaseException as exc:
        state='cancelled'if type(exc).__name__ in {'CancelledError','KeyboardInterrupt','ChatCancelledError'}else'timed_out'if isinstance(exc,TimeoutError)else'failed'
        _safe(store.update,ident,state=state,ended=time.time(),error_kind=type(exc).__name__)
        _safe(monitor.event,'outcome',ident=ident+':outcome',tool=name,**(request.metadata if request else owner),attempt_id=ident,state=state,
            error_kind='cancelled'if state=='cancelled'else'timeout'if state=='timed_out'else'adapter_error',duration_ms=round((time.monotonic()-started)*1000))
        raise
    else:
        kind=tool_result_state(result)
        _safe(store.update,ident,state=kind,ended=time.time(),result_kind=kind)
        values=dict(attempt_id=ident,state=kind,duration_ms=round((time.monotonic()-started)*1000))
        if kind in {'failed','unknown','cancelled','timed_out'}:values['error_kind']={'failed':'business_failure','unknown':'unknown_operation','cancelled':'cancelled','timed_out':'timeout'}[kind]
        _safe(monitor.event,'outcome',ident=ident+':outcome',tool=name,**(request.metadata if request else owner),**values)
        return result
    finally:_LAST.set(prior)
