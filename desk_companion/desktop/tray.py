"""系统托盘。"""
from __future__ import annotations

from PIL import Image, ImageDraw
from pystray import Icon, Menu, MenuItem

from desk_companion.desktop.pet_shell import CMD_BOARD, CMD_HIDE, CMD_QUIT, CMD_SHOW
from desk_companion.desktop.skin import Skin


def start_tray(app, skin: Skin) -> Icon:
    icon = Icon(
        "desk-companion",
        _tray_image(),
        skin.display_name,
        Menu(
            MenuItem("显示宠物", lambda _i, _m: app.post_pet(CMD_SHOW), default=True),
            MenuItem("隐藏宠物", lambda _i, _m: app.post_pet(CMD_HIDE)),
            MenuItem("打开看板", lambda _i, _m: app.post_pet(CMD_BOARD)),
            MenuItem(
                "主动搭话",
                lambda _i, _m: app.toggle_nudge(),
                checked=lambda _i: app.state.nudge_enabled,
            ),
            MenuItem(
                "点击穿透",
                lambda _i, _m: app.toggle_click_through(),
                checked=lambda _i: app.state.click_through,
            ),
            MenuItem("退出", lambda _i, _m: app.post_pet(CMD_QUIT)),
        ),
    )
    icon.run_detached()
    return icon


def _tray_image() -> Image.Image:
    canvas = Image.new("RGBA", (64, 64), (245, 248, 248, 255))
    draw = ImageDraw.Draw(canvas)
    draw.ellipse((10, 8, 54, 52), fill=(240, 240, 240, 255), outline=(45, 50, 56, 255), width=2)
    draw.polygon([(40, 10), (54, 18), (42, 22)], fill=(200, 216, 74, 255))
    return canvas
