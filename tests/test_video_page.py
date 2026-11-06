"""视频工作区的任务隔离、历史识别与追问，不调用真实平台。"""
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from desk_companion.content.video import controller as video_controller
from desk_companion.tasks.manager import TaskManager

URL = "https://youtu.be/abcdefghijk?si=tracking"


class VideoPageTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        env = patch.dict(os.environ, {"DESK_COMPANION_DATA_DIR": temp.name})
        env.start()
        self.addCleanup(env.stop)
        scheduler = patch.object(TaskManager, "_schedule", return_value=None)
        scheduler.start()
        self.addCleanup(scheduler.stop)
        manager = TaskManager()
        self.addCleanup(manager.shutdown)
        self.host = SimpleNamespace(tasks=manager, state=SimpleNamespace(session_id="desktop-current"))

    def test_links_start_independent_supervised_sessions_without_switching_desktop(self):
        first = video_controller.start(self.host, URL)["task_id"]
        second = video_controller.start(self.host, URL)["task_id"]
        rows = [self.host.tasks.get(task) for task in (first, second)]
        self.assertNotEqual(rows[0]["session"], rows[1]["session"])
        self.assertEqual(self.host.state.session_id, "desktop-current")
        self.assertEqual({row["channel"] for row in rows}, {"video"})
        self.assertEqual(rows[0]["source"]["video_url"], "https://www.youtube.com/watch?v=abcdefghijk")
        self.assertEqual(len(video_controller.snapshot(self.host)["items"]), 2)
        self.assertIn("应用会依据用户设置在任务成功后自动归档", rows[0]["text"])
        before = len(self.host.tasks.list()["items"])
        for url in ("https://localhost/video", "file:///cookies.txt", "https://youtube.com.evil/watch?v=abcdefghijk"):
            with self.assertRaises(ValueError):
                video_controller.start(self.host, url)
        self.assertEqual(len(self.host.tasks.list()["items"]), before)
        self.host.tasks.cancel(first)
        with self.assertRaises(ValueError):
            video_controller.continue_task(self.host, first, "   ")
        retried = video_controller.continue_task(self.host, first, "重新读取")["task_id"]
        task = self.host.tasks.get(retried)
        self.assertEqual(task["session"], rows[0]["session"])
        self.assertIn(rows[0]["source"]["video_url"], task["text"])
        self.assertIn("重新读取", task["text"])

    def test_legacy_video_activity_is_included_without_unrelated_session_messages(self):
        manager = self.host.tasks
        desktop = manager.submit("总结视频", "shared", "desktop")
        feishu = manager.submit("视频细节", "feishu-private", "feishu")
        ordinary = manager.submit("查天气", "shared", "desktop")
        manager.event(desktop, "tool_start", {"tool": "read_video", "read_only": True})
        manager.event(feishu, "tool_start", {"tool": "read_video_transcript", "read_only": True})
        manager.event(ordinary, "tool_start", {"tool": "web_search", "read_only": True})
        self.assertEqual(set(video_controller.task_ids(manager)), {desktop, feishu})

    def test_legacy_followup_keeps_context_and_persists_video_membership_without_sending(self):
        manager = self.host.tasks
        parent = manager.submit("总结视频", "feishu-private", "feishu", source={"message_id": "original"})
        manager.event(parent, "tool_start", {"tool": "read_video", "read_only": True})
        with self.assertRaises(ValueError):
            video_controller.continue_task(self.host, parent, "解释 03:20")
        manager.update(parent, state="succeeded", answer="原总结")
        child = video_controller.continue_task(self.host, parent, "解释 03:20")["task_id"]
        task = manager.get(child)
        self.assertEqual(task["session"], "feishu-private")
        self.assertEqual(task["source"]["parent_task"], parent)
        self.assertFalse(task["source"]["send_back"])
        self.assertIn(child, video_controller.task_ids(manager))
        ordinary = manager.submit("普通聊天", "desktop-current")
        manager.update(ordinary, state="succeeded")
        with self.assertRaises(ValueError):
            video_controller.continue_task(self.host, ordinary, "继续")

