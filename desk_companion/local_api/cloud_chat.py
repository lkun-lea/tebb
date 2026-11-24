"""Personal cloud chat. Only the configured, verified Supabase subject owns this session."""
import asyncio
import json
import logging
import os
from uuid import UUID

from fastapi import HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from desk_companion.accounts.personalization_cloud import CloudConfig, CloudError, PersonalizationCloud

log = logging.getLogger('uvicorn.error.cloud_chat')
log.setLevel(logging.INFO)


class Message(BaseModel):
    model_config = ConfigDict(extra='forbid')
    conversation: str = Field(default="", max_length=128, pattern=r"^[a-zA-Z0-9_-]*$")
    request_id: UUID
    text: str = Field(min_length=1, max_length=4000)


def owner(request):
    configured = os.getenv('TEBB_CHAT_OWNER', '')
    if not configured:
        raise HTTPException(503, '云端尚未配置账号。')
    scheme, _, token = request.headers.get('authorization', '').partition(' ')
    if scheme.lower() != 'bearer' or not token:
        raise HTTPException(401, '需要登录。')
    try:
        with PersonalizationCloud(CloudConfig.from_env(), token) as client:
            subject = client.verify_session()
    except CloudError as exc:
        log.warning('cloud_chat auth_failed code=%s', exc.code)
        raise HTTPException(401 if exc.code in {'unauthorized', 'invalid_session'} else 503,
                            '云账号验证失败。') from None
    if subject != configured:
        log.warning('cloud_chat owner_denied')
        raise HTTPException(403, '当前账号无权使用这台服务器。')
    return subject


def session_name(subject, conversation):
    return f"cloud-{subject}" + (f":{conversation}" if conversation else "")


def recent(tasks, subject, conversation=""):
    with tasks.db() as db:
        rows = db.execute('SELECT id,text,answer,state,error,created FROM tasks WHERE session=? AND channel=? '
                          'ORDER BY created DESC, id DESC LIMIT 20', (session_name(subject, conversation), 'desktop')).fetchall()
    return [dict(row) for row in reversed(rows)]


def install_public(app, backend):
    @app.get('/cloud/v1/tools')
    def tools(request: Request):
        owner(request)
        from desk_companion.chat.assistant import build_toolkit
        return {'tools': build_toolkit().to_openai_tools()}

    @app.post('/cloud/v1/messages')
    def submit(request: Request, message: Message):
        subject = owner(request)
        rid = str(message.request_id)
        try:
            run = backend.HOST.tasks.submit(message.text, session_name(subject, message.conversation), channel='desktop',
                source={'transport': 'cloud_chat', 'request_id': rid, 'model': 'qwen3:0.6b'},
                workflow='free_cloud_chat',
                submission_key=f'cloud:{subject}:{rid}')
        except (ValueError, RuntimeError) as exc:
            log.warning('cloud_chat submit_failed request_id=%s reason=%s', rid, type(exc).__name__)
            raise HTTPException(409, '提交失败，请用原请求编号重试。') from None
        log.info('cloud_chat accepted request_id=%s run_id=%s', rid, run)
        return {'run_id': run, 'request_id': rid}

    @app.get('/cloud/v1/events')
    async def events(request: Request, conversation: str = Query(default='', max_length=128, pattern=r'^[a-zA-Z0-9_-]*$')):
        subject = await asyncio.to_thread(owner, request)
        async def stream():
            previous = {}
            states = {}
            # Each reconnect rechecks the login and replays the latest durable turns.
            for tick in range(60):
                rows = await asyncio.to_thread(recent, backend.HOST.tasks, subject, conversation)
                if tick == 0:
                    yield 'data: {"type":"history","data":null}\n\n'
                for row in rows:
                    run = row['id']
                    if previous.get(run) != row:
                        if states.get(run) != row['state']:
                            log.info('cloud_chat observed run_id=%s state=%s', run, row['state'])
                            states[run] = row['state']
                        yield 'data: ' + json.dumps({'type':'turn','data':row}, ensure_ascii=False) + '\n\n'
                previous = {row['id']: row for row in rows}
                if tick % 10 == 0:
                    yield ': heartbeat\n\n'
                await asyncio.sleep(1)
        return StreamingResponse(stream(), media_type='text/event-stream', headers={'X-Accel-Buffering':'no'})
