"""Opt-in real scenarios through authenticated workflow RPC and ordinary workers.

Creates a fresh profile, records every outcome, never retries an unknown write.
No provider credentials or business targets are printed by this command.
"""
import argparse
import asyncio
import copy
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import time
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
TEXT='这是一条 tebb 工作流验收数据，不含业务内容。'
CASES=('tech-news','video-notes','feishu-document','feishu-base','feishu-message')


def scenario(templates,ident,targets,video_url):
    item=copy.deepcopy(next(t for t in templates if t['id']==ident))
    if ident=='video-notes':
        if not video_url:raise ValueError('video-notes requires --video-url')
        item['graph']['nodes'][0]['config']['text']=video_url
    if ident.startswith('feishu-'):
        item['graph']['nodes'][0]['config']['text']=TEXT
        node=item['graph']['nodes'][-1];node['config']['profile']=targets.get('profile','')
        if ident=='feishu-document':node['config'].update(title='tebb 工作流验收 2026-11-02',parent_token=targets.get('parent_token',''))
        elif ident=='feishu-message':node['config']['chat_id']=targets['chat_id']
        else:node['config'].update(base_token=targets['base_token'],table_id=targets['table_id'],key_field=targets['key_field'],fields={targets['content_field']:'{{trigger.text}}'})
    return item


def verify_outputs(ident,run):
    receipts=run['receipts'];proof=dict(all_nodes_confirmed=all(r['state']=='confirmed' for r in receipts.values()))
    if ident=='tech-news':
        candidates=receipts['sources']['output']['candidates'];report=receipts['report']['output']['report'];known={c['id']:c for c in candidates}
        proof.update(five_unique_sources=len(report['items'])==len({i['id'] for i in report['items']})==5,
                     actual_source_binding=all(i['id'] in known and i['url']==known[i['id']]['url'] for i in report['items']),
                     report_text_present=bool(receipts['report']['output']['text'].strip()))
    elif ident=='video-notes':
        source=receipts['video']['output'];note=receipts['note']['output']['text']
        proof.update(actual_subtitles=bool(source['text'].strip()),notes_present=bool(note.strip()),coverage_disclosed=source['complete']or any(w in note for w in ('缺口','不完整','部分','节选','截断')),
                     has_time_reference=bool(__import__('re').search(r'\d{1,2}:\d{2}',note)))
    else:
        from desk_companion.workflow_nodes import reconcile,cli
        node=run['graph']['nodes'][-1];receipt=receipts[node['id']];field={'document':'document_id','base':'record_id','message':'message_id'}[node['kind']]
        cfg=receipt['input'];remote=reconcile(node['kind'],cfg,receipt['receipt_key'],receipt['output'].get(field,''))
        proof['remote_receipt_matched']=remote[field]==receipt['output'][field]
        if node['kind']=='document':proof['remote_text_matched']=TEXT in json.dumps(cli(cfg,['docs','+fetch','--doc',remote[field]]),ensure_ascii=False)
    return proof


