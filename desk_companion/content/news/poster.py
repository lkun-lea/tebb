"""每日海报：原创科技背景 + 当期真实标题与五项重点。"""
from desk_companion.infrastructure.paths import ui_root
from pathlib import Path
import os
from PIL import Image, ImageDraw, ImageFont, ImageOps
from desk_companion.content.news.service import runs_root


def wrap_text(text, font, width, lines):
    rows, line = [], ""
    for ch in str(text):
        if ch == "\n" or font.getlength(line + ch) > width:
            rows.append(line)
            line = "" if ch == "\n" else ch
        else:
            line += ch
    if line:
        rows.append(line)
    if len(rows) > lines:
        rows = rows[:lines]
        while rows[-1] and font.getlength(rows[-1] + "…") > width:
            rows[-1] = rows[-1][:-1]
        rows[-1] += "…"
    return rows


def render_cover(run):
    width, height = 1440, 810
    asset = ui_root() / "news-poster-v1.png"
    if asset.exists():
        with Image.open(asset) as source:
            image = ImageOps.fit(source.convert("RGB"), (width, height)).convert("RGBA")
    else:
        image = Image.new("RGBA", (width, height), "#061021")
    veil = Image.new("RGBA", image.size)
    v = ImageDraw.Draw(veil)
    for x in range(width):
        v.line((x, 0, x, height), fill=(2, 7, 19, int(125 * max(0, 1-x/1000))))
    for y in range(535, height):
        v.line((0, y, width, y), fill=(2, 7, 19, int(205*(y-535)/(height-535))))
    image = Image.alpha_composite(image, veil)
    draw = ImageDraw.Draw(image)
    font_root = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    regular, bold = font_root / "msyh.ttc", font_root / "msyhbd.ttc"
    fallback = ui_root() / "fonts/ZCOOLKuaiLe-Regular.ttf"
    def font(size, heavy=False):
        file = bold if heavy and bold.exists() else regular if regular.exists() else fallback
        return ImageFont.truetype(str(file), size)
    def text(position, value, size, color="#f4f8ff", heavy=False, stroke=0):
        draw.text(position, value, font=font(size, heavy), fill=color, stroke_width=stroke, stroke_fill="#07101f")
    report, items = run["report"], run["report"]["items"]
    draw.rounded_rectangle((60, 45, 336, 90), 12, fill="#81f5cf")
    text((76, 51), "开源前沿 / AI WATCH", 22, "#071421", True)
    text((365, 51), run["day"], 23, "#c4d8ef")
    text((62, 116), "国内 × 海外  /  大厂技术动向", 26, "#98d9ff")
    title = report.get("cover_title") or "开源前沿\n大厂新动向"
    heading = font(82, True)
    rows = wrap_text(title, heading, 810, 2)
    if "\n" not in title and len(rows) == 2:
        # 平衡两行，避免长标题最后只剩一个字，也尽量不拆开英文项目名。
        splits = [(i, title[:i].rstrip(), title[i:].lstrip()) for i in range(1, len(title))]
        fits = [(a, b) for i, a, b in splits if heading.getlength(a) <= 810 and heading.getlength(b) <= 810
                and not (title[i-1].isascii() and title[i-1].isalnum() and title[i].isascii() and title[i].isalnum())]
        if fits:
            rows = min(fits, key=lambda pair: abs(heading.getlength(pair[0])-heading.getlength(pair[1])))
    for i, line in enumerate(rows):
        text((56, 169+i*104), line, 82, "#ffffff" if i == 0 else "#81f5cf", True, 2)
    for i, line in enumerate(wrap_text(report["lead"], font(26), 750, 2)):
        text((62, 398+i*40), line, 26, "#d2e5ff", stroke=1)
    text((63, 516), "从官方发布看变化 · 从工程实践看价值", 23, "#a5bdd8")
    draw.rounded_rectangle((1254, 41, 1375, 177), 20, fill="#13182e", outline="#81f5cf", width=2)
    text((1286, 39), str(len(items)), 77, "#81f5cf", True)
    text((1278, 131), "条重点", 21)
    gap, x = 15, 60
    card_width = (width-120-gap*4)//5
    for i, item in enumerate(items[:5]):
        left = x+i*(card_width+gap)
        draw.rounded_rectangle((left, 604, left+card_width, 764), 15, fill="#0b162b", outline="#355172", width=2)
        draw.rounded_rectangle((left+15, 620, left+49, 651), 7, fill="#81f5cf" if i == 0 else "#93bdff")
        text((left+24, 622), str(i+1), 18, "#091323", True)
        text((left+60, 622), item.get("company") or item["category"][:7], 20, "#b8d7fa", True)
        label = item.get("poster_label") or item.get("title_zh") or item["title"]
        if not item.get("poster_label") and label.startswith(item["title"]):
            label = label[len(item["title"]):].lstrip("：: ") or label
        for j, line in enumerate(wrap_text(label, font(21, True), card_width-30, 3)):
            text((left+15, 662+j*29), line, 21, heavy=True)
    text((62, 781), "AI / AGENT 工程日报    ·    官方来源核实    ·    详解、证据与局限见每日文档", 15, "#96b1cd")
    path = runs_root() / (run["id"]+".png")
    path.parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGB").save(path)
    return path
