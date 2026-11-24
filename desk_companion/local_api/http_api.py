"""Loopback HTTP commands and replayable SSE over the existing product services."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import re
import socket
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from desk_companion.models.sampling import parse_sampling
from desk_companion.tasks.manager import TERMINAL


@asynccontextmanager
async def listening(backend, port, *, legacy=False):
    """Shared real listener for the application and authenticated evaluation parents."""
    import uvicorn
    app = create_app(backend)
    if legacy:
        from desk_companion.local_api.legacy_ws import install
        install(app, backend._handler)
    listener = socket.socket()
    listener.bind(('127.0.0.1', port))
    listener.listen(128)
    listener.setblocking(False)
    service = uvicorn.Server(uvicorn.Config(app, access_log=False, log_level='warning', lifespan='off',
                                          timeout_graceful_shutdown=2))
    async def run():
        try:
            await service.serve(sockets=[listener])
        finally:
            backend.SHUTDOWN.set()
    worker = asyncio.create_task(run())
    try:
        while not service.started:
            if worker.done():
                await worker
                raise RuntimeError('本地 HTTP 服务未启动。')
            await asyncio.sleep(.01)
        yield listener.getsockname()[1]
    finally:
        service.should_exit = True
        await worker
        listener.close()


class Command(BaseModel):
    model_config = ConfigDict(extra='forbid')
    method: str
    args: dict = Field(default_factory=dict)


class Submission(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: str = Field(pattern=r'^[A-Za-z0-9_-]{8,128}$')
    kind: Literal['chat', 'notebook'] = 'chat'
    text: str = Field(min_length=1, max_length=200000)
    session_id: str = Field(default='', max_length=200)
    sampling: dict = Field(default_factory=dict)
    chips: dict | None = None
    model_id: str = Field(default='', max_length=200)
    knowledge: bool = False
    doc_ids: list[str] = Field(default_factory=list, max_length=500)


def frame(kind, data, seq=None):
    prefix = f'id: {seq}\n' if seq is not None else ''
    return prefix + 'data: ' + json.dumps(dict(type=kind, data=data), ensure_ascii=False) + '\n\n'


def create_app(backend):
    # backend owns the frozen account runtime, token, services and shutdown event.
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(CORSMiddleware, allow_origins=[
        'tauri://localhost', 'http://tauri.localhost', 'https://tauri.localhost',
        'http://127.0.0.1:5180', 'http://localhost:5180',
    ], allow_methods=['GET', 'POST'], allow_headers=['Authorization', 'Content-Type', 'Last-Event-ID'])
    transient = {}

    def publish_thought(run_id, piece):
        for queue in transient.get(run_id, ()):
            if not queue.full():
                queue.put_nowait(piece)

    def authorize(request, *, preview=False):
        from desk_companion.collaboration.collaboration_access import preview_allowed
        value = request.headers.get('authorization', '')
        token = value.removeprefix('Bearer ') if value.startswith('Bearer ') else ''
        if backend.TOKEN and hmac.compare_digest(token.encode(), backend.TOKEN.encode()):
            return False
        if preview and preview_allowed(token, request.headers.get('origin', '')):
            return True
        raise HTTPException(401, '本地凭据无效或已过期，请重新连接当前账号。')

    from desk_companion.local_api.cloud_chat import install_public
    from desk_companion.local_api.desktop_cloud_chat import install_desktop
    install_public(app, backend)
    install_desktop(app, backend, authorize)

    def snapshot(run_id, after=0):
        if not re.fullmatch(r'[a-f0-9]{32}', run_id):
            raise HTTPException(404, '任务不存在。')
        try:
            return backend.HOST.tasks.event_snapshot(run_id, after)
        except ValueError:
            raise HTTPException(404, '任务不存在。') from None

    @app.middleware('http')
    async def no_cache(request, call_next):
        # Bound command bodies without buffering arbitrary input in the parser.
        if request.method == 'POST':
            size = 0
            body = bytearray()
            async for chunk in request.stream():
                size += len(chunk)
                if size > 2_000_000:
                    return JSONResponse({'detail': '请求过大。'}, status_code=413)
                body.extend(chunk)
            request._body = bytes(body)
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.get('/health')
    def health():
        return Response('ok\n', media_type='text/plain')

    @app.api_route('/shutdown', methods=['GET', 'POST'])
    async def shutdown(request: Request):
        authorize(request)
        backend.SHUTDOWN.set()
        return Response('shutting down\n', media_type='text/plain')

    @app.post('/rpc')
    async def rpc(request: Request, command: Command):
        preview = authorize(request, preview=True)
        if preview:
            from desk_companion.collaboration.service import METHODS
            if command.method not in METHODS:
                raise HTTPException(403, '此预览凭据仅允许协作操作。')
        result = await asyncio.to_thread(backend._dispatch, command.method, command.args, preview)
        return result

    def submit(command, loop):
        host = backend.HOST
        sampling = parse_sampling(command.sampling)
        session = command.session_id or host.state.session_id
        if command.kind == 'notebook' and not command.session_id:
            raise ValueError('笔记提问需要固定笔记会话。')
        # Resolve a missing selected-session field to the ORIGINAL admitted session
        # when a submit response was lost and selection has since changed.
        from desk_companion.tasks.manager import submission_task_id
        stable_id = submission_task_id('http:' + command.request_id)
        with host.tasks.db() as db:
            existing = db.execute('SELECT session FROM tasks WHERE id=?', (stable_id,)).fetchone()
        if existing and not command.session_id:
            session = existing['session']
        payload = {**command.model_dump(), 'session_id': session, 'sampling': sampling}
        fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        request = dict(sampling=sampling, model_id=command.model_id)
        if command.kind == 'notebook':
            request.update(workflow='notebook_qa', notebook_session=session, doc_ids=command.doc_ids)
        else:
            request.update(chips=command.chips, knowledge=command.knowledge)
        # The stable ID and full input fingerprint are stored in the same tasks row.
        # Account/workspace isolation comes from the existing frozen data directory.
        with host.turn_lock, host.tasks.cv:
            if command.kind == 'notebook' and host.conversation.running and not existing:
                raise RuntimeError('助手正在处理笔记操作，请稍后提交。')
            def callback(kind, data):
                if kind == 'think':
                    try:
                        loop.call_soon_threadsafe(publish_thought, stable_id, data)
                    except RuntimeError:
                        pass
            run_id = host.tasks.submit(command.text, ('notebook-' if command.kind == 'notebook' else '') + session,
                channel='notebook' if command.kind == 'notebook' else 'desktop',
                source=dict(transport='http', kind=command.kind, request_id=command.request_id),
                submission_key='http:' + command.request_id, submission_fingerprint=fingerprint, callback=callback, **request)
        return dict(run_id=run_id, request_id=command.request_id)

    @app.post('/v1/runs')
    async def create_run(request: Request, command: Submission):
        authorize(request)
        try:
            return await asyncio.to_thread(submit, command, asyncio.get_running_loop())
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(409 if '去重' in str(exc) else 400, str(exc)) from None

    @app.get('/v1/runs/{run_id}')
    async def get_run(request: Request, run_id: str):
        authorize(request)
        return await asyncio.to_thread(snapshot, run_id)

    @app.post('/v1/runs/{run_id}/cancel')
    async def cancel_run(request: Request, run_id: str):
        authorize(request)
        await asyncio.to_thread(snapshot, run_id)
        return await asyncio.to_thread(backend.HOST.tasks.cancel, run_id)

    @app.get('/v1/runs/{run_id}/events')
    async def run_events(request: Request, run_id: str, after: int = 0):
        authorize(request)
        try:
            after = int(request.headers.get('last-event-id', after))
            if after < 0:
                raise ValueError()
        except ValueError:
            raise HTTPException(400, '事件游标无效。') from None
        first = await asyncio.to_thread(snapshot, run_id, after)

        async def events():
            nonlocal after
            current = first
            queue = asyncio.Queue(maxsize=256)
            transient.setdefault(run_id, set()).add(queue)
            try:
                while True:
                    authorize(request)
                    if current['expired']:
                        after = current['cursor']
                        yield frame('snapshot', current, after)
                    else:
                        for event in current['events']:
                            after = event['seq']
                            yield frame(event['kind'], event['data'], after)
                    while not queue.empty():
                        yield frame('think', queue.get_nowait())
                    if current['task']['state'] in TERMINAL:
                        yield frame('settled', dict(task=current['task'], cursor=after))
                        return
                    yield ': heartbeat\n\n'
                    await asyncio.sleep(.15)
                    current = await asyncio.to_thread(snapshot, run_id, after)
            finally:
                transient[run_id].discard(queue)
                if not transient[run_id]:
                    del transient[run_id]
        return StreamingResponse(events(), media_type='text/event-stream', headers={'X-Accel-Buffering': 'no'})

    @app.get('/v1/notifications')
    async def notifications(request: Request, topic: Literal['all', 'board', 'collaboration'] = 'all'):
        preview = authorize(request, preview=True)
        if preview and topic == 'board':
            raise HTTPException(403, '预览凭据不能订阅事项数据。')
        loop = asyncio.get_running_loop()
        wake = asyncio.Event()
        pending = {}

        def enqueue(key, kind, data):
            def update():
                previous = pending.get(key)
                if kind == 'run_text' and previous and tuple(data['version']) <= tuple(previous[1]['version']):
                    return
                pending[key] = (kind, data)
                wake.set()
            try:
                loop.call_soon_threadsafe(update)
            except RuntimeError:
                pass

        async def events():
            off_text = (lambda: None) if topic == 'board' else backend.HOST.collaboration.subscribe_stream(lambda run, text, attempt, seq:
                enqueue(run, 'run_text', dict(run=run, text=text, version=[attempt, seq])))
            off_board = (lambda: None) if preview or topic == 'collaboration' else backend.HOST.work_board.subscribe_changes(
                lambda: enqueue('board', 'work_board_changed', None))
            try:
                if not preview and topic != 'collaboration':
                    yield frame('work_board_changed', None)
                while True:
                    try:
                        authorize(request, preview=True)
                    except HTTPException:
                        return
                    try:
                        await asyncio.wait_for(wake.wait(), 2)
                    except asyncio.TimeoutError:
                        yield ': heartbeat\n\n'
                        continue
                    wake.clear()
                    values = list(pending.values())
                    pending.clear()
                    for kind, data in values:
                        try:
                            authorize(request, preview=True)
                        except HTTPException:
                            return
                        yield frame(kind, data)
            finally:
                off_text()
                off_board()
        return StreamingResponse(events(), media_type='text/event-stream')

    @app.get('/pet-assets/{relative:path}')
    def pet_asset(request: Request, relative: str):
        # Preserve the existing restricted suffix list and traversal checks.
        return legacy_response(backend._pet_asset, request.url.path)

    @app.get('/news-cover/{relative:path}')
    def news_cover(request: Request, relative: str):
        return legacy_response(backend._news_cover, request.url.path + '?' + request.url.query)

    return app


def legacy_response(reader, path):
    """Reuse the existing asset validation while the legacy WS adapter is retired."""
    from types import SimpleNamespace
    def respond(status, text):
        return SimpleNamespace(status_code=status, body=text.encode(), headers={})
    result = reader(SimpleNamespace(respond=respond), path)
    return Response(result.body, status_code=result.status_code, headers=dict(result.headers))
