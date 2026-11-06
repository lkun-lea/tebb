"""Declarative, versioned adapter presets; never executable extension code."""
import copy
import hashlib
import json
import re
import time
import uuid

from desk_companion.automation.workflow_graph import KINDS, IDENT, WRITES, validate

INPUT=re.compile(r'\{\{\s*input\.([A-Za-z][A-Za-z0-9_]*)\s*\}\}')


def initialize(db):
    db.executescript('''CREATE TABLE IF NOT EXISTS capabilities(id TEXT PRIMARY KEY,revision INTEGER,version TEXT,body TEXT,updated REAL);
        CREATE TABLE IF NOT EXISTS capability_versions(id TEXT,version TEXT,body TEXT,PRIMARY KEY(id,version));
        CREATE TABLE IF NOT EXISTS capability_operations(id TEXT PRIMARY KEY,digest TEXT,result TEXT);''')
    db.execute('CREATE TABLE IF NOT EXISTS workflow_operations(id TEXT PRIMARY KEY,digest TEXT,result TEXT)')


def _render(value, inputs):
    if isinstance(value,dict):return {k:_render(v,inputs) for k,v in value.items()}
    if isinstance(value,str):return INPUT.sub(lambda m:inputs[m[1]],value)
    return copy.deepcopy(value)


def listing(store):
    with store.db() as db:return [json.loads(row[0]) for row in db.execute('SELECT body FROM capabilities ORDER BY updated DESC')]


def load(store,ident,version=''):
    with store.db() as db:
        row=db.execute('SELECT body FROM capability_versions WHERE id=? AND version=?',(ident,version)).fetchone() if version else db.execute('SELECT body FROM capabilities WHERE id=?',(ident,)).fetchone()
    if not row:raise ValueError('能力或指定版本不存在。')
    return json.loads(row[0])


def save(store,payload):
    operation=payload.get('operation','')
    if not isinstance(operation,str) or not re.fullmatch(r'[a-f0-9]{32}',operation):raise ValueError('能力保存需要稳定的32位操作编号。')
    fingerprint=hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    name,kind,template,parameters=(payload.get(k) for k in ('name','kind','template','parameters'))
    if not isinstance(name,str) or not 1<=len(name.strip())<=100 or kind not in KINDS or kind=='trigger':raise ValueError('能力名称或适配器无效。')
    if not isinstance(parameters,dict) or len(parameters)>20 or any(not isinstance(k,str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,39}',k) or not isinstance(v,str) or len(v)>50000 for k,v in parameters.items()):raise ValueError('能力参数须为最多20项文字默认值。')
    if not isinstance(template,dict) or len(json.dumps(template,ensure_ascii=False).encode())>100000:raise ValueError('能力模板无效或过大。')
    raw=json.dumps(template,ensure_ascii=False)
    if set(INPUT.findall(raw))-set(parameters) or '{{' in INPUT.sub('',raw) or '}}' in INPUT.sub('',raw):raise ValueError('模板只能引用声明过的 {{input.参数}}。')
    # External identities remain fixed exactly as in ordinary nodes.
    fixed={'chat_id','base_token','table_id','key_field','parent_token','profile','model_id','document_id'}
    if any('{{' in str(template.get(k,'')) for k in fixed):raise ValueError('外部目标与模型身份不能由能力参数动态改变。')
    sample=_render(template,{k:v or 'sample' for k,v in parameters.items()})
    probe=dict(nodes=[dict(id='trigger',kind='trigger'),dict(id='sample',kind=kind,config=sample)],edges=[dict(source='trigger',target='sample')])
    validate(probe)
    ident=payload.get('id') or uuid.uuid5(uuid.NAMESPACE_URL,'tebb-capability:'+operation).hex
    if not isinstance(ident,str) or not IDENT.fullmatch('c'+ident):raise ValueError('能力编号无效。')
    with store.db(True) as db:
        prior=db.execute('SELECT digest,result FROM capability_operations WHERE id=?',(operation,)).fetchone()
        if prior:
            if prior[0]!=fingerprint:raise ValueError('操作编号已用于不同能力，不会重放。')
            return json.loads(prior[1])
        old=db.execute('SELECT revision FROM capabilities WHERE id=?',(ident,)).fetchone()
        if not old and payload.get('revision') not in {None,0}:raise ValueError('原能力不存在，未创建替代能力。')
        if old and payload.get('revision')!=old[0]:raise ValueError('能力已变化，请读取新版本；草稿保留。')
        body=dict(id=ident,name=name.strip(),kind=kind,template=template,parameters=parameters,revision=old[0]+1 if old else 1,writes=kind in WRITES)
        body['version']=hashlib.sha256(json.dumps(body,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        encoded=json.dumps(body,ensure_ascii=False)
        db.execute('INSERT OR REPLACE INTO capabilities VALUES(?,?,?,?,?)',(ident,body['revision'],body['version'],encoded,time.time()))
        db.execute('INSERT OR IGNORE INTO capability_versions VALUES(?,?,?)',(ident,body['version'],encoded))
        db.execute('INSERT INTO capability_operations VALUES(?,?,?)',(operation,fingerprint,encoded))
    return body


def instantiate(store,payload):
    cap=load(store,payload['id'],payload.get('version',''))
    args=payload.get('arguments',{})
    if not isinstance(args,dict) or set(args)-set(cap['parameters']) or any(not isinstance(v,str) or len(v)>50000 for v in args.values()):raise ValueError('能力参数无效。')
    return dict(id=payload.get('node_id') or 'n'+uuid.uuid4().hex[:12],kind=cap['kind'],config=_render(cap['template'],{**cap['parameters'],**args}),position=payload.get('position',dict(x=0,y=0)),capability={k:cap[k] for k in ('id','version','name')})
