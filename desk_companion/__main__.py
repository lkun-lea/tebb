"""Windows 桌宠个人助手入口。"""
from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="desk-companion")
    parser.add_argument("--skin", default="kaltsit", help="skins 目录下的形象包文件夹名")
    args = parser.parse_args(argv)
    from desk_companion.observability.logutil import crash, log

    try:
        from desk_companion.desktop.app import run_app

        run_app(args.skin)
    except RuntimeError as exc:
        log(f"启动 RuntimeError: {exc}")
        print(exc, file=sys.stderr)
        return 1
    except Exception as extra:
        crash("main", extra)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
