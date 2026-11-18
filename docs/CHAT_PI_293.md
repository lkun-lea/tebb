# 普通聊天迁移到 Pi Agent Core

2026-11-18，关联 [#293](https://github.com/lkun-lea/tebb/issues/293)。批次3基线为 main `737afbfca856058e24ddcd599d63cf544bf9fe4d`，其 main CI [44285277666](https://github.com/lkun-lea/tebb/actions/runs/44285277666) 已全部通过。

## 调用链与职责

普通聊天经原认证 HTTP/SSE、桌面兼容入口或飞书入站服务进入同一个 TaskManager worker，再由 `ConversationService` 组装当前会话、所选记忆、技能、文档和附件。`assistant.build_agent` 默认创建 `PiChatAgent` 适配器；Node 中官方 Pi Agent Core 持有当次模型/工具循环，官方 Pi AI 负责模型请求和响应拼接。

Python 继续持有会话及记忆、工具注册与执行权限、根预算、任务状态和回执。`PiChatAgent` 映射现有消息、插件及 journal 契约，不创建 Python 模型/工具循环，也不以 Atlas Agent 或 Runtime 回退。缺少固定 Node/Pi 时明确失败。

SDK 每次准备模型请求时通过私有进程桥回到 `ExecutionLLM.admitted_call`，沿用容量检查、保护材料、来源清单、输出绑定和根预算预留。允许发送的 payload 回到 SDK；每次模型响应结束后，SDK 的异步监听器等待 Python 用原始 usage 结算，然后才进入工具执行或下一次请求。`length`、不完整流、取消和错误不能执行其中的工具。

工具只来自当前注册表及本轮明确绑定的 MCP。Pi 做 schema 校验，Python 再核对实际工具、参数及本轮实际发送的授权清单，经原 worker 的预算、已尝试写入指纹、未决操作阻断及业务服务执行；调用未知工具或预算收尾时已移除的工具不进入后端。worker 继续负责一次工具预算准入，直接调用适配器时由适配器补充同一检查，避免重复计数。工具执行保持顺序，不移植 Atlas Runtime 的通用重试循环；业务服务已有的恢复行为保留，未决写入不重放。原始 SDK tool-call ID 保留在模型历史，产品步骤编号加入模型轮次以区分跨轮复用的 ID。

`ConversationService` 继续拥有事实引用范围、用户原话绑定、实际历史写入顺序和临时 MCP 清理。Pi 的正文/思考转入原回调，模型与工具事件进入原任务时间线；思考继续按现有规则与持久监控事件区分。SDK 内的多轮推理块留在当次工具循环，GLM 的 `reasoning_content`、`thinking.clear_thinking=false`、`tool_stream=true` 已用模拟服务检查。

容量未知不造窗口，输出参数只由原验证绑定决定。缺少任一轮 usage 时该轮用量和整次汇总保留 unknown，不向旧用量文件补零。详细记录暂停后元数据仍进入原用量中心。实际 provider payload/解析帧、调用编号及来源记录沿用上一批 [模型边界约定](WORKFLOW_PI_293.md)。Pi AI 单次推理与普通聊天共用模型、采样和网络映射。

暂时复用 Atlas 的 Memory、Toolkit、插件/journal 和限制契约；普通聊天的 `llm.chat` 还供知识问答、压缩等既有单次入口使用，这些调用仍走原传输，属于后续批次。协作和开发团队尚未切换。生产普通聊天已不再调用 Atlas Agent/Runtime 的循环。

## 可复用验收

源码需要 Node **24.22.3**、Pi 三个包 **1.5.2** 和 undici **8.12.4**。固定依赖与下载摘要见 [兼容基线](PI_COMPATIBILITY_293.md)。未发布新安装包。

```powershell
$piNodeRoot = 'E:/tools/node-v24.22.3-win-x64'
$env:TEBB_PI_NODE = "$piNodeRoot/node.exe"
Push-Location desk_companion/pi_runtime
& "$piNodeRoot/node.exe" "$piNodeRoot/node_modules/npm/bin/npm-cli.js" ci --ignore-scripts --no-audit --no-fund
Pop-Location
uv run --locked python -m unittest tests.test_pi_chat tests.test_pi_bridge tests.test_pi_inference tests.test_pi_network -v
uv run --locked python scripts/verify_pi_chat.py --output E:/temporary/pi-chat-new
```

输出目录必须全新；脚本沿用 `verify_workflow.py` 的真实后台启动/关闭与隔离目录，不访问原账号资料。模拟模型要求调用现有 `remember_fact`，后端实际在隔离目录写入“我喜欢四十”；同编号提交去重，第二轮核对保存的历史。验证两轮精确回复、四条历史、一次本地记忆写入、三次实际模型请求及三条 Pi 调用记录。不连接真实付费模型或发送飞书消息。

| 验收 | 证据 |
| --- | --- |
| 认证入口、真实 worker/Node、历史与用户明确记忆 | `scripts/verify_pi_chat.py`，两轮对话、实际事实状态 active，历史循环数 2 / 1 |
| 模型—工具—模型与实际第二次请求 | `test_pi_chat`，加法参数 17/23，工具一次，正文 40，两次模型用量合计输入26/输出14 |
| low/high/max、temperature/top_p、完整历史 | `test_pi_chat`，检查实际发送对象；未知输出绑定没有默认上限 |
| 已验证输出绑定与根预算 | `test_pi_chat`、`test_budget_transport`；实际 max_tokens=4096，根预算拒绝时无请求 |
| GLM 非空思考的工具往返 | `test_pi_chat.test_glm_reasoning_survives_the_tool_round_trip` |
| SDK 拒绝无效参数、截断不执行工具、循环上限 | `test_pi_chat`；无效参数后端次数零，length 中的工具不执行，达到轮次上限不发下一次请求 |
| 真实 worker 未决写入不重放 | `test_pi_chat.test_actual_worker_blocks_second_unknown_write_before_backend`；保留 pi-write-original，模拟目标写入一次，后续写入在原业务检查处阻断 |
| 飞书渠道后台调用 | `test_pi_chat.test_feishu_channel_runs_the_same_real_pi_worker`；渠道为 feishu，真实 worker/Pi 执行两次模型及一次本地工具，无真实回复发送 |
| 取消、部分输出、回收 Node 和迟到终态保护 | `test_pi_chat`；取消已收到40的任务，保留片段、未执行工具、Node 退出，任务保持 cancelled |
| 代理、CA、未知用量、原工作流 | `test_pi_network`、`test_pi_inference`、`test_workflows` 及完整 CI |

已有业务工具单元测试的 FakeLLM 通过明确的测试替身继续验证工具绑定及旧服务语义；该替身只在 `tests/agent_fixture.py` 内使用 Atlas 脚本循环，不能算作 Pi 验收。新增 Pi 测试和认证脚本实际启动固定 Node/官方 SDK，CI 同样安装固定依赖并执行。

脱敏记录见 [本批证据](evals/chat-pi-20261118.json)。开发时的导入/插件契约、测试启动方式及验证脚本方法/终态错误均保留原失败，修正后整组复验；没有将重跑覆盖成无失败首轮。最终完整 CI 按候选提交检查，三项必要 job 通过后才更新 main。

本批覆盖桌面普通聊天 API、旧桌面普通入口和飞书渠道的真实任务后端。路由盘点确认新版 `pet-chat.tsx` 使用 `collaboration_action`，与伙伴私聊/群聊一起留在批次4；不能以本批普通聊天测试声称新版桌宠已经接入 Pi。原生窗口点击、真实飞书卡片发送、真实提供商及代理组合、安装包升级和干净 Windows 的 Node 生命周期未在本批验收。真实模型兼容基线仍见首批报告；不能用本批模拟结果替代实机与真实模型结论。
