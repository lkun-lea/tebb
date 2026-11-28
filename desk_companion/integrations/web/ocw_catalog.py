"""Find captioned lecture candidates in the publisher's public sitemap."""
from collections import Counter
from math import log
import re
from urllib.parse import urlsplit
from xml.etree import ElementTree as ET

from desk_companion.content.video.ocw import metadata

ROOT = 'https://ocw.mit.edu/sitemap.xml'
STOP = set('site ocw mit edu course courses university video videos lecture lectures tutorial official introduction to and for in the on of with learning'.split())


def _links(xml):
    try:
        nodes = ET.fromstring(xml).findall('.//{*}loc')
    except ET.ParseError:
        return []
    return [node.text for node in nodes if node.text
            and node.text.startswith('https://ocw.mit.edu/courses/')]


def _rank(urls, words, slug):
    hits = {url: words.intersection(re.findall('[a-z0-9]+', slug(url).lower())) for url in urls}
    frequency = Counter(term for terms in hits.values() for term in terms)
    scores = {url: sum(log(1 + len(urls) / frequency[t]) for t in terms) for url, terms in hits.items() if terms}
    return sorted(scores, key=lambda url: (-scores[url], url))


def search(query, read):
    words = set(re.findall('[a-z0-9]+', query.lower())) - STOP
    index = _links(read(ROOT))
    courses = _rank([u for u in index if u.endswith('/sitemap.xml')], words, lambda u: u.split('/')[-2])
    candidates = []
    for course in courses[:3]:
        resources = [u for u in _links(read(course)) if '/resources/' in u and u.startswith(course.rsplit('/', 1)[0] + '/')]
        # Restrict candidates to relevant resource slugs; course-level matches alone
        # do not establish that a specific lecture teaches the requested topic.
        candidates.extend(_rank(resources, words, lambda u: urlsplit(u).path.rstrip('/').split('/')[-1]))
    candidates = _rank(list(dict.fromkeys(candidates)), words, lambda u: urlsplit(u).path.rstrip('/').split('/')[-1])
    rows = []
    for url in candidates[:5]:
        try:
            info = metadata(url, read(url))
        except ValueError:
            continue
        if info['title'] and info['playback_url'] and info['subtitles']:
            rows.append(dict(title=info['title'], link=url, snippet='MIT OpenCourseWare 发布页包含视频播放器及字幕轨道；尚未读取字幕。'))
        if len(rows) == 3:
            break
    return rows
