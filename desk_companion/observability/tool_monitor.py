"""Durable tool definitions and lifecycle metadata, without arguments or result bodies.

The registry is evidence of configuration, never an authorization service. A running
adapter must still check its current request, task permissions and budget.
"""
from contextlib import closing
from contextvars import ContextVar
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import time
import uuid

from desk_companion.infrastructure.paths import data_root

_REQUEST = ContextVar('observed_tool_request', default=None)
PHASES = {'catalog', 'discovery', 'load', 'definition_effective', 'offer', 'request', 'intercept', 'attempt', 'outcome'}


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def safe_error(kind):
    """Only a controlled category leaves the private call inspector.

    Raw exceptions often contain arguments, signed URLs or echoed credentials. A
    replacement summary is preferable to a best-effort regex over those bodies.
    """
    return {'invalid_arguments': '参数未通过校验。', 'not_allowed': '工具未获本轮授权。',
            'budget_denied': '任务预算不足，工具未执行。', 'cancelled': '任务已取消。',
            'business_failure': '工具回执报告业务失败，请核对原操作。',
            'unknown_operation': '原操作结果未知，请按原编号核对。',
            'adapter_error': '工具适配器执行失败，请查看原调用。', 'timeout':'工具调用超时，请核对原操作状态。',
            'sdk_validation': 'SDK 拒绝工具参数或工具名称。'}.get(kind, '工具未完成，请查看原调用。')


def collection(name):
    if name in {'get_today_agenda','list_feishu_tasks','get_feishu_tasks'}:return '飞书'
    for prefix, label in [('project_', '项目环境'), ('workspace_', '工作区'), ('workflow_', '工作流'),
                          ('calendar_', '日程'), ('memory_', '记忆'), ('feishu_', '飞书'),
                          ('github_', 'GitHub'), ('web_', '网络资料'), ('tebb_tools_', '工具发现')]:
        if name.startswith(prefix): return label
    return '产品工具'


def tool_result_state(result):
    value=result
    if isinstance(value,str):
        try:value=json.loads(value)
        except (ValueError,TypeError):return 'returned'
    if not isinstance(value,dict):return 'returned'
    state='failed'if value.get('ok')is False or value.get('success')is False else'returned'
    operation=value.get('operation')
    actual=(operation.get('state')if isinstance(operation,dict)else None)or value.get('state')
    if isinstance(actual,str)and actual in {'unknown','failed','timed_out','cancelled'}:state=actual
    if state=='returned'and value.get('cache_hit')is True:state='cached'
    if state=='returned'and value.get('replayed')is True:state='replayed'
    return state


