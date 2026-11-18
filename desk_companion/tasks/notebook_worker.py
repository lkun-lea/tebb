"""Run the existing notebook service under the existing task process supervisor."""
import json


def execute(request, emit):
    from desk_companion.chat.assistant import build_agent
    from desk_companion.chat.conversation import ConversationService
    from desk_companion.chat.chat_sessions import ChatSessionService
    from desk_companion.knowledge.notebook_service import NotebookService
    from desk_companion.models.model_catalog import bind_llm, require_active, require_item
    from desk_companion.models.sampling import parse_sampling

    conversation = ConversationService.for_session(request['session_id'])

    def engage():
        if conversation.agent is not None:
            return
        conversation.agent = build_agent(conversation)
        selected = require_item(request['model_id']) if request.get('model_id') else require_active()
        bind_llm(conversation.agent.llm, selected, timeout=request['limits']['call_timeout'])
        original = conversation.agent.llm.chat
        def chat(*args, **kwargs):
            emit('llm_start', dict(model=conversation.agent.llm.model))
            try:
                return original(*args, **kwargs)
            finally:
                emit('llm_end', {})
        conversation.agent.llm.chat = chat

    conversation.engage_model = engage
    service = NotebookService(ChatSessionService(conversation))
    try:
        found = service.run_notebook(request['notebook_session'], request['text'], request['doc_ids'],
            parse_sampling(request['sampling']), lambda piece: emit('token', piece), lambda text: emit('status', text))
        emit('notebook_result', found)
        if found['ok']:
            emit('result', json.dumps(dict(answer=found['answer'], cites=found['cites']), ensure_ascii=False))
        else:
            emit('failure', dict(type='NotebookGenerationFailed', message=found['error']))
    except Exception as exc:
        emit('failure', dict(type=type(exc).__name__, message='笔记任务未完成，请读取原笔记与任务回执核对。'))
