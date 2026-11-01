"""Local call inspection, shared-assembler preview and tool-free isolated trials."""
from contextlib import closing
import copy
import json
import sqlite3
import uuid

from . import agent_debug, facts, memory_selection
from .context_sources import digest, manifest


def run_revision(run):
    return digest({k:run.get(k) for k in ('input','agent_config','model_id','context','workspace','selection','members',
                                         'requested_strategy','requested_assignees','memory_snapshot','sampling','configuration_revision')})


def read_state(collaboration):
    # No scheduling, migrations, task creation or state write for local inspection.
    with collaboration.lock, closing(sqlite3.connect(collaboration.path.as_uri()+'?mode=ro',uri=True)) as db:
        return json.loads(db.execute('SELECT data FROM workspace WHERE id=1').fetchone()[0])


def chat_scope(state, conversation, agent_id=''):
    chat = next((c for c in state['conversations'] if c['id']==conversation),None)
    if chat is None:
        raise ValueError('会话不存在。')
    agent_id = agent_id or chat['coordinator']
    if agent_id not in chat['members'] and not any(r['conversation']==conversation and r['agent']==agent_id for r in state['runs']):
        raise ValueError('伙伴不属于当前会话。')
    agent = next(a for a in state['agents'] if a['id']==agent_id)
    return chat, agent, dict(conversation=conversation,project=chat.get('project_id',''),partner=agent_id)


def catalog(collaboration, conversation, agent_id=''):
    state=read_state(collaboration)
    chat, agent, scope=chat_scope(state,conversation,agent_id)
    return dict(ok=True, selection=memory_selection.select(scope,partner=agent),scope=scope,
                agents=[dict(id=a['id'],name=a['name']) for a in state['agents'] if a['id'] in chat['members']])


def edit(collaboration, conversation, action):
    state=read_state(collaboration)
    chat,agent,scope=chat_scope(state,conversation,action.get('agent_id',''))
    if str(action.get('id','')).startswith('partner:'):
        if action['id']!='partner:'+agent['id']:
            raise ValueError('伙伴归属不匹配。')
        if action.get('version')!=memory_selection.partner_version(agent):
            raise ValueError('伙伴偏好已变化，请重新读取。')
        text=agent.get('memory','') if action.get('type') in {'disable','revoke'} else action.get('text')
        # Collaboration remains the sole owner of partner configuration.
        collaboration.action(dict(type='partner_memory',conversation=conversation,agent_id=agent['id'],memory=text,
                                  expected_memory=agent.get('memory',''),expected_version=action.get('version'),
                                  memory_state={'disable':'disabled','revoke':'revoked'}.get(action.get('type'),'active'),request_id=action['operation']))
        return catalog(collaboration,conversation,agent['id'])
    kind=action.get('scope','user');owner=action.get('owner','')
    if kind!='user' and scope.get(kind)!=owner:
        raise ValueError('只能保存到当前会话、项目或伙伴。')
    if action.get('id'):
        row=next((i for i in facts.read_facts() if i['id']==action['id']),None)
        if row is None or row.get('scope','user')!='user' and scope.get(row['scope'])!=row.get('owner'):
            raise ValueError('记忆不属于当前范围。')
    facts.change(action,origin=dict(conversation=conversation))
    return catalog(collaboration,conversation,agent['id'])


def worker_request(collaboration, run):
    from .collaboration import call_budget, execution_limits
    from .sampling import TASK_DEFAULTS
    return dict(workflow='collaboration',collab_path=str(collaboration.path),collab_run=run['id'],conversation=run['conversation'],
        role=run['agent_config'],kind=run['kind'],model_id=run['model_id'],context=run['context'],workspace=run.get('workspace'),
        selection=run.get('selection',{}),memory_snapshot=run.get('memory_snapshot'),reference_time=run.get('created',0),
        configuration_revision=run.get('configuration_revision'),sampling=run.get('sampling') or dict(TASK_DEFAULTS),
        members=run.get('members',[]),requested_strategy=run.get('requested_strategy','auto'),
        requested_assignees=run.get('requested_assignees',[]),require_execution=run.get('require_execution',False),
        applied=run.get('applied',0),draft='',budget=call_budget(run['agent'],run['kind'],run['agent_config'].get('tools',())),
        objective=run['input'],parent_run=None,stage='collect',required_sources=[],source_topics=[],source_evidence=[],evidence=[],
        source_scope=run['id'],text=run['input'],task_id='',limits=execution_limits(run['agent'],run['agent_config'].get('tools',())))


