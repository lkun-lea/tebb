"""Run text-only free chat against the private Ollama service on this host."""
import json
import sqlite3
from contextlib import closing

import httpx

from desk_companion.infrastructure.paths import data_root


def answer(request, emit):
    history = []
    with closing(sqlite3.connect(data_root() / "memory/tasks.sqlite3")) as db:
        rows = db.execute("""SELECT text, answer FROM tasks WHERE session=? AND state='succeeded'
            AND created < (SELECT created FROM tasks WHERE id=?) ORDER BY created DESC LIMIT 3""",
            (request["session_id"], request["task_id"])).fetchall()
    for prompt, reply in reversed(rows):
        history.extend([dict(role="user", content=prompt[:350]), dict(role="assistant", content=reply[:350])])
    history.append(dict(role="user", content=request["text"]))
    parts = []
    payload = dict(model="qwen3:0.6b", messages=history, stream=True, think=False,
                   options=dict(num_ctx=2048, num_predict=384))
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
