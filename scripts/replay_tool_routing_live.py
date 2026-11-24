"""Paired real-model replay with Pi and a frozen, read-only task evidence archive."""
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from contextlib import closing
from datetime import datetime, timezone, timedelta
import importlib.util
import json
import os
from pathlib import Path
import re
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

from compare_tool_routing import read_db, sample_records, baseline
from desk_companion.pi_runtime import tool_loading
from desk_companion.pi_runtime.tool_routing import terms, normalize


def old_module(path):
    spec = importlib.util.spec_from_file_location('reference_router', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def evidence(memory, task):
    logs = memory/'agent_debug'
    saved = {}
    with closing(read_db(logs/'index.sqlite3')) as db:
        for ident, in db.execute('SELECT id FROM calls WHERE task_id=? ORDER BY created,id', (task,)):
            path = logs/(ident+'.request.json')
            if not path.exists():
                continue
            calls = {}
            for m in json.loads(path.read_bytes()).get('messages', []):
                for call in m.get('tool_calls') or []:
                    calls[call['id']] = call['function']
                fn = calls.get(m.get('tool_call_id'))
                if m['role'] != 'tool' or not fn:
                    continue
                try:
                    args = json.loads(fn['arguments'])
                except ValueError:
                    continue
                key = fn['name'], json.dumps(args, sort_keys=True, ensure_ascii=False)
                saved.setdefault(key, str(m.get('content') or ''))
    return saved


def archived_call(saved, name, args):
    # No live adapter is registered. Only exact read receipts, or a lookup over
    # this task's saved search pages, are available. Writes never replay as new.
    readers = {'workspace_list','workspace_read','workspace_search','workspace_read_symbol','web_search',
               'web_fetch','calendar_query','read_local_calendar','read_skill','list_skills',
               'get_open_tasks','automation_list','read_local_source','get_current_time'}
    clean = {k:v for k,v in args.items() if not k.startswith('_')}
    key = json.dumps(clean, sort_keys=True, ensure_ascii=False)
    body = saved.get((name,key)) if name in readers else None
    if body is None and name=='web_search':
        words = terms(normalize(str(clean.get('query',''))))
        ranked = [(len(words & terms(normalize(json.loads(k).get('query','')))), v)
                  for (tool,k),v in saved.items() if tool=='web_search']
        if ranked and max(ranked)[0]>=2:
            body = max(ranked)[1]
    if body is None:
        return dict(ok=False, reason='missing_archived_receipt', error='隔离回放中没有这个调用的历史只读结果；未执行外部操作。')
    if re.search(r'(?i)(bearer\s+[\w.-]{15,}|sk-[\w-]{20,}|(?:api_key|access_token|signature)=\S+)',body):
        return dict(ok=False,error='回放材料包含凭据字段，已跳过。')
    return dict(source='本任务历史材料', excerpt=body[:2200], truncated=len(body)>2200)


def contexts(memory):
    with closing(read_db(memory/'collaboration/workspace.sqlite3')) as db:
        state = json.loads(db.execute('SELECT data FROM workspace WHERE id=1').fetchone()[0])
    prior = {}
    for msg in state.get('messages', []):
        if msg.get('sender') != 'user':
            continue
        conversation = msg.get('conversation','')
        text = msg.get('text','')
        earlier = prior.setdefault(conversation, [])
        yield text, earlier[-2:]
        earlier.append(text[:350])


def replay(job):
    from atlas import Toolkit
    from desk_companion.pi_runtime.chat_agent import PiChatAgent
    from desk_companion.pi_runtime.inference import PiInference
    from desk_companion.models import model_network
    case, arm, item, policy, reference, steps = job
    tools = Toolkit()
    business = []
    for spec in case['specs']:
        name = spec['name']
        def execute(args, n=name):
            receipt = archived_call(case['saved'],n,args)
            business.append(dict(name=n, evidence=bool(receipt.get('source'))))
            return receipt
        tools.register(name=name,description=spec['description'],parameters=spec['parameters'],
                       func=execute,isReadOnly=True,retry_max=0)
    result = dict(case=case['index'], arm=arm, model=item['model'], step_limit=steps, searches=[],business=business,
                  expected=case['expected'],turns=[],state='error')
    original = tool_loading.ToolLoading.execute
    def record(loading,name,args,call_id):
        if arm == 'before' and name == tool_loading.SEARCH:
            loading.searched = True
            receipt = tool_loading.search_receipt(loading.router.search(args['query']))
        else:
            receipt = original(loading,name,args,call_id)
        if name==tool_loading.SEARCH:
            if arm=='keyword':
                receipt=baseline(args['query'],loading.definitions)
                receipt['loaded']=list(loading.loaded)
            result['searches'].append(dict(query=args['query'],found=[d['name'] for d in receipt['tools']]))
        return receipt

    class MeasuredAgent(PiChatAgent):
        stable_discovery=arm=='after'
        def _model(self,data):
            if data['event']=='model_end':
                u = data.get('provider_usage') or {}
                from desk_companion.observability.usage_store import normalized_usage
                counts=normalized_usage(u)
                result['turns'].append(dict(prompt_tokens=counts['input_tokens'],completion_tokens=counts['output_tokens'],
                                            total_tokens=counts['total_tokens'],cached_tokens=counts['cached_tokens'],
                                            uncached_tokens=counts['uncached_tokens']))
            return super()._model(data)

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp, patch.dict(os.environ,DESK_COMPANION_DATA_DIR=tmp), patch.object(model_network,'load',return_value=policy), patch.object(tool_loading.ToolLoading,'execute',record), patch.object(tool_loading,'ToolRouter',old_module(reference).ToolRouter if arm=='before' else tool_loading.ToolRouter):
        llm=PiInference(item,timeout=60)
        llm.client=SimpleNamespace(api_key=item['api_key'],base_url=item['base_url'],timeout=SimpleNamespace(read=60))
        llm.sampling={'temperature':0}
        prompt=('你是 tebb。根据用户目标使用已授权工具。工具结果来自隔离的历史资料快照。'
                '无法取得所需材料时说明缺口，不虚构执行结果；用简短中文回答。当前北京时间 '+case['date'])
        agent=MeasuredAgent(llm=llm,tools=tools,system_prompt=prompt,max_steps=steps)
        if case['context']:
            agent.memory.add_user('之前的对话背景：\n'+'\n'.join(case['context']))
        try:
            result['answer']=agent.run(case['query'])
            result['state']='final'
        except Exception as exc:
            result['error']=type(exc).__name__ + ': ' + str(exc)[:160]
        result['attempted_turns']=agent.turn
        result['hit']=bool(set(case['expected']) & {b['name'] for b in business})
        result['usage_complete']=(len(result['turns'])==agent.turn and bool(result['turns'])
                                  and all(t['total_tokens'] is not None for t in result['turns']))
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live',action='store_true',required=True)
    parser.add_argument('--memory',type=Path,required=True)
    parser.add_argument('--before',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--arms',nargs='+',choices=['before','after','keyword'],default=['before','after'])
    parser.add_argument('--cases',nargs='+',type=int,help='Only replay specified business case numbers')
    parser.add_argument('--steps',type=int,choices=range(3,17),default=10)
    parser.add_argument('--parallel',type=int,choices=range(1,7),default=4)
    args=parser.parse_args()
    from desk_companion.models.model_catalog import require_active
    from desk_companion.models.model_network import load
    item=require_active()
    reference=old_module(args.before)
    cases=[]
    histories=dict(contexts(args.memory))
    with closing(read_db(args.memory/'agent_debug/index.sqlite3')) as db:
        for i,(_,q,s,t,task,ident) in enumerate((row for row in sample_records(args.memory) if row[0]=='business'),1):
            if args.cases and i not in args.cases:
                continue
            if t & {d['name'] for d in reference.ToolRouter(s).search(q)}:
                continue
            created=db.execute('SELECT created FROM calls WHERE id=?',(ident,)).fetchone()[0]
            date=datetime.fromtimestamp(created,timezone(timedelta(hours=8))).strftime('%Y-%m-%d')
            # Short references need earlier user turns, never later answers.
            context=histories.get(q,[]) if ('再试试' in q or '给我解释下' in q) else []
            cases.append(dict(index=i,query=q,specs=s,expected=sorted(t),saved=evidence(args.memory,task),date=date,context=context))
    policy=load()
    with args.output.open('x',encoding='utf8') as out, ProcessPoolExecutor(max_workers=args.parallel) as pool:
        jobs=[(case,arm,item,policy,args.before,args.steps) for j,case in enumerate(cases)
              for arm in (args.arms if j%2==0 else args.arms[::-1])]
        pending=[pool.submit(replay,job) for job in jobs]
        for future in as_completed(pending):
            row=future.result()
            out.write(json.dumps(row,ensure_ascii=False)+'\n')
            out.flush()
            print(row['case'],row['arm'],row['state'],row['hit'],len(row['turns']),flush=True)


if __name__=='__main__':
    main()
