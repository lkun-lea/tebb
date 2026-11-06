"""视频工作区复用受监督任务，保留既有桌面与飞书视频记录。"""
import uuid

from desk_companion.content.video.sources import normalize_url


def task_ids(manager):
    with manager.db() as db:
        return [row[0] for row in db.execute(
            "SELECT t.id FROM tasks t WHERE json_extract(t.source, '$.workflow')='video' "
            "OR t.id IN (SELECT e.task FROM events e WHERE e.kind='tool_start' "
            "AND json_extract(e.data, '$.tool') IN ('read_video','read_video_transcript','save_video_summary')) "
            "ORDER BY t.created DESC LIMIT 100")]


def snapshot(host):
    return {"ok": True, "items": [host.tasks.get(task_id, False) for task_id in task_ids(host.tasks)]}


def start(host, url):
    _, canonical = normalize_url(url)
    session = "video-" + uuid.uuid4().hex
    text = ("请读取这个视频并用中文生成简洁易懂的学习笔记：" + canonical +
            "\n先调用 read_video 并读完可用字幕分页，围绕视频的主题和学习目标组织内容。"
            "概念科普优先讲清术语定义、解决的问题和相互关系，只拓展必要的关联名词，"
            "用一个短例子串起来；不要长篇复述作者论证或展开无关评析。保留少量关键时间点出处。"
            "作者观点、补充知识和你的分析简洁区分；当前技术能力或关键争议可联网核实。"
            "未取得字幕时只说明实际取得的元数据和局限。你只需读取并输出笔记；"
            "应用会依据用户设置在任务成功后自动归档，生成回答即可；其它修改不属于本次任务。")
    task_id = host.tasks.submit(text, session, "video", source={"workflow": "video", "video_url": canonical},
                                workflow="video_note", video_url=canonical)
    host._focused_task = task_id
    return {"ok": True, "task_id": task_id}


def continue_task(host, task_id, text):
    if not isinstance(text, str) or not text.strip():
        raise ValueError("请填写有效追问。")
    # 新工作区和既有视频任务均可追问，普通聊天不能被伪装成视频记录。
    if task_id not in task_ids(host.tasks):
        raise ValueError("请选择已有的视频任务。")
    parent = host.tasks.get(task_id, False)
    original = parent["source"].get("video_url")
    if original:
        # 排队时取消或模型调用前失败，原链接还没有写入聊天历史。
        text = "当前会话原视频：" + original + "\n\n用户追问：" + text
    found = host.tasks.resume(task_id, text, send_back=False)
    host.tasks.update_source(found, workflow="video")
    host._focused_task = found
    return {"ok": True, "task_id": found}
