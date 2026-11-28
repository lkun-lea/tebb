"""Read caption track declarations from a single public MIT OCW video player."""
import json
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from desk_companion.content.video.sources import normalize_url


class Player(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title = ""
        self.players = 0
        self.in_video = False
        self.tracks = {}
        self.playback_url = ""

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "meta" and attrs.get("property") == "og:title":
            self.title = attrs.get("content", "").split(" | ")[0]
        if tag == "video":
            self.players += 1
            self.in_video = True
            try:
                for source in json.loads(attrs.get("data-setup", "{}")).get("sources", []):
                    if source.get("type") == "video/youtube":
                        platform, url = normalize_url(source.get("src"))
                        if platform == "YouTube":
                            self.playback_url = url
                            break
            except (ValueError, TypeError, AttributeError):
                pass
        if tag == "track" and self.in_video and attrs.get("kind") in {"captions", "subtitles"}:
            src = attrs.get("src") or ""
            if urlsplit(src).path.lower().endswith(".vtt"):
                self.tracks.setdefault(attrs.get("srclang") or "und", []).append(src)

    def handle_endtag(self, tag):
        if tag == "video":
            self.in_video = False


def metadata(url, page):
    player = Player()
    player.feed(page)
    if player.players != 1:
        raise ValueError("需要包含单个视频播放器的 MIT 课程资源页。")
    subtitles = {lang: [{"url": urljoin(url, src), "ext": "vtt"} for src in tracks]
                 for lang, tracks in player.tracks.items()}
    return dict(title=player.title, uploader="MIT OpenCourseWare", webpage_url=url,
                subtitles=subtitles, playback_url=player.playback_url)
