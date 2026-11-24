"""Replay local tebb requests without sending their contents to a model."""
import argparse
from collections import Counter
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from desk_companion.observability.tool_monitor import collection
from desk_companion.pi_runtime.tool_routing import ToolRouter, search_receipt


def read_db(path):
    return sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)


def chosen_tools(response):
    names = {}
    for line in response.splitlines():
        if not line.startswith('data:'):
            continue
        payload = line[5:].strip()
        if not payload or payload == '[DONE]':
            continue
        for choice in json.loads(payload).get('choices', []):
            for call in (choice.get('delta') or {}).get('tool_calls') or []:
                index = call.get('index', 0)
                names[index] = names.get(index, '') + ((call.get('function') or {}).get('name') or '')
    return set(names.values())


def sample_records(memory):
    texts = {}
    for path in [memory/'tasks.sqlite3', *(memory/'collaboration').glob('*/tasks.sqlite3')]:
        if path.exists():
            with closing(read_db(path)) as db:
                texts.update(db.execute('SELECT id,text FROM tasks'))
    ws = memory/'collaboration/workspace.sqlite3'
    if ws.exists():
        with closing(read_db(ws)) as db:
            state = json.loads(db.execute('SELECT data FROM workspace WHERE id=1').fetchone()[0])
            for run in state['runs']:
                if run.get('parent'):
                    texts.pop(run.get('task'), None)
    logs = memory/'agent_debug'
    seen = set()
    dispatch = {"request_clarification", "start_background_task", "submit_plan", "submit_deliverable"}
    with closing(read_db(logs/'index.sqlite3')) as db:
        for ident, task in db.execute("""SELECT id,task_id FROM calls WHERE channel IN
                ('collaboration','desktop','feishu','video') AND state='complete' ORDER BY created,id"""):
            query = texts.get(task, '').strip()
            if not query or len(query)>200:
                continue
            req, res = logs/(ident+'.request.json'), logs/(ident+'.response.txt')
            if not req.exists() or not res.exists():
                continue
            payload = json.loads(req.read_bytes())
            specs = [t['function'] for t in payload.get('tools', []) if t.get('type')=='function']
            if len(specs)<2 or 'fixture' in payload.get('model','').lower():
                continue
            targets = chosen_tools(res.read_text(encoding='utf-8')) & {d['name'] for d in specs}
            business = targets - dispatch
            group = 'business' if business else 'dispatch'
            if targets and (group, query) not in seen:
                seen.add((group, query))
                yield group, query, [{**d, 'collection':collection(d['name'])} for d in specs], business or targets, task, ident


def samples(memory):
    for group, query, specs, targets, _, _ in sample_records(memory):
        yield group, query, specs, targets


def baseline(query, specs):
    found = [d for d in specs if query.strip().casefold() in
             (d['name']+' '+d['description']+' '+d['collection']).casefold()][:30]
    from desk_companion.observability.tool_monitor import fingerprint
    return dict(ok=True,tools=[dict(name=d['name'],description=d['description'],collection=d['collection'],
                version=fingerprint({**d,'source':'product'})) for d in found],
                loaded=[],scope='currently_authorized',protocol='application_discovery_completions')


# Matched literally in the request, independent of the tool that was called.
DOMAIN_KEYWORDS = ('日程', '会议', '天气', '文件夹', '目录', '文件', '代码', '搜索', '视频',
                   '项目', '仓库', '技术报告', '流程图', '模型', '待办', '工作流', '笔记')


def compare(memory):
    import tiktoken
    encoder = tiktoken.get_encoding('o200k_base')
    counts = {}
    for group, original, specs, targets in samples(memory):
        queries = [(group, original, targets)]
        if group=='business':
            keywords = [k for k in DOMAIN_KEYWORDS if k in original]
            if keywords:
                keyword = max(keywords, key=lambda k: (len(k), -original.index(k)))
                queries.append(('keyword_probe', keyword, targets))
            queries.extend(('exact_name', name, {name}) for name in sorted(targets))
        for scenario, query, expected in queries:
            for key, receipt in [('substring', baseline(query,specs)),
                                 ('router', search_receipt(ToolRouter(specs).search(query)))]:
                names = [d['name'] for d in receipt['tools']]
                row = counts.setdefault(scenario, {}).setdefault(key, Counter())
                row.update(samples=1, hits=int(bool(expected.intersection(names))),
                           top1=int(bool(expected.intersection(names[:1]))),
                           top3=int(bool(expected.intersection(names[:3]))), empty=int(not names),
                           candidates=len(names), tokens=len(encoder.encode_ordinary(
                               json.dumps(receipt,ensure_ascii=False,separators=(',',':')))))
    return counts


if __name__=='__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--memory',type=Path,required=True)
    print(json.dumps(compare(parser.parse_args().memory),indent=2))
