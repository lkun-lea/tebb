"""Temporary compatibility for old local callers; new clients use HTTP/SSE."""
from types import SimpleNamespace

from fastapi import WebSocket, WebSocketDisconnect
from websockets.exceptions import ConnectionClosed


def install(app, handler):
    class Adapter:
        def __init__(self, socket):
            self.socket = socket
            self.request = SimpleNamespace(path=socket.url.path + '?' + socket.url.query, headers=socket.headers)

        async def send(self, text):
            try:
                await self.socket.send_text(text)
            except (WebSocketDisconnect, RuntimeError):
                raise ConnectionClosed(None, None) from None

        async def close(self, code=1000, reason=''):
            await self.socket.close(code=code, reason=reason)

        def __aiter__(self):
            return self.socket.iter_text()

        async def wait_closed(self):
            try:
                while True:
                    await self.socket.receive_text()
            except WebSocketDisconnect:
                pass

    @app.websocket('/ws')
    @app.websocket('/collaboration')
    @app.websocket('/stream')
    async def legacy(socket: WebSocket):
        await socket.accept()
        try:
            await handler(Adapter(socket))
        except (ConnectionClosed, WebSocketDisconnect):
            pass
