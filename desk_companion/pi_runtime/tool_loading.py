"""Application-side discovery over the current authorized Pi tool catalog.

Definitions are immutable within an execution; changes get new content versions.
Completions gateways receive the full currently loaded prefix each request. This
does not claim native tool_search, allowed_tools or provider cache support.
"""
from desk_companion.observability.tool_monitor import ToolMonitor,fingerprint

SEARCH='tebb_tools_search'
LOAD='tebb_tools_load'
META=[dict(name=SEARCH,description='在本任务已授权工具目录内搜索工具。只返回定义摘要，不执行工具；需要时再加载。',
           parameters=dict(type='object',properties=dict(query=dict(type='string',maxLength=200)),required=['query'],additionalProperties=False)),
      dict(name=LOAD,description='按名称加载已授权工具定义，下轮请求开始可用。加载不执行操作、不授予新权限。',
           parameters=dict(type='object',properties=dict(names=dict(type='array',items=dict(type='string'),minItems=1,maxItems=20)),required=['names'],additionalProperties=False))]
# Control tools cannot be hidden behind discovery: clarification, delegation and
# final delivery remain available even when no external tool is needed.
BASIC={'request_clarification','start_background_task','submit_plan','submit_deliverable',
       'request_user_input','get_current_time'}


class ToolLoading:
    def __init__(self, specs, *, session, root='', task='', store=None):
        self.store=store or ToolMonitor(); self.owner=dict(session=session,root=root,task=task)
        self.definitions=self.store.register(specs)
        self.catalog={d['name']:d for d in self.definitions}
        if {SEARCH,LOAD}&self.catalog.keys(): raise ValueError('工具名与发现入口冲突。')
        self.store.register(META)
        self.loaded=[]
        # Restore order only for versions that are still authorized in this run.
        # Never restore an old permission merely because a session once loaded it.
        after=0
        while True:
            page=self.store.events(session=session,after=after,limit=10000)
            for event in page:
                name=event['tool']
                if event['phase']=='load' and name in self.catalog and event.get('definition_version')==self.catalog[name]['version'] and name not in self.loaded:
                    self.loaded.append(name)
            if len(page)<10000:break
            after=page[-1]['seq']
        for name in self.catalog:
            if name in BASIC and name not in self.loaded: self.loaded.append(name)
        for definition in self.definitions:
            self.store.event('catalog',ident='catalog:'+fingerprint([self.owner,definition['version']]),tool=definition['name'],**self.owner,
                definition_version=definition['version'],definition_authorized=True,registered=True,available=None,connection_configured=None,
                loaded=definition['name']in self.loaded,state='registered',protocol='application_discovery_completions')
        for i,name in enumerate(self.loaded): self._loaded(name,'initial',i)

    def _loaded(self,name,trigger,position):
        self.store.event('load',tool=name,**self.owner,definition_version=self.catalog[name]['version'],
                         trigger_call=trigger,position=position,state='loaded',protocol='application_discovery_completions')

    def specs(self, all_tools=False):
        names=list(self.catalog) if all_tools else self.loaded
        return META+[{k:self.catalog[name][k] for k in ('name','description','parameters')} for name in names]

    def execute(self, name, args, call_id):
        if not isinstance(args,dict):raise ValueError('工具发现与加载参数须为对象。')
        if name==SEARCH:
            if set(args)!={'query'} or not isinstance(args['query'],str) or len(args['query'])>200: raise ValueError('搜索参数无效。')
            query=args['query'].casefold()
            found=[d for d in self.definitions if query in (d['name']+' '+d['description']+' '+d['collection']).casefold()][:30]
            self.store.event('discovery',tool=SEARCH,**self.owner,trigger_call=call_id,state='returned')
            return dict(ok=True,tools=[{k:d[k] for k in ('name','description','collection','version')} for d in found],
                        loaded=list(self.loaded),scope='currently_authorized',protocol='application_discovery_completions')
        names=args.get('names')
        if set(args)!={'names'} or not isinstance(names,list) or not 1<=len(names)<=20 or any(not isinstance(n,str)or n not in self.catalog for n in names):
            raise ValueError('只能加载本任务当前授权目录中的工具。')
        for item in names:
            if item not in self.loaded:
                self.loaded.append(item); self._loaded(item,call_id,len(self.loaded)-1)
        return dict(ok=True,loaded=list(self.loaded),versions={n:self.catalog[n]['version']for n in self.loaded},effective='next_model_request',permission_expanded=False)
