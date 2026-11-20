"""Immutable case versions and frozen batch manifests; no executable case content."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import time

from desk_companion.infrastructure.paths import data_root
from desk_companion.observability.tool_monitor import fingerprint
from desk_companion.evaluation.agent_evals import CASES, CONTRACT_VERSION


def builtin_cases():
    """The same immutable built-in contracts for discovery and execution."""
    values=[]
    for spec in CASES:
        value=dict(id=spec['id'],split=spec.get('dataset_split','regression'),spec=spec,contract_version=CONTRACT_VERSION,
                   origin='existing_product_acceptance',criteria='reference_judge_calibration'if spec.get('executor')=='judge_calibration'else'existing_receipt_judge',weight=1)
        value['version']=fingerprint(value)
        values.append(value)
    return values


class GoldenStore:
    def __init__(self,path=None):
        self.path=Path(path or data_root()/'memory/evaluation.sqlite3').resolve()
        self.profile=self.path.parent.parent if self.path.parent.name=='memory'else self.path.parent

    def db(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        db=sqlite3.connect(self.path,timeout=10);db.row_factory=sqlite3.Row
        db.execute('CREATE TABLE IF NOT EXISTS cases(id TEXT,version TEXT,data TEXT,created REAL,PRIMARY KEY(id,version))')
        db.execute('CREATE TABLE IF NOT EXISTS batches(id TEXT PRIMARY KEY,request_id TEXT UNIQUE,created REAL,state TEXT,data TEXT)')
        return db

    def seed(self):
        with closing(self.db()) as db,db:
            for value in builtin_cases():
                db.execute('INSERT OR IGNORE INTO cases VALUES(?,?,?,?)',(value['id'],value['version'],json.dumps(value,ensure_ascii=False),time.time()))

    def cases(self):
        self.seed()
        with closing(self.db()) as db:
            return [json.loads(r[0])for r in db.execute('SELECT data FROM cases ORDER BY id,created DESC')]

    def save_case(self, value):
        if not isinstance(value,dict) or set(value)-{'id','prompt','expected','split','category','source_failure','weight','goals','rubric','change_reason'}:raise ValueError('用例只允许目标、参考结果与来源数据，不允许代码或命令。')
        import re
        ident=value.get('id');prompt=value.get('prompt');split=value.get('split','development');weight=value.get('weight',1)
        if not isinstance(ident,str)or not re.fullmatch(r'[a-zA-Z0-9_-]{1,100}',ident)or ident in {s['id']for s in CASES}:raise ValueError('自定义用例须使用独立编号。')
        if not isinstance(prompt,str)or not 1<=len(prompt)<=20000 or 'expected'not in value:raise ValueError('用例须提供目标与预期 JSON。')
        if split not in {'development','regression','holdout'}or type(weight)not in(int,float)or not 0<weight<=100:raise ValueError('用例分组或目标权重无效。')
        if len(json.dumps(value,ensure_ascii=False,allow_nan=False))>50000:raise ValueError('用例过大。')
        category=value.get('category','custom')
        if not isinstance(category,str)or len(category)>100:raise ValueError('用例分类无效。')
        source=value.get('source_failure')
        if source is not None and (not isinstance(source,str) or len(source)>512):raise ValueError('失败来源编号无效。')
        spec=dict(id=ident,category=category,prompt=prompt,expected=value['expected'],expected_state='success',required_tools=[])
        case=dict(id=ident,split=split,spec=spec,contract_version=CONTRACT_VERSION,origin='edited_draft',source_failure=source,
                  criteria='exact_json_and_task_state',weight=weight)
        reason=value.get('change_reason','initial version')
        if not isinstance(reason,str)or not 1<=len(reason)<=1000:raise ValueError('请记录用例变更原因。')
        case['change_reason']=reason
        rubric=value.get('rubric',[])
        if not isinstance(rubric,list)or len(rubric)>6:raise ValueError('语义评分最多6项。')
        for item in rubric:
            if not isinstance(item,dict)or set(item)!={'id','criterion','weight'}or not isinstance(item['id'],str)or not 1<=len(item['id'])<=100 or not isinstance(item['criterion'],str)or not 1<=len(item['criterion'])<=2000 or type(item['weight'])not in(int,float)or not 0<item['weight']<=100:raise ValueError('评分项须提供编号、标准和有限权重。')
        if len({r['id']for r in rubric})!=len(rubric):raise ValueError('评分项编号重复。')
        if rubric:
            spec['rubric']=rubric;case['criteria']='reference_rubric'
        if source:
            from desk_companion.observability.tool_monitor import ToolMonitor
            from desk_companion.observability.usage_store import UsageStore
            try:event=ToolMonitor(self.profile/'memory/tool-observations.sqlite3').get_event(source)
            except ValueError:event=UsageStore(self.profile/'memory/usage-observations.sqlite3').get(source)
            if event and event.get('state')not in{'failed','rejected','unknown','timed_out','cancelled'}:raise ValueError('来源没有记录失败、拒绝或未知结果。')
            case['source_evidence']={'status':'recorded',**{k:event.get(k)for k in ('id','tool','definition_version','attempt_id','parent_call','model','root','task','error_kind','state','ts','prompt_version','tools_version')}}if event else dict(status='unverified',id=source)
        goals=value.get('goals',[])
        if not isinstance(goals,list)or len(goals)>30:raise ValueError('目标最多30项。')
        for goal in goals:
            if not isinstance(goal,dict)or set(goal)!={'id','path','expected','weight'}or not isinstance(goal['id'],str)or not 1<=len(goal['id'])<=100 or not isinstance(goal['path'],list)or len(goal['path'])>20 or any(not isinstance(k,str)or len(k)>100 for k in goal['path'])or type(goal['weight'])not in(int,float)or not 0<goal['weight']<=100:raise ValueError('目标必须包含编号、JSON字段路径、预期值及有限权重。')
        if len({g['id']for g in goals})!=len(goals):raise ValueError('目标编号重复。')
        case['goals']=goals
        if rubric and goals:raise ValueError('开放式语义标准与JSON路径标准请拆为独立用例。')
        case['version']=fingerprint(case)
        with closing(self.db()) as db,db:
            # Frozen regression/holdout standards are immutable. Editing creates
            # a new independent case ID instead of silently replacing a baseline.
            frozen=db.execute("SELECT data FROM cases WHERE id=?",(ident,)).fetchall()
            if any(json.loads(r[0])['split']in{'regression','holdout'}and json.loads(r[0])['version']!=case['version']for r in frozen):raise ValueError('固定回归集或保留集不可原地修改，请使用新的用例编号。')
            db.execute('INSERT OR IGNORE INTO cases VALUES(?,?,?,?)',(ident,case['version'],json.dumps(case,ensure_ascii=False),time.time()))
        return case

    def create_batch(self, value, request_id):
        encoded=json.dumps(value,ensure_ascii=False,allow_nan=False)
        with closing(self.db()) as db,db:
            old=db.execute('SELECT data FROM batches WHERE request_id=?',(request_id,)).fetchone()
            if old:
                prior=json.loads(old[0])
                if prior['manifest_hash']!=value['manifest_hash']:raise ValueError('同一请求编号已绑定其它评测计划。')
                return prior,False
            db.execute('INSERT INTO batches VALUES(?,?,?,?,?)',(value['id'],request_id,value['created'],value['state'],encoded))
        return value,True

    def request_batch(self,request_id):
        with closing(self.db())as db:row=db.execute('SELECT data FROM batches WHERE request_id=?',(request_id,)).fetchone()
        return json.loads(row[0])if row else None

    def batch(self,ident):
        with closing(self.db()) as db:row=db.execute('SELECT data FROM batches WHERE id=?',(ident,)).fetchone()
        if row is None:raise ValueError('评测批次不存在。')
        return json.loads(row[0])

    def update(self,ident,**changes):
        with closing(self.db()) as db,db:
            db.execute('BEGIN IMMEDIATE');row=db.execute('SELECT data,state FROM batches WHERE id=?',(ident,)).fetchone()
            if not row:raise ValueError('评测批次不存在。')
            if row['state']in{'completed','failed','cancelled','interrupted'}:return json.loads(row['data'])
            value=json.loads(row['data']);value.update(changes,updated=time.time())
            db.execute('UPDATE batches SET state=?,data=? WHERE id=?',(value['state'],json.dumps(value,ensure_ascii=False,allow_nan=False),ident))
        return value

    def batches(self,limit=200,offset=0):
        with closing(self.db()) as db:return [json.loads(r[0])for r in db.execute('SELECT data FROM batches ORDER BY created DESC LIMIT ? OFFSET ?',(limit,offset))]
