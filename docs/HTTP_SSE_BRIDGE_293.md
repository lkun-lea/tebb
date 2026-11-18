# HTTP/SSE 与 Python↔Node 进程桥

2026-11-18，关联 [#293](https://github.com/lkun-lea/tebb/issues/293)，基线 `0a215f11c3f1ae095eaab4299cc8815e54a8a516`。上一批 CI [44263216315](https://github.com/lkun-lea/tebb/actions/runs/44263216315) 的前端、Python/Atlas、Rust 全部通过。本批实现兼容表的批次1，后续工作流、普通对话、协作等模型调用方继续按原批次切换。

## 职责与实际入口

Tauri 继续启动原账号启动器，冻结账号数据目录并生成本机进程 Token。Python 主服务改用 FastAPI/Uvicorn，绑定 `127.0.0.1` 与原随机端口。`/health`、认证 `/shutdown` 和受限图片/素材地址保留，Rust 的启动与退出协议可继续使用。

| 接口 | 用途与契约 |
| --- | --- |
| `POST /rpc` | Bearer Token 认证，正文 `{method,args}`。继续调用原 `_dispatch` 白名单和业务 Bridge；原锁、权限、回执及错误语义由业务服务保留。普通 RPC 不自动重试写入。 |
| `POST /v1/runs` | 提交 `request_id,kind,text,session_id,sampling,chips,model_id,knowledge,doc_ids`。kind 为 chat 或 notebook，额外字段拒绝；sampling 仍走原校验。返回原 TaskManager 的 `run_id`。 |
| `GET /v1/runs/{run_id}` | 从同一 SQLite 读事务读取任务、最多512个尾部事件及 cursor 水位，不返回含模型凭据的内部 request。任务预算和更多诊断继续通过现有 RPC 查询。 |
| `GET /v1/runs/{run_id}/events?after=N` | SSE 正文为 `{type,data}`，持久事件以原 seq 作为 `id`。Last-Event-ID 可覆盖 after。有效游标补读；游标超前或早于512条窗口则发 snapshot，客户端用快照替换正文并从其水位继续。settled 返回真实任务终态。 |
| `POST /v1/runs/{run_id}/cancel` | 调用原 TaskManager.cancel，保留 cancelling、部分正文及原进程树清理。关闭订阅或页面不触发取消。 |
| `GET /v1/notifications?topic=board` 或 `topic=collaboration` | 分别复用事项变更或伙伴正文订阅，避免事项订阅初始化协作执行器。按 run 合并最新正文，保留 attempt/seq 版本。属于只读刷新通知；结构数据仍由业务快照查询。断线重订阅时重读事项。 |

提交编号与完整输入指纹随任务行一起入库。编号作用域为原账号数据目录；同编号相同输入得到原任务，模型、采样、来源等任一输入改变则返回409。丢失提交回执时客户端仅以同一编号作一次限定重试。账号选择或服务重启后仍按原登记核对，不重新执行已完成任务。请求体上限2 MB。

桌面与桌宠共用 `client/api.ts` 的 fetch RPC/SSE。重连保留游标、忽略重复 seq，过期快照替换正文；answer_reset 等到下一段正文才替换旧草稿。账号绑定变化或组件卸载时关闭原订阅，迟到事件不进入新页面。正文终态由服务确认，错误或取消不作为成功完成。

思考仍只推送给当前连接，最多256段待发，不保存到任务 SQLite，也不参与断线重放。通知订阅与思考都在断开时释放。协作预览继续使用原短期凭据、来源限制及方法白名单，不能访问完整账号 RPC 或提交普通任务；每次通知发出前重新检查凭据有效期。CORS 仅允许现有 Tauri 和本地预览来源。

`worker_rpc.py` 和终端的父后台调用使用同一认证 HTTP 接口，显式跳过系统 HTTP 代理。终端字节 offset、输入、尺寸和取消仍由原 TerminalManager 处理；不改变目录、命令、沙箱或工具权限。统一项目评测入口也使用该 HTTP 调用。

笔记提问现在由 TaskManager 调度独立 Python worker，worker 调用原 NotebookService。它保留来源问答、完整正文校验及保存回执，失败时将结构化 partial / answer_complete / cites 送回原界面。任务排队、运行或仍在收尾时，父后台的笔记修改保护继续拒绝修改；只读加载仍可用。停止后先核对原笔记和任务，不自动重放问句或写入。

旧 `/ws`、`/collaboration`、`/stream` 仅通过独立 legacy_ws 适配器暂留兼容，原契约回归继续运行。本批桌面及内部正式调用方已改用 HTTP/SSE；批次6再移除兼容代码。

## Pi 私有进程协议

固定依赖移至 `desk_companion/pi_runtime/package.json` 及 package-lock.json，由兼容探针与正式进程桥共用。Node 24.22.3、Pi Agent Core / Pi AI / Pi Schema 1.5.2、undici 8.12.4 沿用首批锁定版本。

Python `PiBridge` 通过隐藏子进程 stdin/stdout 发送版本1的 JSON 行。每个子进程只接纳一个运行，配置、凭据和工具参数不经命令行或临时配置文件，Node不继承父后台的RPC令牌。启动必须完成 Node/Pi/协议握手。Python 持有 ProcessTree 并作有界清理；TaskManager 仍拥有任务状态、取消及整个 Python/Node 进程树。桥不另建任务队列或业务状态库。

| 消息 | 责任 |
| --- | --- |
| ready | 校验固定版本与 protocol=1。错误依赖或运行时直接失败。 |
| complete / agent | 单次推理由 Pi AI 执行，有工具的运行由 Pi Agent Core 官方循环执行。输入为已映射模型、上下文、工具定义及网络策略。 |
| before_model → reply | Node 在实际发送前，按 call_id 将真实请求正文交给 Python 准入回调。预算或策略拒绝时不发网络请求。实际预算与调用记录仍由业务适配方接入现有服务。 |
| tool_call → reply | 仅注册本次传入的工具定义；SDK 参数校验后回到 Python 工具入口。Python 检查声明名称并执行现有授权/业务回调，返回原回执。 |
| text_delta / thinking_delta / http_status / provider_usage | 关联当前运行和模型 call_id，供业务映射及实际边界观测。每轮独立标记原始 usage 是否存在，不能把 SDK 的零默认值当作已知用量。未显式绑定已知价格时cost_known=false。 |
| result / error / cancel | 检查最终 stopReason。length/error 等不完整结果拒绝完整交付；显式取消与调用超时分别报告，保留已收到的片段。取消后不再派发模型或工具回调，不转发迟到增量。 |

`TEBB_PI_NODE` 可指定固定 Node 的绝对路径，未指定则检查 PATH 中 Node 的精确版本。SDK maxRetries 固定为0。Node 网络策略按调用注入 dispatcher，不改全局代理环境。生产模型绑定、原上下文容量、工具策略及预算/观测服务的接入归随后调用方迁移；本批不切换现有 Atlas 模型调用。

## 可复制验证与验收边界

```powershell
$env:TEBB_PI_NODE = 'E:/temporary/node-v24.22.3-win-x64/node.exe'
$piNpm = Join-Path (Split-Path $env:TEBB_PI_NODE) 'node_modules/npm/bin/npm-cli.js'
Push-Location desk_companion/pi_runtime
& $env:TEBB_PI_NODE $piNpm ci --ignore-scripts --no-audit --no-fund
Pop-Location
uv run --locked python -m unittest tests.test_http_api tests.test_pi_bridge -v
uv run --locked python scripts/pi_compat/run.py --node $env:TEBB_PI_NODE --output E:/temporary/pi-offline-new.json
# 已安装 client 依赖时，直接运行客户端传输代码与隔离后台的端到端验证
uv run --locked python scripts/verify_http_transport.py --node $env:TEBB_PI_NODE --output E:/temporary/http-client-new
# 完整回归按 DEVELOPMENT.md 配置固定 Atlas/skills 源码后运行 scripts/ci_checks.py test。
```

这些用例自行创建临时账号资料、SQLite、受控子进程和回环模拟模型服务，不访问真实模型或发送外部消息。CI 的 Python job 安装同一固定 Node 和锁定依赖，实际运行进程测试。

脱敏结果、原失败与修正后的整组复验见[证据记录](evals/http-sse-bridge-20261118.json)。本地完整1514项先发现旧WebSocket测试监听器的两处HTTP接入失败；改用正式监听器后，本地API整组58项通过，新增HTTP/Pi进程15项、评测与启动21项、前端315项、类型检查和构建通过。提交的最终全量结论以同一提交的CI记录为准，三项CI通过后才更新main。

首个候选CI的HTTP/进程桥相关用例通过，但既有个性化批次验收因私有线程6秒等待未结束而失败。该用例单独关联#238，改用已有service.wait的25秒有界入口，补验首批处理25条、余1条及两批共写26次。生产同步规则未变，相关18项回归通过；原CI失败记录保留。

| 验收 | 证据入口 |
| --- | --- |
| 健康、账号、认证退出与无 GUI 后台启动 | `test_backend_startup`、`test_headless_host` 和 HTTP 真实回环服务 |
| Token、RPC白名单、跨来源拒绝、预览限制与过期订阅收回 | `test_http_api` |
| 并发同编号只入队一次，输入冲突、选中会话变化及服务重启后核对原任务 | `test_http_api.test_atomic_dedup_conflict_replay_and_snapshot_watermark` |
| SSE有序补读、去重、过期快照、断订阅不取消、显式取消与worker释放 | `test_http_api`、前端 workspace 真实流解析用例 |
| 笔记一次问题、一次回答及失败体 | `test_http_api.test_notebook_lost_ack_uses_same_task_and_saves_question_once`、前端 notebook SSE 用例 |
| 事项变更后页面更新、卸载后不再刷新 | 前端 work-board 真实组件、账号订阅清理用例 |
| 真实事项服务伙伴改状态后通知刷新，实际客户端重连读取已提交事项与对话历史 | `test_http_api.test_partner_board_change_refreshes_real_sse_and_releases_listener`、`scripts/verify_http_transport.py` |
| 原终端记录的字节offset、输入、尺寸及停止标记 | `test_http_api.test_terminal_http_calls_reuse_real_service_records_and_controls`、`test_terminal` |
| 真实Node/Pi文本、思考、用量、官方工具循环与Python回执 | `test_pi_bridge` |
| 预算拒绝前无网络发送，length拒绝、缺usage未知、独立超时及取消 | `test_pi_bridge` |
| TaskManager取消后Python worker和Node后代退出 | `test_pi_bridge.test_existing_task_cancel_reaps_python_worker_and_node_descendant` |

本批不调用真实模型。首批的真实模型结果保留在 [兼容报告](PI_COMPATIBILITY_293.md)。真实代理、自定义CA、非空推理历史的多轮、授权工具运行中取消、升级/回退及无全局Node的安装包验收仍按相应后续批次执行。开发 node_modules 从 wheel 包发现和运行时拷贝中排除，正式Node/Pi候选包来源与许可归批次6。用户现有账号、配置和历史未用于这些测试。
