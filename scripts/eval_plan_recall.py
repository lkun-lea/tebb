"""离线旧方案召回对照。仅使用合成材料和本机已有的中文向量模型。"""
import json
import math
import sqlite3
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from desk_companion.knowledge.index import _embed

# 每项最后一条均为较晚的原文，回看时按事项展开，而非由相似度选择决定。
PLANS = {
    "mobile": ["七月移动端待答接续方案", "配对电脑从公网回传状态。", "决定改为服务器中转。"],
    "lan": ["七月移动端离线阅读方案", "手机暂存文档。", "决定仅缓存摘要。"],
    "travel": ["出差报销方案", "汇总票据。", "只报销火车票。"],
    "search": ["本地资料检索", "查阅授权目录。", "决定保留原文件。"],
    "voice": ["语音录入", "识别说话内容。", "松手允许编辑。"],
    "calendar": ["会议提醒", "读取日程。", "到期通知。"],
    "office": ["办公室门禁", "申请设备。", "仅限前台。"],
    "food": ["食堂采购", "安排午饭。", "取消晚餐。"],
}
CASES = [
    ("原词", "移动端待答接续方案", "mobile"),
    ("口语", "手机怎么接着处理电脑上的工作", "mobile"),
    ("模糊时间", "夏天讨论的手机离线读文件", "lan"),
    ("同名线索", "七月移动端离线阅读方案", "lan"),
    ("无答案", "深海珊瑚的繁殖周期", None),
]


def evaluate():
    import torch
    torch.set_num_threads(min(4, torch.get_num_threads()))
    # 此索引只驻留在本次评测进程。用户私有数据不作为样本。
    sources = dict(PLANS)
    permitted = set(sources)
    ids = list(sources)
    bodies = ["\n".join(sources[key]) for key in ids]
    vectors = dict(zip(ids, _embed(bodies)))
    gold = {"mobile": "决定改为服务器中转。", "lan": "决定仅缓存摘要。"}
    db = sqlite3.connect(":memory:")
    try:
        db.execute("create virtual table plans using fts5(id unindexed, body, tokenize='trigram')")
        db.executemany("insert into plans values(?,?)", zip(ids, bodies))

        def search(query, semantic):
            phrase = '"' + query.replace('"', '""') + '"'
            exact = {r[0] for r in db.execute("select id from plans where plans match ?", (phrase,))}
            # 始终按当前来源及授权过滤；即使向量仍在内存也不能返回已撤销材料。
            valid = permitted.intersection(sources)
            vector = _embed([query])[0] if semantic else []
            scores = []
            for key in valid:
                score = sum(a * b for a, b in zip(vector, vectors[key])) if semantic else 0
                if key in exact or semantic and score >= 0.55:
                    scores.append((key in exact, score, key))
            return [key for _, _, key in sorted(scores, reverse=True)[:5]]

        result = {}
        for semantic in (False, True):
            samples = []
            elapsed = []
            for group, query, expected in CASES:
                start = time.perf_counter()
                ranked = search(query, semantic)
                elapsed.append((time.perf_counter() - start) * 1000)
                evidence = sources[ranked[0]] if ranked else []
                samples.append(dict(group=group, candidates=ranked, top5=expected in ranked if expected else None,
                                    wrong_first=bool(ranked and ranked[0] != expected),
                                    latest=bool(expected and ranked and ranked[0] == expected and gold[expected] in evidence),
                                    evidence_chars=sum(map(len, evidence))))
            result["hybrid" if semantic else "fts5"] = dict(samples=samples,
                top5=sum(bool(s["top5"]) for s in samples), answerable=4, wrong_first=sum(s["wrong_first"] for s in samples),
                latest=sum(s["latest"] for s in samples), p95_ms=round(sorted(elapsed)[math.ceil(.95*len(elapsed))-1], 3),
                mean_evidence_chars=statistics.mean(s["evidence_chars"] for s in samples))
        permitted.remove("mobile")
        del sources["lan"]
        for semantic in (False, True):
            assert "mobile" not in search("移动端待答接续方案", semantic)
            assert "lan" not in search("七月移动端离线阅读方案", semantic)
        result["deleted_and_revoked_filtered"] = True
    finally:
        db.close()
    return result


if __name__ == "__main__":
    print(json.dumps(evaluate(), ensure_ascii=False, indent=2))

