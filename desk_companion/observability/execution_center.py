"""Read-only projections of owner state and actual model/tool observations.

An edge means recorded containment or an observed model→tool link. Chronological
adjacency is only a timeline and must never be presented as a causal dependency.
"""
from collections import Counter, defaultdict
import time
import math

from desk_companion.observability.usage_store import UsageStore
from desk_companion.observability.usage_sources import task_metadata
from desk_companion.observability.tool_monitor import ToolMonitor


def valid_filters(filters):
    allowed={'kind','root','task','session','tool','collection','model','agent','role','purpose','configuration_version','code_version','state','channel','since','until'}
    if not isinstance(filters,dict) or set(filters)-allowed: raise ValueError('执行筛选参数无效。')
    for key,value in filters.items():
        if key in {'since','until'}:
            if type(value) not in (int,float) or not 0<=value<=1e12: raise ValueError('执行时间范围无效。')
        elif not isinstance(value,str) or len(value)>512: raise ValueError('执行筛选值无效。')
    return filters


class UnlinkedTask(ValueError):
    """The physical task has no observed execution yet."""


class ExecutionCenter:
    def __init__(self, usage=None, tools=None, sources=None, owner_source=None,checks_source=None):
        self.usage=usage or UsageStore();self.tools=tools or ToolMonitor();self.sources=sources or (lambda:task_metadata(include_titles=True))
        from desk_companion.observability.execution_sources import owner_nodes
        self.owner_source=owner_source or owner_nodes
        from desk_companion.observability.execution_sources import task_checks
        self.checks_source=checks_source or task_checks

    def operate(self, operation, payload=None):
        payload={} if payload is None else payload
        if not isinstance(payload,dict): raise ValueError('执行查询参数无效。')
        if operation=='list': return self.list(**payload)
        if operation=='trace': return self.trace(**payload)
        if operation=='locate':
            try: return self.locate(**payload)
            except UnlinkedTask: return dict(ok=True, state='unlinked')
        if operation=='tools': return self.tool_query(**payload)
        if operation=='capabilities':
            return dict(ok=True,version=1,sdk=dict(pi='1.5.2',node='24.22.3'),
                current_transport='openai-completions',application_discovery='implemented',
                request_disabling='omit_definitions_and_revalidate_at_product_gate',
                native=dict(tool_choice_none='not_enabled_provider_verification_required',allowed_tools='not_enabled_in_current_adapter',
                    tool_search='not_enabled_in_current_adapter',defer_loading='not_enabled_in_current_adapter',developer_additional_tools='not_sent_by_current_completions_adapter'),
                history='replay_owned_matching_version_receipts; missing_receipts_declared_at_current_position',
                cache='current_loaded_tools_resent_in_order; only_provider_usage_is_measurement')
        raise ValueError('执行查询操作无效。')

    def locate(self, task):
        if not isinstance(task,str) or not 1<=len(task)<=512: raise ValueError('任务编号无效。')
        sources=self.sources()
        root=next((r['root'] for r in sources['attempts'] if r['id']==task and r.get('root')),None)
        if root is None:root=next((r['id'] for r in sources['tasks'] if r.get('attempt')==task),None)
        if root is None:root=next((r['root'] for r in self.usage.rows(task=task) if r.get('root')),None)
        if root is None:raise UnlinkedTask('该任务尚无已关联的执行记录。')
        return self.trace(root)

    def list(self, filters=None, offset=0, limit=50):
        filters=valid_filters(filters or {})
        if type(offset) is not int or offset<0 or type(limit) is not int or not 1<=limit<=200: raise ValueError('执行分页无效。')
        sources=self.sources();rows=self.usage.rows(filters.get('since',0),filters.get('until',time.time()))
        roots={r['id']:dict(r) for r in sources['tasks']}
        for row in rows:
            root=row.get('root')
            if root and root not in roots:
                roots[root]=dict(id=root,kind='task'if root.startswith(('task:','collab:','workflow:'))else'operation',state='unknown',created=row['started'],source=row.get('source'),channel=row.get('channel'),owner_missing=True,model=row.get('model'),purpose=row.get('purpose'))
        items=list(roots.values())
        for key in ('state','channel','kind'):
            if filters.get(key): items=[r for r in items if r.get(key)==filters[key]]
        if filters.get('root'): items=[r for r in items if filters['root'] in r['id']]
        for key in ('model','tool','task','session','agent','role','purpose','configuration_version','code_version'):
            if filters.get(key):
                matched={r.get('root')for r in rows if r.get(key)==filters[key]}
                items=[r for r in items if r['id']in matched]
        items=[r for r in items if filters.get('since',0)<=r['created']<filters.get('until',time.time())]
        items.sort(key=lambda r:(r['created'],r['id']),reverse=True)
        goals=[r for r in items if r['kind']=='task']
        checked=[r for r in goals if r.get('completion')in{'checked','assessed','incomplete'}and r.get('feedback_ok')is not None]
        return dict(ok=True,items=items[offset:offset+limit],total=len(items),next_offset=offset+limit if len(items)>offset+limit else None,
                    states=dict(Counter(r['state'] for r in items)),task_states=dict(Counter(r['state']for r in goals)),kinds=dict(Counter(r['kind']for r in items)),
                    acceptance=dict(passed=sum(bool(r['feedback_ok'])and r.get('completion')in{'checked','assessed'}for r in checked),known=len(checked),total=len(goals),unknown=len(goals)-len(checked)),version=1)

    def trace(self, root):
        if not isinstance(root,str) or not 1<=len(root)<=512: raise ValueError('根任务编号无效。')
        sources=self.sources();owner=next((r for r in sources['tasks'] if r['id']==root),None)
        records=self.usage.rows(root=root)
        attempts=[r for r in sources['attempts'] if r.get('root')==root]
        events=[];after=0
        while True:
            page=self.tools.events(root=root,after=after,limit=10000);events.extend(page)
            if len(page)<10000:break
            after=page[-1]['seq']
            if len(events)>100000: raise ValueError('执行图超过单次范围，请用工具事件分页查询。')
        if owner is None and not records and not events: raise ValueError('未找到执行记录。')
        if owner is None and records:
            first=min(records,key=lambda row:row['started'])
            owner=dict(state='unknown',owner_missing=True,created=first['started'],model=first.get('model'),purpose=first.get('purpose'))
        nodes={root:{'id':root,'kind':'task'if root.startswith(('task:','collab:','workflow:'))else'operation','label':root,**(owner or dict(state='unknown',owner_missing=True))}};edges=[]
        owned=self.owner_source(root)
        if owned.get("note_refs"): nodes[root]["note_refs"] = owned["note_refs"]
        nodes.update({n['id']:n for n in owned['nodes']});edges.extend(owned['edges'])
        def add(value,parent,relation):
            nodes[value['id']]=value
            if parent:edges.append(dict(id=parent+'>'+value['id'],source=parent,target=value['id'],relation=relation))
        for r in attempts:
            ident='physical:'+r['id']
            add({**r,'id':ident,'task':r['id'],'kind':'physical','label':r['id'],'started':r.get('started') or r['created']},owned['task_bindings'].get(r['id'],root),'budget_member')
        checks=self.checks_source([r['id']for r in attempts]);nodes.update({n['id']:n for n in checks['nodes']});edges.extend(checks['edges'])
        for r in sorted(records,key=lambda r:(r['started'],r['id'])):
            parent=r.get('parent_call') if r.get('parent_call') in {v['id'] for v in records} else 'physical:'+r.get('task','')
            if parent not in nodes and not any(v['id']==parent for v in records): parent=root
            state=r['state']
            task=next((a for a in attempts if a['id']==r.get('task')),None)
            if state=='running' and task and task['state'] in {'succeeded','failed','cancelled','timed_out','interrupted'}:state='unknown'
            if r.get('kind') == 'model' and state in {'failed','timed_out'} and r.get('debug_call'):
                from desk_companion.observability.agent_debug import load_timing
                timing = load_timing(r['debug_call'], directory=self.usage.path.parent / 'agent_debug')
                if timing:
                    r = {**r, 'network_spans': timing.get('spans', [])}
            add({**r,'state':state,'observed_state':r['state'],'label':r.get('tool')or r.get('model')or r['id']},parent,'model_tool'if r.get('parent_call')==parent else'contains')
        for e in events:
            parent=e.get('attempt_id') or e.get('parent_call') or e.get('trigger_call') or 'physical:'+e.get('task','')
            if parent not in nodes:parent=root
            add({**e,'id':'tool-event:'+e['id'],'kind':'tool_'+e['phase'],'started':e['ts'],'label':e['tool']+' · '+e['phase'],'state':e.get('state','recorded')},parent,'observation')
        timeline=sorted(nodes.values(),key=lambda n:(n.get('started')or n.get('created')or 0,n['id']))
        return dict(ok=True,root=root,nodes=list(nodes.values()),edges=edges,timeline=[n['id']for n in timeline],
                    acceptance=dict(state=(owner or{}).get('completion','unverified'),feedback_ok=(owner or{}).get('feedback_ok')),
                    coverage=dict(history_inferred=False,missing_fields=['prompt_version','skill_version','retrieval_version','code_version'],
                                  tool_payloads=False,business_state_owner='original_task_service'),version=1)

    def tool_query(self, filters=None, after=0, limit=100):
        filters=valid_filters(filters or {})
        if set(filters)-{'root','task','session','tool','collection','model','state','since','until'}:raise ValueError('工具查询不支持该筛选维度。')
        from desk_companion.planning.calendar_proposals import tool_spec, create_spec
        from desk_companion.integrations.feishu.feishu_tools import AGENDA_SPEC, TASKS_SPEC
        # 定义目录可在首次模型调用前浏览，调用记录仍按当前空间独立保存。
        self.tools.register([AGENDA_SPEC, TASKS_SPEC, tool_spec(), create_spec()])
        definitions=self.tools.definitions();versions={d['version']:d for d in definitions}
        by_name={d['name']:d for d in definitions}
        # Stats use the same filtered sequence as details, independently of paging.
        events=[];position=0
        while True:
            page=self.tools.events(root=filters.get('root'),session=filters.get('session'),after=position,limit=10000,
                filters={k:v for k,v in filters.items()if k in{'since','until','tool','task','model','state'}})
            events.extend(page)
            if len(page)<10000:break
            position=page[-1]['seq']
            if len(events)>100000:raise ValueError('工具记录超过单次统计范围，请指定根任务或会话。')
        def matches(e):
            for k in ('task','tool','model','state'):
                if filters.get(k) and e.get(k)!=filters[k]:return False
            if filters.get('collection') and versions.get(e.get('definition_version'),by_name.get(e['tool'],{})).get('collection')!=filters['collection']:return False
            return filters.get('since',0)<=e['ts']<filters.get('until',time.time())
        events=[e for e in events if matches(e)]
        if type(after) is not int or after<0 or type(limit) is not int or not 1<=limit<=200:raise ValueError('工具分页无效。')
        page=[e for e in events if e['seq']>after][:limit]
        per_tool=defaultdict(Counter)
        durations=defaultdict(list)
        last_error={}
        trend=defaultdict(lambda:[0]*12)
        start=filters.get('since',min((e['ts'] for e in events),default=0))
        end=filters.get('until',time.time())
        for e in events:
            name=e['tool']
            per_tool[name][e['phase']]+=1
            if e['phase']=='outcome':
                bucket=min(11,max(0,int((e['ts']-start)*12/max(1,end-start))))
                trend[name][bucket]+=1
            duration=e.get('duration_ms')
            if e['phase']=='outcome' and type(duration) in (int,float) and duration>=0:
                durations[name].append(duration)
            if e.get('error_kind'):
                last_error[name]={k:e.get(k) for k in ('id','root','ts','state','error_kind','error_message')}
            if e['phase'] in {'outcome','intercept'}:per_tool[e['tool']][e.get('state','unknown')]+=1
        timings={};scope_status={}
        for name in per_tool:
            values=sorted(durations[name])
            timings[name]=dict(samples=len(values),p50_ms=values[(len(values)-1)//2]if values else None,p95_ms=values[math.ceil(len(values)*.95)-1]if len(values)>=20 else None,
                latest_error=last_error.get(name),trend=trend[name])
        if filters.get('root')or filters.get('session'):
            for event in events:
                if event['phase']in{'catalog','load','offer'}:
                    value=scope_status.setdefault(event['tool'],{})
                    value.update({k:event[k]for k in ('registered','definition_authorized','connection_configured','available','loaded','definition_version')if k in event})
                    if event['phase']=='load':value['loaded']=True
                    if event['phase']=='offer':value['request_allowed_recorded']=True
        return dict(ok=True,definitions=definitions,items=page,stats={k:dict(v)for k,v in per_tool.items()},timings=timings,scope_status=scope_status,
                    filters=filters,collections=sorted({d['collection']for d in definitions}),
                    next_after=page[-1]['seq'] if page and any(e['seq']>page[-1]['seq']for e in events) else None,
                    authorization='historical_configuration_only_revalidated_at_execution',cost_attribution=None,version=1)
