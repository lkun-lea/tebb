"""Isolated process fixture for real HTTP/SSE task lifecycle tests."""
import json
import sys
import time

request = json.loads(sys.stdin.readline())

def emit(kind, data):
    print(json.dumps(dict(kind=kind, data=data), ensure_ascii=False), flush=True)

if request.get('workflow') == 'notebook_qa':
    from unittest.mock import patch
    from types import SimpleNamespace
    from atlas.testing import FakeLLM
    from desk_companion.tasks import task_budgets
    from desk_companion.tasks.notebook_worker import execute

    def answer(question, docs, complete):
        return dict(answer=complete('Isolated sources', question), cites=[dict(n=1,doc='fixture',title='source',text='isolated source',doc_id='fixture')])
    with (task_budgets.installed(request['task_id'], emit),
          patch('desk_companion.chat.assistant.build_agent', return_value=SimpleNamespace(llm=FakeLLM(['HTTP笔记完整回答。']))),
          patch('desk_companion.models.model_catalog.require_active', return_value={}),
          patch('desk_companion.models.model_catalog.bind_llm'),
          patch('desk_companion.knowledge.index.ask_sources', side_effect=answer)):
        execute(request, emit)
else:
    emit('llm_start', dict(model='offline-http-fixture'))
    emit('token', '隔离片段')
    emit('think', '不持久保存的思考')
    if request['text'] == 'wait':
        time.sleep(30)
    else:
        time.sleep(.4)
        emit('llm_end', {})
        emit('result', '隔离片段完成')
