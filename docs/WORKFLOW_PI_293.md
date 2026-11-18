# 工作流 AI 节点迁移到 Pi

2026-11-18，关联 [#293](https://github.com/lkun-lea/tebb/issues/293)，从 main `867f90f32e1170ddcefb7a61d2670bcf49fb3291` 继续批次2。该基线的 CI `44275513532` 和 main CI `44278192581` 均已通过 Frontend、Python / Atlas、Rust。

## 职责与行为

只有通用 `ai` 节点切换到官方 Pi AI。现有 `WorkflowService`、解释器、TaskManager 和 SQLite 继续持有版本、计划绑定、运行、确认、节点回执和续跑状态；没有新增 Agent 循环。资讯、视频等专用节点沿用原服务，列入剩余单次入口批次。

`PiInference` 通过 `ExecutionLLM` 的传输接口复用上下文准入、来源清单、根预算预留、实际用量结算及取消检查。暂时保留 Atlas 的契约类型、基类初始化和既有整理原语；借用的路由对象不创建 OpenAI Python 客户端，模型网络请求与响应拼接在 Node/Pi 内执行。普通聊天、协作等原调用方继续使用原传输。

Pi 的 `onPayload` 在发送前回到 Python，核对实际模型、完整消息、容量/输出绑定版本及计数。根预算进入收尾时附加的系统消息也原样保留。已验证的 `max_tokens` 或 `max_completion_tokens` 由产品映射，未验证时不填 SDK 默认上限；SDK 合成的窗口、输出容量和零价格不作为产品能力或费用依据。

实际 provider usage 原样用于预算和用量中心，缺失时保持 unknown，旧用量文件不补写零。`length`、缺少完成原因、工具调用、空正文均不能成为有效节点产物。取消/超时保留已接收片段与可确认用量，停止所属 Node，不重试模型。

调用记录沿用现有检查台和 task/call 关联。请求保存实际通过准入的 payload；成功响应保存 Pi 回调解析的 provider JSON 帧重新编码的 SSE，元数据 `response_format` 明确这一点，不能据此声称保存了逐字节网络流。HTTP 错误保存返回体与状态，公共错误只给安全说明。暂停详细记录后，用量中心仍保存计数、状态和实际网络尝试。

直连、系统和自定义代理均使用现有模型网络配置。Python 使用与 HTTPX 相同的标准库代理发现结果传入私有进程；Node 按请求协议选代理，保留 NO_PROXY、代理认证和 ALL_PROXY。`SSL_CERT_FILE`/`SSL_CERT_DIR` 映射为显式信任根，默认沿用 certifi，保持证书校验。SOCKS5H 映射到 undici 的 SOCKS5 远端域名解析；仅 HTTPS 代理服务器启用代理侧 TLS。

## 可复用验证入口

源码运行的前置条件为 Node **24.22.3** 与锁定的 Pi **1.5.2**、undici **8.12.4**。没有固定运行时或依赖不匹配时明确失败，不能静默退回 Atlas。CI 安装相同版本，进程用例实际执行 Node。

```powershell
$piNodeRoot = 'E:/temporary/node-v24.22.3-win-x64'
$env:TEBB_PI_NODE = "$piNodeRoot/node.exe"
Push-Location desk_companion/pi_runtime
& "$piNodeRoot/node.exe" "$piNodeRoot/node_modules/npm/bin/npm-cli.js" ci --ignore-scripts --no-audit --no-fund
Pop-Location
uv run --locked python -m unittest tests.test_pi_inference tests.test_pi_network tests.test_pi_bridge tests.test_workflows tests.test_workflow_scenarios tests.test_workflow_authoring tests.test_execution_context tests.test_budget_transport tests.test_task_budgets tests.test_usage_center tests.test_agent_debug tests.test_model_network -v
uv run --locked python scripts/verify_workflow.py --output E:/temporary/workflow-pi-new
```

脚本输出目录必须全新。脚本通过认证 API 创建临时模型、固定输入工作流及禁用的计划，实际启动 Python worker 和 Node/Pi；断言精确正文、条件分支、原运行去重、实际调用 payload、调用记录和用量编号，不向真实模型或飞书发送请求。

## 验收表

| 验收 | 证据 |
| --- | --- |
| 认证 API→真实任务进程→Node/Pi→节点回执 | `scripts/verify_workflow.py`，精确正文“发布包对话正常。”，一次模型请求；重复提交使用原运行和任务 |
| 原消息、采样、完成原因、输出绑定、预算、用量及检查台 | `test_pi_inference`；13/7 token 按 provider 原值入账，未知不计为零，429 只发送一次 |
| 未完成、工具返回、空正文拒绝 | `test_pi_inference`；片段留存，不产生完整节点正文 |
| 取消、超时及进程清理 | `test_pi_inference`、`test_pi_bridge`；取消片段保留，TaskManager 回收 Python worker 与 Node 后代 |
| 手动全量、条件分支 | 认证脚本及 `test_workflows`；选中节点 confirmed，另一分支 skipped |
| 定时绑定旧版本与原输入 | `test_pi_inference.test_scheduled_saved_version_calls_pi_with_original_input`；更新定义后仍通过 Pi 处理原输入 |
| 逐步执行、明确写入确认、丢回执核对与续跑 | `test_pi_inference.test_step_confirmed_ai_and_unknown_write_resume_without_replaying`；确认前零写入，未知时禁止 advance，按原 receipt_key 核对后完成；AI 请求一次、模拟目标写一次 |
| 原状态所有权、并发及版本契约 | `test_workflows`、`test_workflow_authoring`、`test_workflow_scenarios` |
| 直连隔离环境代理、环境代理、自定义 HTTP 认证代理 | `test_pi_network`，代理实际收到请求及 Basic 认证 |
| 认证 SOCKS5/SOCKS5H 与远端 DNS | `test_pi_network`；本地无法解析的 provider.invalid 由模拟代理接收并转发 |
| TLS 信任根 | `test_pi_network`；未信任证书拒绝，指定 CA 文件/目录接受，HTTPS 请求不误用仅 HTTP 的代理 |

脱敏证据见 [本批记录](evals/workflow-pi-20261118.json)。开发验证中发现的状态录制、SOCKS 代理 TLS 映射和测试替身问题均保留原失败日志；修正后执行整组回归。最终全量结果以本批实际提交的 GitHub CI 为准，三项必要 job 全通过后再合入 main。

本批没有真实付费模型、真实外部写入、原生 Tauri 点击或新安装包验证。真实 provider/代理的完整组合、流中空闲超时矩阵、跨账号及干净 Windows 的打包 Node/Pi 生命周期仍按后续批次验收。未发布版本或删除 Atlas。无全局 Node/Pi 的安装包交付属于批次6。
