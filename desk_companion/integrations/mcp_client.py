"""斜杠菜单里的 MCP：只读 desk-companion/mcp.json，stdio + Content-Length。"""
from __future__ import annotations

from desk_companion.infrastructure.paths import data_root

import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path

CREATE_NO_WINDOW = 0x08000000
LIST_TIMEOUT = 15
CALL_TIMEOUT = 45
SEP = "\u001f"
_ALLOWED = frozenset({"command", "args", "env"})


def mcp_config_path() -> Path:
    return data_root() / "mcp.json"


def mcp_fn_name(server: str, tool: str) -> str:
    """登记到模型侧的工具名。同一轮里必须和【本轮指定】用的是同一个。"""
    name = f"mcp_{_safe(server)}_{_safe(tool)}"
    if len(name) > 64:
        name = name[:64]
    if not name[0].isalpha():
        name = "m" + name[:63]
    return name


def menu_id(server: str, tool: str) -> str:
    return f"{server}{SEP}{tool}"


def list_mcp_menu() -> dict:
    try:
        servers = load_mcp_config()
    except RuntimeError as exc:
        return {"ok": False, "error": str(exc), "items": []}
    items: list[dict] = []
    errors: list[str] = []
    for name, spec in servers.items():
        try:
            tools = list_tools(name, spec)
        except RuntimeError as exc:
            errors.append(f"{name}：{exc}")
            continue
        for tool in tools:
            desc = tool["description"].replace("\n", " ").strip()
            if len(desc) > 80:
                desc = desc[:80] + "…"
            items.append(
                {
                    "id": menu_id(name, tool["name"]),
                    "label": f"{name} / {tool['name']}",
                    "description": desc,
                }
            )
    if errors and not items:
        return {"ok": False, "error": "\n".join(errors), "items": []}
    out: dict = {"ok": True, "items": items}
    if errors:
        out["error"] = "\n".join(errors)
    return out


def load_mcp_config() -> dict[str, dict]:
    path = mcp_config_path()
    if not path.is_file():
        raise RuntimeError(
            f"没有 {path}。在 desk-companion/mcp.json 写上 mcpServers 后再开 MCP。"
            "每一项只要 command，可选 args 和 env。不支持 url。"
        )
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{path} 不是合法 JSON。删掉或修好后再开 MCP。") from exc
    return parse_mcp_config(raw, str(path))


def parse_mcp_config(raw, path: str) -> dict[str, dict]:
    if not isinstance(raw, dict):
        raise RuntimeError(f"{path} 根节点必须是对象。")
    if set(raw) != {"mcpServers"}:
        raise RuntimeError(f"{path} 只能有 mcpServers。")
    servers = raw["mcpServers"]
    if not isinstance(servers, dict) or not servers:
        raise RuntimeError(f"{path} 的 mcpServers 必须是非空对象。")
    out: dict[str, dict] = {}
    for name, spec in servers.items():
        if type(name) is not str or not name.strip() or _bad_token(name):
            raise RuntimeError(f"{path} 里有空的或带空白的服务器名。")
        if not isinstance(spec, dict):
            raise RuntimeError(f"MCP 服务器 {name} 必须是对象。")
        extra = set(spec) - _ALLOWED
        if extra:
            raise RuntimeError(
                f"MCP 服务器 {name} 有不认识的字段：{', '.join(sorted(extra))}。"
                "只支持 command、args、env。"
            )
        command = spec.get("command")
        if type(command) is not str or not command.strip():
            raise RuntimeError(f"MCP 服务器 {name} 缺少 command。")
        args = spec.get("args") or []
        if type(args) is not list or any(type(item) is not str for item in args):
            raise RuntimeError(f"MCP 服务器 {name} 的 args 必须是字符串列表。")
        env = spec.get("env") or {}
        if not isinstance(env, dict) or any(type(key) is not str or type(val) is not str for key, val in env.items()):
            raise RuntimeError(f"MCP 服务器 {name} 的 env 必须是字符串到字符串。")
        out[name.strip()] = {"command": command.strip(), "args": list(args), "env": dict(env)}
    return out


def list_tools(server: str, spec: dict) -> list[dict]:
    with _session(server, spec, LIST_TIMEOUT) as request:
        return _collect_tools(request)


def describe_tool(server: str, tool: str) -> dict:
    servers = load_mcp_config()
    if server not in servers:
        raise RuntimeError(f"mcp.json 里没有服务器 {server}。")
    found = [item for item in list_tools(server, servers[server]) if item["name"] == tool]
    if len(found) != 1:
        raise RuntimeError(f"MCP 服务器 {server} 里没有工具 {tool}。")
    return found[0]


