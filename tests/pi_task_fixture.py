"""A TaskManager-owned Python worker exercising its real Node descendant."""
import json
import sys

from desk_companion.infrastructure.paths import data_root
from desk_companion.pi_runtime.bridge import PiBridge

request = json.loads(sys.stdin.readline())
def emit(kind, data):
    print(json.dumps(dict(kind=kind, data=data)), flush=True)

with PiBridge() as bridge:
    (data_root() / 'pi-child.pid').write_text(str(bridge.process.pid))
    def receive(kind, data):
        if kind == 'text_delta':
            emit('token', data)
    bridge.call('complete', request['pi_payload'], before_model=lambda data: emit('llm_start', {}),
                on_event=receive, timeout=15)
    emit('result', '40')
