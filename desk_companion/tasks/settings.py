"""Persistence and validation of user task settings."""
import json

from desk_companion.infrastructure.paths import data_root
from desk_companion.infrastructure.storage import atomic_write

DEFAULTS = {"parallel": 2, "call_timeout": 90, "task_timeout": 300, "pet_progress": True}


def settings_path(directory=None):
    return (directory or data_root() / "memory") / "task_settings.json"


def validate(parallel, call_timeout, task_timeout, pet_progress):
    if type(parallel) is not int or not 1 <= parallel <= 4:
        raise ValueError("并行数须为 1～4。")
    if type(call_timeout) is not int or not 10 <= call_timeout <= 300:
        raise ValueError("单次调用时限须为 10～300 秒。")
    if type(task_timeout) is not int or not call_timeout <= task_timeout <= 1800:
        raise ValueError("总时限须大于单次调用时限，且不超过 1800 秒。")
    if type(pet_progress) is not bool:
        raise ValueError("桌宠进度反馈须为开关。")


def read_settings(path, defaults):
    """Missing fields inherit the caller's defaults, including role-specific budgets."""
    try:
        saved = json.loads(path.read_text("utf-8"))
        if not isinstance(saved, dict):
            return dict(defaults)
        settings = {key: saved.get(key, value) for key, value in defaults.items()}
        validate(**{**DEFAULTS, **{key: saved[key] for key in DEFAULTS if key in saved}, **settings})
        return settings
    except (FileNotFoundError, ValueError):
        return dict(defaults)


def save_settings(path, settings):
    validate(**settings)
    atomic_write(path, settings)
