"""Atlas 工具：只读技能库。不是插件市场。"""
from __future__ import annotations

from desk_companion.integrations.skill_catalog import list_skills, read_skill


def list_skills_tool(_args: dict) -> str:
    items = list_skills()
    lines = ["已有技能（看板对话「技能」子界面也能看见全文）："]
    for item in items:
        lines.append(f"- {item['id']}: {item['description']}")
    lines.append("读某份正文请调用 read_skill，参数 name 用上面的 id。")
    return "\n".join(lines)


def read_skill_tool(args: dict) -> str:
    name = args.get("name") if isinstance(args, dict) else None
    snap = read_skill(name if type(name) is str else "")
    return f"# {snap['id']}\n{snap['description']}\n\n{snap['body']}"


LIST_SKILLS_SPEC = {
    "func": list_skills_tool,
    "name": "list_skills",
    "description": (
        "列出桌宠技能库里全部 SKILL.md 的名字和何时用。"
        "用户问有哪些技能、技能库、分析日志或写飞书总结该用哪份规程时调用。"
        "本周复盘在自动化任务「周复盘」子界面用 weekly-retro；总结 GitHub 仓库最近用 github-repo-summary。"
    ),
    "parameters": {"type": "object", "properties": {}, "required": []},
    "isReadOnly": True,
}

READ_SKILL_SPEC = {
    "func": read_skill_tool,
    "name": "read_skill",
    "description": (
        "读取一份技能的正文。"
        "写今日工作总结用 feishu-doc-writing；"
        "本周复盘用 weekly-retro（自动化任务「周复盘」子界面生成，不要用 github_recent 冒充一周）；"
        "总结 GitHub 仓库最近用 github-repo-summary（须先 github_recent）。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "技能文件夹名，与 SKILL.md 的 name 一致。",
            }
        },
        "required": ["name"],
    },
    "isReadOnly": True,
}
