"""Fixed authoring task over product queues, authenticated RPC and durable graphs."""
from contextlib import contextmanager
import asyncio
import os
import threading
import time
from types import SimpleNamespace
import uuid


@contextmanager
def parent(host):
    from .local_api import server
    previous=(server.HOST,server.TOKEN)
    environment={k:os.environ.get(k) for k in ('DESK_TERMINAL_PORT','DESK_TERMINAL_TOKEN')}
    ready=threading.Event();state={};token=uuid.uuid4().hex
    async def main():
        from websockets.asyncio.server import serve
        state.update(loop=asyncio.get_running_loop(),stop=asyncio.Event())
        try:
            async with serve(server._handler,'127.0.0.1',0) as listener:
                state['port']=listener.sockets[0].getsockname()[1];ready.set();await state['stop'].wait()
        except Exception as exc:state['error']=type(exc).__name__;ready.set()
    server.HOST,server.TOKEN=host,token
    thread=threading.Thread(target=lambda:asyncio.run(main()),daemon=True);thread.start()
    try:
        if not ready.wait(10) or 'error' in state:raise RuntimeError('authenticated authoring parent did not start')
        os.environ.update(DESK_TERMINAL_PORT=str(state['port']),DESK_TERMINAL_TOKEN=token)
        yield state
    finally:
        if state.get('loop') and not state['loop'].is_closed():state['loop'].call_soon_threadsafe(state['stop'].set)
        thread.join(10);state['stopped']=not thread.is_alive()
        server.HOST,server.TOKEN=previous
        for key,value in environment.items():
            if value is None:os.environ.pop(key,None)
            else:os.environ[key]=value


def execute(spec,*,profile,workspace,model_id,timeout,command=None,progress=lambda _:None):
    from .collaboration import Collaboration
    from .tasks import TaskManager
    from .automation_service import AutomationService
    from .bridge import Bridge
    from .workflow_graph import validate
    from . import agent_debug
    from .workflow_capabilities import listing
    managers={};service=None;proof=dict(verified=False,scope='authenticated_workflow_authoring',deadline_exceeded=False)
    tasks={};calls={};root={};started=time.monotonic();tag=uuid.uuid4().hex[:8]
    try:
        for channel in ('work','chat'):
            manager=TaskManager(path=profile/'memory'/('authoring-'+tag+'-'+channel+'.sqlite3'),command=command)
            manager.configure(1,min(timeout,90),timeout,False);managers[channel]=manager
        service=Collaboration(path=workspace,managers=managers,start=False)
        agent=next(a for a in service.snapshot()['state']['agents'] if a['id']=='writer')
        service.action(dict(type='agent',agent={**agent,'model':model_id,'tools':['自动化工作流'],'memory':''},request_id=uuid.uuid4().hex))
        automation=AutomationService(tasks=lambda:managers['work'])
        host=SimpleNamespace(collaboration=service,automation=automation,state=SimpleNamespace(session_id='authoring-eval'),turn_lock=threading.RLock());host.bridge=Bridge(host)
        store=automation.workflows.store;before={d['id'] for d in store.definitions()};caps_before={c['id'] for c in listing(store)}
        with parent(host) as connection:
            prompt=spec['prompt']+'\nWORKFLOW_EVAL_TAG:'+tag+'；能力和图名称加此唯一后缀。'
            accepted=service.submit_execution('writer',prompt,'',dict(kind='authoring-eval',id=tag),uuid.uuid4().hex)
            if not accepted['ok']:raise RuntimeError('authoring task not admitted')
            run_id=accepted['run_id'];deadline=started+timeout;cancelled=False
            try:
                while True:
                    service.tick();root=service.execution_status(run_id=run_id)
                    for manager in managers.values():
                        for item in manager.list()['items']:
                            task=manager.get(item['id']);tasks[item['id']]=task
                            for call in agent_debug.listing(task_id=item['id'])['items']:calls[call['id']]=call
                    progress(dict(root_run=run_id,task_ids=list(tasks),task_id=next(iter(tasks),''),authoring=dict(state=root['state'],calls=len(calls))))
                    if root['state'] not in {'pending','queued','running','waiting','cancelling'}:break
                    if time.monotonic()>=deadline:
                        if not cancelled:
                            proof['deadline_exceeded']=True;service.action(dict(type='cancel',id=run_id,request_id=uuid.uuid4().hex));cancelled=True;deadline=time.monotonic()+8
                        else:break
                    time.sleep(.05)
                definitions=[store.definition(d['id']) for d in store.definitions() if d['id'] not in before]
                capabilities=[c for c in listing(store) if c['id'] not in caps_before]
                proof['artifacts']=[dict(kind='workflow_definition',id=d['id'],version=d['version']) for d in definitions]+[dict(kind='atomic_capability',id=c['id'],version=c['version']) for c in capabilities]
                artifact_ok=False
                if len(definitions)==len(capabilities)==1:
                    definition,cap=definitions[0],capabilities[0];graph,order=validate(definition['graph'])
                    instances=[n for n in graph['nodes'] if n.get('capability',{}).get('id')==cap['id']]
                    artifact_ok=bool(cap['kind']=='ai' and len(instances)==1 and instances[0]['config'].get('prompt','').count('{{trigger.text}}')==1 and len(graph['nodes'])==2 and order[0]==next(n['id'] for n in graph['nodes'] if n['kind']=='trigger') and len({(n['position']['x'],n['position']['y']) for n in graph['nodes']})==2)
                proof.update(verified=artifact_ok and root['state']=='succeeded' and not proof['deadline_exceeded'] and not store.runs(),draft_only=not store.runs(),definitions=len(definitions),capabilities=len(capabilities),layout_and_reference_verified=artifact_ok,cancellation_confirmed=root['state']=='cancelled' if cancelled else None)
            finally:service.shutdown();service=None;managers={}
        proof['authenticated_parent_stopped']=connection.get('stopped',False)
        proof['verified']=proof['verified'] and proof['authenticated_parent_stopped']
        events=[event for task in tasks.values() for event in task.get('events',[])]
        return dict(state=root.get('state','failed'),answer=root.get('answer',''),error=root.get('error',''),events=events,task_budget=root.get('task_budget')),proof,list(tasks),list(calls.values())
    finally:
        if service:service.shutdown()
        else:
            for manager in managers.values():manager.shutdown()
