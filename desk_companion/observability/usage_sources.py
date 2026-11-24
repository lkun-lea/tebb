"""Read-only composition of each domain's own task metadata projection."""
from desk_companion.infrastructure.paths import data_root
import sqlite3


def scope_metadata(scope):
    if scope is None:return dict(root='',task='',project_id=None,channel='operation',source='operation')
    root=scope.ledger.read(scope.member['id']);owner=root['owner'];kind,_,ident=owner.partition(':')
    origin=None
    try:
        if kind=='task':
            from desk_companion.tasks.manager import usage_origin
            origin=usage_origin(ident)
        elif kind=='collab':
            from desk_companion.collaboration.service import usage_origin
            origin=usage_origin(ident)
        elif kind=='workflow':
            from desk_companion.automation.workflows import usage_origin
            origin=usage_origin(ident)
    except (OSError,ValueError,sqlite3.Error):pass
    return dict(root=owner,task=scope.task,project_id=(origin or{}).get('project_id'),
        channel=(origin or{}).get('channel',None if kind in{'task','collab','workflow'}else'operation'),source={'collab':'collaboration'}.get(kind,kind),purpose=scope.member.get('purpose',''))


def task_metadata(profile=None,collaboration_paths=None,*,include_titles=False):
    from desk_companion.tasks.manager import usage_metadata as tasks
    from desk_companion.collaboration.service import usage_metadata as collaboration
    from desk_companion.automation.workflows import usage_metadata as workflows
    from pathlib import Path
    from desk_companion.tasks.task_budgets import Ledger
    directory=Path(profile)if profile is not None else data_root()
    ledger=Ledger(directory/'memory/task_budgets.sqlite3');roots=[];attempts=[]
    for relative in ('memory/tasks.sqlite3','memory/collaboration/work/tasks.sqlite3','memory/collaboration/chat/tasks.sqlite3'):
        result=tasks(directory/relative,ledger);roots.extend(result['tasks']);attempts.extend(result['attempts'])
    for path in collaboration_paths or [directory/'memory/collaboration/workspace.sqlite3']:roots.extend(collaboration(path,include_titles=include_titles))
    roots.extend(workflows(directory/'memory/workflows.sqlite3'))
    owners={r['id']:r for r in roots}
    for attempt in attempts:
        origin=owners.get(attempt['root'])
        attempt['queue']=attempt['channel']
        if origin:attempt.update(project_id=origin['project_id'],channel=origin['channel'])
        elif attempt['channel']=='collaboration':attempt['channel']=None
    return dict(tasks=list(owners.values()),attempts=list({r['id']:r for r in attempts}.values()))
