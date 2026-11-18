"""Actual product/Pi worker; only two bounded local tools are synthetic."""
import os
from pathlib import Path
from unittest.mock import patch

from desk_companion.chat import assistant
from desk_companion.pi_runtime import chat_agent
from desk_companion.tasks.worker import main

original_build=assistant.build_agent
OriginalBridge=chat_agent.PiBridge


class MarkedBridge(OriginalBridge):
    def __enter__(self):
        bridge=super().__enter__()
        (Path(os.environ['DESK_COMPANION_DATA_DIR'])/'pi-chat.pid').write_text(str(self.process.pid))
        return bridge


def build(host):
    agent=original_build(host)
    root=Path(os.environ['DESK_COMPANION_DATA_DIR'])
    def add(args):
        (root/'read_called').write_text('1')
        return args['a']+args['b']
    def write(args):
        path=root/'write_count'
        path.write_text(str(int(path.read_text())+1 if path.exists()else 1))
        return dict(ok=False,operation=dict(id='pi-write-original',state='unknown'),change_state='unconfirmed')
    agent.tools.register(name='probe_add',description='Isolated local addition',parameters=dict(type='object',
        properties=dict(a=dict(type='integer'),b=dict(type='integer')),required=['a','b']),func=add,isReadOnly=True)
    agent.tools.register(name='probe_write',description='Isolated local simulated lost write receipt',parameters=dict(type='object',
        properties=dict(attempt=dict(type='string')),required=['attempt']),func=write,retry_max=0)
    return agent


with patch.object(assistant,'build_agent',build),patch.object(chat_agent,'PiBridge',MarkedBridge):main()
