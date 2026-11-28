"""MuMu 待答卡验收。用独立任务、临时配对和真实账号中转，标准输入确认配对码。"""
import argparse
import base64
import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from desk_companion.accounts.account_store import AccountRuntime, AccountStore, profile_root
from desk_companion.accounts.service import AccountService
from desk_companion.local_api.mobile_pairing import MobilePairing
from desk_companion.local_api.paired_workspace import exchange
from desk_companion.planning.today import defaults
from desk_companion.collaboration.store import transaction
from tests.test_execution_flow import ExecutionFlowTests


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', required=True, action='store_true')
    parser.add_argument('--qr', type=Path, required=True, help='临时二维码 PNG，供 MuMu 图片选择器读取')
    parser.add_argument('--address', default='')
    parser.add_argument('--observation', type=Path, help='将隔离任务的桌面投影和原会话写入新的验收目录')
    args = parser.parse_args()
    home = Path.cwd()
    key = AccountStore(home).read()['selected']
    account = AccountService(AccountRuntime(home, key, profile_root(home, key)))
    def headers():
        with account.cloud_client() as cloud:
            return cloud.chat_authorization()
    flow = ExecutionFlowTests()
    flow.setUp()
    try:
        root = flow.send('今日看板隔离验收')
        flow.finish(root['id'], [flow.control('request_clarification', question='今日验收：评审需要多少分钟？')])
        question, = flow.service.mobile_questions()
        with transaction(flow.service.path) as (state, _):
            state['projects'].append(dict(id='today-demo', name='今日看板验收'))
            next(c for c in state['conversations'] if c['id'] == question['conversation'])['project_id'] = 'today-demo'
        prefs = defaults()
        prefs.update(project='today-demo', morning=dict(time='00:00', focus='both'))
        flow.service.today_board(prefs)
        if args.observation:
            args.observation.mkdir(exist_ok=False)
        def observe():
            if args.observation:
                state = dict(board=flow.service.today_board(), history=flow.service.shared_history([question['conversation']]))
                staged = args.observation / 'view.tmp'
                staged.write_text(json.dumps(state, ensure_ascii=False), encoding='utf-8')
                staged.replace(args.observation / 'view.json')
        observe()
        print('Windows 待答卡：', question['prompt'], flush=True)
        with tempfile.TemporaryDirectory() as tmp:
            pair = MobilePairing(tmp, key, account.mobile_active, lambda: flow.service, account.mobile_lease, headers)
            try:
                started = pair.desktop('start', address=args.address)
                with args.qr.open('xb') as output:
                    output.write(base64.b64decode(started['qr'].split(',', 1)[1]))
                try:
                    while pair.desktop()['state'] == 'waiting':
                        time.sleep(0.5)
                    pending = pair.desktop('pending')
                    if pending['state'] != 'pending':
                        raise RuntimeError('配对码已过期')
                    print('请从 MuMu 读取配对确认码并输入：', flush=True)
                    if input().strip() != str(pending['code']):
                        raise ValueError('配对码不匹配')
                    pair.desktop('approve_relay', pending['id'])
                    pair.desktop('share_history', question['conversation'])
                    while flow.service.mobile_questions():
                        exchange(pair, headers)
                        time.sleep(1)
                    exchange(pair, headers)
                    updates = flow.service.execution_status(root['id'])['updates']
                    assert len(updates) == 1
                    rows = flow.service.shared_history([question['conversation']])[0]['rows']
                    assert sum(row['kind'] == '原文' and row['text'] == updates[0] for row in rows) == 1
                    observe()
                    print('Windows 待答卡 0；原会话答复一次：', updates[0], flush=True)
                    for _ in range(10):
                        exchange(pair, headers)
                        time.sleep(1)
                finally:
                    args.qr.unlink(missing_ok=True)
            finally:
                pair.close()
    finally:
        flow.tearDown()


if __name__ == '__main__':
    main()
