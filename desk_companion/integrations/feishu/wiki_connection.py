"""桌宠连接飞书知识空间；读取目录与视频归档共用用户身份。"""
from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

from desk_companion.infrastructure.paths import data_root

DEFAULTS = {"wiki_url": "", "video_parent_url": "", "profile": "", "auto_video_save": False}


class CatalogIncomplete(RuntimeError):
    def __init__(self, items, cause):
        from desk_companion.integrations.feishu.feishu_connection import classify
        super().__init__('飞书知识库目录未加载完整，已保留可读取的文档。请刷新目录重试。' + str(classify(cause)))
        self.items = items


def settings_path():
    return data_root() / "memory" / "wiki_connection.json"


def load_settings():
    path = settings_path()
    cfg = {**DEFAULTS, **(json.loads(path.read_text("utf-8")) if path.exists() else {})}
    cfg.pop("include_video_frames", None)
    return cfg


def wiki_url(value):
    if not isinstance(value, str) or len(value) > 2048:
        raise ValueError("请填写飞书知识库页面链接。")
    p = urlsplit(value.strip())
    host = p.hostname or ""
    if p.scheme != "https" or p.username or p.password or p.port or not (
        host.endswith(".feishu.cn") or host.endswith(".larksuite.com")) or not re.fullmatch(r"/wiki/[A-Za-z0-9]+/?", p.path):
        raise ValueError("请填写 https://…feishu.cn/wiki/… 形式的知识库页面链接。")
    return f"https://{host}{p.path.rstrip('/')}"


def cli(cfg, args, *, stdin=None, timeout=60):
    from desk_companion.integrations.feishu.feishu_auth import _first_json
    from desk_companion.integrations.feishu.feishu_tools import _run_lark
    prefix = ["--profile", cfg["profile"]] if cfg.get("profile") else []
    env = json.loads(_first_json(_run_lark([*prefix, *args, "--as", "user", "--format", "json"], timeout=timeout, stdin=stdin)))
    if env.get("ok") is not True or not isinstance(env.get("data"), dict):
        raise RuntimeError("飞书知识库请求未确认成功，请检查登录和文档权限。")
    return env["data"]


def save_settings(payload):
    from desk_companion.infrastructure import storage
    if not isinstance(payload, dict) or type(payload.get("auto_video_save")) is not bool:
        raise ValueError("知识库设置或自动保存开关不正确。")
    cfg = {key: payload.get(key, default) for key, default in DEFAULTS.items()}
    if not isinstance(cfg["profile"], str) or len(cfg["profile"]) > 100:
        raise ValueError("飞书应用配置名不正确。")
    cfg["profile"] = cfg["profile"].strip()
    if not cfg["wiki_url"] and not cfg["video_parent_url"] and not cfg["auto_video_save"]:
        storage.atomic_write(settings_path(), cfg)
        return {"ok": True, "settings": cfg}
    cfg["wiki_url"] = wiki_url(cfg["wiki_url"])
    root = cli(cfg, ["wiki", "+node-get", "--node-token", cfg["wiki_url"]])
    cfg.update(space_id=root["space_id"], title=root.get("title", ""))
    if cfg["video_parent_url"]:
        cfg["video_parent_url"] = wiki_url(cfg["video_parent_url"])
        if urlsplit(cfg["video_parent_url"]).hostname != urlsplit(cfg["wiki_url"]).hostname:
            raise ValueError("视频父文档需与知识库使用同一飞书域名。")
        parent = cli(cfg, ["wiki", "+node-get", "--node-token", cfg["video_parent_url"]])
        if parent.get("space_id") != root["space_id"] or parent.get("obj_type") != "docx":
            raise ValueError("视频父文档必须是该知识库内的云文档。")
        cfg.update(video_parent_token=parent["node_token"], video_parent_title=parent.get("title", ""))
    elif cfg["auto_video_save"]:
        raise ValueError("开启自动保存前，请选择视频笔记父文档。")
    storage.atomic_write(settings_path(), cfg)
    return {"ok": True, "settings": cfg}


