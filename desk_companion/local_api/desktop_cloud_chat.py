"""Relay cloud chat and tool discovery to the pinned tebb HTTPS origin."""
import asyncio

from pydantic import Field
from fastapi import HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask

from desk_companion.accounts.personalization_cloud import CloudError
from desk_companion.local_api.cloud_chat import Message

ORIGIN = 'https://8.136.145.17'


class DesktopMessage(Message):
    """本机项目只用于检查目录授权，转发前移除此字段。"""
    project_id: str = Field(default="", max_length=128)


def install_desktop(app, backend, authorize):
    def credentials():
        try:
            with backend.HOST.accounts.cloud_client() as cloud:
                return cloud.chat_authorization()
        except CloudError as exc:
            raise HTTPException(401 if exc.code == 'needs_login' else 503, str(exc)) from None

    async def connect(request, path, message=None, method=None):
        import httpx
        authorize(request)
        headers = await asyncio.to_thread(credentials)
        client = httpx.AsyncClient(timeout=httpx.Timeout(20, connect=6), follow_redirects=False)
        try:
            upstream = await client.send(client.build_request(method or request.method, ORIGIN + '/cloud/v1/' + path,
                headers=headers, json=message), stream=True)
            if upstream.status_code != 200:
                raise HTTPException(upstream.status_code, f'云端返回 HTTP {upstream.status_code}。')
            return client, upstream
        except httpx.RequestError:
            await client.aclose()
            raise HTTPException(502, '连接云端 HTTPS 失败。') from None
        except BaseException:
            await client.aclose()
            raise

    @app.post('/desktop/cloud/tools')
    async def catalog(request: Request):
        import json
        from desk_companion.chat.assistant import build_toolkit
        from desk_companion.observability.tool_monitor import ToolMonitor
        client, result = await connect(request, 'tools', method='GET')
        try:
            remote = json.loads(await result.aread())['tools']
            names = {item['function']['name'] for item in remote}
            compatible = [spec for spec in build_toolkit().to_openai_tools() if spec['function']['name'] in names]
            definitions = await asyncio.to_thread(ToolMonitor().register, compatible)
            return {'available': len(names), 'loaded': len(definitions)}
        finally:
            await result.aclose()
            await client.aclose()

    @app.post('/desktop/cloud/messages')
    async def submit(request: Request, message: DesktopMessage):
        import json
        authorize(request)
        service = backend.HOST.collaboration if message.conversation else None
        body = message.model_dump(mode='json', exclude={'project_id', 'local_history'})
        if message.conversation:
            try:
                body["local_history"] = await asyncio.to_thread(service.validate_cloud_conversation, message.conversation, message.project_id)
            except ValueError as exc:
                raise HTTPException(409, str(exc)) from None
        if len(json.dumps(body, ensure_ascii=False).encode()) > 32000 or len(body.get('local_history', [])) > 500:
            raise HTTPException(413, '会话超过云端上下文容量，请在本地继续。')
        client, result = await connect(request, 'messages', body)
        try:
            receipt = json.loads(await result.aread())
            if message.conversation:
                await asyncio.to_thread(service.action, dict(type='cloud_conversation',
                    request_id='cloud-'+str(message.request_id), conversation=message.conversation, text=message.text, project_id=message.project_id))
            return receipt
        finally:
            await client.aclose()

    @app.get('/desktop/cloud/events')
    async def events(request: Request, conversation: str = Query(default='', max_length=128, pattern=r'^[a-zA-Z0-9_-]*$')):
        authorize(request)
        service = backend.HOST.collaboration if conversation else None
        client, result = await connect(request, 'events' + ('?conversation=' + conversation if conversation else ''))
        if not result.headers.get('content-type','').startswith('text/event-stream'):
            await client.aclose()
            raise HTTPException(502, '云端事件流格式错误。')
        async def replay():
            import json
            async for line in result.aiter_lines():
                if conversation and line.startswith('data: '):
                    event = json.loads(line[6:])
                    if event['type'] == 'turn' and event['data']['state'] not in ('queued', 'running'):
                        await asyncio.to_thread(service.record_cloud_turn, conversation, event['data'])
                yield line + '\n'
        return StreamingResponse(replay(), media_type='text/event-stream',
                                 background=BackgroundTask(client.aclose))
