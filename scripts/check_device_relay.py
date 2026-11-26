"""显式检查个人 ECS 的密文中转。隔离运行与设备编号，使用当前桌面账号的正常鉴权。"""
import argparse
import base64
import json
import os
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from desk_companion.accounts.account_store import AccountRuntime, AccountStore, profile_root
from desk_companion.accounts.service import AccountService
from desk_companion.local_api.desktop_cloud_chat import ORIGIN
from desk_companion.local_api.paired_workspace import exchange, seal, unseal
from tests.test_execution_flow import ExecutionFlowTests


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', required=True)
    parser.add_argument('--home', type=Path, default=Path.cwd())
    args = parser.parse_args()
    home = args.home.resolve()
    selected = AccountStore(home).read()['selected']
    accounts = AccountService(AccountRuntime(home, selected, profile_root(home, selected)))
    with accounts.cloud_client() as cloud:
        headers = cloud.chat_authorization()
    flow = ExecutionFlowTests()
    flow.setUp()
    try:
        run = flow.send()
        flow.finish(run['id'], [flow.control('request_clarification', question='隔离验收：评审多长时间？')])
        q, = flow.service.mobile_questions()
        device = uuid.uuid4().hex
        key = os.urandom(32)
        with tempfile.TemporaryDirectory() as tmp, httpx.Client(headers=headers, timeout=15) as phone:
            path = Path(tmp) / 'approved.json'
            path.write_text(json.dumps(dict(account=selected, id=device, relay_key=base64.b64encode(key).decode(),
                                            shared_chats=[q['conversation']])), encoding='utf-8')
            pair = SimpleNamespace(calendar=None, lock=threading.RLock(),active=lambda:True,record=path,account=selected,collaboration=lambda:flow.service)
            endpoint = ORIGIN + '/cloud/v1/device-snapshot'
            params = dict(device=device, stream='windows')
            def read():
                sealed = phone.get(endpoint,params=params).raise_for_status().json()['sealed']
                return unseal(key,device,'windows',sealed)
            exchange(pair, lambda:headers)
            first = read()
            assert first['questions'] == [q] and first['history'][0]['id'] == q['conversation']
            request = dict(id=str(uuid.uuid4()),time=int(time.time()),action='answer',text='45 分钟',
                           **{field:q[field] for field in ('conversation','run','version')})
            phone.post(endpoint,json=dict(device=device,stream='phone',sealed=seal(key,device,'phone',request))).raise_for_status()
            exchange(pair, lambda:headers)
            result = read()
            assert result['ack']['id'] == request['id'] and result['ack']['accepted'] and not result['questions']
            exchange(pair, lambda:headers)
            assert flow.service.execution_status(q['run'])['updates'] == ['45 分钟']
            # 使用与产品隔离的日程、笔记和会话数据，只让真实账号承担中转鉴权。
            from desk_companion.planning.scheduling import SchedulingService
            from desk_companion.planning.work_board import WorkBoardService
            from desk_companion.knowledge.notebook import _read
            from tests.schedule_fixture import START, END, TimeCalendar
            with patch.dict(os.environ, DESK_COMPANION_DATA_DIR=tmp):
                pair.calendar = SchedulingService(WorkBoardService(), TimeCalendar()).local
                record = json.loads(path.read_text(encoding='utf-8'))
                record['write_grants'] = ['agent.request', 'calendar.create', 'note.create']
                path.write_text(json.dumps(record), encoding='utf-8')

                def submit(action, **fields):
                    message = dict(id=str(uuid.uuid4()), time=int(time.time()), action=action, **fields)
                    phone.post(endpoint, json=dict(device=device, stream='phone', sealed=seal(key,device,'phone',message))).raise_for_status()
                    exchange(pair, lambda:headers)
                    ack = read()['ack']
                    assert ack['id'] == message['id'] and ack.get('accepted'), ack.get('error')
                    return ack

                saved = submit('calendar.create', summary='验收评审', start=START, end=END)
                submit('calendar.update', event=saved['event'], version=saved['version'],
                       summary='已修改的评审', start=START, end=END)
                event, = submit('calendar.list')['events']
                assert event['summary'] == '已修改的评审' and event['id'] == saved['event']
                note = submit('note.create', title='中转验收', body='仅保存在隔离笔记本')
                assert _read()['sessions'][0]['notes'][0]['id'] == note['note']
                submit('agent.request', conversation=q['conversation'], text='整理隔离验收资料')
                assert len(flow.service.snapshot()['state']['runs']) == 2
            assert httpx.get(endpoint,params=params).status_code == 401
            time.sleep(46)
            assert phone.get(endpoint,params=params).raise_for_status().json()['sealed'] is None
            print('PASS 账号鉴权、授权原文、原问题版本、加密回复、Windows 回执、重复读取、45 秒过期。')
    finally:
        flow.tearDown()


if __name__ == '__main__':
    main()

