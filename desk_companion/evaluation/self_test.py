"""Discoverable, fixture-only acceptance contracts over the existing evaluator."""
import re

from desk_companion.evaluation.coverage import coverage, GAPS
from desk_companion.evaluation.golden_store import builtin_cases
from desk_companion.observability.tool_monitor import fingerprint

GUIDE='docs/AGENT_SELF_TEST.md'
LIMITATIONS=['隔离模拟结果只验证所选产品链路，不证明真实模型能力。',
             '后台评测不证明原生窗口、界面交互或安装生命周期通过。',
             '不执行真实外部写入，不改变原业务任务的验收状态。']
OPERATIONS={
    'catalog':{},
    'describe':{'capability':{'type':'string'}},
    'start':{'capability':{'type':'string'},'request_id':{'type':'string','minLength':8,'maxLength':128}},
    'get':{'ident':{'type':'string'}},
    'report':{'ident':{'type':'string'}},
    'cancel':{'ident':{'type':'string'}},
    'diagnose':{'ident':{'type':'string'}},
    'trace':{'ident':{'type':'string'},'case_id':{'type':'string'},'sample':{'type':'integer','minimum':1}},
    'debug_call':{'ident':{'type':'string'},'case_id':{'type':'string'},'sample':{'type':'integer','minimum':1},'call_id':{'type':'string'}},
}


def catalog():
    cases={c['id']:c for c in builtin_cases()}
    existing=coverage(list(cases.values()))
    smoke=set(existing['suites']['smoke'])
    areas=[('smoke','首批冒烟','mixed',[c['id']for c in cases.values()if c['version']in smoke]),
           *[(a['id'],a['label'],a['level'],[c['id']for c in a['cases']])for a in existing['areas']]]
    if existing['unmapped_cases']:areas.append(('unmapped','尚未归组的内置样本','unknown',existing['unmapped_cases']))
    capabilities=[]
    for ident,label,level,ids in areas:
        selected=[cases[i]for i in ids if i in cases]
        capabilities.append(dict(id=ident,description=label,verification_level=level,
            available=bool(selected),cases=[dict(id=c['id'],version=c['version'],split=c['split'])for c in selected],
            mode='fixture',samples=1,timeout=120,guide=GUIDE))
    return dict(ok=True,version=1,capabilities=capabilities,operations={op:dict(type='object',properties=properties,
        required=[k for k in properties if k!='sample'],additionalProperties=False)for op,properties in OPERATIONS.items()},
        entrypoints=dict(cli='python scripts/agent_inspect.py selftest catalog',rpc='agent_self_test',
            tools=['self_test_catalog','self_test_start','self_test_inspect','self_test_cancel']),
        guide=GUIDE,gaps=GAPS,limitations=LIMITATIONS,authentication='existing_full_token_rpc; no credentials in model arguments',
        prerequisites=dict(execution=['running_authenticated_local_backend','Node 24.22.3','Pi 1.5.2','Promptfoo 0.125.1','source evaluation harness'],
                           discovery='offline; no token required'),
        procedure=['catalog','read contract in catalog.capabilities (CLI/RPC describe is optional)','start with stable request_id','get original batch','report','trace/debug_call/diagnose when needed','cancel then get original batch'],
        response=dict(envelope='ok/result; check both envelope and result ok',start='batch.id, batch.state, reused',
                      report='passed, results_complete, evidence_complete, metrics, results, missing_samples, limitations'))


def validate(operation,payload):
    from jsonschema import validate as check
    if operation not in OPERATIONS:raise ValueError('自测操作不存在，请先查询 catalog。')
    schema=catalog()['operations'][operation]
    try:check(payload,schema)
    except Exception as exc:
        from jsonschema import ValidationError
        if isinstance(exc,ValidationError):raise ValueError('自测参数与目录 Schema 不一致。')from None
        raise


class SelfTestService:
    def __init__(self,evaluate,owner='external'):
        self.evaluate=evaluate
        self.candidate='selftest:'+fingerprint(owner)[:24]
        self.external=owner=='external'

    def operate(self,operation,payload=None):
        payload={}if payload is None else payload
        validate(operation,payload)
        if operation=='catalog':return catalog()
        if operation in {'describe','start'}:
            capability=next((c for c in catalog()['capabilities']if c['id']==payload['capability']),None)
            if not capability or not capability['available']:raise ValueError('自测能力不可用，请先查询 catalog。')
            if operation=='describe':return dict(ok=True,capability=capability,limitations=LIMITATIONS)
            request_id=payload['request_id']
            if not re.fullmatch(r'[A-Za-z0-9_-]{8,128}',request_id):raise ValueError('自测请求编号无效。')
            # The owner is part of the immutable manifest. Reuse the original request on uncertain delivery.
            return self.evaluate('start',dict(request_id='selftest-'+fingerprint([self.candidate,request_id])[:48],
                case_versions=[c['version']for c in capability['cases']],candidate=self.candidate,mode='fixture',
                samples=capability['samples'],timeout=capability['timeout'],tool_loading='demand'))
        batch=self.evaluate('get',dict(ident=payload['ident']))['batch']
        marker=batch.get('candidate','')
        if batch.get('mode')!='fixture' or not marker.startswith('selftest:') or (not self.external and marker!=self.candidate):
            raise ValueError('批次不属于当前自测调用范围。')
        if operation=='get':return dict(ok=True,batch=batch)
        if operation=='report':return self.report(batch)
        if operation in {'trace','debug_call'}:payload={'sample':1,**payload}
        return self.evaluate(operation,payload)

    @staticmethod
    def report(batch):
        planned={(p['case_id'],p['sample'])for p in batch['planned']}
        rows=batch.get('results',[])
        observed={(r['case_id'],r['sample'])for r in rows}
        complete=bool(planned)and len(planned)==len(rows)and planned==observed
        evidence=complete and all(r.get('call_ids')and r.get('calls')and r.get('model_observations')
            and r.get('call_evidence_complete')is True and r.get('model_observations_complete')is True for r in rows)
        passed=batch['state']=='completed'and evidence and all(r.get('outcome')=='success'and not r.get('progress')for r in rows)
        return dict(ok=True,ident=batch['id'],state=batch['state'],passed=passed,verification_mode='fixture',
            results_complete=complete,evidence_complete=evidence,manifest_hash=batch['manifest_hash'],code_version=batch['code_version'],
            metrics=batch.get('metrics'),results=rows,missing_samples=[dict(case_id=c,sample=s)for c,s in sorted(planned-observed)],
            next_action='完成所选模拟链路验收'if passed else '查询原批次和失败证据；未完成时继续查询，未知结果不得自动新建重跑。',
            limitations=LIMITATIONS,gaps=GAPS)


def execute(host,evaluate,operation,payload=None,*,task_id='',run_id=''):
    """Bind model tools to their actual active task; external full-token CLI stays explicit."""
    owner='external'
    if run_id:
        from desk_companion.collaboration.store import transaction
        from desk_companion.collaboration.service import ACTIVE
        with host.collaboration.lock,transaction(host.collaboration.path)as(state,_):
            run=next((r for r in state['runs']if r['id']==run_id),None)
            if not task_id or not run or run.get('task')!=task_id or run['state']not in ACTIVE or run['state']=='cancelling' or run['kind']!='task':
                raise ValueError('自测调用所属的伙伴任务已结束或身份不匹配。')
        owner='collaboration:'+run_id
    elif task_id:
        if host.tasks.get(task_id)['state']!='running':raise ValueError('自测调用所属任务未运行。')
        owner='task:'+task_id
    return SelfTestService(evaluate,owner).operate(operation,payload)
