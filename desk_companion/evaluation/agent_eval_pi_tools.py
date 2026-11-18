"""Receipt verification over ordinary chat's real private Pi worker."""
import json
from pathlib import Path
import sys
import time
import uuid

from desk_companion.tasks.manager import TaskManager
from desk_companion.evaluation.agent_evals import wait_task
from desk_companion.observability.tool_monitor import ToolMonitor


def execute(spec,*,profile,model_id,timeout,progress=lambda value:None):
    manager=TaskManager(path=Path(profile)/'memory/collaboration/chat/tasks.sqlite3',
        command=[sys.executable,'-u','-m','desk_companion.evaluation.pi_tools_worker'])
    try:
        ident=manager.submit(spec['prompt'],'eval-pi-'+uuid.uuid4().hex,'desktop',model_id=model_id)
        progress(dict(task_id=ident,task_ids=[ident]))
        task,expired=wait_task(manager,ident,time.monotonic()+timeout)
        path=Path(profile)/('pi-tools-'+ident+'.jsonl')
        rows=[json.loads(line)for line in path.read_text('utf-8').splitlines()]if path.exists()else[]
        expected=['web_fixture_sum','project_fixture_check']
        valid=([r['tool']for r in rows]==expected and rows[0]['arguments']==dict(a=7,b=11)
               and rows[1]['arguments']==dict(total=18)and rows[1]['result']==dict(ok=True,checked=True,total=18))
        events=ToolMonitor().events(root='task:'+ident,limit=10000)
        loaded={e['tool']for e in events if e['phase']=='load'}
        verification=dict(verified=valid and set(expected)<=loaded and not expired,scope='ordinary_product_pi_chat',
            receipts=rows,loaded=sorted(loaded),discoveries=sum(e['phase']=='discovery'for e in events),
            attempts=sum(e['phase']=='attempt'for e in events),external_writes=False)
        return task,verification,[ident],None,expired
    finally:manager.shutdown()
