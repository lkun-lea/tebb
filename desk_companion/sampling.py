"""这一轮对话的采样参数。缺字段或越界就失败，不补默认值。"""
from __future__ import annotations

EFFORTS = ("low", "high", "max")
TASK_DEFAULTS = dict(reasoning_effort='low',temperature=.5,top_p=1)


def parse_sampling(raw: object) -> dict:
    if not isinstance(raw, dict):
        raise RuntimeError("这条消息没有采样参数。恢复：重新打开客户端后再发。")
    effort = raw.get("reasoning_effort")
    if effort not in EFFORTS:
        raise RuntimeError("思考力度只能是 low、high、max。恢复：在对话框里重选一档再发。")
    temperature = _number(raw.get("temperature"), "温度", 0, 1)
    top_p = _number(raw.get("top_p"), "top_p", 0.01, 1)
    return {
        "reasoning_effort": effort,
        "temperature": temperature,
        "top_p": top_p,
    }


def _number(value: object, name: str, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RuntimeError(f"{name} 必须是数字。恢复：拖动滑块后再发。")
    number = float(value)
    if number < low or number > high:
        raise RuntimeError(
            f"{name} 要在 {low} 到 {high} 之间。恢复：把滑块拖回范围内再发。"
        )
    return number
