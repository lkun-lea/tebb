"""Metadata-only adapters for existing collaboration and workflow owners."""
from desk_companion.infrastructure.paths import data_root
from desk_companion.observability.usage_store import read_rows


def owner_nodes(root,profile=None,collaboration_paths=None):
    from pathlib import Path
    directory=Path(profile)if profile is not None else data_root()
    nodes=[];edges=[];bindings={}
    note_refs=[]
    if root.startswith('collab:'):
        fields=['id','parent','task','agent','stage','round','state','created','finished','model_id']
        selected=','.join("json_extract(j.value,'$."+k+"') AS "+k for k in fields)
        rows=[]
        for path in collaboration_paths or [directory/'memory/collaboration/workspace.sqlite3']:
            found=read_rows(path,'SELECT '+selected+" FROM workspace,json_each(workspace.data,'$.runs') j WHERE workspace.id=1")
            if any(r['id']==root.removeprefix('collab:')for r in found):
                rows=found
                note_refs=read_rows(path, """
                    SELECT DISTINCT json_extract(ref.value, '$.id') AS id,
                                    json_extract(ref.value, '$.title') AS title
                    FROM workspace, json_each(workspace.data, '$.messages') AS msg,
                         json_each(msg.value, '$.note_refs') AS ref
                    WHERE workspace.id=1 AND json_extract(msg.value, '$.run')=?
                      AND json_extract(msg.value, '$.sender')='user'
                """, (root.removeprefix('collab:'),))
                break
        owners={root.removeprefix('collab:')};pending=list(rows)
        while pending:
            ready=[r for r in pending if r['parent'] in owners]
            if not ready:break
            for row in ready:
                owners.add(row['id']);pending.remove(row)
                ident='collab:'+row['id'];parent='collab:'+row['parent']
                nodes.append(dict(id=ident,kind='agent',label=(row['agent']or'Agent')+' · '+(row['stage']or'任务'),
                                  state=row['state'],started=row['created'],ended=row['finished'],agent=row['agent'],stage=row['stage'],round=row['round'],model_id=row['model_id']))
                edges.append(dict(id=parent+'>'+ident,source=parent,target=ident,relation='delegation'))
        for row in rows:
            if row['id'] in owners and row.get('task'):bindings[row['task']]='collab:'+row['id']
    elif root.startswith('workflow:'):
        ident=root.removeprefix('workflow:');path=directory/'memory/workflows.sqlite3'
        rows=read_rows(path,'SELECT node,kind,state,started,ended,receipt_key FROM receipts WHERE run=? ORDER BY started,node',(ident,))
        for row in rows:
            nid=root+':node:'+row['node'];nodes.append(dict(id=nid,kind='workflow_node',label=row['node']+' · '+row['kind'],
                state=row['state'],started=row['started'],ended=row['ended'],receipt_key=row['receipt_key']))
            edges.append(dict(id=root+'>'+nid,source=root,target=nid,relation='workflow_receipt'))
    return dict(nodes=nodes,edges=edges,task_bindings=bindings,note_refs=note_refs)


def task_checks(tasks,profile=None):
    """Attach only recorded phase/check metadata; bodies stay in the task owner."""
    nodes=[];edges=[]
    for relative in ('memory/tasks.sqlite3','memory/collaboration/work/tasks.sqlite3','memory/collaboration/chat/tasks.sqlite3'):
        path=(profile if profile is not None else data_root())/relative
        for offset in range(0,len(tasks),300):
            group=tasks[offset:offset+300]
            if not group:continue
            rows=read_rows(path,"SELECT task,seq,ts,kind,json_extract(data,'$.stage') AS stage,"
                           "json_extract(data,'$.ok') AS ok,json_extract(data,'$.completion') AS completion "
                           "FROM events WHERE task IN ("+','.join('?'for _ in group)+") AND kind IN ('worker_phase','knowledge','evidence','feedback_check','citation_check','execution_check') ORDER BY seq",group)
            for row in rows:
                ident='task-event:'+row['task']+':'+str(row['seq']);parent='physical:'+row['task']
                state='recorded'if row['ok']is None else'checked'if row['ok']else'failed'
                nodes.append(dict(id=ident,kind=row['kind'],label=row['stage']or row['kind'],state=state,
                    started=row['ts'],task=row['task'],sequence=row['seq'],completion=row['completion'],owner='task_events'))
                edges.append(dict(id=parent+'>'+ident,source=parent,target=ident,relation='recorded_check'))
    return dict(nodes=nodes,edges=edges)