class ToolMonitor:
    def __init__(self, path=None):
        self.path = Path(path or data_root() / 'memory/tool-observations.sqlite3')

    def _db(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('CREATE TABLE IF NOT EXISTS definitions(version TEXT PRIMARY KEY,name TEXT,collection TEXT,data TEXT)')
        db.execute('CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT UNIQUE,ts REAL,session TEXT,root TEXT,task TEXT,phase TEXT,tool TEXT,data TEXT)')
        db.execute('CREATE INDEX IF NOT EXISTS tool_events_root ON events(root,seq)')
        db.execute('CREATE INDEX IF NOT EXISTS tool_events_session ON events(session,seq)')
        return db

    def register(self, specs, *, source='product'):
        result = []
        for spec in specs:
            fn = spec.get('function', spec)
            # Keep only protocol definitions, never Python implementations or credentials.
            value = {k: fn[k] for k in ('name', 'description', 'parameters')}
            if not re.fullmatch(r'[a-zA-Z0-9_-]{1,128}', value['name']): raise ValueError('工具名称无效。')
            value.update(source=source, collection=collection(value['name']))
            value['version'] = fingerprint(value)
            result.append(value)
        with closing(self._db()) as db, db:
            for value in result:
                db.execute('INSERT OR IGNORE INTO definitions VALUES(?,?,?,?)',
                           (value['version'], value['name'], value['collection'], json.dumps(value, ensure_ascii=False)))
        return result

    def event(self, phase, *, ident=None, tool='', session='', root='', task='', **metadata):
        if phase not in PHASES: raise ValueError('工具阶段无效。')
        allowed = {'definition_version', 'trigger_call', 'position', 'state', 'error_kind', 'attempt_id',
                   'parent_call', 'model', 'loaded', 'protocol', 'duration_ms', 'retry_of', 'effective_turn',
                   'definition_authorized','registered','available','connection_configured'}
        if set(metadata) - allowed: raise ValueError('工具观测只允许安全元数据。')
        if 'error_kind' in metadata: metadata['error_message'] = safe_error(metadata['error_kind'])
        ident = ident or uuid.uuid4().hex
        value = dict(id=ident, ts=time.time(), session=session, root=root, task=task, phase=phase, tool=tool, **metadata)
        with closing(self._db()) as db, db:
            old = db.execute('SELECT root,task,session,phase,tool FROM events WHERE id=?', (ident,)).fetchone()
            if old:
                if tuple(old) != (root,task,session,phase,tool): raise ValueError('工具事件编号已绑定。')
                return ident
            db.execute('INSERT INTO events(id,ts,session,root,task,phase,tool,data) VALUES(?,?,?,?,?,?,?,?)',
                       (ident,value['ts'],session,root,task,phase,tool,json.dumps(value,ensure_ascii=False,allow_nan=False)))
        return ident

    def events(self, *, root=None, session=None, after=0, limit=1000,filters=None):
        if type(after) is not int or after < 0 or type(limit) is not int or not 1 <= limit <= 10000: raise ValueError('工具分页无效。')
        if not self.path.exists(): return []
        clauses=['seq>?']; args=[after]
        for name, value in [('root',root), ('session',session)]:
            if value is not None: clauses.append(name+'=?'); args.append(value)
        filters=filters or{}
        if set(filters)-{'since','until','tool','task','model','state'}:raise ValueError('工具筛选无效。')
        for key,value in filters.items():
            if key in {'since','until'}:clauses.append('ts'+('>=?'if key=='since'else'<?'));args.append(value)
            elif key in {'tool','task'}:clauses.append(key+'=?');args.append(value)
            else:clauses.append("json_extract(data,'$."+key+"')=?");args.append(value)
        with closing(self._db()) as db:
            rows=db.execute('SELECT seq,data FROM events WHERE '+' AND '.join(clauses)+' ORDER BY seq LIMIT ?', (*args,limit)).fetchall()
        return [dict(json.loads(r['data']), seq=r['seq']) for r in rows]

    def definitions(self):
        if not self.path.exists(): return []
        with closing(self._db()) as db:
            return [json.loads(r[0]) for r in db.execute('SELECT data FROM definitions ORDER BY collection,name,rowid')]

    def get_event(self,ident):
        if not isinstance(ident,str)or not 1<=len(ident)<=512:raise ValueError('工具事件编号无效。')
        if not self.path.exists():raise ValueError('工具事件不存在。')
        with closing(self._db())as db:row=db.execute('SELECT data FROM events WHERE id=?',(ident,)).fetchone()
        if not row:raise ValueError('工具事件不存在。')
        return json.loads(row[0])


class ToolRequest:
    """Correlate a requested call, admission and the actual adapter attempt."""
    def __init__(self, name, *, ident=None, store=None, metadata=None):
        self.name=name if isinstance(name,str)and re.fullmatch(r'[a-zA-Z0-9_-]{1,128}',name)else'invalid_tool_name'
        self.id='tool-request:'+fingerprint(ident)if ident else uuid.uuid4().hex; self.store=store or ToolMonitor()
        if metadata is None:
            from desk_companion.observability.usage_observer import _metadata
            from desk_companion.observability.agent_debug import metadata as debug_metadata
            scope=_metadata(); metadata={k:scope.get(k,'') for k in ('root','task')}
            metadata['session']=debug_metadata().get('session','')
        self.metadata=metadata; self.admitted=False; self.rejected=False

    def emit(self, phase, **values):
        from desk_companion.observability.usage_observer import _safe
        return _safe(self.store.event,phase,ident=self.id+':'+phase,tool=self.name,**self.metadata,**values)

    def __enter__(self):
        self.emit('request'); self.token=_REQUEST.set(self); return self

    def reject(self, kind):
        self.rejected=True; self.emit('intercept',state='cancelled'if kind=='cancelled'else'rejected',error_kind=kind)

    def __exit__(self, kind, exc, tb):
        try:
            if kind and not self.admitted and not self.rejected:
                error=kind.__name__
                self.reject('cancelled' if 'Cancel' in error else 'budget_denied' if 'Budget' in error else 'invalid_arguments' if error in {'ValueError','ValidationError','ToolInputValidationError'} else 'not_allowed')
        finally: _REQUEST.reset(self.token)


def current_request(): return _REQUEST.get()


def intercept_current(kind):
    request=current_request()
    if request:request.reject(kind)