def preview(collaboration, action):
    if not isinstance(action,dict) or action.get('type')!='send' or action.get('new_chat') or action.get('run'):
        raise ValueError('预览需要现有会话中的新消息。')
    state=read_state(collaboration)
    chat_scope(state,action.get('conversation',''))
    original=len(state['runs'])
    collaboration._apply(state,copy.deepcopy(action),dry_run=True)
    if len(state['runs'])!=original+1:
        raise ValueError('此次输入未组装为新的模型请求。')
    run=state['runs'][-1]
    request=worker_request(collaboration,run)
    from .collaboration_worker import _execute
    from .execution_context import prepare_request
    from . import model_catalog,model_capacity
    # The worker returns before its model/tool loop. No fake model completion.
    class AssemblyOnly:
        def chat(self,*args,**kwargs):
            raise RuntimeError('只读组装不能调用模型。')
    built=_execute(request,lambda *_:None,AssemblyOnly(),preview=True)
    model=model_catalog.require_item(run['model_id'])
    payload=dict(model=model['model'],messages=built['messages'])
    from .sampling import parse_sampling,TASK_DEFAULTS
    sampling=parse_sampling(run.get('sampling') or dict(TASK_DEFAULTS))
    payload.update({k:v for k,v in sampling.items() if k in {'temperature','top_p'}})
    payload['reasoning_effort']='low' if run['kind']=='route' else sampling.get('reasoning_effort','low')
    if built['tools']:payload['tools']=built['tools']
    capacity=model_capacity.for_call(model['id'],model['model'],model['base_url'].rstrip('/')+'/chat/completions')
    prepared,report=prepare_request(payload,capacity)
    return dict(ok=True,kind=run['kind'],request=prepared,sources=manifest(prepared['messages'],built['selection']),
                revision=run_revision(run),action=action,admission=report,
                model=dict(id=model['id'],model=model['model'],base_url=model['base_url']),
                note='真实组装器的下一次首调用；工具结果、后续路由尚未知。采样/输出上限由发送时的任务预算准入。')


def trial_material(collaboration, conversation, call_id, overrides=None):
    from .context_inspector import inspect
    checked=inspect(collaboration,conversation,call_id)
    detail=checked.get('detail')
    if detail is None or not detail.get('request'):
        raise ValueError('调用快照缺失，不能创建试验。')
    sources=detail.get('meta',{}).get('sources',{})
    payload=copy.deepcopy(detail['request'])
    overrides=overrides or {}
    if not isinstance(overrides,dict) or len(overrides)>100:
        raise ValueError('试验覆盖内容无效。')
    from .context_sources import experiment
    payload['messages'],trial_selection,diffs=experiment(payload['messages'],sources,overrides)
    payload.pop('tools',None)
    payload.pop('tool_choice',None)
    from .context_sources import Message
    payload['messages'].append(Message(dict(role='system',content='这是独立的记忆调试试验；未登记任何执行工具，不进行外部操作。仅根据可观察输入回答，不能声称真实任务已执行。'),'trial'))
    from .model_catalog import require_item
    model=require_item(checked['model_id'])
    # Copy observable inputs, not transport-only IDs or stale generation caps.
    # The existing adapter and task admission own effective transport parameters.
    payload={k:v for k,v in payload.items() if k in {'model','messages','temperature','top_p','reasoning_effort'}}
    payload['model']=model['model']
    target=dict(id=model['id'],model=model['model'],base_url=model['base_url'])
    from .execution_context import configuration_revision
    material=dict(request=payload,diffs=diffs,target=target,original_call=call_id,sources=manifest(payload['messages'],trial_selection),configuration_revision=configuration_revision(model))
    return dict(ok=True,**material,revision=digest(material),limits=dict(model_calls=1,tool_calls=0,time_seconds=90),
                note='仅本地组装。保留输入及采样参数；有效输出上限由试验预算准入。明确试跑后发送到所示模型；不登记工具、不写回会话或记忆。')


