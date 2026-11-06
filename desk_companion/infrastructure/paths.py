"""源码运行沿用仓库目录；发布版由客户端指定独立用户目录。"""
import os
from pathlib import Path


def package_root() -> Path:
    """Installed Python package root, independent of the working directory."""
    return Path(__file__).resolve().parents[1]


def source_root() -> Path:
    """Source checkout or the packaged site-packages directory."""
    return package_root().parent


def ui_root() -> Path:
    return package_root() / "ui"


def data_root() -> Path:
    value = os.environ.get("DESK_COMPANION_DATA_DIR")
    root = Path(value).expanduser().resolve() if value else source_root()
    root.mkdir(parents=True, exist_ok=True)
    return root


def asset_root() -> Path:
    value = os.environ.get("DESK_COMPANION_ASSET_DIR")
    return Path(value).resolve() if value else source_root() / "client/public"
