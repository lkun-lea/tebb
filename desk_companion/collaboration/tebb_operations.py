"""Parent-owned capability dispatch for an actual active tebb run."""
import hashlib
import copy
from desk_companion.collaboration.store import transaction
from desk_companion.collaboration.service import ACTIVE
from desk_companion.collaboration.tebb_tools import work_item_request_id

def execute(host,run_id,tool,args):
    try:
        with host.collaboration.lock,transaction(host.collaboration.path) as (state,_):
            run=next((r for r in state['runs'] if r['id']==run_id),None)
            if not run or run['agent']!='tebb' or run['state'] not in ACTIVE or run['state']=='cancelling':
                raise ValueError('tebb执行已结束或身份不匹配。')
            if tool in {'work_item_query', 'work_item_move'} and (
                run['kind'] != 'task' or not run.get('task') or run['task'] != args.get('_task_id')
            ):
                raise ValueError('原事项工具调用所属的任务已结束或阶段不匹配。')
            project_id=run.get('workspace',{}).get('project_id','')
        args=copy.deepcopy(args)
        call_id=str(args.pop('_call_id',''))
        if tool=='connection_status':
            return host.bridge.connection_status(args['service'])
        if tool=='connection_authorize':
            service = args['service']
            if service == 'feishu':
                try:
                    result = host.bridge.feishu_login()
                except Exception:
                    return dict(ok=False,service=service,error='飞书授权未启动，请在设置的外部连接中检查状态。')
                return dict(ok=result.get('ok', False), service=service,
                            next_step='在官方授权页确认后，用 connection_status 核对账号状态。')
            if service == 'github':
                return host.bridge.github_account_dialog('login')
            directions = {'Bilibili':'设置 → 外部连接 → 哔哩哔哩，点击登录 / 扫码，完成后点击使用此登录态。',
                          'YouTube':'设置 → 外部连接 → YouTube，登录后点击使用此登录态。'}
            if service not in directions:
                raise ValueError('未知的外部服务')
            return dict(ok=True, service=service, state='needs_confirmation', next_step=directions[service])
        if tool=='work_item_query':
            return host.work_board.query_status(project_id, query=args.get('query', ''),
                                                item_id=args.get('item_id', ''), request_id=args.get('request_id', ''))
        if tool=='work_item_move':
            if not call_id:
                raise ValueError('缺少本轮事项工具调用编号。')
            return host.work_board.change(dict(type='move', id=args['item_id'], version=args['version'],
                                               state=args['state'], request_id=work_item_request_id(run_id, call_id)),
                                          project_id=project_id)
        if tool=='calendar_query':
            result=host.scheduling.load_month(args['day'],True,args.get('request_id','')) if args.get('month') else host.scheduling.load(args['day'],refresh=True,request_id=args.get('request_id',''))
            if args.get('query') and result.get('events'):
                result['events']=[e for e in result['events'] if args['query'].casefold() in e['summary'].casefold()]
            return result
        if tool in {'calendar_change','automation_save','automation_manage'} and not call_id:raise ValueError('缺少本轮工具调用编号。')
        if tool=='calendar_change':
            action=args['action'];action['request_id']='tebb-'+hashlib.sha256((run_id+':'+call_id).encode()).hexdigest()[:50]
            kind=action.get('type')
            if kind=='create':raise ValueError('创建安排请使用calendar_create；明确要求先预览时使用calendar_propose。')
            if kind in {'update','sync','resolve_delete'}:return host.scheduling.local.change(action)
            return host.scheduling.change(action)
        if tool in {'knowledge_sources', 'knowledge_rename'}:
            from desk_companion.knowledge import material_sources
            if tool == 'knowledge_rename':
                row = material_sources.rename(args['source_id'], project_id, args['revision'], args['title'])
                return dict(ok=True, source_id=row['id'], title=row['title'], revision=row['revision'])
            query = args.get('query', '').casefold()
            rows = [row for row in material_sources.listing(project_id) if query in row['title'].casefold()]
            return dict(ok=True, sources=[{k: row[k] for k in ('id','title','revision')} for row in rows[:50]],
                        truncated=len(rows) > 50)
        if tool=='automation_list':return host.automation.list_automation_jobs()
        if tool=='automation_save':
            payload=args['payload'];payload.setdefault('project_id',project_id);payload.setdefault('agent_id','tebb');payload.setdefault('doc','')
            payload['operation_id']='tebb-'+hashlib.sha256((run_id+':'+call_id).encode()).hexdigest()[:50]
            return host.automation.save_automation_job(payload,_from_agent=True)
        if tool=='automation_manage':
            if args['action']=='delete':return host.automation.delete_automation_job(args['job_id'],_from_agent=True)
            if args['action']=='run':return host.automation.run_automation_job(args['job_id'],'tebb-'+hashlib.sha256((run_id+':'+call_id).encode()).hexdigest()[:50],_from_agent=True)
            if args['action']=='check':return host.automation.check_agent_execution(args['job_id'])
        raise ValueError('不支持的tebb能力。')
    except Exception as exc:
        result = dict(ok=False,error=str(exc),stage='tebb_operation')
        if tool == 'work_item_move':
            result['change_state'] = 'not_changed'
        return result
