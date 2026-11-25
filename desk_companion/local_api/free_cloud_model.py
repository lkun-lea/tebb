"""Run text-only free chat against the private Ollama service on this host."""
import json
import sqlite3
from pathlib import Path
from uuid import UUID, uuid4
import os
import tempfile
from contextlib import closing

import httpx

from desk_companion.infrastructure.paths import data_root


def history_path(ident):
    root = Path("/dev/shm") if os.name == "posix" else Path(tempfile.gettempdir())
    directory = root / ("tebb-chat-" + str(os.getuid()) if os.name == "posix" else "tebb-chat-context")
    directory.mkdir(mode=0o700, exist_ok=True)
    return directory / UUID(ident).hex


def stage_history(lines):
    import threading
    ident = uuid4().hex
    path = history_path(ident)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(lines, stream, ensure_ascii=False)
    expiry = threading.Timer(600, path.unlink, kwargs=dict(missing_ok=True))
    expiry.daemon = True
    expiry.start()
    return ident


def answer(request, emit):
    lines = []
    if request.get("local_history_file"):
        path = history_path(request["local_history_file"])
        try:
            lines = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            emit("failure", dict(type="ContextExpired", message="本轮临时上下文已过期，请重新发送。"))
            return
        finally:
            path.unlink(missing_ok=True)
    with closing(sqlite3.connect(data_root() / "memory/tasks.sqlite3")) as db:
        rows = db.execute("""SELECT created, text, answer FROM tasks WHERE session=? AND state='succeeded'
            AND created < (SELECT created FROM tasks WHERE id=?) ORDER BY created, id""",
            (request["session_id"], request["task_id"])).fetchall()
    for created, prompt, reply in rows:
        lines.extend([dict(created=created, role="user", content=prompt), dict(created=created, role="assistant", content=reply)])
    history = [dict(role=line["role"], content=line["content"]) for line in sorted(lines, key=lambda line: line["created"])]
    history.append(dict(role="user", content=request["text"]))
    # UTF-8 字节数给出保守上界，预留模板与回答空间，避免 Ollama 静默截断。
    budget = sum(len(line["content"].encode()) + 24 for line in history) + 512
    if budget > 16384:
        emit("failure", dict(type="ContextLimit", message="本会话超过云端模型上下文容量，请在本地继续。"))
        return
    parts = []
    payload = dict(model="qwen3:0.6b", messages=history, stream=True, think=False,
                   options=dict(num_ctx=max(2048, budget), num_predict=384))
    with httpx.Client(trust_env=False, timeout=120) as client:
        with client.stream("POST", "http://127.0.0.1:11434/api/chat", json=payload) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                event = json.loads(line)
                if event.get("error"):
                    raise RuntimeError("Ollama generation failed")
                token = event.get("message", {}).get("content", "")
                if token:
                    parts.append(token)
                    emit("token", token)
                if event.get("done") and "".join(parts).strip():
                    emit("result", "".join(parts))
                    return
    raise RuntimeError("Ollama stream ended without an answer")
