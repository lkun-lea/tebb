"""Product, Skill and configured MCP adapters for the tebb execution loop."""
import hashlib

from desk_companion.local_api.worker_rpc import call


def work_item_request_id(run_id, call_id):
    return 'tebb-work-' + hashlib.sha256(f'{run_id}:{call_id}'.encode()).hexdigest()[:50]


def local_calendar_spec(workspace_path):
    """A separate local-only capability, independent of OS Feishu credentials."""
    def query(arguments):
        from desk_companion.planning.work_board import WorkBoardService
        from desk_companion.planning.scheduling import SchedulingService
        return SchedulingService(WorkBoardService(path=workspace_path)).local.query(arguments.get('day'))
    return dict(type='function', function=dict(name='read_local_calendar',
        description='按北京时间日期读取已保存的本地日程及同步快照。不会读取飞书实时日历、刷新远端或修改日程。最多返回100项，truncated为true时不能称列出全部。',
        parameters=dict(type='object', properties={'day':dict(type='string',description='明确日期 YYYY-MM-DD')},
                        required=['day'], additionalProperties=False)), implementation=query, read_only=True)


def specs(request):
    run_id=request['collab_run']
    def spec(name,description,properties,required,implementation,readonly=True):
        return dict(type='function',function=dict(name=name,description=description,parameters=dict(type='object',properties=properties,required=required)),implementation=implementation,read_only=readonly)
    def product(name,args):
        return call('tebb_operation',dict(run_id=run_id,tool=name,args=args))

    def work_item(name, args):
        args = {**args, '_task_id': request['task_id']}
        call_id = args.get('_call_id')
        try:
            return product(name, args)
        except Exception:
            if name != 'work_item_move' or not call_id:
                raise
            return dict(ok=False, change_state='unconfirmed', request_id=work_item_request_id(run_id, call_id),
                        error='未收到事项操作回执。请用 work_item_query 按原操作编号核对。')

    from desk_companion.planning.work_items import STATES
    string=dict(type='string')
    out=[
        spec('work_item_query', '读取当前项目（未选项目时为未归属）的事项状态。可按标题、事项ID或原操作编号查，最多50项。重名先确认。回执为空表示结果仍待核对。',
             dict(query=string,item_id=string,request_id=string),[],lambda args:work_item('work_item_query',args)),
        spec('work_item_move', '用户明确要求时修改一件事项的状态。先用 work_item_query 获取唯一ID和当前版本。版本冲突先读最新状态，结果未知按原编号核对，勿重放。待办=todo、进行中=doing、待验收=review、已完成=done。',
             dict(item_id=string,version=dict(type='integer',minimum=1),state=dict(type='string',enum=list(STATES))),
             ['item_id','version','state'],lambda args:work_item('work_item_move',args),False),
        spec('calendar_query','查询指定北京时间日期或月份的本地及飞书日程。month=true读取该月；query可按标题过滤。先查再按准确身份修改，重名或意图不明先询问用户。',dict(day=string,month=dict(type='boolean'),query=string,request_id=string),['day'],lambda args:product('calendar_query',args)),
        spec('calendar_change','修改已保存日程，action.type=update/sync/retime/delete/resolve_delete。新建必须使用calendar_propose，由用户在界面明确保存。更新传local_id/version；改期传calendar_id/event_id/day/original_start/original_end/start/end，改标题同时传summary和original_summary（已同步必须用此入口）；删除传calendar_id/event_id与原时间（本地另传version）。操作编号由本轮call_id自动登记，失败先核对，不自动重做。',dict(action=dict(type='object')),['action'],lambda args:product('calendar_change',args),False),
        spec('automation_list','读取本地自动化规则、状态及上次执行。',{},[],lambda args:product('automation_list',args)),
        spec('automation_save','只维护原有tebb_task目标规则；可视化工作流用workflow_save保存草稿，不能经此工具启用工作流发布或定时。payload含name/action=tebb_task/goal/project_id/agent_id默认tebb/enabled/cadence=once|daily|weekly/hour/minute/weekdays(周一0至周日6)/date(一次时YYYY-MM-DD)/doc空；修改已有规则须带id。缺目标或时间先问，不得擅自扩大目标。后台运行时触发。',dict(payload=dict(type='object')),['payload'],lambda args:product('automation_save',args),False),
        spec('automation_manage','明确删除或立即执行原有规则（工作流计划须在界面管理）：action=delete|run|check,job_id。先读取精确规则身份。',dict(action=dict(type='string',enum=['delete','run','check']),job_id=string),['action','job_id'],lambda args:product('automation_manage',args),False),
    ]
    from desk_companion.chat.assistant import LIST_SKILLS_SPEC, READ_SKILL_SPEC, REMEMBER_SPEC, FORGET_SPEC, STATUS_SPEC, ROADMAP_SPEC, RECENT_SPEC, REPOSITORY_SPEC, ERROR_LOG_SPEC, AGENDA_SPEC, TASKS_SPEC
    from desk_companion.content.video.tools import specs as video_specs
    from desk_companion.memory.facts import bind_turn_user
    def bound(func):
        def invoke(args):
            from desk_companion.memory.memory_selection import bind_scope
            with bind_turn_user(request.get('objective',request['text'])), bind_scope(
                conversation=request.get('conversation',''),partner=request.get('role',{}).get('id',''),
                project=(request.get('workspace') or {}).get('project_id','')):
                return func(args)
        return invoke
    for item in (*video_specs(lambda:'collaboration-'+request.get('session_id',run_id),lambda status:None),LIST_SKILLS_SPEC,READ_SKILL_SPEC,REMEMBER_SPEC,FORGET_SPEC,STATUS_SPEC,ROADMAP_SPEC,RECENT_SPEC,REPOSITORY_SPEC,ERROR_LOG_SPEC,AGENDA_SPEC,TASKS_SPEC):
        out.append(dict(type='function',function={k:item[k] for k in ('name','description','parameters')},implementation=bound(item['func']),read_only=item.get('isReadOnly',True)))
    from desk_companion.integrations import mcp_client as mcp
    def catalog(args):
        servers=mcp.load_mcp_config()
        server=args.get('server')
        if not server:return dict(servers=list(servers))
        if server not in servers:raise ValueError('MCP服务未配置。')
        return dict(server=server,tools=mcp.list_tools(server,servers[server]))
    out.append(spec('mcp_catalog','发现已配置MCP服务器；提供server则读取该服务工具及参数。配置/凭据不返回。',dict(server=string),[],catalog))
    out.append(spec('mcp_call','按发现的服务/工具及其真实参数调用MCP，不猜工具名；失败不自动重试外部写入。',dict(server=string,tool=string,arguments=dict(type='object')),['server','tool','arguments'],lambda args:mcp.call_mcp_tool(args['server'],args['tool'],args['arguments']),False))
    return out
