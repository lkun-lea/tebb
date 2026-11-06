"""Read-only replay of explicitly registered native evaluation artifacts."""
import json
from collections import Counter
from pathlib import Path



def native_replay(folder):
    folder = Path(folder)
    result = json.loads((folder / 'result.json').read_text('utf-8'))
    if result['delivery'] not in {'succeeded', 'failed', 'timed_out', 'cancelled', 'interrupted'}:
        raise ValueError('仅登记已结束的原生实验')
    event_file = folder / 'events.jsonl'
    if event_file.stat().st_size > 2_000_000:
        raise ValueError('实验事件文件超过回放上限')
    events = [json.loads(line) for line in event_file.read_text('utf-8').splitlines() if line.strip()]
    events.sort(key=lambda e: e.get('seconds', 0))
    runs = result['runs']
    counts = Counter(e['task'] for e in events if e['kind'] == 'llm_start')
    # Old trials retained process task IDs but not their run ID relation. Assign
    # only when the recorded call count identifies exactly one run and one task.
    stages = {}
    for run in runs:
        if run.get('task'):
            stages[run['task']] = 0 if not run.get('parent') else 2 if run.get('integration_verification') else 1
    for task, count in counts.items():
        if task in stages:
            continue
        matches = [r for r in runs if r.get('calls') == count]
        if len(matches) == 1 and list(counts.values()).count(count) == 1:
            run = matches[0]
            stages[task] = 0 if not run.get('parent') else 1 if run['agent'] == 'coder' else 2
    steps = []
    delegated = False
    for event in events:
        kind, data = event['kind'], event['data']
        if kind not in {'llm_start', 'tool_start', 'tool_end', 'file_change', 'verification'}:
            continue
        name = data.get('tool') or {'llm_start':'调用模型', 'file_change':'修改文件', 'verification':'运行验证'}.get(kind, kind)
        if not delegated and stages.get(event['task']) == 1:
            steps.append(dict(stage=0, state='succeeded', label='已观察到编码任务启动',
                              note='已保存的父子任务关系及编码任务事件表明分工完成；未记录派发的精确时间。'))
            delegated = True
        bad = data.get('status') == 'failed' or (kind == 'verification' and data.get('exit_code') not in (None, 0))
        steps.append(dict(stage=stages.get(event['task']), state='failed' if bad else 'running',
                          label=str(name)[:200] + (' · 开始' if kind.endswith('start') else ' · 返回'),
                          note=str(data.get('error') or data.get('query') or data.get('command') or data.get('path') or '')[:2000],
                          seconds=event.get('seconds')))
    root = next(r for r in runs if not r.get('parent'))
    for run in runs:
        if run.get('parent') and run.get('calls', 0) > 0:
            steps.append(dict(stage=1 if run['agent'] == 'coder' else 2, state=run['state'],
                              label='任务结束', note=run.get('error') or run.get('status') or ''))
    scores = result.get('checks') or {}
    steps.append(dict(stage=3 if result['delivery']=='succeeded' else None, state=result['delivery'], label='实验结束',
                      note=root.get('error') or result.get('error') or '已结束', seconds=result.get('elapsed_s')))
    consumed = (result.get('budget') or {}).get('consumed') or {}
    return dict(model=result['model'], status=result['delivery'], steps=steps,
                checks=[dict(name=k, passed=v) for k,v in scores.items()],
                input_tokens=consumed.get('input_tokens'), output_tokens=consumed.get('output_tokens'),
                elapsed_s=result.get('elapsed_s'), starting_point=result.get('starting_point'),
                note='历史工具事件阶段按唯一模型调用次数对应；未能对应的事件不推进阶段。结束后固定测试独立展示，不代表团队执行过验收。')

