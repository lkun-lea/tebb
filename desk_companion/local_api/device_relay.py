"""Authenticated short-lived ciphertext snapshots for one paired Windows and Android."""
import base64
import binascii
import threading
import time

from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal


class Envelope(BaseModel):
    model_config = ConfigDict(extra='forbid')
    device: str = Field(pattern='^[a-f0-9]{32}$')
    stream: Literal['windows', 'phone']
    sealed: str = Field(min_length=40, max_length=262144)


def install_relay(app, authorize):
    snapshots = {}
    lock = threading.Lock()

    def expire(key, deadline):
        with lock:
            if key in snapshots and snapshots[key][0] == deadline:
                snapshots.pop(key)

    @app.post('/cloud/v1/device-snapshot')
    def publish(body: Envelope, request: Request):
        subject = authorize(request)
        key = (subject, body.device, body.stream)
        try:
            base64.b64decode(body.sealed, validate=True)
        except (ValueError, binascii.Error):
            raise HTTPException(422, '快照编码无效')
        with lock:
            if key not in snapshots and len(snapshots) >= 16:
                raise HTTPException(429, '请稍后重试')
            deadline = time.monotonic() + 45
            if key in snapshots:
                snapshots[key][2].cancel()
            timer = threading.Timer(45, expire, (key, deadline))
            timer.daemon = True
            snapshots[key] = (deadline, body.sealed, timer)
            timer.start()
        return {'stored': True}

    @app.get('/cloud/v1/device-snapshot')
    def read(request: Request, device: str, stream: Literal['windows', 'phone']):
        key = (authorize(request), device, stream)
        with lock:
            entry = snapshots.get(key)
            return {'sealed': entry[1] if entry and entry[0] > time.monotonic() else None}

