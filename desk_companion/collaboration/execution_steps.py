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
