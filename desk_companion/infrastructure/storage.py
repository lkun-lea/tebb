"""Atomic JSON replacement shared by domain-owned stores."""
import json
from pathlib import Path
import uuid


def atomic_write(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix("." + uuid.uuid4().hex + ".tmp")
    try:
        temp.write_text(json.dumps(value, ensure_ascii=False), "utf-8")
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)
