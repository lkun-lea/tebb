import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from desk_companion.local_api import guest_portrait


class GuestPortraitTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        guest_portrait.install(app)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def test_raw_profile_or_unlisted_labels_never_reach_model(self):
        with patch.object(guest_portrait, "generate") as generate:
            for payload in ({"birthday": "2000-01-01"}, {"habit": "arbitrary prompt"}, {"history": []}):
                self.assertEqual(self.client.post("/cloud/v1/portrait", json=payload).status_code, 422)
            generate.assert_not_called()

    def test_guest_without_tags_and_rate_limit(self):
        with patch.object(guest_portrait, "generate", return_value={"summary": "尚未分享资料。"}) as generate:
            self.assertEqual(self.client.post("/cloud/v1/portrait", json={}).status_code, 200)
            self.assertEqual(self.client.post("/cloud/v1/portrait", json={}).status_code, 429)
            generate.assert_called_once_with(guest_portrait.PortraitInput())
