"""Synthetic memory checks over the ordinary durable partner/task pipeline."""
import json
import time
import uuid

from .agent_evals import json_answer,same_json,wait_task


def execute(spec,*,profile,workspace,model_id,timeout,command=None,progress=lambda _:None):
    from .collaboration import Collaboration
    from .tasks import TaskManager
    from . import facts,agent_debug
    from .memory_inspector import read_state
    from .context_sources import digest
    managers={};service=None;item=None;tasks=[];calls=[];expired=False
    proof=dict(verified=False,scope='synthetic_scoped_memory_actual_send_boundary')
    started=time.monotonic()
    try:
        for kind in ('chat','work'):
            managers[kind]=TaskManager(path=profile/'memory'/('memory-'+uuid.uuid4().hex+'-'+kind+'.sqlite3'),command=command)
        service=Collaboration(path=workspace,managers=managers,start=False)
        agent=next(a for a in service.snapshot()['state']['agents'] if a['id']=='writer')
        service.action(dict(type='agent',agent={**agent,'model':model_id,'tools':[],'memory':''},request_id=uuid.uuid4().hex))
        cid=next(c['id'] for c in read_state(service)['conversations'] if c['coordinator']=='writer')
        scope='project' if spec['scenario'] in {'project','foreign_project'} else 'user'
        if scope=='project':
            result=service.action(dict(type='create_project',name='合成记忆验收项目',request_id=uuid.uuid4().hex))
            project_id=result['state']['projects'][-1]['id']
            service.action(dict(type='move_conversation',id=cid,project_id=project_id,request_id=uuid.uuid4().hex))
            owner=project_id if spec['scenario']=='project' else 'unrelated-project'
        else:owner=''
        item=facts.change(dict(type='save',operation=uuid.uuid4().hex,text='合成记忆代号是 Cedar-217',scope=scope,owner=owner))
        if spec['scenario']=='disabled':
            item=facts.change(dict(type='disable',id=item['id'],version=item['version'],operation=uuid.uuid4().hex))
        service.action(dict(type='send',conversation=cid,text=spec['prompt'],mode='message',request_id=uuid.uuid4().hex))
        from .task_budgets import Ledger
        budget=Ledger().create('memory-eval:'+uuid.uuid4().hex,'memory_trial',min(timeout,90)*1000)
        from .collaboration import transaction
        with transaction(workspace) as (state,_):
            state['runs'][-1]['budget_id']=budget
        service.tick()
        run=read_state(service)['runs'][-1]
        ident=run['task'];tasks=[ident]
        progress(dict(task_id=ident,task_ids=tasks,root_run=run['id']))
        task,expired=wait_task(managers['chat'],ident,started+timeout)
        service.tick()
        calls=agent_debug.listing(task_id=ident)['items']
        selected=[];matched=False;unselected=False;tool_free=False
        if len(calls)==1:
            detail=agent_debug.detail(calls[0]['id'])
            sources=detail.get('meta',{}).get('sources',{})
            selection=sources.get('selection') or {}
            selected=[i['id'] for i in selection.get('selected',[])]
            matched=sources.get('request_sha256')==digest(detail['request']) and all(i['status']=='matched' for i in sources.get('messages',[]))
            unselected='Cedar-217' not in json.dumps(detail['request'],ensure_ascii=False)
            tool_free=not detail['request'].get('tools')
        wanted=spec['scenario'] in {'global','project','trial'}
        if spec['scenario']=='trial' and len(calls)==1:
            from .memory_inspector import trial_material,operate
            try:matched=matched and same_json(json_answer(task.get('answer','')),dict(code='Cedar-217'))
            except (ValueError,TypeError):matched=False
            original=calls[0]['id']
            material=trial_material(service,cid,original,{item['id']:'合成记忆代号是 Maple-217'})
            accepted=operate(service,lambda:managers['work'],cid,dict(type='trial_run',call_id=original,
                overrides={item['id']:'合成记忆代号是 Maple-217'},revision=material['revision'],operation=uuid.uuid4().hex))
            tasks.append(accepted['task_id']);progress(dict(task_ids=tasks))
            trial_task,trial_expired=wait_task(managers['work'],tasks[-1],started+timeout)
            expired=expired or trial_expired
            trial_calls=agent_debug.listing(task_id=tasks[-1])['items']
            calls.extend(trial_calls)
            if len(trial_calls)==1:
                trial_detail=agent_debug.detail(trial_calls[0]['id'])
                matched=matched and trial_detail.get('meta',{}).get('sources',{}).get('request_sha256')==digest(trial_detail['request'])
                tool_free=tool_free and not trial_detail['request'].get('tools')
                proof['original_memory_unchanged']=next(i for i in facts.read_facts() if i['id']==item['id'])['text']==item['text']
                matched=matched and proof['original_memory_unchanged']
            else:matched=False
            task=trial_task
        try:answer_ok=same_json(json_answer(task.get('answer','')),spec['expected'])
        except (ValueError,TypeError):answer_ok=False
        proof.update(verified=bool(task['state']=='succeeded' and answer_ok and matched and tool_free and ((item['id'] in selected) if wanted else unselected and item['id'] not in selected)),
                     answer_matches=answer_ok,actual_source_matches=matched,no_registered_tools=tool_free,
                     memory_selected=item['id'] in selected,scope=scope,scenario=spec['scenario'],deadline_exceeded=expired,
                     artifacts=[dict(kind='memory_call',call_id=c['id']) for c in calls])
        return task,proof,tasks,calls
    finally:
        if service:service.shutdown()
        else:
            for manager in managers.values():manager.shutdown()
        if item:
            facts.delete_user_fact(item['id'])
