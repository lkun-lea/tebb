# Agent 自测能力目录与调用指南

关联 #320。2026-11-20 用户确认：外部开发 Agent 与产品内伙伴共用目录，首批提供发现、隔离模拟运行、进度与证据查询、取消及验收报告；真实模型调用和外部写入保留显式授权边界。

## Agent 如何知道

仓库 `AGENTS.md` 指向本指南及离线目录命令；普通会话和伙伴执行的提示中提供同一入口指引。产品内提供 `self_test_catalog`、`self_test_start`、`self_test_inspect`、`self_test_cancel`。Pi 通过已有 `tebb_tools_search` 搜索“自测”再加载；Python 侧默认 tebb，以及已有目录和编辑/命令工具权限的开发任务伙伴，在非只读分析的 task 阶段获得这些工具。其他角色保持原工具范围；路由和规划阶段不运行评测。

唯一机器合同在 `desk_companion/evaluation/self_test.py`：目录和 Schema 从现行内置用例及覆盖分组生成，CLI 和工具读取同一份。用例存在不表示通过。`catalog.gaps` 保留知识库、笔记、内容学习及研发完整闭环的独立黄金样本缺口；后台验收不替代原生 UI/安装验收。

不将全量内部 RPC 或进程 Token 放入提示词。工具通过已有父后台认证调用，参数没有凭据、任意路径、Shell、provider、模型或 `live_authorized` 字段。修改工具注册或提示后需重新开始相应任务/会话，已有运行保持其原快照。

其他专项接口继续使用现有文档：[调用与业务调试索引](AGENT_DEBUG.md)、[UI 渲染与控件契约](UI_CONTRACT.md)、[原生窗口生命周期](WINDOW_LIFECYCLE.md)、[安装生命周期](INSTALLER.md)。这些入口不因列入文档而变成可在后台模拟执行的能力；Agent 根据当前任务的验收范围选择，并把未执行项留在报告中。

## 外部开发 Agent

在仓库根目录先读取当前目录，无需后台或凭据：

```powershell
uv run --locked python scripts/agent_inspect.py selftest catalog
uv run --locked python scripts/agent_inspect.py selftest describe --payload '{"capability":"smoke"}'
```

`catalog` 返回能力 ID、当前固定用例版本、验证层级、已知缺口及每种操作的 JSON Schema。首次先选择 `smoke`；按目标另选 `chat`、`workflow`、`project`、`calendar`、`memory`、`timeout` 等，不能把某一分组通过推广为全部功能通过。

执行需已准备的本机认证后台、固定 Node/Pi 和 Promptfoo 依赖，依赖安装见 [开发指南](DEVELOPMENT.md)。认证沿用 [既有 CLI](EXECUTION_VISUALIZATION_315_316.md#ai-接口与复现)：宿主将 `DESK_COMPANION_API_URL` 与 `DESK_COMPANION_API_TOKEN` 安全注入进程环境，不写进文档、命令参数、报告或聊天。目录可以离线读取；没有后台或完整 Token 时不能运行，不搜索日志/进程来窃取凭据。

```powershell
# 同一执行请求保留 request_id；返回 batch.id 后一直查询这个编号。
uv run --locked python scripts/agent_inspect.py selftest start --payload '{"capability":"smoke","request_id":"acceptance-smoke-0001"}'
uv run --locked python scripts/agent_inspect.py selftest get --payload '{"ident":"返回的批次编号"}'
uv run --locked python scripts/agent_inspect.py selftest report --payload '{"ident":"返回的批次编号"}'
uv run --locked python scripts/agent_inspect.py selftest diagnose --payload '{"ident":"返回的批次编号"}'
uv run --locked python scripts/agent_inspect.py selftest trace --payload '{"ident":"返回的批次编号","case_id":"pi_tools_discovery","sample":1}'
uv run --locked python scripts/agent_inspect.py selftest cancel --payload '{"ident":"返回的批次编号"}'
```

`debug_call` 另传实际 `call_id`；调用必须属于该批次用例。CLI 标准输出沿用 `{ok,result}` RPC 信封，业务错误不能只看进程退出码或 HTTP 200，必须检查两层 `ok` 和实际报告。任意操作的准确必填参数以当前 `catalog.operations` 为准。

## 产品内工具包

| 工具 | 行为 |
| --- | --- |
| `self_test_catalog` | 读取能力、调用 Schema、步骤和限制，不启动任务。 |
| `self_test_start` | 输入 `capability`、`request_id`，固定 fixture、1 样本/用例、120 秒/用例，复用原评测服务。 |
| `self_test_inspect` | 输入 `operation`、`ident`；按需提供 `case_id`、`sample`、`call_id`，读取原进度、报告、诊断或证据。 |
| `self_test_cancel` | 取消自己创建的原批次；继续查询收尾状态。 |

父后台核对实际活动任务；伙伴调用另核对 run、物理任务和阶段。工具参数不允许模型选择其他调用者。产品内 Agent 只能操作本调用者创建的自测批次，完整 Token 的外部 CLI 可核对本账号空间内的自测 fixture 批次；都不经此入口读取普通业务批次或真实模型批次。

评测 Worker 内禁止启动或干预嵌套自测。关闭聊天不等于取消评测；失败、宿主重启、取消与资源清理沿用 EvaluationCenter / TaskManager，查询未明结果时保留原编号，不自动重跑外部动作。

## 验收报告与闭环

报告返回批次状态、固定清单哈希、代码版本、原始结果、指标、缺失样本和证据完整性；保存 JSON 即可形成可审查产物。`passed:true` 必须同时满足：批次 completed、计划样本全部有唯一结果、每项原合同通过、无临时进展行且调用/模型观测完整。失败、取消、缺证据和未启动都不能当通过。

处理顺序：发现能力 → 查看合同与缺口 → 启动隔离样本 → 查询原状态 → 查看失败任务/调用/产物 → 修复 → 用新的请求编号建立独立批次 → 比较原始证据。用例与原分数不回改；真实模型、原生 UI、安装和真实外部服务另行验收。

接口文档解释流程和边界，工具 Schema 约束实际调用，目录负责自动发现。官方 Skill 由独立 `tebb-skills` 仓库固定发布；本批通过受版本管理的产品工具和仓库入口交付，不往被忽略的本地 `skills/` 放临时文件冒充正式 Skill。

## 隔离验证

```powershell
uv run --locked python -m unittest tests.test_self_test tests.test_self_test_http tests.test_execution_http tests.test_evaluation_center -v
```

测试采用临时 profile、已有假模型与真实 loopback 认证服务；不使用真实账号数据，不调用付费模型，不向真实飞书目标写入。Windows/Tauri 界面未因这些测试而自动视为通过。
