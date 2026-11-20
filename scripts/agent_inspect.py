"""Machine-readable queries through the normal full-token local RPC boundary.

Example: uv run --locked python scripts/agent_inspect.py execution list --payload '{}'
Uses DESK_COMPANION_API_URL and DESK_COMPANION_API_TOKEN; never prints the token.
"""
import argparse
import json
import os
import sys
from urllib.parse import urlsplit
import urllib.request
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def main():
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('service',choices=['execution','evaluation','selftest']);parser.add_argument('operation')
    parser.add_argument('--payload',default='{}');parser.add_argument('--payload-file')
    args=parser.parse_args()
    payload=json.loads(Path(args.payload_file).read_text('utf-8')if args.payload_file else args.payload)
    if args.service=='selftest':
        from desk_companion.evaluation.self_test import SelfTestService, validate
        validate(args.operation,payload)
        if args.operation in {'catalog','describe'}:
            print(json.dumps(dict(ok=True,result=SelfTestService(None).operate(args.operation,payload)),ensure_ascii=False))
            return
    address=os.environ.get('DESK_COMPANION_API_URL','');token=os.environ.get('DESK_COMPANION_API_TOKEN','')
    parsed=urlsplit(address)
    if parsed.scheme!='http'or parsed.hostname not in{'127.0.0.1','localhost','::1'}or parsed.username or parsed.password or not token:parser.error('需要本机 HTTP 地址与完整桌面认证令牌环境变量。')
    method={'execution':'execution_inspect','evaluation':'agent_evaluation','selftest':'agent_self_test'}[args.service]
    body=json.dumps(dict(method=method,args=dict(operation=args.operation,payload=payload))).encode()
    request=urllib.request.Request(address.rstrip('/')+'/rpc',data=body,headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
    with urllib.request.urlopen(request,timeout=30)as response:print(response.read().decode())


if __name__=='__main__':main()
