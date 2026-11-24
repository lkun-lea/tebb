"""Application-side discovery over the current authorized Pi tool catalog.

Definitions are immutable within an execution; changes get new content versions.
Completions gateways receive the full currently loaded prefix each request. This
does not claim native tool_search, allowed_tools or provider cache support.
"""
from desk_companion.observability.tool_monitor import ToolMonitor,fingerprint

from desk_companion.pi_runtime.tool_routing import ToolRouter, search_receipt, local_project_request

SEARCH='tebb_tools_search'
LOAD='tebb_tools_load'
META=[dict(name=SEARCH,description='在本任务已授权工具目录内搜索工具。按名称、用途或分类搜索。找到后用 tebb_tools_load 加载需要的工具。',
           parameters=dict(type='object',properties=dict(query=dict(type='string',maxLength=200)),required=['query'],additionalProperties=False)),
      dict(name=LOAD,description='按名称加载已授权工具定义，下轮请求开始可用。加载不执行操作、不授予新权限。',
           parameters=dict(type='object',properties=dict(names=dict(type='array',items=dict(type='string'),minItems=1,maxItems=20)),required=['names'],additionalProperties=False))]
CALL = 'tebb_tools_call'
CALL_SPEC = dict(name=CALL, description='调用已搜索到的工具。name 和 arguments 使用搜索回执中的定义。',
                 parameters=dict(type='object', properties=dict(name=dict(type='string'), arguments=dict(type='object',additionalProperties=True)),
                                 required=['name','arguments'], additionalProperties=False))
SEARCH_SPEC = {**META[0], 'description':'按需搜索本任务已授权工具。结果含参数定义，随后用 tebb_tools_call 执行。'}


