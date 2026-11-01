"""Partner access to parent-owned, draft-only workflow authoring."""
TOOLS=frozenset({'workflow_catalog','workflow_load','workflow_save','capability_save','capability_load','capability_instantiate'})


def specs(request):
    from .worker_rpc import call
    from .workflow_graph import KINDS
    string=dict(type='string')
    position=dict(type='object',properties=dict(x=dict(type='number'),y=dict(type='number')),required=['x','y'],additionalProperties=False)
    node=dict(type='object',properties=dict(id=string,kind=dict(type='string',enum=list(KINDS)),config=dict(type='object',description='该kind在目录中的defaults配置对象；文字引用形如{{trigger.text}}。'),position=position,capability=dict(type='object')),required=['id','kind','config','position'],additionalProperties=False)
    edge=dict(type='object',properties=dict(source=string,target=string,branch=dict(type='string',enum=['','true','false'])),required=['source','target'],additionalProperties=False)
    fields={
        'workflow_catalog':({},[]),
        'workflow_load':(dict(id=string,version=string),['id']),
        'workflow_save':(dict(name=string,id=string,revision=dict(type='integer'),graph=dict(type='object',properties=dict(nodes=dict(type='array',items=node),edges=dict(type='array',items=edge)),required=['nodes','edges'],additionalProperties=False)),['name','graph']),
        'capability_save':(dict(name=string,id=string,revision=dict(type='integer'),kind=dict(type='string',enum=[k for k in KINDS if k!='trigger']),template=dict(type='object',description='适配器配置对象，字段同目录defaults。例如AI: {"prompt":"提取：{{input.text}}","model_id":""}；不能直接传字符串或将model_id放到payload顶层。'),parameters=dict(type='object',additionalProperties=string,description='参数名到文字默认值，例如{"text":""}。')),['name','kind','template','parameters']),
        'capability_load':(dict(id=string,version=string),['id']),
        'capability_instantiate':(dict(id=string,version=string,arguments=dict(type='object',additionalProperties=string),node_id=string,position=position),['id','arguments']),
    }
    descriptions={
        'workflow_catalog':'发现工作流原子适配器、输入默认值/输出/写入标记、用户声明式能力和示例。先发现再配置，不猜节点类型。',
        'workflow_load':'按id读取已保存工作流图和revision/version；修改前读取，结果不明先核对原ID。',
        'workflow_save':'保存可视化工作流草稿。payload含name、graph(nodes/edges)，更新须id/revision。需要恰有一个trigger、有效上游引用和完整固定目标；不启用定时、不执行节点或飞书写入。返回真实id/version后才可称搭建完成。',
        'capability_save':'创建/修改声明式原子能力。payload含name、kind(已注册适配器，非trigger)、template、parameters(参数名:文字默认值)，模板用{{input.参数}}；外部目标/模型身份须固定。更新带id/revision。只保存能力，不执行代码或外部写入。',
        'capability_load':'按id、可选version读取可复用能力定义。旧版本不随编辑变化。',
        'capability_instantiate':'按能力id/version及arguments生成普通节点，可选node_id和position。将返回节点放入workflow_save的graph；不执行能力。实际配置将冻结到图版本。',
    }
    return [dict(type='function',function=dict(name=name,description=description,parameters=dict(type='object',properties=dict(payload=dict(type='object',properties=fields[name][0],required=fields[name][1],additionalProperties=False)),required=['payload'],additionalProperties=False)),read_only=name not in {'workflow_save','capability_save'},implementation=lambda args,n=name:call('workflow_authoring',dict(run_id=request['collab_run'],task_id=request.get('task_id',''),tool=n,payload=args.get('payload',{}),call_id=args.get('_call_id','')))) for name,description in descriptions.items()]


def execute(host,run_id,tool,payload,call_id,task_id=''):
    import copy
    import uuid
    from .collaboration import transaction
    if tool not in TOOLS or not isinstance(payload,dict):raise ValueError('不支持的工作流草稿操作。')
    with host.collaboration.lock,transaction(host.collaboration.path) as (state,_):
        run=next((r for r in state['runs'] if r['id']==run_id),None)
        if not run or run.get('kind')!='task' or run['state'] not in {'running','queued'}:raise ValueError('原伙伴任务已结束或不在执行阶段，拒绝迟到操作。')
        config=run['agent_config']
        if run['agent']!='tebb' and '自动化工作流' not in config.get('tools',[]):raise ValueError('此伙伴未授予自动化工作流能力。')
        if not task_id or run.get('task')!=task_id:raise ValueError('工作流操作不属于当前实际任务阶段。')
    task=host.collaboration.managers['work'].get(task_id,False)
    if task.get('state')!='running' or task.get('channel')!='collaboration' or task.get('session')!='collab-'+run_id:raise ValueError('原任务已停止或工作进程身份不匹配。')
    payload=copy.deepcopy(payload)
    if tool in {'workflow_save','capability_save'}:
        if not isinstance(call_id,str) or not 1<=len(call_id)<=200:raise ValueError('缺少本轮工具调用编号。')
        operation=uuid.uuid5(uuid.NAMESPACE_URL,'tebb-authoring:'+run_id+':'+task_id+':'+call_id).hex
        if tool=='capability_save':payload['operation']=operation
        else:payload['operation_id']=operation;payload.setdefault('id','w'+operation)
    service=host.automation.workflows
    if tool=='workflow_catalog':
        result=service.operation('catalog')
        result.update(service.operation('templates'))
        result.update(definitions=service.store.definitions(),runs=service.store.runs())
        return result
    return service.operation({'workflow_load':'load','workflow_save':'save'}.get(tool,tool),payload)
