"""升级后旧游戏作业不影响其余定时任务；配置保存保留其它数据。"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from desk_companion.automation import schedule as automation
from desk_companion.infrastructure import envconf
from desk_companion.local_api.bridge import Bridge
from desk_companion.local_api.server import RPC_METHODS


class FeatureCleanupTests(unittest.TestCase):
    def test_legacy_game_job_is_ignored_without_disabling_other_jobs(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(automation, "jobs_path", return_value=Path(directory)/"jobs.json"):
            automation.upsert_job({"name": "日报", "action": "ai_news", "enabled": True,
                                   "cadence": "daily", "weekdays": [], "hour": 9, "minute": 0})
            path = automation.jobs_path()
            raw = json.loads(path.read_text("utf-8"))
            old = {**raw["jobs"][0], "id": "old-game", "name": "旧游戏作业", "action": "maa_daily"}
            raw["jobs"].insert(0, old)
            path.write_text(json.dumps(raw), "utf-8")
            loaded = automation.load_store()
            self.assertEqual([(x["name"], x["enabled"]) for x in loaded["jobs"]], [("日报", True)])
            self.assertEqual(automation.list_snapshot()["items"][0]["action"], "ai_news")
            # 读取不破坏旧数据，新配置也不允许重新启用已移除的动作。
            self.assertEqual(len(json.loads(path.read_text("utf-8"))["jobs"]), 2)
            with self.assertRaises(RuntimeError):
                automation.upsert_job({**old, "id": "", "name": "新游戏作业"})

    def test_removed_rpc_cannot_be_reached(self):
        removed = {"load_maa", "maa_start_daily", "maa_authorize", "load_depot", "load_raise",
                   "load_skland", "sync_skland", "compute_farm_plan"}
        self.assertFalse(removed & RPC_METHODS)
        self.assertTrue(all(not hasattr(Bridge, name) for name in removed))

    def test_model_save_preserves_other_env_configuration(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(envconf, "env_path", return_value=Path(directory)/".env"):
            path = envconf.env_path()
            path.write_text("# user configuration\nOTHER_KEY=keep-me\nSKLAND_TOKEN=legacy-value\nATLAS_API_KEY=old\n", "utf-8")
            envconf.write_llm_env(api_key="new-key", base_url="https://example.com/v1", model="test")
            text = path.read_text("utf-8")
            self.assertIn("# user configuration\nOTHER_KEY=keep-me\nSKLAND_TOKEN=legacy-value", text)
            self.assertNotIn("ATLAS_API_KEY=old", text)
            self.assertEqual(envconf.require_llm_env()["ATLAS_API_KEY"], "new-key")
