import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from desk_companion.observability.redaction import redact,debug_detail
from desk_companion.observability import agent_debug


class DiagnosticRedactionTests(unittest.TestCase):
    def test_credentials_and_signed_urls_are_masked_without_destroying_schema_or_public_sources(self):
        raw=dict(api_key='opaque-test-value',headers={'Authorization':'Bearer token-that-must-not-leak'},
            schema=dict(properties=dict(api_key=dict(type='string'))),
            message='api_key=opaque-test-value https://user:password@example.test/file?X-Amz-Signature=original-signature&name=private-file',
            source='https://example.test/source?q=%E4%B8%AD%E6%96%87&n=2')
        raw['google']='https://storage.test/object?X-Goog-Signature=google-secret&X-Goog-Credential=account-secret&name=private-name'
        raw['headers']['X-Api-Key']='other-service-secret'
        value=redact(raw,['opaque-test-value']);serialized=json.dumps(value)
        for secret in ('opaque-test-value','token-that-must-not-leak','original-signature','private-file','user:password','google-secret','account-secret','private-name','other-service-secret'):
            self.assertNotIn(secret,serialized)
        self.assertEqual(value['schema'],raw['schema']);self.assertEqual(value['source'],raw['source'])
        schema=json.dumps(raw['schema']);self.assertEqual(redact(schema),schema)

    def test_eval_inspection_uses_owned_profile_without_switching_global_account(self):
        with tempfile.TemporaryDirectory()as folder:
            private=Path(folder)/'private';public=Path(folder)/'account';private.mkdir();public.mkdir()
            with patch.dict(os.environ,DESK_COMPANION_DATA_DIR=str(private)):
                payload=dict(model='fixture',messages=[dict(role='user',content='api_key=private-secret-value')])
                ident=agent_debug.begin(SimpleNamespace(content=json.dumps(payload).encode(),url='http://127.0.0.1/v1/chat/completions'),payload)
                agent_debug.safe_update(ident,state='complete')
            with patch.dict(os.environ,DESK_COMPANION_DATA_DIR=str(public)):
                value=debug_detail(ident,profile=private)
                self.assertEqual(value['call']['id'],ident)
                self.assertNotIn('private-secret-value',json.dumps(value))
                self.assertTrue(agent_debug.root().samefile(public/'memory/agent_debug'))
                self.assertEqual(os.environ['DESK_COMPANION_DATA_DIR'],str(public))