def catalog(cfg=None):
    """遍历整个已连接空间，分页不可静默截断；不读取文档正文。"""
    cfg = cfg or load_settings()
    if not cfg.get("wiki_url"):
        return []
    root = cli(cfg, ["wiki", "+node-get", "--node-token", cfg["wiki_url"]])
    space = root["space_id"]
    base = cfg["wiki_url"].split("/wiki/")[0]
    queue, visited, result = [""], set(), []
    while queue:
        parent, page, cursors = queue.pop(0), "", set()
        while True:
            args = ["wiki", "+node-list", "--space-id", space]
            if parent:
                args += ["--parent-node-token", parent]
            if page:
                args += ["--page-token", page]
            try:
                data = cli(cfg, args, timeout=20)
            except Exception as exc:
                raise CatalogIncomplete(result, exc) from None
            for row in data.get("nodes", []):
                token = row["node_token"]
                if token in visited:
                    continue
                visited.add(token)
                if len(visited) > 1000:
                    raise RuntimeError("知识库超过 1000 个节点，请连接较小的知识空间后再列出文档。")
                if row.get("obj_type") == "docx":
                    result.append({"title": row.get("title", "（无标题）"), "url": base + "/wiki/" + token,
                                   "token": row["obj_token"], "source": "wiki", "space_id": space,
                                   "space_name": cfg.get("space_name") or f"飞书知识库 · {space}"})
                if row.get("has_child") and row.get("node_type") != "shortcut":
                    queue.append(token)
            if not data.get("has_more"):
                break
            page = data.get("page_token")
            if not page or page in cursors:
                raise RuntimeError("知识库目录分页未完成，请刷新后重试。")
            cursors.add(page)
    return result


def cached_source(doc):
    path = data_root() / 'memory' / 'wiki_catalog_sources.json'
    try:
        data = json.loads(path.read_text('utf-8')) if path.exists() else {}
    except (ValueError, OSError):
        data = {}
    return data.get('docs', {}).get(doc, {})


def enrich_catalog(items):
    """按真实空间归属分组；目录和归属缓存仅在本机保存，不移动云端资源。"""
    from desk_companion.infrastructure import storage
    cfg = load_settings()
    path = data_root() / 'memory' / 'wiki_catalog_sources.json'
    try:
        cache = json.loads(path.read_text('utf-8')) if path.exists() else {}
    except (ValueError, OSError):
        cache = {}
    docs = cache.setdefault('docs', {})
    names = cache.get('names', {}) if cache.get('profile') == cfg.get('profile', '') else {}
    if not names or time.time() - cache.get('names_at', 0) > 600:
        try:
            spaces = cli(cfg, ['wiki', '+space-list', '--page-all', '--page-limit', '0'], timeout=20)
            names = {str(s['space_id']): s['name'] for s in spaces.get('spaces', [])}
            cache.update(names=names, names_at=time.time(), profile=cfg.get('profile', ''))
        except Exception:
            pass  # 名称无法获取时保留真实空间 ID，不编造归属。
    def resolve(item):
        url = item.get('url', '')
        if item.get('space_id') or '/wiki/' not in url:
            return url, ''
        old = docs.get(url, {})
        if old.get('space_id') and time.time() - old.get('_at', 0) < 600 and old.get('_profile') == cfg.get('profile', ''):
            return url, old['space_id']
        try:
            node = cli(cfg, ['wiki', '+node-get', '--node-token', url], timeout=20)
            return url, str(node['space_id'])
        except Exception:
            return url, ''
    with ThreadPoolExecutor(max_workers=4) as executor:
        resolved = dict(executor.map(resolve, items))
    for item in items:
        url = item.get('url', '')
        space = str(item.get('space_id') or '')
        old = docs.get(url, {})
        is_wiki = '/wiki/' in url
        if is_wiki and not space:
            space = resolved.get(url, '')
        item.update(source='wiki' if is_wiki or space else 'drive', space_id=space,
                    space_name=names.get(space) or (old.get('space_name') if space == old.get('space_id') else '')
                        or (f'飞书知识库 · {space}' if space else '飞书知识库（归属待识别）' if is_wiki else '飞书云文档'))
        metadata = {key: item.get(key, '') for key in ('source', 'space_id', 'space_name')}
        metadata.update(_at=time.time(), _profile=cfg.get('profile', ''))
        for key in (url, item.get('token')):
            if key: docs[key] = metadata
    storage.atomic_write(path, cache)
    return items


def profile_for(doc):
    cfg = load_settings()
    if cfg.get("wiki_url") and urlsplit(doc).hostname == urlsplit(cfg["wiki_url"]).hostname:
        return cfg.get("profile", "")
    return ""
