"""Record Pi's actual provider payload/decoded frames in the existing call inspector."""
import json
import time
from types import SimpleNamespace

from desk_companion.observability import agent_debug as debug
from desk_companion.observability.usage_observer import current_model_attempt, http_returned, _safe


class PiObserver:
    def __init__(self, endpoint):
        self.endpoint = endpoint
        self.call_id = None
        self.handle = None
        self.started = time.monotonic()
        self.first = None
        self.lost = False
        self.status = None

    def sending(self, payload):
        attempt = current_model_attempt()
        if attempt:
            _safe(attempt.observe,payload)
            self.handle = attempt.sending()
        try:
            if debug.settings()['enabled']:
                request = SimpleNamespace(url=self.endpoint, content=json.dumps(payload, ensure_ascii=False).encode())
                self.call_id = debug.begin(request, payload)
                path = debug.root()/(self.call_id+'.meta.json')
                metadata = json.loads(path.read_text('utf-8')) if path.exists() else {}
                metadata.update(transport='pi', response_format='provider_sse_json_reencoded_or_http_error_body',
                                usage_call_id=attempt.id if attempt else None)
                from desk_companion.infrastructure.storage import atomic_write
                atomic_write(path, metadata)
        except Exception:
            self.lost = True
            if self.call_id:
                debug.safe_update(self.call_id, state='recording_failed', error='TraceWriteError')

    def event(self, kind, data):
        if kind in {'text_delta','thinking_delta'}and isinstance(data,str)and data:
            attempt=current_model_attempt()
            if attempt:
                attempt.output_received()
                if kind=='text_delta':attempt.text_received()
        if kind == 'http_status':
            self.status = data['status']
            http_returned(self.handle, status=data['status'])
            if self.call_id:
                debug.safe_update(self.call_id, status=data['status'], state='receiving', updated=time.time())
        elif kind == 'provider_frame' and self.call_id:
            if self.first is None:
                self.first = round((time.monotonic()-self.started)*1000)
            if not debug.safe_append(self.call_id, ('data: '+json.dumps(data, ensure_ascii=False)+'\n\n').encode()):
                self.lost = True
        elif kind == 'provider_error' and self.call_id:
            if not debug.safe_append(self.call_id, data['body'].encode()):
                self.lost = True

    def finish(self, error=None):
        if error:
            http_returned(self.handle, status=self.status, error=error)
        if self.call_id:
            state = 'recording_failed' if self.lost else (
                'cancelled' if type(error).__name__ == 'ChatCancelledError' else 'failed' if error else 'complete')
            debug.safe_update(self.call_id, state=state, updated=time.time(),
                duration_ms=round((time.monotonic()-self.started)*1000), first_byte_ms=self.first or 0,
                error=type(error).__name__ if error else '')