def call_mcp_tool(server: str, tool: str, arguments: dict) -> str:
    if not isinstance(arguments, dict):
        return "参数必须是对象。"
    try:
        servers = load_mcp_config()
        if server not in servers:
            return f"mcp.json 里没有服务器 {server}。"
        with _session(server, servers[server], CALL_TIMEOUT) as request:
            result = request("tools/call", {"name": tool, "arguments": arguments})
    except RuntimeError as exc:
        return str(exc)
    content = result.get("content")
    if not isinstance(content, list) or not content:
        return "工具没有返回文本。"
    texts: list[str] = []
    for part in content:
        if not isinstance(part, dict) or part.get("type") != "text" or type(part.get("text")) is not str:
            return "工具返回了非文本内容，这一轮用不了。"
        texts.append(part["text"])
    body = "\n".join(texts).strip()
    if not body:
        return "工具没有返回文本。"
    if result.get("isError") is True:
        return f"工具失败：{body}"
    return body


def attach_mcp_tools(toolkit, picks: list) -> list[str]:
    """这一轮点中的 MCP 工具登记进 toolkit。返回登记名，说完由调用方删掉。"""
    if type(picks) is not list or not picks:
        raise RuntimeError("MCP 点选必须是非空列表。")
    names: list[str] = []
    try:
        for pick in picks:
            if not isinstance(pick, dict):
                raise RuntimeError("MCP 点选的每一项必须是对象。")
            server = str(pick.get("server") or "").strip()
            tool = str(pick.get("tool") or "").strip()
            spec = describe_tool(server, tool)
            name = mcp_fn_name(server, tool)
            if name in names or name in toolkit._tools:
                raise RuntimeError(f"MCP 工具名和已有工具撞了：{name}。")
            toolkit.register(
                func=_caller(server, tool),
                name=name,
                description=spec["description"] or f"调用 MCP {server} 的 {tool}。",
                parameters=spec["parameters"],
                isReadOnly=False,
                retry_max=0,
            )
            names.append(name)
    except Exception:
        detach_mcp_tools(toolkit, names)
        raise
    return names


def detach_mcp_tools(toolkit, names: list[str]) -> None:
    for name in names:
        toolkit._tools.pop(name, None)


def _caller(server: str, tool: str) -> Callable[[dict], str]:
    def call(args: dict) -> str:
        if not isinstance(args, dict):
            return "参数必须是对象。"
        return call_mcp_tool(server, tool, args)

    return call


def _collect_tools(request: Callable) -> list[dict]:
    tools: list[dict] = []
    cursor = ""
    for _ in range(5):
        params: dict = {}
        if cursor:
            params["cursor"] = cursor
        result = request("tools/list", params)
        batch = result.get("tools")
        if not isinstance(batch, list):
            raise RuntimeError("tools/list 缺少 tools。")
        for item in batch:
            tools.append(_parse_tool(item))
        cursor = result.get("nextCursor") or ""
        if type(cursor) is not str:
            raise RuntimeError("tools/list 的 nextCursor 必须是字符串。")
        if not cursor:
            return tools
    raise RuntimeError("MCP 工具翻页超过 5 次，没有列完。")


def _parse_tool(item) -> dict:
    if not isinstance(item, dict):
        raise RuntimeError("MCP 工具必须是对象。")
    name = item.get("name")
    if type(name) is not str or not name.strip() or _bad_token(name):
        raise RuntimeError("MCP 工具缺少可用的 name。")
    description = item.get("description") or ""
    if type(description) is not str:
        raise RuntimeError(f"MCP 工具 {name} 的 description 必须是字符串。")
    schema = item.get("inputSchema")
    if not isinstance(schema, dict) or schema.get("type") != "object":
        raise RuntimeError(f"MCP 工具 {name} 的 inputSchema 必须是 type=object。")
    return {"name": name.strip(), "description": description, "parameters": schema}


def _session(server: str, spec: dict, timeout: int):
    return _McpSession(server, spec, timeout)


