"""桌宠技能库：只读 skills/*/SKILL.md。不是插件市场。"""
from __future__ import annotations

from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parents[1] / "skills"
DEFAULT_SKILLS_DIR=SKILLS_DIR


def validate_source_manifest(value):
    import re
    if not isinstance(value,dict) or value.get('repository')!='lkun-lea/tebb-skills' or not re.fullmatch('[a-f0-9]{40}',value.get('commit','')):raise ValueError('技能来源必须是官方仓库及完整固定提交。')
    files=value.get('files')
    if not isinstance(files,dict) or 'LICENSE' not in files or not any(k.startswith('skills/') for k in files):raise ValueError('技能来源清单缺失。')
    for name,expected in files.items():
        if name!='LICENSE' and not re.fullmatch(r'skills/[a-zA-Z0-9_-]{1,80}/SKILL\.md',name):raise ValueError('技能路径无效。')
        if not isinstance(expected,str) or not re.fullmatch('[a-f0-9]{64}',expected):raise ValueError('技能摘要无效。')
    return value


def _verify_snapshot():
    if SKILLS_DIR!=DEFAULT_SKILLS_DIR:return
    import hashlib,json
    source=SKILLS_DIR/'source.json'
    if not source.is_file():raise RuntimeError('官方技能快照尚未准备。请按开发指南运行 scripts/prepare_skills.py；客户端不会自动下载。')
    value=validate_source_manifest(json.loads(source.read_text('utf-8')))
    for name,expected in value.get('files',{}).items():
        path=SKILLS_DIR/name.removeprefix('skills/')
        if not path.resolve().is_relative_to(SKILLS_DIR.resolve()) or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=expected:raise RuntimeError('官方技能快照不完整或内容已变化；请导出到新目录核对，保留自定义技能。')


def list_skills() -> list[dict]:
    _verify_snapshot()
    if not SKILLS_DIR.is_dir():
        raise RuntimeError(
            f"没有技能目录 {SKILLS_DIR}。在 desk-companion/skills/<名>/SKILL.md 放入技能。"
        )
    names = sorted(p.name for p in SKILLS_DIR.iterdir() if p.is_dir())
    if not names:
        raise RuntimeError(f"{SKILLS_DIR} 里没有技能文件夹。")
    out = []
    for name in names:
        meta, body = _read_skill_file(name)
        out.append(
            {
                "id": meta["name"],
                "description": meta["description"],
                "body": body,
                "path": str(SKILLS_DIR / name / "SKILL.md"),
            }
        )
    return out


def skill_turn_block(names: list) -> str:
    """点名的技能正文。只拼进发给模型的这一轮，不写入对话记录。"""
    if type(names) is not list or not names:
        raise RuntimeError("技能点选必须是非空字符串列表。")
    if any(type(name) is not str or not name.strip() for name in names):
        raise RuntimeError("技能点选必须是非空字符串列表。")
    parts = ["【技能正文】"]
    for name in names:
        snap = read_skill(name.strip())
        parts.append(f"# {snap['id']}\n{snap['description']}\n\n{snap['body']}")
    parts.append("以上就是技能正文，按正文执行，不要再调用 read_skill。")
    return "\n\n".join(parts)


def read_skill(name: str) -> dict:
    _verify_snapshot()
    if type(name) is not str or not name.strip():
        raise RuntimeError("技能名必须是非空字符串。")
    meta, body = _read_skill_file(name.strip())
    return {
        "id": meta["name"],
        "description": meta["description"],
        "body": body,
        "path": str(SKILLS_DIR / name.strip() / "SKILL.md"),
    }


def _read_skill_file(name: str) -> tuple[dict, str]:
    import re
    if not isinstance(name, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", name): raise ValueError("技能名称无效")
    path = SKILLS_DIR / name / "SKILL.md"
    if not path.is_file():
        raise RuntimeError(
                f"没有技能 {name}。打开看板对话「技能」子界面查看已有技能，或检查 {path}。"
        )
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        raise RuntimeError(f"{path} 必须以 YAML frontmatter 开头。")
    rest = text.split("\n", 1)[1] if "\n" in text else ""
    end = rest.find("\n---")
    if end < 0:
        raise RuntimeError(f"{path} 的 frontmatter 没有结束 ---。")
    raw_meta = rest[:end]
    body = rest[end + 4 :].lstrip("\n")
    meta = {}
    for line in raw_meta.splitlines():
        if ":" not in line or line.startswith(" "):
            continue
        key, value = line.split(":", 1)
        meta[key.strip()] = value.strip().strip('"').strip("'")
    if meta.get("name") != name:
        raise RuntimeError(f"{path} 的 name 必须是 {name!r}，与文件夹一致。")
    if type(meta.get("description")) is not str or not meta["description"].strip():
        raise RuntimeError(f"{path} 缺少 description。")
    if not body.strip():
        raise RuntimeError(f"{path} 正文为空。")
    return meta, body
