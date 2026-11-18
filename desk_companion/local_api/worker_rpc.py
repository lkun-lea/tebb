"""Authenticated worker access to existing parent-owned product services."""
import json
import os

def request(port, token, method, args=None, timeout=120):
    from urllib.request import Request, build_opener, ProxyHandler
    opener = build_opener(ProxyHandler({}))
    command = Request(f'http://127.0.0.1:{int(port)}/rpc',
        data=json.dumps(dict(method=method, args=args or {})).encode(),
        headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
    with opener.open(command, timeout=timeout) as response:
        envelope = json.load(response)
    if not envelope.get('ok'):
        raise RuntimeError(envelope.get('error', '后台调用失败'))
    return envelope['result']


def call(method, args=None, timeout=120):
    port,token=os.environ.get('DESK_TERMINAL_PORT'),os.environ.get('DESK_TERMINAL_TOKEN')
    if not port or not token:
        raise RuntimeError('当前执行未连接父后台，不能执行产品操作。')
    return request(port, token, method, args, timeout)
