"""把 Atlas 流式字推到头顶气泡。"""
from __future__ import annotations

from dataclasses import dataclass

from atlas.core.plugin import BasePlugin

TOOL_STATUS = {
    "execute_command": "正在沙箱中执行命令，可在侧栏终端查看输出或停止。",
    "read_terminal_output": "正在读取命令执行记录。",
    "read_video": "正在读取视频信息与字幕。",
    "read_video_transcript": "正在核对视频字幕原文。",
    "save_video_summary": "正在将视频总结保存到飞书文档。",
    "get_today_agenda": "在看今天的日程…",
    "get_open_tasks": "在看未完成的待办…",
    "calendar_propose": "在准备日程提案…",
    "web_search": "正在搜索网络来源，核实最新信息。",
    "remember_fact": "正在保存你明确要求记住的内容。",
    "forget_fact": "正在删除你指定的记忆。",
    "github_recent": "正在读取仓库最近的提交。",
    "github_status": "正在检查 GitHub 连接和仓库。",
    "github_roadmap": "正在读取仓库的路线图。",
    "read_skill": "正在查阅这项任务的操作规程。",
    "list_skills": "正在检查可用技能。",
    "read_recent_errors": "正在检查最近的错误日志。",
}


@dataclass
class BubbleStreamPlugin(BasePlugin):
    host: object
    name: str = "desk_bubble_stream"
    priority: int = 40

    def on_llm_delta(self, *, run_id: str, turn_idx: int, delta: str) -> None:
        piece = delta
        self.host.ui(lambda: self.host.on_llm_delta(piece))

    def on_tool_before_call(
        self,
        *,
        run_id: str,
        turn_idx: int,
        step_id: str,
        tool_name: str,
        input: dict,
    ) -> None:
        text = TOOL_STATUS.get(tool_name, f"在用 {tool_name}…")
        self.host.ui(lambda: self.host.on_stream_status(text))
