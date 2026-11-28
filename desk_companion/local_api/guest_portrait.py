"""Anonymous, bounded portrait generation. Only predefined consented tags cross the network."""
import json
import threading
import time
from typing import Literal

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict


class PortraitInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    habit: Literal["", "简短回答", "分步说明"] = ""
    activity: Literal["", "学习", "开发项目", "整理资料"] = ""


def generate(data):
    # Constrain a small model to grounded formulations. No account identifier, tools or history.
    clauses = []
    if data.habit:
        clauses.append([f"你偏好{data.habit}。", f"和你交流时，我会尽量{data.habit}。"])
    if data.activity:
        clauses.append([f"你最近在{data.activity}。", f"你提到近期在{data.activity}。"])
    options = [""]
    for clause in clauses:
        options = [prefix + phrase for prefix in options for phrase in clause]
    if not clauses:
        options = ["你还没有分享想让我了解的资料。"]
    schema = {"type": "object", "properties": {"summary": {"type": "string", "enum": options}},
              "required": ["summary"], "additionalProperties": False}
    payload = dict(model="qwen3:0.6b", stream=False, think=False, format=schema,
                   prompt="用中文写一小段对用户的了解，仅据这些资料：" + "、".join(filter(None, (data.habit, data.activity))),
                   options=dict(num_ctx=1024, num_predict=160))
    with httpx.Client(trust_env=False, timeout=60) as client:
        response = client.post("http://127.0.0.1:11434/api/generate", json=payload)
        response.raise_for_status()
    result = response.json()
    summary = json.loads(result["response"])["summary"]
    if not result.get("done") or summary not in options:
        raise ValueError("生成结果缺少依据")
    return {"summary": summary}


def install(app):
    lock = threading.Lock()
    next_allowed = 0.0

    @app.post("/cloud/v1/portrait")
    def portrait(data: PortraitInput):
        nonlocal next_allowed
        if not lock.acquire(blocking=False):
            raise HTTPException(429, "生成繁忙，请稍后重试")
        try:
            if time.monotonic() < next_allowed:
                raise HTTPException(429, "请稍后再生成")
            next_allowed = time.monotonic() + 15
            return generate(data)
        except (httpx.HTTPError, KeyError, ValueError):
            raise HTTPException(503, "云端生成未完成，请重试") from None
        finally:
            lock.release()


app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
install(app)
