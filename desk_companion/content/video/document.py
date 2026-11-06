"""视频笔记的飞书原生呈现：流程图与内嵌网页，不读取视频流。"""
from __future__ import annotations

import json
import re
import uuid
from html import escape
from urllib.parse import quote, unquote


def render_note(source, markdown):
    from desk_companion.content.video.sources import normalize_url
    def link(match):
        label, url = match.groups()
        try:
            same = normalize_url(url.replace('&amp;', '&')) == normalize_url(source['url'])
        except ValueError:
            same = False
        return label if same else match.group(0)
    note = re.sub(r'\[([^\]\n]+)\]\((https?://[^\s)]+)\)', link, markdown.strip())
    note = note.replace(source['url'], '')
    count = 0
    def diagram(match):
        nonlocal count
        code = match[1].strip()
        if count or len(code) > 8000 or not re.match(r'^(?:flowchart|graph)\s+(?:TD|TB|LR|RL|BT)\b', code):
            return match[0]
        if re.search(r'(?im)^\s*(?:click|%%\{|init:)', code):
            return match[0]
        count += 1
        return '<whiteboard type="mermaid">' + escape(code, quote=False) + '</whiteboard>'
    return re.sub(r'```mermaid[^\S\n]*\n(.*?)\n```', diagram, note, flags=re.S), count


def embed_video(cfg, document_id, source):
    from desk_companion.content.video.sources import normalize_url
    from desk_companion.integrations.feishu.wiki_connection import cli
    if not re.fullmatch(r'[A-Za-z0-9]+', document_id or ''):
        raise ValueError('未取得有效文档 ID，无法插入原视频。')
    platform, url = normalize_url(source['url'])
    kind = 1 if platform == 'Bilibili' else 99
    token = str(uuid.uuid5(uuid.NAMESPACE_URL, document_id + ':original-video:' + url))
    path = f'/open-apis/docx/v1/documents/{document_id}/blocks/{document_id}/children'
    payload = {'index': 1, 'children': [
        {'block_type': 4, 'heading2': {'elements': [{'text_run': {'content': '原视频'}}]}},
        {'block_type': 26, 'iframe': {'component': {'iframe_type': kind, 'url': quote(url, safe='')}}},
    ]}
    result = cli(cfg, ['api', 'POST', path, '--params', json.dumps({'client_token': token}), '--data', '-'],
                 stdin=json.dumps(payload, ensure_ascii=False), timeout=60)
    rows = result.get('children', [])
    frames = [row for row in rows if row.get('block_type') == 26]
    if len(frames) != 1 or not frames[0].get('block_id'):
        raise RuntimeError('原视频内嵌结果未确认。')
    frame = cli(cfg, ['api', 'GET', f"/open-apis/docx/v1/documents/{document_id}/blocks/{frames[0]['block_id']}"])
    component = frame.get('block', {}).get('iframe', {}).get('component', {})
    if unquote(component.get('url', '')) != url or component.get('iframe_type') != kind:
        raise RuntimeError('原视频内嵌验证未通过。')
    return frames[0]['block_id']


def separate_diagrams(note):
    """Markdown 导入不识别 whiteboard XML；资源必须单独以 XML 写入。"""
    diagrams = re.findall(r'<whiteboard type="mermaid">.*?</whiteboard>', note, flags=re.S)
    text = re.sub(r'<whiteboard type="mermaid">.*?</whiteboard>', '', note, flags=re.S)
    return text.strip(), diagrams


def embed_diagrams(cfg, document_id, diagrams):
    from desk_companion.integrations.feishu.wiki_connection import cli
    if not re.fullmatch(r'[A-Za-z0-9]+', document_id or '') or len(diagrams) != 1:
        raise ValueError('流程图或文档 ID 不正确。')
    result = cli(cfg, ['docs', '+update', '--doc', document_id, '--command', 'append', '--content', '-'],
                 stdin='<h2>流程图（笔记整理）</h2>' + diagrams[0], timeout=90)
    boards = [b for b in result.get('document', {}).get('new_blocks', [])
              if b.get('block_type') == 'whiteboard' and b.get('block_id') and b.get('block_token')]
    if result.get('result') != 'success' or result.get('warnings') or len(boards) != 1:
        raise RuntimeError('飞书原生流程图写入未确认。')
    return [b['block_id'] for b in boards]
