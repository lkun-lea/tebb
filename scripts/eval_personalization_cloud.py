"""Explicit synthetic-data acceptance for a dedicated Supabase test project.

This never reads existing tebb data. Without --live it does not contact any server.
The report journals IDs before writes so an ambiguous result can be reconciled.
"""
import argparse
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from desk_companion.personalization_cloud import CloudConfig, CloudError, PersonalizationCloud


def evaluate(clients, report, checkpoint):
    a, a2, b = clients
    owners = [client.verify_session() for client in clients]
    if owners[0] != owners[1] or owners[0] == owners[2]:
        raise CloudError('test_identity_mismatch', 'A/A2 必须属于同一测试账号，B 必须属于另一账号。')
    for client in clients:
        client.status()
    report['steps'].append('identities_verified')
    start = a.status()['revision']
    record = report['record_id']
    payload = {'kind':'memory','category':'other','text':'tebb synthetic acceptance '+record}

    def write(label, client, version, action, value):
        op = str(uuid4())
        report['operations'].append({'step':label,'operation_id':op,'expected_version':version,'action':action,'state':'pending'})
        checkpoint()
        result = client.apply(op,record,version,action,value)
        report['operations'][-1].update(state=result['status'],version=result['version'],cursor=result['cursor'])
        checkpoint()
        return result

    def current(client):
        cursor = start
        for _ in range(100):
            page = client.pull(cursor)
            for row in page['records']:
                if row['id'] == record:
                    return row
            if not page['has_more']:
                return None
            cursor = page['cursor']
        raise CloudError('test_page_limit', '测试账号同步量超出本次有界验收范围。')

    first = write('create',a,0,'put',payload)
    if first['status'] != 'applied' or first['version'] != 1:
        raise CloudError('test_create_failed', '合成记录创建未得到预期回执。')
    report['cleanup'] = 'needed'
    checkpoint()
    try:
        observed = current(a2)
        if not observed or observed['text'] != payload['text']:
            raise CloudError('test_device_read_failed', '第二设备没有读到同一账号的合成记录。')
        if b.operation(first['operation_id'])['found']:
            raise CloudError('test_isolation_failed', '另一账号读到了不属于自己的操作。')
        # B has its own cursor space: scan from zero, not A's cursor.
        cursor = 0
        for _ in range(100):
            page = b.pull(cursor)
            if any(row['id'] == record for row in page['records']):
                raise CloudError('test_isolation_failed', '另一账号读到了合成记录。')
            if not page['has_more']:
                break
            cursor = page['cursor']
        else:
            raise CloudError('test_page_limit', '另一测试账号数据超出验收范围。')
        report['steps'].append('cross_device_read_and_user_isolation')
        changed = write('device_two_update',a2,1,'put',payload|{'text':payload['text']+' updated'})
        stale = write('stale_device_update',a,1,'put',payload)
        if changed['status'] != 'applied' or changed['version'] != 2 or stale['status'] != 'conflict':
            raise CloudError('test_conflict_failed', '旧版本写入未明确冲突。')
        if a.operation(stale['operation_id'])['receipt'] != stale:
            raise CloudError('test_receipt_failed', '操作查询与原回执不一致。')
        report['steps'].append('version_conflict_and_receipt_lookup')
        removed = write('delete',a,2,'delete',None)
        tombstone = current(a2)
        if removed['status'] != 'applied' or not tombstone or tombstone['state'] != 'deleted' or tombstone['text'] is not None:
            raise CloudError('test_delete_failed', '删除结果未同步为无正文墓碑。')
        resurrect = write('resurrection_attempt',a2,3,'put',payload)
        retry = a.apply(first['operation_id'],record,0,'put',payload)
        if resurrect['status'] != 'gone' or retry != first or current(a2)['state'] != 'deleted':
            raise CloudError('test_resurrection_failed', '删除或幂等重试结果不符合契约。')
        report['steps'].append('deletion_and_no_resurrection')
        report['cleanup'] = 'tombstone_confirmed'
    finally:
        if report['cleanup'] != 'tombstone_confirmed':
            try:
                item = current(a)
                if item and item['state'] == 'deleted':
                    report['cleanup'] = 'tombstone_confirmed'
                elif item and item['text'].startswith(payload['text']):
                    cleaned = write('cleanup',a,item['version'],'delete',None)
                    report['cleanup'] = 'tombstone_confirmed' if cleaned['status']=='applied' else 'needs_reconciliation'
                else:
                    report['cleanup'] = 'needs_reconciliation'
            except CloudError:
                report['cleanup'] = 'needs_reconciliation'
            checkpoint()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live',action='store_true',help='explicitly write only synthetic records to a dedicated test project')
    parser.add_argument('--report',type=Path,help='local journal/report path; required for live writes')
    args = parser.parse_args()
    if not args.live:
        print(json.dumps({'status':'not_run','reason':'Live acceptance requires explicit --live and a dedicated test project.'}))
        return 2
    if args.report is None or os.environ.get('TEBB_CLOUD_TEST_PROJECT') != '1':
        print(json.dumps({'status':'not_run','reason':'Set TEBB_CLOUD_TEST_PROJECT=1 and supply --report for a disposable test project.'}))
        return 2
    if args.report.exists():
        print(json.dumps({'status':'not_run','reason':'Report exists. Reconcile its pending IDs before starting a new run.'}))
        return 2
    report = {'status':'running','record_id':str(uuid4()),'operations':[],'steps':[],'cleanup':'not_created'}
    args.report.parent.mkdir(parents=True,exist_ok=True)
    try:
        with args.report.open('x',encoding='utf-8') as target:
            target.write(json.dumps(report,ensure_ascii=False,indent=2))
    except FileExistsError:
        print(json.dumps({'status':'not_run','reason':'Another run reserved this report; use its existing operation journal.'}))
        return 2
    def checkpoint():
        args.report.parent.mkdir(parents=True,exist_ok=True)
        pending = args.report.with_suffix(args.report.suffix+'.tmp')
        pending.write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf-8')
        pending.replace(args.report)
    clients = []
    try:
        config = CloudConfig.from_env()
        used_tokens = set()
        for suffix in ('A','A2','B'):
            token = os.environ.get('TEBB_CLOUD_TEST_TOKEN_'+suffix,'')
            if not token:
                raise CloudError('needs_test_sessions','需要两个测试账号、三个独立已登录会话的访问令牌。')
            if token in used_tokens:
                raise CloudError('needs_distinct_sessions','请为三个独立登录会话提供不同的短期访问令牌。')
            used_tokens.add(token)
            clients.append(PersonalizationCloud(config,token))
        checkpoint()
        evaluate(clients,report,checkpoint)
        report['status'] = 'passed'
    except CloudError as exc:
        report.update(status='failed',error_code=exc.code,error=str(exc))
        if report['operations'] and report['operations'][0]['state']=='pending':
            report['cleanup'] = 'needs_reconciliation'
    finally:
        for client in clients:
            client.close()
        checkpoint()
    print(json.dumps({'status':report['status'],'steps':report['steps'],'cleanup':report['cleanup']},ensure_ascii=False))
    return 0 if report['status']=='passed' else 1


if __name__=='__main__':raise SystemExit(main())
