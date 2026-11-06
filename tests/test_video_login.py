"""真实 DPAPI 加密和读取链路；不读取真实用户浏览器或写入真实数据目录。"""
import json
import os
import tempfile
import time
import unittest
from unittest.mock import patch

from desk_companion.content.video import sources as video
from desk_companion.content.video import login as video_login
from desk_companion.content.video.worker import retrieve


def cookie(domain=".bilibili.com", name="SESSDATA", expiry=0):
    return {"domain": domain, "name": name, "value": "test-private-cookie", "path": "/",
            "expires": expiry, "secure": True, "http_only": True}


class LoginTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        env = patch.dict(os.environ, {"DESK_COMPANION_DATA_DIR": temp.name})
        env.start()
        self.addCleanup(env.stop)

    def test_dpapi_roundtrip_status_expiry_and_clear_never_expose_values(self):
        self.assertEqual(video_login.status()["items"][0]["state"], "missing")
        result = video_login.save("Bilibili", [cookie()])
        self.assertEqual(result["items"][0]["state"], "saved")
        self.assertNotIn("test-private-cookie", json.dumps(result))
        self.assertNotIn("test-private-cookie", video_login.path("Bilibili").read_text())
        self.assertEqual(video_login.cookies("Bilibili"), [cookie()])
        with patch("desk_companion.content.video.login.time.time", return_value=time.time() + 30):
            video_login.save("Bilibili", [cookie(expiry=int(time.time()) + 60)])
        with patch("desk_companion.content.video.login.time.time", return_value=time.time() + 90):
            self.assertEqual(video_login.status()["items"][0]["state"], "expired")
            self.assertEqual(video_login.cookies("Bilibili"), [])
        video_login.clear("Bilibili")
        self.assertFalse(video_login.path("Bilibili").exists())

    def test_reject_foreign_domains_anonymous_expired_and_malformed_cookies(self):
        for row in [cookie("bilibili.com.evil"), cookie(".google.com"), cookie(name="anonymous"),
                    cookie(expiry=1), {**cookie(), "value": "a\nb"}, {**cookie(), "expires": False}]:
            with self.assertRaises(ValueError):
                video_login.save("Bilibili", [row])
        with self.assertRaises(ValueError):
            video_login.clear("../../other")
        video_login.save("YouTube", [cookie(".youtube.com", "__Secure-3PAPISID")])
        self.assertEqual(video_login.status()["items"][1]["state"], "saved")
        file = video_login.path("YouTube")
        file.write_text('{"saved_at": 1, "encrypted": "invalid"}')
        self.assertEqual(video_login.status()["items"][1]["state"], "error")
        with self.assertRaisesRegex(ValueError, "无法解密"):
            video_login.cookies("YouTube")

    def test_saved_login_used_by_video_reader_cache_invalidates_and_manual_file_wins(self):
        from tests.test_video import SOURCE
        url = "https://www.bilibili.com/video/BV1ojfDBSEPv"
        source = {**SOURCE, "url": url}
        with patch.object(video, "extract", return_value=source.copy()) as extract:
            video.read_video("session", url)
            self.assertEqual(extract.call_args.args[1]["cookie_rows"], [])
            video_login.save("Bilibili", [cookie()])
            video.read_video("session", url)
            self.assertEqual(extract.call_count, 2)
            self.assertEqual(extract.call_args.args[1]["cookie_rows"], [cookie()])
            video.read_video("session", url)
            self.assertEqual(extract.call_count, 2)
            video_login.clear("Bilibili")
            video.read_video("session", url)
            self.assertEqual(extract.call_count, 3)
            with patch.object(video, "load_settings", return_value={"cookie_file": "own-file", "proxy": ""}):
                video.read_video("session", url)
                self.assertNotIn("cookie_rows", extract.call_args.args[1])

    def test_worker_supplies_http_only_and_session_cookie_without_disk_cookie_file(self):
        from tests.test_video import SOURCE
        with patch("yt_dlp.YoutubeDL") as factory:
            downloader = factory.return_value.__enter__.return_value
            downloader.extract_info.return_value = {"title": "Title", "webpage_url": SOURCE["url"]}
            row = cookie(".youtube.com", "SID")
            retrieve(SOURCE["url"], {"cookie_rows": [row]}, lambda _: None)
            value = downloader.cookiejar.set_cookie.call_args.args[0]
            self.assertEqual(value.value, row["value"])
            self.assertIsNone(value.expires)
            self.assertTrue(value.has_nonstandard_attr("HttpOnly"))
            self.assertNotIn("cookiefile", factory.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
