import unittest
from unittest.mock import patch

from desk_companion.content.video import sources, worker

URL = "https://ocw.mit.edu/courses/example/resources/lecture/"
META = '<meta property="og:title" content="Lecture | MIT">'
TRACK = '<track kind="captions" srclang="en" src="/courses/example/sub.vtt">'
VTT = """WEBVTT

00:01.010 --> 00:02.020
same

00:03.030 --> 00:04.040
same
"""


class PublisherCaptions(unittest.TestCase):
    def read(self, page, *tracks):
        with patch.object(worker, "caption_bytes", side_effect=[META + page, *tracks]) as fetch:
            result = worker.retrieve(URL, {}, lambda _: None)
            self.assertEqual(fetch.call_count, 1 + len(tracks))
            return result

    def test_exact_ranges_and_repeated_cues(self):
        result = self.read("<video>" + TRACK + "</video>", VTT)
        page = sources.transcript_page(dict(result, source_id="ocw"))
        self.assertTrue(page["complete"])
        self.assertEqual(result["caption_url"], "https://ocw.mit.edu/courses/example/sub.vtt")
        self.assertEqual([(r["time"], r["end_time"]) for r in page["items"]],
                         [("00:01.010", "00:02.020"), ("00:03.030", "00:04.040")])

    def test_missing_unreadable_and_outside_player(self):
        for page, tracks, status in [
            ("<video></video>" + TRACK, [], "missing"),
            ("<video>" + TRACK + "</video>", [VTT.replace("WEBVTT", "<html>")], "unavailable"),
            ("<video>" + TRACK.replace("/courses", "https://example.org/courses") + "</video>", [], "unavailable"),
        ]:
            with self.subTest(status=status, page=page):
                result = self.read(page, *tracks)
                self.assertEqual(result["subtitle_status"], status)
                self.assertFalse(sources.transcript_page(dict(result, source_id="ocw"))["complete"])