def execute_trial(request,emit):
    from .collaboration_llm import CollaborationLLM
    from .model_catalog import require_item
    model=require_item(request['model_id'])
    if digest({k:model[k] for k in ('id','model','base_url')})!=request['target_revision']:
        raise ValueError('模型路由已变化，未发送。')
    emit('status','独立记忆试验：一次模型调用，未登记工具。')
    import time
    started=time.monotonic()
    emit('llm_start',dict(model=model['model'],turn=1,phase='memory_trial'))
    try:
        with CollaborationLLM(model,request.get('sampling',{}),min(60,request['limits']['call_timeout']),purpose='memory_trial',expected_configuration_revision=request.get('configuration_revision')) as llm:
            from .context_sources import restore
            llm.on_reasoning=lambda _:emit('llm_progress',True)
            llm.on_progress=lambda:emit('llm_progress',True)
            result=llm.chat(restore(request['trial_messages'],request.get('trial_assembly')),tools=None,on_delta=lambda text:emit('token',text))
    finally:
        emit('llm_end',dict(phase='memory_trial',duration_ms=int((time.monotonic()-started)*1000)))
    calls=result.get('message',{}).get('tool_calls') or []
    emit('memory_trial',dict(unexpected_tool_calls=calls,usage=result.get('usage'),applied=False,original_call=request['original_call']))
    if calls:
        emit('failure',dict(type='UnexpectedToolCalls',message='试验返回未登记工具调用，未执行，未按已完成处理。'))
        return
    emit('result',result.get('message',{}).get('content') or '模型未返回正文。')


def operate(collaboration,tasks,conversation,action):
    if not isinstance(action,dict):
        raise ValueError('调试操作须为对象。')
    kind=action.get('type','catalog')
    if kind=='catalog':
        return catalog(collaboration,conversation,action.get('agent_id',''))
    if kind=='edit':
        return edit(collaboration,conversation,action['change'])
    if kind=='preview':
        return preview(collaboration,dict(action['send'],conversation=conversation,type='send'))
    if kind=='send_preview':
        send=dict(action['send'],conversation=conversation,type='send',preview_revision=action['revision'])
        return collaboration.action(send)
    if kind in {'trial_prepare','trial_run'}:
        material=trial_material(collaboration,conversation,action.get('call_id',''),action.get('overrides'))
        if kind=='trial_prepare':
            return material
        if material['revision']!=action.get('revision'):
            raise ValueError('试验输入或目标模型已变化，请重新组装核对。')
        operation=agent_debug.valid_id(action.get('operation'))
        ident=tasks().submit('记忆独立试验 '+material['revision'],'memory-trial-'+conversation,'debug',
            workflow='memory_trial',kind='memory_trial',model_id=material['target']['id'],trial_messages=material['request']['messages'],trial_assembly=material['sources'],configuration_revision=material['configuration_revision'],
            sampling={k:v for k,v in material['request'].items() if k in {'temperature','top_p','reasoning_effort'}},
            target_revision=digest(material['target']),original_call=material['original_call'],
            submission_key='memory-trial:'+operation,task_limits=dict(call_timeout=60,task_timeout=90),auto_video_archive=False)
        return dict(ok=True,task_id=ident,revision=material['revision'])
    if kind in {'trial_status','trial_cancel'}:
        tasks=tasks()
        from .tasks import submission_task_id
        ident=action.get('task_id') or submission_task_id('memory-trial:'+agent_debug.valid_id(action.get('operation')))
        task=tasks.get(ident)
        if task['session']!='memory-trial-'+conversation:
            raise ValueError('试验不属于当前会话。')
        if kind=='trial_cancel':
            tasks.cancel(task['id'])
        task=tasks.get(task['id'])
        task['memory_calls']=[]
        for call in agent_debug.listing(task_id=task['id'])['items']:
            try:
                detail=agent_debug.detail(call['id'])
                task['memory_calls'].append(dict(id=call['id'],request_raw=detail['request_raw'],sources=detail.get('meta',{}).get('sources')))
            except FileNotFoundError:
                task['memory_calls'].append(dict(id=call['id'],missing=True))
        return dict(ok=True,task=task)
    if kind=='cleanup_preview':
        return cleanup_preview(collaboration,conversation,action.get('id',''))
    if kind=='cleanup_apply':
        return cleanup_apply(collaboration,conversation,action)
    if kind=='open_source':
        state=read_state(collaboration)
        chat_scope(state,conversation)
        if action.get('call_id'):
            from .context_inspector import inspect
            detail=inspect(collaboration,conversation,action['call_id']).get('detail') or {}
            selection=detail.get('meta',{}).get('sources',{}).get('selection') or {}
        else:selection=catalog(collaboration,conversation)['selection']
        item=next((i for i in [*selection.get('selected',[]),*selection.get('excluded',[])] if i['id']==action.get('id')),None)
        target=(item or {}).get('source',{}).get('conversation')
        if not target or not any(c['id']==target for c in state['conversations']):
            raise ValueError('原来源会话未记录或已不可用。')
        return collaboration.action(dict(type='select',conversation=target,request_id=uuid.uuid4().hex))
    raise ValueError('未知记忆调试操作。')


