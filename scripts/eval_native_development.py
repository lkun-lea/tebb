"""Run an opt-in native tebb team/single comparison on an isolated SQLite order project."""
import argparse
import json
import os
from pathlib import Path
import tempfile
import time
import uuid

from desk_companion.models import model_catalog
from desk_companion.models import model_network
from desk_companion.projects import project_workspace
from desk_companion.collaboration.store import transaction
from desk_companion.collaboration.service import Collaboration

GOAL = ("修复订单 CLI、服务层和 SQLite 存储层。每个账户初始余额 100。同账户同订单号重复提交，"
        "包括进程重启及并发提交，只扣款一次并返回首次成功时的余额。不同账户可使用相同订单号。"
        "余额不足返回 -1，不能留下订单。兼容已有 balances 表和现有 CLI 参数，只改源文件。"
        "用 python3 smoke.py 和你自行设计的集成检查验证。无需联网、发布或更改系统配置。")
FILES = {
    "cli.py": "import sys\nfrom service import submit\nprint(submit(*sys.argv[1:]))\n",
    "service.py": "from storage import debit\ndef submit(db,account,order,amount):\n return debit(db,account,order,int(amount))\n",
    "storage.py": """import sqlite3
def debit(db,account,order,amount):
 with sqlite3.connect(db) as conn:
  conn.execute('create table if not exists balances(account text primary key, balance integer)')
  conn.execute('insert or ignore into balances values (?,100)',(account,))
  current=conn.execute('select balance from balances where account=?',(account,)).fetchone()[0]
  if current<amount:return -1
  current-=amount
  conn.execute('update balances set balance=? where account=?',(current,account))
  return current
""",
    "smoke.py": """import tempfile, pathlib
from service import submit
with tempfile.TemporaryDirectory() as d:
 assert submit(str(pathlib.Path(d)/'db'),'a','first','10')==90
""",
}
HOLDOUT = """from concurrent.futures import ThreadPoolExecutor
import pathlib, subprocess, sys, tempfile, json
def check(case):
 with tempfile.TemporaryDirectory() as tmp:
  db=str(pathlib.Path(tmp)/'db')
  def call(account,order,n):
   return int(subprocess.check_output([sys.executable,'cli.py',db,account,order,str(n)],text=True).strip())
  if case=='restart':return [call('a','1',10),call('a','2',15),call('a','1',10)]==[90,75,90]
  if case=='account':return [call('a','1',10),call('b','1',30)]==[90,70]
  if case=='rollback':return [call('a','1',110),call('a','1',20)]==[-1,80]
  with ThreadPoolExecutor(4) as pool: values=list(pool.map(lambda _:call('a','1',10),range(4)))
  return values==[90]*4 and call('a','2',10)==80
rows={}
for case in ['restart','account','rollback','concurrency']:
 try:rows[case]=check(case)
 except Exception:rows[case]=False
print(json.dumps(rows),flush=True)
raise SystemExit(0 if all(rows.values()) else 1)
"""


def trial(arm, output, model, policy, *, seed=None, goal=GOAL, holdout=HOLDOUT, observe=None):
    folder=output/arm
    if seed is None:
        folder.mkdir()
        for name,content in FILES.items():
            (folder/name).write_text(content,'utf-8')
    else:
        seed(folder)
    with tempfile.TemporaryDirectory(prefix='tebb-team-profile-') as tmp:
        profile=Path(tmp)
        (profile/'models.json').write_text(json.dumps(dict(active=model['id'],items=[model])),'utf-8')
        (profile/'model-network.json').write_text(json.dumps(policy),'utf-8')
        os.environ['DESK_COMPANION_DATA_DIR']=tmp
        service=Collaboration(start=False)
        def action(**kw):
            return service.action(dict(request_id=uuid.uuid4().hex,**kw))['state']
        try:
            action(type='add_coder')
            state=action(type='open_folder_project',primary=str(folder))
            pid=next(c['project_id'] for c in state['conversations'] if c['id']==state['selected'])
            ws=project_workspace.save(str(folder),[],True,True,project_id=pid)['workspace']
            with transaction(service.path) as (db,_):
                for a in db['agents']:
                    a['model']=model['id']
                    if a['id']=='tebb':a['tools']=[]
                    if a['id']=='research':
                        a.update(role='独立验证跨模块集成和失败路径',tools=['工作区读取','终端'])
            if arm=='team':
                group=action(type='group',title='开发验证团队',members=['tebb','coder','research'],project_id=pid)['selected']
                started=time.time()
                sent=action(type='send',conversation=group,target='tebb',mode='task',text=goal,strategy='delegate',development_task=True)
            else:
                dm=action(type='open_dm',agent_id='coder',project_id=pid)['selected']
                started=time.time()
                sent=action(type='send',conversation=dm,target='coder',mode='task',text=goal)
            rid=sent['runs'][-1]['id']
            while True:
                service.tick()
                runs=service.snapshot()['state']['runs']
                root=next(r for r in runs if r['id']==rid)
                if observe:
                    observe(service, started)
                rows=[{k:r.get(k) for k in ('id','parent','agent','kind','task','stage','integration_verification','state','status','calls','input_tokens','output_tokens','error')} for r in runs]
                (output/(arm+'-progress.json')).write_text(json.dumps(rows,ensure_ascii=False,indent=2),'utf-8')
                if root['state'] not in {'running','pending','queued','waiting','cancelling'}:break
                time.sleep(1)
            oracle='held_out_'+uuid.uuid4().hex+'.py'
            with (folder/oracle).open('x',encoding='utf-8') as script:
                script.write(holdout)
            elapsed=time.time()-started
            try:
                result=project_workspace.run('python3 '+oracle,ws,'evaluation-'+rid,60)
            finally:
                (folder/oracle).unlink(missing_ok=True)
            try: scores=json.loads(result.get('output','').strip().splitlines()[-1])
            except (ValueError,IndexError):scores=None
            return dict(model=model['model'],delivery=root['state'],runs=rows,checks=scores,budget=root.get('task_budget'),
                        elapsed_s=round(elapsed,1),test_exit=result.get('exit_code'),test_state=result.get('state'),error=result.get('error'))
        finally:
            service.shutdown()
            (profile/'models.json').unlink(missing_ok=True)
            (profile/'model-network.json').unlink(missing_ok=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--live',action='store_true',required=True)
    parser.add_argument('--arm',choices=('single','team','both'),default='both')
    args=parser.parse_args()
    output=args.output.resolve()
    output.mkdir(parents=True,exist_ok=False)
    model=model_catalog.require_active()
    policy=model_network.load()
    original=os.environ.get('DESK_COMPANION_DATA_DIR')
    passed=True
    try:
        for arm in (['single','team'] if args.arm=='both' else [args.arm]):
            try: result=trial(arm,output,model,policy)
            except Exception as exc: result=dict(error=type(exc).__name__,delivery='unverified')
            (output/(arm+'.json')).write_text(json.dumps(result,indent=2,ensure_ascii=False),'utf-8')
            print(arm,result.get('delivery'),result.get('checks'),flush=True)
            scores=result.get('checks') or {}
            passed=passed and result['delivery']=='succeeded' and result.get('test_exit')==0 and all(
                scores.get(name) is True for name in ('restart','account','rollback','concurrency'))
    finally:
        if original is None:os.environ.pop('DESK_COMPANION_DATA_DIR',None)
        else:os.environ['DESK_COMPANION_DATA_DIR']=original
    return 0 if passed else 1


if __name__=='__main__':
    raise SystemExit(main())
