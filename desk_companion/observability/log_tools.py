"""Atlas 工具：只读今日出错日志段。"""
from __future__ import annotations

from desk_companion.observability.log_inspect import inspect_today_errors


def read_recent_errors(_args: dict) -> str:
    snap = inspect_today_errors()
    return snap["text"]


ERROR_LOG_SPEC = {
    "func": read_recent_errors,
    "name": "read_recent_errors",
    "description": "读取今日桌宠出错日志、重点和原文。解释错误前调用，依据实际记录，不编原因。",
    "parameters": {"type": "object", "properties": {}, "required": []},
    "isReadOnly": True,
}
