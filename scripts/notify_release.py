"""GitHub 发布通知入口；dry-run 仅生成预览，不读取凭据或操作飞书。"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from desk_companion.infrastructure.release_info import load_manifest, RELEASES_URL
from desk_companion.infrastructure.release_notify import Notifier, release_card


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", default=os.environ.get("RELEASE_TAG", ""))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--reconcile", choices=("auto", "confirmed_absent", "confirmed_sent"),
                        default=os.environ.get("RELEASE_RECONCILE", "auto"))
    args = parser.parse_args()
    manifest = load_manifest()
    if args.dry_run:
        print(json.dumps(release_card(manifest, "PREVIEW_IMAGE", RELEASES_URL+"/tag/"+manifest["tag"]), ensure_ascii=False, indent=2))
        return
    if not re.fullmatch(r"v\d+\.\d+\.\d+", args.tag): raise ValueError("请指定正式版本 tag。")
    notify = Notifier(os.environ.get("GH_TOKEN", ""), os.environ.get("FEISHU_APP_ID", ""),
                      os.environ.get("FEISHU_APP_SECRET", ""), os.environ.get("FEISHU_RELEASE_CHAT_ID", ""))
    release = notify.github("releases/tags/"+args.tag)
    result = notify.send(release, manifest, ROOT/"desk_companion/ui"/manifest["image"], reconcile=args.reconcile)
    print(json.dumps({"tag": args.tag, "state": result["state"]}, ensure_ascii=False))


if __name__ == "__main__":
    try: main()
    except Exception as exc:
        # 不打印原始平台响应、请求、环境或 traceback。
        print("发布通知未完成："+(str(exc) if isinstance(exc, (ValueError, RuntimeError)) else "请查看平台状态并核实后补跑。"), file=sys.stderr)
        sys.exit(1)
