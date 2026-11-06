"""Workspace identity and atomic transactions; collaboration owns schema initialization."""
from contextlib import contextmanager
import json
import sqlite3

from desk_companion.infrastructure.paths import data_root


def workspace_path():
    return data_root() / "memory" / "collaboration" / "workspace.sqlite3"



@contextmanager
def transaction(path):
    db = sqlite3.connect(path, timeout=10)
    try:
        db.execute("BEGIN IMMEDIATE")
        raw = db.execute("SELECT data FROM workspace WHERE id=1").fetchone()[0]
        state = json.loads(raw)
        state.setdefault("projects", [])
        yield state, db
        value = json.dumps(state, ensure_ascii=False)
        if value != raw:
            state["revision"] = int(state.get("revision", 0)) + 1
            value = json.dumps(state, ensure_ascii=False)
            db.execute("UPDATE workspace SET data=? WHERE id=1", (value,))
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()
