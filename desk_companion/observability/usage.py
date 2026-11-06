"""对话用量落盘：token 来自 Atlas，金额按用户填的单价。"""
from __future__ import annotations

from desk_companion.infrastructure.paths import data_root

import json
import threading
from datetime import datetime
from pathlib import Path

from desk_companion.memory.history import TZ

from desk_companion.infrastructure.resource_lock import ResourceLock
_LOCK = ResourceLock("usage")


def usage_path() -> Path:
    return data_root() / "memory" / "usage.jsonl"


def cost_cny(model: str, input_tokens: int, output_tokens: int, prices: dict) -> float | None:
    if not model:
        return None
    item = prices.get(model)
    if not isinstance(item, dict):
        return None
    if "input_cny_per_mtok" not in item or "output_cny_per_mtok" not in item:
        return None
    if input_tokens == 0 and output_tokens == 0:
        return None
    inn = item["input_cny_per_mtok"]
    out = item["output_cny_per_mtok"]
    return round(input_tokens * inn / 1_000_000 + output_tokens * out / 1_000_000, 6)


def append_usage(rec: dict) -> None:
    required = ("ts", "model", "input_tokens", "output_tokens", "total_tokens", "cost_cny", "run_id")
    missing = [key for key in required if key not in rec]
    if missing:
        raise RuntimeError(f"用量记录缺少字段 {', '.join(missing)}。")
    line = json.dumps(rec, ensure_ascii=False) + "\n"
    path = usage_path()
    with _LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line)


def summarize_usage() -> dict:
    path = usage_path()
    now = datetime.now(TZ)
    today = now.date().isoformat()
    month = now.strftime("%Y-%m")
    buckets = {
        "today": _empty_bucket(),
        "month": _empty_bucket(),
        "total": _empty_bucket(),
    }
    priced = False
    unpriced = False
    if not path.is_file():
        return {**{k: buckets[k] for k in buckets}, "priced": False, "unpriced": False}
    with _LOCK:
        lines = path.read_text(encoding="utf-8").splitlines()
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"{path} 有损坏行。请检查或删掉该文件。\n{line}") from exc
        ts = rec.get("ts")
        if not isinstance(ts, str) or len(ts) < 7:
            raise RuntimeError(f"{path} 记录缺合法 ts。\n{line}")
        inn = int(rec.get("input_tokens") or 0)
        out = int(rec.get("output_tokens") or 0)
        cost = rec.get("cost_cny")
        _add(buckets["total"], inn, out, cost)
        if ts[:7] == month:
            _add(buckets["month"], inn, out, cost)
        if ts[:10] == today:
            _add(buckets["today"], inn, out, cost)
        if cost is None:
            unpriced = True
        else:
            priced = True
    return {
        "today": buckets["today"],
        "month": buckets["month"],
        "total": buckets["total"],
        "priced": priced,
        "unpriced": unpriced,
    }


def _empty_bucket() -> dict:
    return {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "runs": 0, "cost_cny": 0.0}


def _add(bucket: dict, inn: int, out: int, cost) -> None:
    bucket["input_tokens"] += inn
    bucket["output_tokens"] += out
    bucket["total_tokens"] += inn + out
    bucket["runs"] += 1
    if isinstance(cost, (int, float)):
        bucket["cost_cny"] += float(cost)
