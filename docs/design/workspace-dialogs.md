# tebb 弹窗设计索引

按可见交互目的归并创建与编辑、动态标题及同一确认框的不同触发路径。稿号对应已评审的 Figma 状态。源码入口用于定位实现。

确认操作绑定当前账号与原对象；取消、Escape 和 Android 返回均不提交写入。危险操作须在提交后等待业务回执。

|稿号|端 / 业务|弹层|源码入口|
|---|---|---|---|
|1.01|聊天与项目|创建伙伴 / 伙伴设置|client/src/client/chat-prototype.tsx|
|1.02|聊天与项目|新建 / 调整协作群|client/src/client/chat-prototype.tsx|
|1.03|聊天与项目|新建项目 / 项目设置|client/src/client/chat-prototype.tsx|
|1.04|聊天与项目|整理已有对话|client/src/client/chat-prototype.tsx|
|1.05|聊天与项目|删除项目？|client/src/client/chat-prototype.tsx|
|1.06|聊天与项目|移动对话|client/src/client/chat-prototype.tsx|
|1.07|聊天与项目|删除这段对话？|client/src/client/chat-prototype.tsx|
|1.08|聊天与项目|重命名群聊|client/src/client/chat-prototype.tsx|
|1.09|聊天与项目|放弃新对话草稿？|client/src/client/chat-prototype.tsx|
|1.10|聊天与项目|成果文档|client/src/client/chat-prototype.tsx|
|1.11|聊天与项目|重置原型演示？|client/src/client/chat-prototype.tsx|
|1.12|聊天与项目|会话操作|client/src/client/chat-prototype.tsx|
|1.13|聊天与项目|项目管理|client/src/client/chat-sidebar.tsx|
|1.14|聊天与项目|本轮技能、工具与资料|client/src/client/slash-menu.tsx|
|1.15|聊天与项目|选择仓库|client/src/client/slash-menu.tsx|
|1.16|聊天与项目|提及伙伴 / 选择技能|client/src/client/composer-popover.tsx|
|1.17|聊天与项目|参数与上下文|client/src/client/context-debug.tsx|
|1.18|聊天与项目|本地文件与附件|client/src/client/local-sources.tsx|
|1.19|聊天与项目|桌宠聊天浮窗|client/src/client/pet-chat.tsx|
|1.20|聊天与项目|桌宠聊天菜单|client/src/client/pet-chat.tsx|
|1.21|聊天与项目|桌宠快捷菜单|client/index.html|
|1.22|聊天与项目|桌宠提醒气泡|client/src/main.ts|
|2.01|事项与日程|事项详情 / 编辑事项|client/src/client/work-board.tsx|
|2.02|事项与日程|事项有未保存修改|client/src/client/work-board.tsx|
|2.03|事项与日程|日程安排|client/src/client/schedule.tsx|
|2.04|事项与日程|未保存的安排|client/src/client/schedule.tsx|
|2.05|事项与日程|新建 / 编辑日程|client/src/client/calendar-event-editor.tsx|
|2.06|事项与日程|日程时间详情|client/src/client/schedule-week.tsx|
|2.07|事项与日程|日程时间尚未保存|client/src/client/schedule-week.tsx|
|2.08|事项与日程|整体同步到飞书|client/src/client/schedule-week.tsx|
|2.09|事项与日程|同步与核对|client/src/client/calendar-sync-status.tsx|
|2.10|事项与日程|确认未创建有效日程？|client/src/client/schedule-week.tsx|
|2.11|事项与日程|登记当前本地状态？|client/src/client/schedule-week.tsx|
|2.12|事项与日程|保留记录并结束等待？|client/src/client/schedule-week.tsx|
|2.13|事项与日程|删除这场日程？|client/src/client/schedule-week.tsx|
|2.14|事项与日程|删除飞书待办？|client/src/client/task-completion.tsx|
|2.15|事项与日程|飞书待办|client/src/client/calendar-workspace.tsx|
|2.16|事项与日程|本周复盘|client/src/client/calendar-workspace.tsx|
|2.17|事项与日程|选择日期和时间|client/src/client/datetime-field.tsx|
|2.18|事项与日程|日历更多操作|client/src/client/schedule-week.tsx|
|2.19|事项与日程|当日更多日程|client/src/client/schedule-week.tsx|
|2.20|事项与日程|日程详情更多操作|client/src/client/schedule-week.tsx|
|3.01|笔记与工具|添加笔记来源|client/src/client/notebook-sources.tsx|
|3.02|笔记与工具|阅读笔记|client/src/client/note.tsx|
|3.03|笔记与工具|笔记更多操作|client/src/client/note.tsx|
|3.04|笔记与工具|删除笔记？|client/src/client/note.tsx|
|3.05|笔记与工具|删除关联文件？|client/src/client/note.tsx|
|3.06|笔记与工具|工具详情 / 编辑展示信息|client/src/client/tool-library.tsx|
|3.07|笔记与工具|让 tebb 创建 / 调整工具|client/src/client/tool-library.tsx|
|3.08|笔记与工具|删除自定义能力？|client/src/client/tool-library.tsx|
|3.09|笔记与工具|工具调用记录|client/src/client/tool-monitor.tsx|
|3.10|笔记与工具|放大图表|client/src/client/report-charts.tsx|
|3.11|笔记与工具|放弃原创建请求？|client/src/client/project-runtime.tsx|
|3.12|笔记与工具|工作区文件|client/src/client/terminal.tsx|
|4.01|运行与设置|邮箱登录|client/src/client/accounts.tsx|
|4.02|运行与设置|手机申请连接|client/src/client/mobile-pairing.tsx|
|4.03|运行与设置|版本介绍|client/src/client/release.tsx|
|4.04|运行与设置|裁剪封面|client/src/client/settings.tsx|
|4.05|运行与设置|执行设置|client/src/client/agent-monitor.tsx|
|4.06|运行与设置|任务详情|client/src/client/agent-monitor.tsx|
|4.07|运行与设置|模型调用调试|client/src/client/agent-debug.tsx|
|4.08|运行与设置|调用详情|client/src/client/agent-debug.tsx|
|4.09|运行与设置|调用检查台|client/src/client/memory-inspector.tsx|
|4.10|运行与设置|清理范围预览|client/src/client/memory-inspector.tsx|
|4.11|运行与设置|选择固定用例|client/src/client/evaluation-center.tsx|
|4.12|运行与设置|评测执行详情|client/src/client/evaluation-center.tsx|
|4.13|运行与设置|覆盖范围详情|client/src/client/evaluation-evidence.tsx|
|4.14|运行与设置|运行依赖图|client/src/client/execution-trace.tsx|
|4.15|运行与设置|工作流专注画布|client/src/client/workflow-surface.tsx|
|4.16|运行与设置|放弃工作流草稿？|client/src/client/workflow-editor.tsx|
|4.17|运行与设置|运行详情|client/src/client/workspace-runs.tsx|
|4.18|运行与设置|删除定时任务？|desk_companion/ui/board.html|
|4.19|运行与设置|平台登录窗口|client/src-tauri/src/video_login.rs|
|4.20|运行与设置|操作反馈|client/src/client/toast.tsx|
|4.21|运行与设置|模型容量与分词器|client/src/client/context-debug.tsx|
|5.01|Android|聊天更多操作|android/app/src/main/java/dev/tebb/mobile/ChatScreen.kt|
|5.02|Android|清空对话记录？|android/app/src/main/java/dev/tebb/mobile/ChatScreen.kt|
|5.03|Android|执行位置|android/app/src/main/java/dev/tebb/mobile/ChatScreen.kt|
|5.04|Android|正在连接电脑|android/app/src/main/java/dev/tebb/mobile/ChatScreen.kt|
|5.05|Android|Windows 原任务|android/app/src/main/java/dev/tebb/mobile/ContextSuggestion.kt|
|5.06|Android|手记来源|android/app/src/main/java/dev/tebb/mobile/JournalScreen.kt|
|5.07|Android|已共享方案|android/app/src/main/java/dev/tebb/mobile/SharedPlanCard.kt|
|5.08|Android|共享方案详情|android/app/src/main/java/dev/tebb/mobile/SharedPlanCard.kt|
|5.09|Android|选择邮箱域名|android/app/src/main/java/dev/tebb/mobile/LoginScreen.kt|
|5.10|Android|桌宠提示气泡|android/app/src/main/java/dev/tebb/mobile/ChatPet.kt|