class ToolLoading:
    def __init__(self, specs, *, session, root='', task='', store=None, user_input='', stable=False):
        self.stable = stable
        self.store=store or ToolMonitor(); self.owner=dict(session=session,root=root,task=task)
        self.definitions=self.store.register(specs)
        self.router=ToolRouter(self.definitions)
        self.catalog={d['name']:d for d in self.definitions}
        if {SEARCH,LOAD,CALL}&self.catalog.keys(): raise ValueError('工具名与发现入口冲突。')
        self.store.register([SEARCH_SPEC,CALL_SPEC] if stable else META)
        self.prefer_workspace = 'workspace_list' in self.catalog and local_project_request(user_input)
        from desk_companion.projects.workspace_source import overview_kind
        source_kind = overview_kind(user_input) if self.prefer_workspace else ''
        self.source_overview = bool(source_kind)
        self.implementation_overview = source_kind == 'implementation'
        self.source_guidance_sent = False
        self.misses = 0
        self.loaded=[]
        self.searched=False
        # Restore order only for versions that are still authorized in this run.
        # Never restore an old permission merely because a session once loaded it.
        after=0
        while not stable:
            page=self.store.events(session=session,after=after,limit=10000)
            for event in page:
                name=event['tool']
                if event['phase']=='discovery' and name==SEARCH:self.searched=True
                if event['phase']=='load' and name in self.catalog and event.get('definition_version')==self.catalog[name]['version'] and name not in self.loaded:
                    self.loaded.append(name)
            if len(page)<10000:break
            after=page[-1]['seq']
        for definition in self.definitions:
            self.store.event('catalog',ident='catalog:'+fingerprint([self.owner,definition['version']]),tool=definition['name'],**self.owner,
                definition_version=definition['version'],definition_authorized=True,registered=True,available=None,connection_configured=None,
                loaded=definition['name']in self.loaded,state='registered',protocol='application_discovery_completions')
        for i,name in enumerate(self.loaded): self._loaded(name,'initial',i)

    def _loaded(self,name,trigger,position):
        self.store.event('load',tool=name,**self.owner,definition_version=self.catalog[name]['version'],
                         trigger_call=trigger,position=position,state='loaded',protocol='application_discovery_completions')

    def specs(self, all_tools=False):
        if self.stable:
            return [SEARCH_SPEC,CALL_SPEC] if all_tools or self.searched else [SEARCH_SPEC]
        names=list(self.catalog) if all_tools else self.loaded
        controls=META if all_tools or self.searched or names else META[:1]
        return controls+[{k:self.catalog[name][k] for k in ('name','description','parameters')} for name in names]

    def execute(self, name, args, call_id):
        if not isinstance(args,dict):raise ValueError('工具发现与加载参数须为对象。')
        if name==SEARCH:
            if set(args)!={'query'} or not isinstance(args['query'],str) or len(args['query'])>200: raise ValueError('搜索参数无效。')
            self.searched=True
            found=self.router.search(args['query'], prefer_workspace=self.prefer_workspace)
            if (self.stable and self.prefer_workspace and 'workspace_read_symbol' in self.catalog
                    and args['query'].strip() != 'workspace_read'):
                # A mixed navigation query needs the ranged reader alongside search/list.
                found = [self.catalog['workspace_read_symbol'] if d['name']=='workspace_read' else d for d in found]
                found = list({d['name']:d for d in found}.values())
                names = {d['name'] for d in found}
                if names == {'workspace_list','workspace_read_symbol'} and 'workspace_search' in self.catalog:
                    found.append(self.catalog['workspace_search'])
                if self.source_overview and {'workspace_list', 'workspace_read_symbol', 'workspace_search'} == {d['name'] for d in found}:
                    found = [self.catalog['workspace_read_symbol'], self.catalog['workspace_search']]
            self.misses = 0 if found else self.misses + 1
            self.store.event('discovery',tool=SEARCH,**self.owner,trigger_call=call_id,state='returned')
            receipt = search_receipt(found)
            if not found:
                receipt.update(reason='no_tool_match', next_action=(
                    '换一种简短的动作和对象表述，再搜一次。' if self.misses == 1 else
                    '已尝试改述；说明当前工具范围的缺口，目标不清时询问用户。'))
            elif self.prefer_workspace and {'workspace_search','workspace_read_symbol'} <= self.catalog.keys():
                from desk_companion.projects.workspace_source import SOURCE_REVIEW_GUIDE
                receipt['next_action'] = '复用已发现工具，独立操作可同轮提交。'
                if self.source_overview and not self.source_guidance_sent and any(d['name'].startswith('workspace_') for d in found):
                    self.source_guidance_sent = True
                    focus = ('解释实现时，结合本项目代表性控制流与状态如何初始化，按行读到对应函数体。'
                             if self.implementation_overview else '架构概览以项目文档说明模块职责，用一个核心源码实例说明协作。证据足够就作答。')
                    receipt['next_action'] += SOURCE_REVIEW_GUIDE + focus
            elif self.prefer_workspace and found[0]['name'] == 'workspace_list':
                receipt['next_action'] = '从已绑定本地根目录开始（path 为空）；解释实现时引用实际读到的源码。描述包依赖时核对包清单或 import，构建顺序只说明构建顺序。'
            if self.stable:
                for row in receipt['tools']:
                    item=self.catalog[row['name']]
                    row['parameters']=item['parameters']
                    if row['name'] not in self.loaded:
                        self.loaded.append(row['name'])
                        self._loaded(row['name'],call_id,len(self.loaded)-1)
            return receipt
        names=args.get('names')
        if set(args)!={'names'} or not isinstance(names,list) or not 1<=len(names)<=20 or any(not isinstance(n,str)or n not in self.catalog for n in names):
            raise ValueError('只能加载本任务当前授权目录中的工具。')
        for item in names:
            if item not in self.loaded:
                self.loaded.append(item); self._loaded(item,call_id,len(self.loaded)-1)
        return dict(ok=True,loaded=list(self.loaded),versions={n:self.catalog[n]['version']for n in self.loaded},effective='next_model_request',permission_expanded=False)
