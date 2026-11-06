import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from desk_companion.integrations.feishu.feishu_cards import CardReply, card, memory_pages
from desk_companion.integrations.feishu.feishu_agent import FeishuAgent, Inbox, MENU_EVENT
from desk_companion.local_api.host import HeadlessApp
from desk_companion.tasks.manager import TaskManager

BINDING = dict(profile="test", app_id="app", owner_id="ou_owner", app_name="测试")


class CardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = patch.dict(os.environ, {"DESK_COMPANION_DATA_DIR": self.temp.name})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.host = HeadlessApp()
        self.gateway = self.host.feishu_agent
        self.gateway._binding = BINDING
        self.gateway._inbox = Inbox(Path(self.temp.name) / "inbox.db")

    def test_card_transport_sequences_full_text_and_closes_stream(self):
        requests = []
        saved = {}
        def run(args, **kwargs):
            requests.append((args, kwargs))
            if "api" in args:
                return '{"ok":true,"data":{"card_id":"123"}}'
            return '{"ok":true,"data":{"message_id":"om_reply"}}'
        with patch("desk_companion.integrations.feishu.feishu_cards._run_lark", side_effect=run):
            reply = CardReply("test", "om_original", "ou_owner", "stable", persist=lambda **kw: saved.update(kw))
            reply.start()
            reply.update("查询中", "第一段")
            reply.update("整理中", "第一段第二段")
            reply.finish("完成", "最终答案")
        bodies = [json.loads(kw['stdin']) for args, kw in requests if 'api' in args]
        self.assertEqual([b['sequence'] for b in bodies[1:]], [1, 2, 3, 4, 5, 6])
        self.assertEqual(bodies[4]['content'], '第一段第二段')
        self.assertFalse(json.loads(bodies[5]['settings'])['config']['streaming_mode'])
        self.assertEqual(saved['reply_id'], 'om_reply')
        self.assertEqual(sum('+messages-reply' in args for args, kw in requests), 1)
        payload = json.loads(bodies[0]['data'])
        self.assertEqual(payload['schema'], '2.0')
        self.assertEqual(payload['body']['elements'][0]['tag'], 'column_set')

    def test_menu_owner_action_freshness_and_dedup_without_model(self):
        event = dict(type=MENU_EVENT, event_key="memory_request_from_feishu", event_id="click-1", app_id="app",
                     operator_open_id="ou_owner", timestamp=str(int(time.time()*1000)))
        with patch.object(self.gateway, "_send_memory") as send, patch.object(self.host, "run_channel_chat") as model:
            for change in ({"operator_open_id":"ou_other"}, {"app_id":"other"}, {"event_key":"other"}, {"timestamp":"1"}):
                self.assertFalse(self.gateway.process_menu({**event, **change}))
            self.assertTrue(self.gateway.process_menu(event))
            self.assertFalse(self.gateway.process_menu(event))
            send.assert_called_once()
            model.assert_not_called()

    def test_memory_contains_existing_facts_and_no_generated_summary(self):
        from desk_companion.memory.facts import add_user_fact
        add_user_fact("博士喜欢简短回答。")
        pages = memory_pages(self.host.state.session_id)
        self.assertIn("博士喜欢简短回答", pages[0])
        self.assertIn("还没有生成压缩摘要", pages[0])

    def test_card_retry_never_reexecutes_finished_agent(self):
        self.host._tasks = TaskManager(self.host, command=[sys.executable, "-u", "-c", "exec(open('tests/worker_fixture.py', encoding='utf-8').read())"])
        self.addCleanup(self.host._tasks.shutdown)
        event = dict(message_id="om_1", chat_id="oc_private", sender_id="ou_owner", content="离线查询", message_type="text")
        self.gateway._inbox.add("app", event)
        row = self.gateway._inbox.take("app")
        requests = []
        def run(args, **kwargs):
            requests.append(args)
            return '{"ok":true,"data":{"card_id":"123"}}' if "api" in args else '{"ok":true,"data":{"message_id":"om_reply"}}'
        with patch("desk_companion.integrations.feishu.feishu_cards._run_lark", side_effect=run):
            self.gateway.process_message(row)
            finished = self.gateway._inbox.get("app", "om_1")
            self.assertEqual(finished['state'], 'sent')
            self.assertEqual(self.host.tasks.get(finished['task_id'])['state'], 'succeeded')
            self.gateway._inbox.update("app", "om_1", state="answered")
            with patch.object(self.gateway, "_answer") as agent:
                self.gateway.process_message(self.gateway._inbox.take("app"))
                agent.assert_not_called()
        self.assertEqual(sum('+messages-reply' in args for args in requests), 1)

    def test_continue_rejects_other_owner_before_submit(self):
        self.host._tasks = TaskManager(self.host, command=[sys.executable, "-u", "-c", "exec(open('tests/worker_fixture.py', encoding='utf-8').read())"])
        self.addCleanup(self.host._tasks.shutdown)
        task_id = self.host.tasks.submit("test", "s", "feishu", source=dict(app_id="app", owner_id="ou_other", message_id="om_other"))
        with self.assertRaises(ValueError):
            self.gateway.continue_task(task_id, "继续")

    def test_local_continuation_keeps_context_without_exposing_internal_note_as_user_text(self):
        self.host._tasks = TaskManager(self.host, command=[sys.executable, "-u", "-c", "exec(open('tests/worker_fixture.py', encoding='utf-8').read())"])
        self.addCleanup(self.host._tasks.shutdown)
        first = self.host.tasks.submit("离线查询", "same-feishu-session", "feishu")
        self.assertEqual(self.host.tasks.wait(first)["state"], "succeeded")
        found = self.host.bridge.continue_agent_task(first, "继续核对", False)
        self.assertEqual(self.host.tasks.wait(found["task_id"])["state"], "succeeded")
        from desk_companion.memory.history import list_chat
        messages = list_chat("same-feishu-session")
        users = [r['text'] for r in messages if r['role'] == 'user']
        self.assertEqual(users, ["离线查询", "继续核对"])
        seen = (Path(self.temp.name) / "seen.json").read_text("utf-8")
        self.assertIn("离线查询", seen)
        self.assertIn("继续任务", seen)
        self.assertFalse(self.host.tasks.get(found["task_id"])["source"]["send_back"])

    def test_resume_actually_blocks_duplicate_write_in_new_agent(self):
        self.host._tasks = TaskManager(self.host, command=[sys.executable, "-u", "-c", "exec(open('tests/worker_fixture.py', encoding='utf-8').read())"])
        self.addCleanup(self.host._tasks.shutdown)
        first = self.host.tasks.submit("写入测试", "s")
        self.assertEqual(self.host.tasks.wait(first)["state"], "succeeded")
        second = self.host.tasks.resume(first, "继续写入测试")
        self.assertEqual(self.host.tasks.wait(second)["state"], "succeeded")
        self.assertEqual((Path(self.temp.name) / "write_count").read_text("utf-8"), "1")


if __name__ == "__main__":
    unittest.main()
