"""Electron 宠物壳：TCP 行协议连 pet-ui，不再画逐帧分层窗。"""
from __future__ import annotations
from desk_companion.infrastructure.paths import source_root

import json
import socket
import subprocess
import threading
import time
from pathlib import Path

from desk_companion.desktop.layered import SCALES, screen_area, work_area
from desk_companion.observability.logutil import crash, log
from desk_companion.memory.history import recent_chat

CMD_SHOW = 1
CMD_HIDE = 2
CMD_BOARD = 3
CMD_QUIT = 4

BASE_PET_W = 400
BASE_PET_H = 500
BASE_SCALE = 1.5
PET_UI = source_root() / "pet-ui"
READY_WAIT_S = 25
PIN_LIFT_Y = 24


def pet_box(scale: float) -> tuple[int, int]:
    factor = float(scale) / BASE_SCALE
    return round(BASE_PET_W * factor), round(BASE_PET_H * factor)


class PetShell:
    def __init__(self, host, skin) -> None:
        self.host = host
        self.skin = skin
        self.hwnd = 0
        self.busy = False
        self.bubble_open = False
        self._visible = True
        self._proc: subprocess.Popen | None = None
        self._client: socket.socket | None = None
        self._lock = threading.Lock()
        self._ready = threading.Event()
        self._fail = ""
        self.thread = threading.current_thread()
        self._listen()
        self._spawn()
        if not self._ready.wait(READY_WAIT_S):
            self.close()
            raise RuntimeError(
                "Electron 宠物窗没有在规定时间内就绪。请确认已在 pet-ui 执行 npm install && npm run build。"
                f" 详情见 {PET_UI / 'electron.log'}。"
            )
        if self._fail:
            self.close()
            raise RuntimeError(self._fail)
        threading.Thread(target=self._pump, daemon=True).start()

    def _listen(self) -> None:
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind(("127.0.0.1", 0))
        self._server.listen(1)
        host, port = self._server.getsockname()
        self.bridge = f"{host}:{port}"
        threading.Thread(target=self._accept, daemon=True).start()

    def _electron_exe(self) -> Path:
        exe = PET_UI / "node_modules" / "electron" / "dist" / "electron.exe"
        if not exe.is_file():
            raise RuntimeError(
                f"找不到 Electron。请在 {PET_UI} 执行 npm install && npm run build。"
            )
        main_js = PET_UI / "out" / "main" / "index.js"
        if not main_js.is_file():
            raise RuntimeError(
                f"找不到打包结果 {main_js}。请在 {PET_UI} 执行 npm run build。"
            )
        return exe

    def _spawn(self) -> None:
        state = self.host.state
        left, top, right, bottom = work_area()
        pet_w, pet_h = pet_box(state.scale)
        if state.drop_to_bottom:
            _sleft, _stop, _sright, screen_bottom = screen_area()
            x = right - pet_w
            y = screen_bottom - pet_h - PIN_LIFT_Y
        else:
            x = min(max(int(state.x), left), max(left, right - pet_w))
            y = min(max(int(state.y), top), max(top, bottom - pet_h))
        if x != state.x or y != state.y:
            state.x = x
            state.y = y
            state.save()
        cmd = [
            str(self._electron_exe()),
            str(PET_UI),
            "--",
            f"--bridge={self.bridge}",
            f"--model={self.skin.model_path}",
            f"--x={x}",
            f"--y={y}",
            f"--scale={state.scale}",
            f"--pin={'true' if state.drop_to_bottom else 'false'}",
            f"--click-through={'true' if state.click_through else 'false'}",
        ]
        log(f"启动 Electron: {cmd}")
        self._proc = subprocess.Popen(cmd, cwd=str(PET_UI))

    def _accept(self) -> None:
        try:
            client, _addr = self._server.accept()
        except OSError:
            return
        self._client = client
        buf = ""
        while True:
            try:
                chunk = client.recv(65536)
            except OSError:
                break
            if not chunk:
                break
            buf += chunk.decode("utf-8")
            while "\n" in buf:
                line, buf = buf.split("\n", 1)
                line = line.strip()
                if line:
                    self._on_line(line)
        self.host.ui(self.host.quit)

    def _on_line(self, line: str) -> None:
        msg = json.loads(line)
        if msg.get("dir") == "req":
            self._on_req(msg)
            return
        if msg.get("dir") == "evt":
            event = msg.get("event")
            params = msg.get("params") or {}
            if event == "ready":
                self.hwnd = int(params.get("hwnd") or 0)
                self._ready.set()
                return
            if event == "fail":
                self._fail = str(params.get("error") or "Electron 宠物窗启动失败。")
                self._ready.set()
                return
            self.host.ui(lambda m=msg: self._on_evt(m))
            return
        raise RuntimeError(f"未知桥方向 {msg.get('dir')!r}。")

    def _reply(self, req_id, ok: bool, result=None, error: str | None = None) -> None:
        payload = {"v": 1, "id": req_id, "dir": "res", "ok": ok}
        if ok:
            payload["result"] = result
        else:
            payload["error"] = error or "调用失败。"
        self._send(payload)

    def _send(self, obj: dict) -> None:
        data = (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")
        with self._lock:
            if self._client is None:
                raise RuntimeError("Electron 还没连上桥。")
            self._client.sendall(data)

    def emit(self, event: str, **params) -> None:
        self._send({"v": 1, "dir": "evt", "event": event, "params": params})

    def _on_req(self, msg: dict) -> None:
        method = msg.get("method")
        params = msg.get("params") or {}
        req_id = msg.get("id")
        try:
            result = self._dispatch(method, params)
        except Exception as exc:
            log(f"桥 req {method}: {exc}")
            self._reply(req_id, False, error=str(exc))
            return
        self._reply(req_id, True, result)

    def _dispatch(self, method: str, params: dict):
        if method == "send_chat":
            self.host.ui(lambda: self.host.send_chat(params.get("text") or ""))
            return None
        if method == "clear_chat":
            return self.host.clear_chat_history()
        if method == "load_history":
            return recent_chat(40, self.host.state.session_id)
        if method == "log_error":
            raise RuntimeError(str(params.get("message") or "Electron 渲染错误。"))
        if method == "bubble_today":
            from desk_companion.planning.board_data import bubble_today

            return bubble_today(refresh=bool(params.get("refresh")))
        raise RuntimeError(f"未知桥方法 {method}。")

    def _on_evt(self, msg: dict) -> None:
        event = msg.get("event")
        params = msg.get("params") or {}
        if event == "ready":
            return
        if event == "persist":
            self.host.state.x = int(params["x"])
            self.host.state.y = int(params["y"])
            self.host.state.save()
            return
        if event == "persist_scale":
            scale = float(params["scale"])
            if scale not in SCALES:
                raise RuntimeError(f"不支持的缩放 {scale}。")
            self.host.state.scale = scale
            self.host.state.save()
            return
        if event == "persist_pin":
            pin = params.get("pin")
            if type(pin) is not bool:
                raise RuntimeError("锁定右下角必须是 true/false。")
            self.host.state.drop_to_bottom = pin
            self.host.state.save()
            return
        if event == "persist_click_through":
            through = params.get("click_through")
            if type(through) is not bool:
                raise RuntimeError("点击穿透必须是 true/false。")
            self.host.state.click_through = through
            self.host.state.save()
            return
        if event == "open_board":
            self.host.show_board()
            return
        if event == "toggle_chat":
            self.bubble_open = True
            self.host.show_bubble()
            return
        if event == "bubble_opened":
            self.bubble_open = True
            return
        if event == "bubble_closed":
            self.bubble_open = False
            return
        if event == "hide_pet":
            self.host.hide_pet()
            return
        if event == "quit":
            self.host.quit()
            return
        raise RuntimeError(f"未知桥事件 {event}。")

    def _pump(self) -> None:
        while not self.host._quitting:
            try:
                self.host.drain_queue()
                self.host.on_pet_tick()
            except Exception as exc:
                crash("pet_pump", exc)
                return
            time.sleep(0.016)

    def post_cmd(self, cmd: int) -> None:
        if cmd == CMD_SHOW:
            self.show()
            return
        if cmd == CMD_HIDE:
            self.hide()
            return
        if cmd == CMD_BOARD:
            self.host.show_board()
            return
        if cmd == CMD_QUIT:
            self.host.quit()
            return
        raise RuntimeError(f"未知托盘命令 {cmd}。")

    def show(self) -> None:
        self._visible = True
        self.emit("show_pet")

    def hide(self) -> None:
        self._visible = False
        self.bubble_open = False
        self.emit("hide_pet")

    def visible(self) -> bool:
        return self._visible

    def persist(self) -> None:
        self.host.state.save()

    def set_busy(self, busy: bool) -> None:
        self.busy = busy
        self.emit("set_busy", busy=busy)

    def fail(self) -> None:
        self.busy = False
        self.emit("set_busy", busy=False)
        self.emit("play_motion", group="Fail")

    def review(self) -> None:
        self.busy = False
        self.emit("set_busy", busy=False)
        self.emit("play_motion", group="Done")

    def wave(self) -> None:
        self.emit("play_motion", group="Talk")

    def close(self) -> None:
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
        if self._client:
            try:
                self._client.close()
            except OSError:
                pass
        try:
            self._server.close()
        except OSError:
            pass


def start_pet_thread(host, skin) -> PetShell:
    box: list[PetShell | BaseException] = []
    ready = threading.Event()

    def run() -> None:
        try:
            box.append(PetShell(host, skin))
        except BaseException as exc:
            box.append(exc)
        finally:
            ready.set()

    threading.Thread(target=run, daemon=True, name="pet-shell").start()
    if not ready.wait(READY_WAIT_S + 5):
        raise RuntimeError("宠物壳启动超时。")
    item = box[0]
    if isinstance(item, BaseException):
        raise item
    return item
