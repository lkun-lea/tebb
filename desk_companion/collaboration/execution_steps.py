"""Bind observed tool activity to the published checklist."""
def step_tools(tools, count):
    if not count:
        return tools
    result = []
    for tool in tools:
        function = tool['function']
        schema = function.get('parameters', {})
        if function['name'] == 'submit_deliverable' or schema.get('type') != 'object':
            result.append(tool)
            continue
        properties = {**schema.get('properties', {}), 'execution_step': dict(
            type='integer', minimum=1, maximum=count, description='本次工具调用对应的已发布清单序号，从 1 开始。')}
        result.append({**tool, 'function': {**function, 'parameters': {**schema, 'properties': properties}}})
    return result


def attach_activity(run, task, event):
    data = event['data']
    index = data['step']
    if type(index) is not int or not 1 <= index <= len(run.get('execution_steps', [])):
        return
    calls = run['execution_steps'][index-1].setdefault('calls', [])
    record = next((r for r in calls if r['task'] == task and r['call_id'] == data['call_id']), None)
    if record is None:
        record = dict(task=task, call_id=data['call_id'], tool=data['tool'], started=event['ts'])
        calls.append(record)
    record['state'] = data['state']
    if data['state'] != 'running':
        record['ended'] = event['ts']

def revision_tool(count):
    return dict(type='function', function=dict(name='revise_execution_steps',
        description='在执行业务工具前按用户修订更新原清单。只列受影响步骤及其新范围或时间；保留已有成果。没有影响时传空列表。',
        parameters=dict(type='object', properties=dict(changes=dict(type='array', maxItems=count,
            items=dict(type='object', properties=dict(step=dict(type='integer', minimum=1, maximum=count),
                note=dict(type='string', maxLength=300)), required=['step','note'], additionalProperties=False))),
            required=['changes'], additionalProperties=False)))


def revision_changes(value, count):
    changes = value.get('changes') if isinstance(value, dict) else None
    if not isinstance(changes, list) or len(changes) > count:
        raise ValueError('执行清单修订无效。')
    seen = set()
    for change in changes:
        if (not isinstance(change, dict) or set(change) != {'step', 'note'}
                or type(change['step']) is not int or not 1 <= change['step'] <= count or change['step'] in seen
                or not isinstance(change['note'], str) or not 1 <= len(change['note'].strip()) <= 300):
            raise ValueError('修订须使用现有步骤序号并说明变化。')
        seen.add(change['step'])
    return changes
