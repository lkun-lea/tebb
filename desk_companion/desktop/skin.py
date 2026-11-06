"""Live2D 形象包：只认 skins/<id>/pet.json + model3.json。"""
from __future__ import annotations
from desk_companion.infrastructure.paths import source_root

import json
from dataclasses import dataclass
from pathlib import Path


def skins_dir() -> Path:
    return source_root() / "skins"


@dataclass
class Skin:
    skin_id: str
    display_name: str
    folder: Path
    model_path: Path


def load_skin(skin_id: str) -> Skin:
    folder = skins_dir() / skin_id
    manifest_path = folder / "pet.json"
    if not manifest_path.is_file():
        raise RuntimeError(
            f"形象包 {skin_id} 不存在。当前桌宠只加载 Live2D，请使用 skins/kaltsit。"
        )
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    model_name = data.get("model")
    display = data.get("displayName") or data.get("id") or skin_id
    if not model_name:
        raise RuntimeError(f"{manifest_path} 缺少 model。")
    model_path = folder / str(model_name)
    if not model_path.is_file():
        raise RuntimeError(f"缺少模型文件 {model_path}。")
    return Skin(
        skin_id=str(data.get("id") or skin_id),
        display_name=str(display),
        folder=folder,
        model_path=model_path,
    )
