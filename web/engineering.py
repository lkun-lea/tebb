"""官网技术文章。源码链接固定到采集桌面演示时的版本。"""
REV = "ae4ba24b24afbed4ced4af3ebd61ecc6fb325a46"
MOBILE = "android/app/src/main/java/dev/tebb/mobile/"
POSTS = [
    ("android-super-agent", "工程笔记", "Android Super-Agent 怎样把一句回复交回电脑？",
     "从「评审留 45 分钟」追踪一次跨设备待答，看看手机、Windows 和 ECS 各自保存什么。", [
        ("同样一句话，可以去三个地方", "在手机主聊输入「45 分钟」，先要知道它在回答谁。引用了电脑的待答卡，发送目标就是那个问题；没有引用时，普通消息才按本地或云端选择走。手机可以处理离线快捷问题；配置了可达的模型服务时，也能从手机直接请求模型。选择云端的普通消息则提交给 ECS。"),
        ("为什么卡片上需要三个编号", "Windows 在协作运行进入 needs_input 时投影出问题。conversation 找到原会话，run 找到正在等答复的那次执行，version 标识这一次提问。同一会话可能有多次运行，一次运行也可能再次追问。仅凭会话标题或相同问题文字，无法安全地恢复原任务。"),
        ("中转只保存短时密文", "同账号设备完成配对，并由电脑明确共享相关会话后，手机能取得授权的问题快照。走公网中转时，ECS 暂存按设备与方向区分的密文，约 45 秒后清理。Windows 收到回复后核对目标，将文字交给原运行，再产生接收回执。局域网配对另有固定证书指纹的直连路径。"),
        ("如果电脑已经答过了", "手机可能仍显示缓存卡片。这时要重新确认问题版本；未获确认、断线或授权失效时保留草稿。相同版本和正文的重试可复用回执。仓库的隔离测试断开写入端，再读同一份快照：问题仍在；Windows 处理后再读，卡片消失。#347 的正式手机今日入口、原会话单次入账和两端同状态画面仍待完整实机验收。")
     ], "blob/main/docs/ANDROID_TASK_REPLIES.md"),
    ("cloud-turn-recovery", "工程笔记", "消息送达后断网，重连怎样找回同一次回答？",
     "拆开免费云聊的一次 POST 和一条 SSE 连接：提交、执行与观察各有自己的生命周期。", [
        ("先分清两次失败", "假设手机发出「概括这份提纲」，服务端已接收，手机却没收到 HTTP 回包。此时重新生成请求号可能创建另一次执行。如果拿到了回包，只是在等待正文时断网，真正需要恢复的是对已提交任务的观察。"),
        ("提交键由账号和请求号共同组成", "Android 向云端提交 conversation、request_id 和正文。服务端验证登录主体，并以 cloud:{subject}:{request_id} 作为 submission_key 交给任务管理器。响应里的 run_id 标识执行记录。request_id 用于重试提交，run_id 用于在多个回答之间找到目标；重试时必须保留原来的请求号。"),
        ("SSE 重连后先读数据库", "GET /cloud/v1/events 每次连接都会重新鉴权。第一轮读取该账号、该会话的持久记录，先发 history 标记，再发 turn。随后每秒检查最近 20 条，只有记录改变才发更新。服务端每十轮发心跳，一个连接最多检查 60 轮。这里没有逐 token 的 Last-Event-ID 游标。"),
        ("看到哪个状态才交付答案", "手机跳过其他 run_id。queued 和 running 更新界面进度，succeeded 才取 answer；failed、cancelled、interrupted 或 timed_out 走失败分支。连接提前结束时提示可重试。接口回归用相同请求号重复提交，再断开并重新订阅事件流，核对取回的运行记录。测试中的身份及生成过程使用替身。能恢复的是任务库保存的状态，断开期间的每个中间画面不会被逐一重播。")
     ], "blob/main/desk_companion/local_api/cloud_chat.py"),
]
SOURCES = {
    "android-super-agent": [("手机发送路由", MOBILE+"ChatViewModel.kt"), ("电脑核对目标和版本", "desk_companion/local_api/paired_workspace.py"), ("中转过期处理", "desk_companion/local_api/device_relay.py"), ("隔离中转回归", "tests/test_mobile_status_relay_demo.py")],
    "cloud-turn-recovery": [("Android 提交与读流", MOBILE+"CloudChatClient.kt"), ("服务端提交与 SSE", "desk_companion/local_api/cloud_chat.py"), ("任务管理器", "desk_companion/tasks/manager.py"), ("重复请求与重连回归", "tests/test_http_api.py")],
}
STEPS = {
    "android-super-agent": [("Windows → 手机", "投影已授权的待答", "conversation · run · version"), ("手机 → ECS → Windows", "提交选项或文字", "加密回复 · 原问题版本"), ("Windows → 手机", "原任务接收后回执", "accepted · run · version")],
    "cloud-turn-recovery": [("手机 → 提交接口", "POST 正文与请求号", "request_id"), ("任务库 → 手机", "返回执行编号", "run_id"), ("事件接口 → 手机", "重放快照，再推送变化", "history → turn")],
}