class _McpSession:
    def __init__(self, server: str, spec: dict, timeout: int) -> None:
        self._server = server
        self._spec = spec
        self._timeout = timeout
        self._proc: subprocess.Popen | None = None
        self._queue: queue.Queue = queue.Queue()
        self._err: list[bytes] = []
        self._seq = 0

    def __enter__(self) -> Callable:
        creationflags = CREATE_NO_WINDOW if sys.platform == "win32" else 0
        env = os.environ.copy()
        env.update(self._spec["env"])
        try:
            self._proc = subprocess.Popen(
                _argv(self._spec["command"], self._spec["args"]),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(mcp_config_path().parent),
                env=env,
                creationflags=creationflags,
            )
        except OSError as exc:
            raise RuntimeError(f"启动 MCP {self._server} 失败。{exc}") from exc
        proc = self._proc
        threading.Thread(target=_pump, args=(proc.stdout, self._queue), daemon=True).start()
        threading.Thread(target=_drain, args=(proc.stderr, self._err), daemon=True).start()
        self.request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "desk-companion", "version": "0.2.0"},
            },
        )
        self.request("notifications/initialized", None, notify=True)
        return self.request

    def __exit__(self, exc_type, exc, tb) -> None:
        proc = self._proc
        if proc is None:
            return
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()

    def request(self, method: str, params, notify: bool = False):
        proc = self._proc
        if proc is None or proc.stdin is None:
            raise RuntimeError(f"MCP {self._server} 没有启动。")
        self._seq += 1
        mid = self._seq
        msg: dict = {"jsonrpc": "2.0", "method": method}
        if not notify:
            msg["id"] = mid
        if params is not None:
            msg["params"] = params
        _write(proc, msg)
        if notify:
            return None
        deadline = time.monotonic() + self._timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError(self._fail(f"MCP {self._server} 超时（{self._timeout}s）。"))
            try:
                item = self._queue.get(timeout=remaining)
            except queue.Empty:
                raise RuntimeError(self._fail(f"MCP {self._server} 超时（{self._timeout}s）。")) from None
            if isinstance(item, Exception):
                raise RuntimeError(self._fail(f"MCP {self._server}：{item}")) from item
            if item.get("id") != mid:
                continue
            if "error" in item:
                raise RuntimeError(self._fail(f"MCP {self._server}：{_rpc_error(item['error'])}"))
            result = item.get("result")
            if not isinstance(result, dict):
                raise RuntimeError(self._fail(f"MCP {self._server} 的响应没有 result。"))
            return result

    def _fail(self, message: str) -> str:
        tail = _err_tail(self._err)
        if tail:
            return f"{message}\n{tail}"
        return message


def _argv(command: str, args: list[str]) -> list[str]:
    found = shutil.which(command)
    if not found:
        raise RuntimeError(f"找不到命令 {command}。把可执行文件放进 PATH，或在 mcp.json 里写绝对路径。")
    if os.name == "nt" and found.lower().endswith((".cmd", ".bat")):
        return ["cmd.exe", "/c", subprocess.list2cmdline([found, *args])]
    return [found, *args]


def _write(proc: subprocess.Popen, msg: dict) -> None:
    if proc.stdin is None:
        raise RuntimeError("MCP 进程没有 stdin。")
    body = json.dumps(msg, ensure_ascii=False).encode("utf-8")
    proc.stdin.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body)
    proc.stdin.flush()


def _pump(stdout, out: queue.Queue) -> None:
    try:
        buf = b""
        while True:
            msg, buf = _read_frame(stdout, buf)
            out.put(msg)
    except Exception as exc:
        out.put(exc)


def _read_frame(stdout, buf: bytes) -> tuple[dict, bytes]:
    while b"\r\n\r\n" not in buf:
        chunk = stdout.read(1)
        if not chunk:
            raise RuntimeError("进程在送出完整帧之前退出了。")
        buf += chunk
        if len(buf) > 65536:
            raise RuntimeError("帧头过长，不是 Content-Length。")
    head, buf = buf.split(b"\r\n\r\n", 1)
    length = _content_length(head)
    while len(buf) < length:
        chunk = stdout.read(length - len(buf))
        if not chunk:
            raise RuntimeError("正文被截断。")
        buf += chunk
    body, buf = buf[:length], buf[length:]
    try:
        msg = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError("正文不是 JSON。") from exc
    if not isinstance(msg, dict):
        raise RuntimeError("消息不是对象。")
    return msg, buf


def _content_length(head: bytes) -> int:
    length = None
    for line in head.split(b"\r\n"):
        if line.lower().startswith(b"content-length:"):
            raw = line.split(b":", 1)[1].strip()
            if not raw.isdigit():
                raise RuntimeError("Content-Length 不是整数。")
            length = int(raw)
    if length is None:
        raise RuntimeError("帧头没有 Content-Length。")
    if length > 8_000_000:
        raise RuntimeError("MCP 正文超过 8MB。")
    return length


def _drain(stderr, chunks: list[bytes]) -> None:
    if stderr is None:
        return
    data = stderr.read()
    if data:
        chunks.append(data)


def _err_tail(chunks: list[bytes]) -> str:
    if not chunks:
        return ""
    text = b"".join(chunks).decode("utf-8", errors="replace").strip()
    if len(text) > 500:
        text = text[-500:]
    return text


def _rpc_error(error) -> str:
    if isinstance(error, dict):
        message = error.get("message")
        if type(message) is str and message.strip():
            return message.strip()
    return "调用被拒绝。"


def _bad_token(text: str) -> bool:
    return any(ch.isspace() for ch in text) or SEP in text


def _safe(part: str) -> str:
    chars = []
    for ch in part:
        chars.append(ch if ch.isascii() and (ch.isalnum() or ch == "_") else "_")
    text = "".join(chars).strip("_") or "x"
    return text[:24]