def cleanup_preview(collaboration,conversation,ident):
    """Explicit known copies; never claim semantic erasure or provider deletion."""
    state=read_state(collaboration)
    _,_,scope=chat_scope(state,conversation)
    row=next((i for i in facts.read_facts() if i['id']==ident),None)
    if row is None:
        raise ValueError('记忆已不存在。')
    if row.get('scope','user')!='user' and scope.get(row['scope'])!=row.get('owner'):
        raise ValueError('记忆不属于当前范围。')
    calls=[]
    artifacts=[]
    unknown=[]
    for path in agent_debug.root().glob('*.meta.json'):
        try:
            meta=json.loads(path.read_text('utf-8'))
        except (OSError,UnicodeError,json.JSONDecodeError):
            unknown.append(path.name.split('.')[0])
            continue
        selection=meta.get('sources',{}).get('selection') or {}
        if any(i['id']==ident for i in selection.get('selected',[])):
            call=path.name.split('.')[0];agent_debug.valid_id(call);calls.append(call)
            with agent_debug.database() as db:
                record=db.execute('SELECT state FROM calls WHERE id=?',(call,)).fetchone()
            files=[]
            import hashlib
            for suffix in ('.request.json','.response.txt','.meta.json','.timing.json'):
                target=agent_debug.root()/(call+suffix)
                if target.is_file():
                    files.append(dict(suffix=suffix,sha256=hashlib.sha256(target.read_bytes()).hexdigest()))
            artifacts.append(dict(id=call,state=record['state'] if record else 'missing',files=files))
    revision=digest(dict(memory=row,artifacts=artifacts))
    return dict(ok=True,memory=row,known_calls=calls,artifacts=artifacts,revision=revision,unknown_call_metadata=unknown,conversation_summary=bool(next(c for c in state['conversations'] if c['id']==conversation).get('summary')),
                residuals=['记忆的旧版本','原聊天与手动摘要可能仍含同义内容，无法凭条目编号完整归因','任务输入/输出及未记录调用无法确认','服务商副本不受本机控制'],
                note='这是清理范围预览；尚未删除任何内容。停止使用后仍需分别处理相关会话、摘要和调用记录。')


def cleanup_apply(collaboration,conversation,action):
    from .resource_lock import ResourceLock
    results=[]
    with ResourceLock('memory-cleanup'):
        preview=cleanup_preview(collaboration,conversation,action.get('id',''))
        if preview['revision']!=action.get('revision'):
            raise ValueError('清理范围已变化，请重新预览；未删除。')
        selected=action.get('calls',[])
        if not isinstance(selected,list) or any(not isinstance(v,str) for v in selected) or not set(selected)<=set(preview['known_calls']):
            raise ValueError('只能清理预览内明确选择的本机调用。')
        if type(action.get('delete_source',False))is not bool:
            raise ValueError('来源清理须为明确开关。')
        for call in selected:
            artifact=next(a for a in preview['artifacts'] if a['id']==call)
            if artifact['state'] in {'sending','receiving'}:
                results.append(dict(id=call,state='skipped',reason='调用仍在进行，不删除'))
                continue
            for file in artifact['files']:
                target=agent_debug.root()/(call+file['suffix'])
                try:
                    target.unlink(missing_ok=True)
                    results.append(dict(id=call,part=file['suffix'],state='deleted'))
                except OSError as exc:
                    results.append(dict(id=call,part=file['suffix'],state='failed',reason=type(exc).__name__))
        if action.get('delete_source'):
            try:
                facts.erase_checked(preview['memory']['id'],preview['memory'].get('version',1))
                results.append(dict(id=preview['memory']['id'],state='deleted',part='source_and_versions'))
            except (OSError,ValueError) as exc:
                results.append(dict(id=preview['memory']['id'],state='failed',reason=str(exc)))
    return dict(ok=True,results=results,residuals=preview['residuals'],
                note='仅清理所选本机副本。原聊天、摘要、任务及服务商副本未被本操作删除。调用索引保留缺失状态。')
