"""生成可部署在任意子路径下的免登录官方站。运行 python web/build.py。"""
import shutil
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "dist"
REPO = "https://github.com/lkun-lea/tebb"
VERSION = "0.4.1"
DOWNLOAD = f"{REPO}/releases/download/v{VERSION}/tebb-{VERSION}-windows-x64.zip"
POSTS = [
    ("project-companions", "产品故事", "给一个项目，留一位熟悉它的伙伴", "从打开文件夹开始，把讨论、资料和下一次行动留在同一个项目里。", [
        ("从一个具体问题开始", "假设你在准备一场方案评审。打开项目文件夹，把已有的说明文档附在聊天中，问研究助手：“这份方案有哪些结论还缺少依据？”先确认它看到了哪些材料，再决定接下来要补哪一段。"),
        ("让不同的伙伴分工", "需要一起讨论时，可以创建协作群，用 @ 指定研究或写作伙伴。研究伙伴核对资料，写作伙伴根据已确认的结论整理提纲。群里的往来和项目私聊分别保留，方便回到原话题。"),
        ("给下一次工作留个起点", "有用的答复可以收藏为笔记，下次再作为资料加入聊天。需要改文件时，先给项目授权，再核对实际差异和命令结果。重新打开同一文件夹，可以沿着项目中的会话继续。")], "blob/main/docs/FOLDER_PROJECTS.md"),
    ("getting-started", "使用指南", "在 Windows 上开始第一段对话", "下载、解压、连接自己的模型，然后用一份文档试试伙伴聊天。", [
        ("完整解压便携包", "下载 Windows x64 ZIP，在 Windows 10 或 11 上完整解压，保留 tebb.exe 旁的 runtime 文件夹，再启动 tebb.exe。客户端需要 WebView2 Runtime，便携包已包含 Python 运行环境。"),
        ("连接自己的模型", "在模型设置中填写模型服务地址、模型 ID 和该服务签发的 API Key，保存后选为聊天模型。先发一条普通问题确认可以收到回复。要让伙伴调用工具，请选用支持工具调用的模型。"),
        ("试一次有来源的提问", "打开伙伴聊天，附上一份你愿意交给所选模型处理的说明文档，问：“请列出这份说明中提到的三个步骤。”对照原文看看答案，再追问其中一个步骤。只有确实需要读写目录时，再授权对应的项目。")], "blob/main/docs/GETTING_STARTED.md"),
    ("release-0-4-1", "版本手记", "v0.4.1，让对话更清晰", "新对话先保留为草稿，流式回复保留已收到的片段，飞书连接由你确认。", [
        ("先写草稿，发送时建立会话", "点击新对话后可以先写下想法，普通对话在首次发送时进入列表。暂时切页后可以回到当前窗口继续写；关闭窗口前，仍建议先保存重要内容。"),
        ("看得见回复的真实进度", "这一版修复了流式正文被后续刷新覆盖的问题。已经收到的片段会保留，中断时可以看到实际状态，再决定是否继续。"),
        ("升级后核对外部连接", "先退出旧版并备份本地数据目录，再解压替换程序文件。需要使用飞书日程等能力时，在连接页面核对账号并明确连接。完整改动和校验文件可在正式 Release 中查看。")], "releases/tag/v0.4.1"),
]


