"""崩溃日志：写 stderr 和 desk_companion.log，卡住则由独立进程杀。"""
from __future__ import annotations

from desk_companion.infrastructure.paths import data_root

import os
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path

LOG_PATH = data_root() / "desk_companion.log"
READY_FLAG = data_root() / "desk_companion.ready"
_LOCK = threading.Lock()
CREATE_NO_WINDOW = 0x08000000


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} [{threading.current_thread().name}] {msg}"
    print(line, file=sys.stderr, flush=True)
    with _LOCK:
        with LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")


def mark_ready() -> None:
    READY_FLAG.write_text("ok", encoding="utf-8")


def crash(where: str, exc: BaseException | None = None) -> None:
    """记下堆栈后立刻结束全部进程，避免 WNDPROC / 死锁把窗口挂住。"""
    tb = traceback.format_exc()
    if exc is None:
        log(f"CRASH {where}\n{tb}")
    else:
        log(f"CRASH {where}: {type(exc).__name__}: {exc}\n{tb}")
    os._exit(1)


def start_os_watchdog(seconds: int = 25) -> None:
    """独立进程倒计时。主进程 GIL 卡死时也能 taskkill。"""
    if READY_FLAG.exists():
        READY_FLAG.unlink()
    pid = os.getpid()
    log_path = str(LOG_PATH)
    flag = str(READY_FLAG)
    code = (
        "import subprocess, time, pathlib\n"
        f"time.sleep({seconds})\n"
        f"flag = pathlib.Path(r'{flag}')\n"
        "if flag.exists():\n"
        "    raise SystemExit(0)\n"
        f"log = pathlib.Path(r'{log_path}')\n"
        "log.open('a', encoding='utf-8').write(\n"
        f"    '{time.strftime('%Y-%m-%d %H:%M:%S')} [watchdog] WATCHDOG 杀进程 {pid}\\n')\n"
        f"subprocess.run(['taskkill', '/F', '/T', '/PID', '{pid}'], capture_output=True)\n"
    )
    subprocess.Popen(
        [sys.executable, "-c", code],
        creationflags=CREATE_NO_WINDOW,
    )
    log(f"OS watchdog {seconds}s pid={pid}")


def install_crash_hooks() -> None:
    def hook(exc_type, exc, tb) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            os._exit(0)
        log("CRASH sys.excepthook\n" + "".join(traceback.format_exception(exc_type, exc, tb)))
        os._exit(1)

    def thread_hook(args) -> None:
        if args.exc_type is KeyboardInterrupt:
            return
        crash(f"thread:{args.thread.name if args.thread else '?'}", args.exc_value)

    sys.excepthook = hook
    threading.excepthook = thread_hook
    log(f"日志文件 {LOG_PATH}")
