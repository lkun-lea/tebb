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


def main():
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('service',choices=['execution','evaluation']);parser.add_argument('operation')
    parser.add_argument('--payload',default='{}');parser.add_argument('--payload-file')
    args=parser.parse_args()
    address=os.environ.get('DESK_COMPANION_API_URL','');token=os.environ.get('DESK_COMPANION_API_TOKEN','')
    parsed=urlsplit(address)
    if parsed.scheme!='http'or parsed.hostname not in{'127.0.0.1','localhost','::1'}or parsed.username or parsed.password or not token:parser.error('需要本机 HTTP 地址与完整桌面认证令牌环境变量。')
    from pathlib import Path
    payload=json.loads(Path(args.payload_file).read_text('utf-8')if args.payload_file else args.payload)
    method='execution_inspect'if args.service=='execution'else'agent_evaluation'
    body=json.dumps(dict(method=method,args=dict(operation=args.operation,payload=payload))).encode()
    request=urllib.request.Request(address.rstrip('/')+'/rpc',data=body,headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
    with urllib.request.urlopen(request,timeout=30)as response:print(response.read().decode())


if __name__=='__main__':main()