async def run_cases(args,profile,port,token,report,save):
    from websockets.asyncio.client import connect
    from desk_companion import agent_debug
    from desk_companion.workflows import WorkflowStore
    async def rpc(method,**params):
        async with connect(f'ws://127.0.0.1:{port}/ws?token={token}',proxy=None) as ws:
            await ws.send(json.dumps(dict(type='rpc',id='scenario',method=method,args=params)))
            result=json.loads(await asyncio.wait_for(ws.recv(),130))['result']
        if not result['ok']:raise RuntimeError(result.get('error','RPC failed'))
        return result['result']
    async def workflow(operation,**payload):
        value=await rpc('automation_workflow',operation=operation,payload=payload)
        if not value['ok']:raise ValueError(value.get('error','workflow rejected'))
        return value
    templates=(await workflow('templates'))['templates']
    targets=json.loads(args.write_targets.read_text('utf-8')) if args.write_targets else {}
    for ident in args.case:
        row=dict(case=ident,outcome='running',started=time.time(),real_model=ident in {'tech-news','video-notes'},external_write=ident.startswith('feishu-'),proof={});report['cases'].append(row);save()
        run=None
        try:
            if ident.startswith('feishu-') and not args.confirm_test_writes:
                row.update(outcome='pending',reason='explicit_test_target_confirmation_required');continue
            item=scenario(templates,ident,targets,args.video_url)
            definition=(await workflow('save',name='场景验收 '+ident+' '+secrets.token_hex(4),graph=item['graph']))['definition']
            row.update(definition_id=definition['id'],version=definition['version']);save()
            run=(await workflow('start',id=definition['id'],version=definition['version'],request_id=secrets.token_hex(16),mode='full',confirm_writes=args.confirm_test_writes))['run']
            row['run_id']=run['id'];row['task_id']=run['task_id'];deadline=time.monotonic()+args.timeout
            while run['state'] in {'queued','running'}:
                row.update(state=run['state'],node_states={k:v['state'] for k,v in run['receipts'].items()});save()
                if time.monotonic()>=deadline:
                    await workflow('cancel',run_id=run['id']);row.update(outcome='timed_out',reason='scenario_deadline');break
                await asyncio.sleep(.5);run=(await workflow('get',run_id=run['id']))['run']
            if row['outcome']!='timed_out':
                if run['state']=='completed':
                    row['proof']=verify_outputs(ident,run)
                    row['outcome']='passed' if all(row['proof'].values()) else 'failed'
                else:row.update(outcome='failed',reason=run.get('error') or run['state'])
        except Exception as exc:row.update(outcome='failed',reason=str(exc),error_type=type(exc).__name__)
        finally:
            if run:
                try:run=(await workflow('get',run_id=run['id']))['run']
                except Exception as exc:row['observation_error']=type(exc).__name__
                row['state']=run['state'];row['node_states']={k:v['state'] for k,v in run['receipts'].items()}
                (args.output/(ident+'-run.json')).write_text(json.dumps(run,ensure_ascii=False,indent=2),'utf-8')
                row['calls']=[{k:v.get(k) for k in ('id','state','status','duration_ms','error')} for v in agent_debug.listing(task_id=row['task_id'])['items']]
            row['elapsed_seconds']=round(time.time()-row['started'],2);save()
    report['workflow_runs']=len(WorkflowStore().runs());save()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live',action='store_true',required=True)
    parser.add_argument('--case',action='append',choices=CASES,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--timeout',type=int,default=600)
    parser.add_argument('--video-url',default='')
    parser.add_argument('--use-connected-video-login',action='store_true')
    parser.add_argument('--confirm-test-writes',action='store_true')
    parser.add_argument('--write-targets',type=Path)
    args=parser.parse_args()
    if not 20<=args.timeout<=900 or len(args.case)!=len(set(args.case)):parser.error('timeout 20..900 and unique cases required')
    args.output=args.output.resolve()
    if args.output.exists():parser.error('--output must be a new directory; previous results are preserved')
    args.output.mkdir(parents=True);profile=args.output/'private-profile';profile.mkdir()
    from desk_companion.paths import data_root
    from desk_companion.model_catalog import require_active
    original=data_root();model=require_active();env_before=os.environ.get('DESK_COMPANION_DATA_DIR')
    selected={k:model[k] for k in ('id','model','base_url','api_key')}
    sensitive=[]
    def copy_file(source,destination):
        if source.is_file():destination.parent.mkdir(parents=True,exist_ok=True);sensitive.append(destination);shutil.copyfile(source,destination)
    report=dict(schema_version=1,model=model['model'],cases=[],max_model_calls_for_examples=2*('tech-news'in args.case)+('video-notes'in args.case),source_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT).decode().strip())
    evidence=['scripts/verify_workflow_scenarios.py',*[f'desk_companion/{name}.py' for name in ('workflow_templates','workflow_nodes','workflow_worker','workflows','news','video','tasks','execution_context')]]
    report['source_snapshot']={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in evidence}
    def save():(args.output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf-8')
    token=secrets.token_hex(24)
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    environment={**os.environ,'DESK_COMPANION_DATA_DIR':str(profile),'PYTHONUTF8':'1','PYTHONPATH':str(ROOT)+os.pathsep+os.environ.get('PYTHONPATH','')}
    process=None
    try:
        credential=profile/'models.json';sensitive.append(credential);credential.write_text(json.dumps(dict(active=model['id'],items=[selected])),'utf-8')
        copy_file(original/'model-network.json',profile/'model-network.json')
        capacity=original/'model-capacity.json'
        if capacity.is_file():
            data=json.loads(capacity.read_text('utf-8'));(profile/capacity.name).write_text(json.dumps({model['id']:data[model['id']]} if model['id'] in data else {}),'utf-8')
        copy_file(original/'feishu-connection.json',profile/'feishu-connection.json')
        if args.use_connected_video_login:
            for name in ('bilibili.json','youtube.json'):copy_file(original/'memory/video_login'/name,profile/'memory/video_login'/name)
        os.environ['DESK_COMPANION_DATA_DIR']=str(profile);save()
        with (args.output/'backend.log').open('w',encoding='utf-8') as log:
            process=subprocess.Popen([sys.executable,'-u','-m','desk_companion.local_api.server','--port',str(port),'--token',token],cwd=ROOT,env=environment,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            deadline=time.monotonic()+60
            while True:
                if process.poll() is not None:raise RuntimeError('isolated backend failed to start')
                try:
                    with urllib.request.urlopen(f'http://127.0.0.1:{port}/health',timeout=.5):break
                except OSError:
                    if time.monotonic()>deadline:raise TimeoutError('backend startup deadline')
                    time.sleep(.1)
            asyncio.run(run_cases(args,profile,port,token,report,save))
    finally:
        try:
            if process and process.poll() is None:
                request=urllib.request.Request(f'http://127.0.0.1:{port}/shutdown',headers={'Authorization':'Bearer '+token})
                with urllib.request.urlopen(request,timeout=5):pass
                process.wait(timeout=25)
        finally:
            for path in sensitive:path.unlink(missing_ok=True)
            from desk_companion import agent_debug
            from desk_companion.agent_eval_lifecycle import worker_alive
            calls=agent_debug.listing()['items'] if os.environ.get('DESK_COMPANION_DATA_DIR')==str(profile) else []
            report['cleanup']=dict(credentials_removed=all(not p.exists() for p in sensitive),backend_stopped=process is None or process.poll() is not None,observed_workers_exited=all(not worker_alive(c) for c in calls));save()
            if env_before is None:os.environ.pop('DESK_COMPANION_DATA_DIR',None)
            else:os.environ['DESK_COMPANION_DATA_DIR']=env_before
    print(json.dumps(dict(cases=[dict(case=r['case'],outcome=r['outcome']) for r in report['cases']],cleanup=report['cleanup'],report=str(args.output/'report.json')),ensure_ascii=False))
    return int(any(r['outcome']!='passed' for r in report['cases']))


if __name__=='__main__':raise SystemExit(main())
