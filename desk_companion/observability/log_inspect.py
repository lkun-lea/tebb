"""收集今日桌宠出错记录；不读取外部游戏日志。"""
from __future__ import annotations
import re
from datetime import datetime
from pathlib import Path
from desk_companion.observability.logutil import LOG_PATH
MAX_BYTES = 2 * 1024 * 1024
MAX_TEXT = 8000
_TS = re.compile(r"^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2}) \[")

def inspect_today_errors() -> dict:
    items, note = _desk_items(datetime.now().strftime("%Y-%m-%d"))
    highlights = items[-3:]
    parts = ["【重点】"]
    parts.extend(f"{x['time']} {x['title']}" for x in highlights)
    if not highlights:
        parts.append("今日没有桌宠出错记录。")
    parts.append(f"【桌宠】 {LOG_PATH}")
    if note:
        parts.append(note)
    parts.extend(x["text"] for x in items)
    return {"ok": True, "alert": bool(items), "empty": not items,
            "text": "\n".join(parts), "highlights": highlights,
            "desk": {"path": str(LOG_PATH), "note": note, "items": items}}

def _desk_items(today: str) -> tuple[list[dict], str]:
    if not LOG_PATH.is_file():
        return [], f"没有日志文件 {LOG_PATH}。"
    try:
        raw = _tail_text(LOG_PATH)
    except OSError as exc:
        return [], f"读不了 {LOG_PATH}：{exc}"
    lines = raw.splitlines()
    out: list[dict] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        matched = _TS.match(line)
        if not matched or matched.group(1) != today:
            i += 1
            continue
        kind = ""
        title = ""
        if "CRASH" in line:
            kind, title = "crash", "崩溃"
        elif "WATCHDOG" in line:
            kind, title = "watchdog", "看门狗"
        if not kind:
            i += 1
            continue
        block = [line]
        i += 1
        while i < len(lines) and not _TS.match(lines[i]):
            block.append(lines[i])
            i += 1
        out.append(
            _entry(
                source="desk",
                kind=kind,
                time=f"{matched.group(1)} {matched.group(2)}",
                title=title,
                text="\n".join(block),
            )
        )
    return out[-12:], ""

def _entry(source: str, kind: str, time: str, title: str, text: str) -> dict:
    return {
        "source": source,
        "kind": kind,
        "time": time,
        "title": title,
        "text": text,
    }

def _tail_text(path: Path, max_bytes: int = MAX_BYTES) -> str:
    with path.open("rb") as fh:
        fh.seek(0, 2)
        size = fh.tell()
        start = max(0, size - max_bytes)
        fh.seek(start)
        raw = fh.read()
    if start > 0:
        nl = raw.find(b"\n")
        if nl >= 0:
            raw = raw[nl + 1 :]
    return raw.decode("utf-8", errors="replace")
