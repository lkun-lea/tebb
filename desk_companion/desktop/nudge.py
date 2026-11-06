"""到点模板纸条：只根据今日日程/过期待办拼句，不调模型。"""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

TZ = timezone(timedelta(hours=8))


def pick_template(board: dict, now: datetime | None = None) -> str:
    now = now or datetime.now(TZ)
    agenda = board.get("agenda")
    tasks = board.get("tasks")
    if not isinstance(agenda, dict) or "ok" not in agenda:
        raise RuntimeError("看板数据缺少 agenda.ok。")
    if not isinstance(tasks, dict) or "ok" not in tasks:
        raise RuntimeError("看板数据缺少 tasks.ok。")
    if not agenda["ok"]:
        raise RuntimeError(agenda.get("error") or "读取日程失败。")
    if not tasks["ok"]:
        raise RuntimeError(tasks.get("error") or "读取待办失败。")

    candidates: list[str] = []
    nearest = _nearest_event(agenda.get("items") or [], now)
    if nearest:
        minutes, title = nearest
        if minutes <= 0:
            candidates.append(f"「{title}」该开始了")
        else:
            candidates.append(f"{minutes} 分钟后有「{title}」")
    overdue = _overdue_tasks(tasks.get("items") or [], now)
    if overdue:
        candidates.append(f"「{overdue[0]}」还没做完")
    if not candidates:
        candidates.append(_time_line(now))
    return random.choice(candidates)


def _time_line(now: datetime) -> str:
    hour = now.hour
    if 6 <= hour < 11:
        return "上午好，要不要看今日安排？"
    if 11 <= hour < 14:
        return "中午了，待办还挂着吗？"
    if 14 <= hour < 18:
        return "下午了，日程还跟得上吗？"
    if 18 <= hour < 23:
        return "晚上了，记得收一收待办。"
    return "还没睡？记得休息。"


def _nearest_event(items: list, now: datetime) -> tuple[int, str] | None:
    best: tuple[int, str] | None = None
    for item in items:
        if not isinstance(item, dict):
            raise RuntimeError("日程条目不是对象。")
        title = item.get("summary")
        start = item.get("start")
        if not title or not start:
            raise RuntimeError(f"日程缺 summary/start: {item}")
        start = str(start)
        if "全天" in start:
            continue
        event = _parse_today_hm(start, now)
        delta_min = int(round((event - now).total_seconds() / 60))
        if delta_min < -5 or delta_min > 45:
            continue
        if best is None or delta_min < best[0]:
            best = (max(delta_min, 0), str(title))
    return best


def _parse_today_hm(start: str, now: datetime) -> datetime:
    text = start.strip()
    if len(text) >= 5 and text[2] == ":":
        try:
            hour = int(text[:2])
            minute = int(text[3:5])
        except ValueError as exc:
            raise RuntimeError(f"无法解析日程时间 {start!r}。") from exc
        return now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    raise RuntimeError(f"无法解析日程时间 {start!r}。")


def _overdue_tasks(items: list, now: datetime) -> list[str]:
    out: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            raise RuntimeError("待办条目不是对象。")
        title = item.get("summary")
        if not title:
            raise RuntimeError(f"待办缺 summary: {item}")
        due = item.get("due_at") or ""
        if due and _due_passed(str(due), now):
            out.append(str(title))
    return out


def _due_passed(due: str, now: datetime) -> bool:
    text = due.strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RuntimeError(f"无法解析待办截止时间 {due!r}。") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=TZ)
    return parsed <= now