def page(title, description, body, prefix, section):
    def nav(label, url, active):
        current = ' aria-current="page"' if active else ''
        return f'<a href="{url}"{current}>{label}</a>'
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)} · tebb.</title><meta name="description" content="{escape(description)}">
<link rel="icon" href="{prefix}assets/pet.svg"><link rel="stylesheet" href="{prefix}assets/site.css"></head><body>
<a class="skip" href="#main">跳到正文</a><header><div class="bar"><a class="brand" href="{prefix}index.html" aria-label="tebb 首页">tebb<span>.</span></a><nav aria-label="主导航">
{nav("产品",prefix+"index.html",section=="product")}{nav("博客",prefix+"blog/index.html",section=="blog")}<a href="{REPO}">GitHub ↗</a></nav></div></header>
<main id="main">{body}</main><footer><a class="brand" href="{prefix}index.html">tebb<span>.</span></a><a href="{REPO}/issues">反馈问题 ↗</a></footer></body></html>"""


def cards(posts, prefix):
    result = []
    for slug, category, title, summary, _, _ in posts:
        if slug == "release-0-4-1":
            visual = f'<img src="{prefix}assets/release.webp" alt="" loading="lazy">'
        elif slug == "getting-started":
            visual = f'<img src="{prefix}assets/notebook.webp" alt="" loading="lazy">'
        else:
            visual = f'<div class="pet-cover"><img src="{prefix}assets/pet.svg" alt=""></div>'
        result.append(f'<a class="story" href="{prefix}blog/{slug}/index.html"><div class="cover">{visual}</div><small>{category}</small><h3>{title}</h3><p>{summary}</p></a>')
    return '<div class="stories">' + ''.join(result) + '</div>'


def write(path, content):
    target = OUT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def build():
    shutil.copytree(ROOT / "assets", OUT / "assets", dirs_exist_ok=True)
    hero = f"""<section class="hero"><div class="wrap"><div class="intro"><p class="eyebrow">tebb. / 个人 AI 工作区</p>
<h1>让桌面伙伴，<br>一起做项目。</h1><p class="lead">把 AI 伙伴、项目文件和笔记放在同一个工作区。从读懂一份材料，到动手修改、核对结果，都能接着上一次的讨论往下做。</p>
<div class="actions"><a class="primary" href="{DOWNLOAD}">↓ 下载 Windows 版</a><a class="secondary" href="{REPO}">查看开源代码 ↗</a></div><p class="meta">v{VERSION} · Windows 10 / 11 x64 · 便携 ZIP</p></div>
<div class="orbit" aria-hidden="true"><i></i><b></b><img src="assets/pet.svg" alt=""></div></div></section>"""
    home = hero + '<section class="section"><h2>在项目里，伙伴能做什么？</h2><div class="features">' + ''.join(
        f'<div><h3>{title}</h3><p>{desc}</p></div>' for title, desc in [
            ("一起读资料", "把文档带进聊天，追问来源，把有用的结论收藏到笔记。"),
            ("一起改文件", "给项目目录授权，让伙伴修改文件、运行验证，再查看差异与输出。"),
            ("一起分工", "和一位伙伴深入讨论，或在群里 @ 不同伙伴，一起完成研究与写作。")]
    ) + '</div></section><section class="section"><div class="heading"><h2>官方博客</h2><a href="blog/index.html">全部文章 →</a></div>' + cards(POSTS, '') + '</section>'
    write("index.html", page("产品介绍", "tebb 本地优先的 AI 伙伴工作区，下载 Windows 版或查看开源代码。", home, "", "product"))
    categories = [("全部文章", ""), ("产品故事", "stories"), ("使用指南", "guides"), ("版本手记", "releases")]
    for category, key in categories:
        prefix = "../../" if key else "../"
        links = ''.join(f'<a href="{prefix}blog/{route+"/" if route else ""}index.html"'+(' aria-current="page"' if route==key else '')+f'>{label}</a>' for label, route in categories)
        body = '<section class="section archive"><p class="eyebrow">tebb. / 编辑部</p><h1>官方博客</h1><nav class="filters" aria-label="文章栏目">'+links+'</nav>'+cards([p for p in POSTS if not key or p[1]==category],prefix)+'</section>'
        write("blog/"+(key+"/" if key else "")+"index.html",page(category+" · 官方博客", "产品故事、使用指南与版本手记。",body,prefix,"blog"))
    for slug, category, title, summary, sections, source in POSTS:
        body = f'<article><a href="../index.html">← 官方博客</a><p class="eyebrow">{category}</p><h1>{title}</h1><p class="lead">{summary}</p>'
        if slug == "release-0-4-1":
            body += '<img class="poster" src="../../assets/release.webp" alt="tebb v0.4.1 官方版本插画">'
        body += ''.join(f'<h2>{heading}</h2><p>{text}</p>' for heading,text in sections)
        body += f'<hr><a href="{REPO}/{source}">查看项目原文 ↗</a></article>'
        write(f"blog/{slug}/index.html",page(title,summary,body,"../../","blog"))


if __name__ == "__main__":
    build()
