"""同账号配对桌面的短时状态。密钥及原始材料保留在端上。"""
import base64
import hashlib
import json
import os
import time
from uuid import UUID

import httpx
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from desk_companion.local_api.desktop_cloud_chat import ORIGIN


def seal(key, device, stream, value):
    nonce = os.urandom(12)
    aad = ('tebb-v1/' + device + '/' + stream).encode()
    plain = json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode()
    return base64.b64encode(nonce + AESGCM(key).encrypt(nonce, plain, aad)).decode()


def unseal(key, device, stream, sealed):
    raw = base64.b64decode(sealed, validate=True)
    aad = ('tebb-v1/' + device + '/' + stream).encode()
    return json.loads(AESGCM(key).decrypt(raw[:12], raw[12:], aad))


def apply_request(service, device, request, now):
    UUID(request['id'])
    if not now - 30 < request['time'] <= now + 5:
        raise ValueError('请求已过期')
    fields = {k: request[k] for k in ('run', 'version', 'conversation')}
    if request['action'] == 'defer':
        return service.defer_question(fields['conversation'], fields['run'], fields['version'], request['until'])
    if request['action'] != 'answer' or not isinstance(request['text'], str) or not 1 <= len(request['text']) <= 4000:
        raise ValueError('回复无效')
    # 与局域网发送共用持久回执，即使换网络也只恢复一次原运行。
    parts = [device, fields['conversation'], fields['run'], fields['version'], request['text']]
    digest = hashlib.sha256(json.dumps(parts, ensure_ascii=False).encode()).hexdigest()
    service.action(dict(type='send', conversation=fields['conversation'], run=fields['run'],
                        question_version=fields['version'], text=request['text'], request_id='mobile-'+digest))
    return dict(run=fields['run'], version=fields['version'], accepted=True)


def exchange(pair, headers):
    with pair.lock:
        if not pair.active() or not pair.record.exists():
            return
        record = json.loads(pair.record.read_text(encoding='utf-8'))
        if not record.get('relay_key') or record.get('account') != pair.account:
            return
        device = record['id']
        key = base64.b64decode(record['relay_key'])
    endpoint = ORIGIN + '/cloud/v1/device-snapshot'
    with httpx.Client(headers=headers(), timeout=6, follow_redirects=False) as http:
        incoming = http.get(endpoint, params=dict(device=device, stream='phone')).raise_for_status().json()['sealed']
        with pair.lock:
            if not pair.active() or not pair.record.exists():
                return
            latest = json.loads(pair.record.read_text(encoding='utf-8'))
            if latest['id'] != device:
                return
            service = pair.collaboration()
            ack = latest.get('relay_ack')
            if incoming:
                request = unseal(key, device, 'phone', incoming)
                if not ack or ack.get('id') != request.get('id'):
                    try:
                        result = apply_request(service, device, request, time.time())
                    except (KeyError, ValueError, TypeError):
                        result = dict(error='原问题或请求已变化，请核对')
                    ack = dict(id=request.get('id'), **result)
                    latest['relay_ack'] = ack
                    tmp = pair.record.with_suffix('.tmp')
                    tmp.write_text(json.dumps(latest), encoding='utf-8')
                    os.replace(tmp, pair.record)
            workspace = service.mobile_workspace(latest.get('shared_chats', []))
            payload = dict(time=int(time.time()), device=device, ack=ack, **workspace)
            sealed = seal(key, device, 'windows', payload)
        http.post(endpoint, json=dict(device=device, stream='windows', sealed=sealed)).raise_for_status()

