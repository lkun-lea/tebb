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


def create_calendar_entry(calendar, grants, device, request):
    if 'calendar.create' not in grants:
        raise PermissionError('这台电脑还未允许手机新增日程')
    if set(request) != {'id', 'action', 'summary', 'start', 'end'} or request['action'] != 'calendar.create':
        raise ValueError('日程操作无效')
    request_id = f'mobile-{device}-{UUID(request["id"]).hex}'
    result = calendar.save(dict(type='create', request_id=request_id, summary=request['summary'],
                                start=request['start'], end=request['end']))
    if not result['ok']:
        raise ValueError(result['error'])
    return dict(accepted=True, event=result['event']['local_id'], version=result['event']['local_version'])


def apply_request(service, device, request, now, *, calendar=None, grants=(), shared=()):
    UUID(request['id'])
    if not now - 30 < request['time'] <= now + 5:
        raise ValueError('请求已过期')
    if request.get('action') == 'agent.request':
        if 'agent.request' not in grants or request.get('conversation') not in shared:
            raise PermissionError('请先在电脑授权并共享目标会话')
        if set(request) != {'action', 'time', 'id', 'conversation', 'text'}:
            raise ValueError('任务参数无效')
        text = request['text']
        if not isinstance(text, str) or not 1 <= len(text.strip()) <= 4000:
            raise ValueError('任务说明须为 1 至 4000 字')
        conversation = request['conversation']
        service.action(dict(type='send', conversation=conversation, text=text.strip(), mode='task',
                            request_id=f'mobile-{device}-{UUID(request["id"]).hex}'))
        return dict(accepted=True, conversation=conversation)
    if request.get('action') == 'note.create':
        if 'note.create' not in grants:
            raise PermissionError('这台电脑还未允许手机新增笔记')
        if set(request) != {'action', 'time', 'id', 'title', 'body'}:
            raise ValueError('笔记操作无效')
        from desk_companion.knowledge.notebook import save_mobile_note
        note = save_mobile_note(device, str(UUID(request['id'])), request['title'], request['body'])
        return dict(accepted=True, note=note)
    if request.get('action') == 'calendar.list':
        if 'calendar.create' not in grants:
            raise PermissionError('电脑未授权手机维护本机日程')
        with calendar.board.workspace_transaction() as (state, _):
            own = [row for row in calendar.records(state).values()
                   if row['id'].startswith('mobile-' + device + '-')]
            own.sort(key=lambda row: row.get('updated_at', row['created_at']), reverse=True)
            return dict(accepted=True, events=[{k: row[k] for k in ('id', 'summary', 'start', 'end', 'version')}
                                                for row in own[:30]])
    if request.get('action') == 'calendar.update':
        if 'calendar.create' not in grants:
            raise PermissionError('电脑未授权手机维护本机日程')
        required = {'action', 'id', 'time', 'event', 'version', 'summary', 'start', 'end'}
        if set(request) != required or not isinstance(request['event'], str) or not request['event'].startswith('mobile-' + device + '-'):
            raise ValueError('仅可编辑这台手机新增的日程')
        result = calendar.save(dict(type='update', local_id=request['event'], version=request['version'],
                                   request_id=f'mobile-{device}-{UUID(request["id"]).hex}', summary=request['summary'],
                                   start=request['start'], end=request['end']), mobile_only=True)
        if not result['ok']:
            raise ValueError(result['error'])
        return dict(accepted=True, event=result['event']['local_id'], version=result['event']['local_version'])
    if request.get('action') == 'calendar.create':
        return create_calendar_entry(calendar, grants, device, {k: v for k, v in request.items() if k != 'time'})
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


def publish_presence(pair):
    """首版每个账号一台电脑。在线标记与配对凭据分开，密文只含名称和时间。"""
    import socket
    with pair.lock:
        key = pair._key()
    device = '0' * 32
    sealed = seal(key, device, 'presence', dict(computer=socket.gethostname(), time=int(time.time())))
    httpx.post(ORIGIN + '/cloud/v1/device-snapshot', headers=pair.relay_headers(),
               json=dict(device=device, stream='presence', sealed=sealed), timeout=6).raise_for_status()


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
                        result = apply_request(service, device, request, time.time(), calendar=pair.calendar,
                                               grants=latest.get('write_grants', []), shared=latest.get('shared_chats', []))
                    except PermissionError as exc:
                        result = dict(error=str(exc))
                    except ValueError as exc:
                        result = dict(error=str(exc)[:200])
                    except (KeyError, TypeError):
                        result = dict(error='原问题或请求已变化，请核对')
                    ack = dict(id=request.get('id'), **result)
                    latest['relay_ack'] = ack
                    tmp = pair.record.with_suffix('.tmp')
                    tmp.write_text(json.dumps(latest), encoding='utf-8')
                    os.replace(tmp, pair.record)
            workspace = service.mobile_workspace(latest.get('shared_chats', []))
            payload = dict(time=int(time.time()), device=device, ack=ack, grants=latest.get('write_grants', []), **workspace)
            sealed = seal(key, device, 'windows', payload)
        http.post(endpoint, json=dict(device=device, stream='windows', sealed=sealed)).raise_for_status()

