# Pi SDK 首批兼容验证与迁移验收

2026-11-18，关联 [#293](https://github.com/lkun-lea/tebb/issues/293)。基线为 main `fbc482dd78f4e4f88e69927a70a2442b512a6bdc`。本批交付调用入口盘点、固定版本探针、模拟及真实模型证据和后续批次。生产切换由下表各批验收推进。

## 固定依赖与复现入口

| 项目 | 本批固定值 | 依据 |
| --- | --- | --- |
| Node Windows x64 | 24.22.3 LTS | [官方发行清单](https://nodejs.org/dist/index.json)，满足 Pi 的 Node >=22.19.0 要求 |
| Node ZIP SHA-256 | `e612af99f626ab415ea225af6bce5c971feb448cb5cae250bb1c3fa50c5f7d9f` | [官方摘要](https://nodejs.org/dist/v24.22.3/SHASUMS256.txt) |
| Pi Agent Core / Pi AI / Pi Schema | 全部 1.5.2 | [Agent Core](https://www.npmjs.com/package/@earendil-works/pi-agent-core/v/1.5.2)、[Pi AI](https://www.npmjs.com/package/@earendil-works/pi-ai/v/1.5.2)，完整传递依赖及 integrity 见 package-lock.json |
| 独立 fetch 传输 | undici 8.12.4 | 在 Pi 官方 fetch 注入点验证直连与代理，按调用持有 dispatcher |
| 探针定义 | [package.json](../desk_companion/pi_runtime/package.json) / [锁文件](../desk_companion/pi_runtime/package-lock.json) | 与客户端前端依赖分别安装 |
| 结果 | [脱敏逐项报告](evals/pi-compatibility-20261118.json) | 保留首轮失败及单独复验 |

默认开发机 Node 20.17.0 低于本批 SDK 要求。使用解压的固定 Node，并核对下载 ZIP 摘要。以下命令中的 `$piNodeRoot` 指向该目录，输出文件必须尚不存在。

```powershell
$piNodeRoot = 'E:/temporary/node-v24.22.3-win-x64'
Push-Location desk_companion/pi_runtime
& "$piNodeRoot/node.exe" "$piNodeRoot/node_modules/npm/bin/npm-cli.js" ci --ignore-scripts --no-audit --no-fund
Pop-Location
uv run --locked python scripts/pi_compat/run.py --node "$piNodeRoot/node.exe" --output E:/temporary/pi-offline.json

# 显式真实模型探针，读取现有配置，通过子进程标准输入传递配置
uv run --locked python scripts/pi_compat/run.py --node "$piNodeRoot/node.exe" --output E:/temporary/pi-live.json --live --profile E:/path/to/existing-profile

# 限定复验一项，另存证据
uv run --locked python scripts/pi_compat/run.py --node "$piNodeRoot/node.exe" --output E:/temporary/pi-one.json --live --profile E:/path/to/existing-profile --case live-text-deepseek-flash
```

真实批次限定已有直连配置、最多两个模型。每模型文本用例至多一次请求，工具用例至多三次请求，全部设置 maxRetries=0。工具只执行隔离整数加法。文本与工具结果分别断言 `PI_COMPAT_OK` 和 `40`。配置只读，报告保存模型名、端点摘要、事件与用量。每例完成即保存结果。Python 总等待上限为330秒，Node 请求与 Agent 也分别有取消时限。

本批 Node 探针在独立进程运行。生产服务仍使用原 Atlas 路径。Node 随 Windows 安装包分发与干净机器验证列入最后一批。

## Atlas 生产调用入口

对基线全部 `desk_companion/**/*.py` 解析 AST，发现16处直接导入，集中在7个文件。每次探针报告记录路径、行号和模块。迁移还需覆盖下列间接调用。

| 路径或入口 | 当前 Atlas 接入与上层调用 | 迁移归属 |
| --- | --- | --- |
| `chat/assistant.py` | build_agent 组装 Agent、Toolkit、InMemoryJournal、TokenCostPlugin；list_providers 读取提供商目录 | 普通聊天的 Pi Agent；模型目录继续归产品 |
| `collaboration/execution_context.py` | ExecutionLLM 继承 LLM；ChatOptions、取消异常；CompactManager 的工具结果裁剪 | 统一模型边界，保留输入准入、根预算、上下文来源及用量结算 |
| `collaboration/collaboration_llm.py` | ChatOptions/ChatCallbacks，经 ExecutionLLM 发起模型调用，持有超时/思考/工具分片回调 | Pi AI 事件与产品事件映射 |
| `collaboration/readonly_research.py` | Atlas Agent、Toolkit、journal、MaxSteps；当前只读研究试点 | 研究批次的 Pi Agent，保留父子任务和权限 |
| `tasks/worker.py` | 普通任务 build_agent；BasePlugin 提取工具/用量事件；MaxSteps/Timeout；协作等 workflow 分支分别派发 | 普通聊天及任务生命周期 |
| `desktop/stream_plugin.py` | BubbleStreamPlugin 转接正文、思考、工具进度 | 旧桌面和气泡输出适配 |
| `models/model_generation.py` | 两次输出上限探针；ChatOptions 与 IncompleteResponseError | 设置/诊断与输出参数绑定 |
| 工作台、桌宠、飞书普通会话 | `chat/conversation.py` → agent.run；`integrations/feishu/feishu_agent.py` 经任务或会话服务 | 普通聊天，逐入口验证 |
| 多伙伴、路由、计划、交付、开发团队 | `collaboration/collaboration_worker.py` → CollaborationLLM，产品当前拥有循环和独立审阅；另有 Atlas 只读研究驱动 | 分阶段替换循环，保留角色/阶段/预算/审阅契约 |
| 可视化工作流 AI 节点 | `automation/workflow_nodes.py` → CollaborationLLM；确定性节点由现有解释器执行 | 工作流首批，节点调用 Pi AI |
| 笔记问答与勾选总结 | `knowledge/notebook_service.py` → conversation.agent.llm；来源检索由产品处理 | 单次模型入口 |
| 知识库试问 | `knowledge/knowledge_service.py` → 同一 llm | 单次模型入口 |
| 视频笔记、字幕分段 | `content/video/analysis.py` → ExecutionLLM；原检查点和归档回执 | 单次模型入口及任务恢复 |
| 资讯摘要、日报 | `content/news/service.py` → ExecutionLLM | 单次模型入口及调度回执 |
| 周复盘和旧桌面日报 | `content/weekly_review.py` → agent.llm；`desktop/app.py` → agent.run | 剩余入口，分别保留文本校验与工具控制 |
| 手动/自动上下文压缩 | `memory/context_compression.py` / `memory/context_pack.py` → ConversationService.prepare_context → agent.llm.chat | 单次摘要调用，原文与覆盖水位继续由产品保存 |
| 记忆独立试验、调用解读、模型连通测试 | `memory/memory_inspector.py` → CollaborationLLM；`observability/agent_debug.py` → ExecutionLLM；`chat/assistant_settings.py` | 诊断和设置批次 |
| 构建、CI、发布 | `pyproject.toml` / uv.lock、`scripts/python_dependencies.py`、prepare_runtime、release_audit、smoke_release、CI 和 release-candidate workflow | Atlas 退出批次 |

普通产品任务、协作任务、只读试点目前有不同循环入口。迁移时应按调用链逐个接通 Pi Agent Core，并在替换对应入口时移除其旧循环。

## 模型、网络与事件兼容结论

真实配置为 `deepseek-flash` 和 `glm-5.3`，二者使用同一个已配置 HTTPS 路由。验证对象是这组模型名与路由配置。模型上下文窗口、单价和服务端能力仍沿用产品的已验证配置。

| 用例 | 结果 | 观察值或迁移要求 |
| --- | --- | --- |
| 模拟正文、思考和用量尾帧 | 通过 | text_delta / thinking_delta，prompt 13 = input 10 + cacheRead 3，output 7 已包含 reasoning 2，total 20 |
| low / high / max、temperature、top_p、输出上限 | 模拟三档通过 | thinkingLevelMap 显式声明 max；top_p 经 samplingParams；maxTokens 按模型已验证绑定选择 max_tokens 或 max_completion_tokens |
| 分片工具参数与工具往返 | 通过 | Pi Agent 执行加法一次、模型两次，最终40；GLM 模拟检查 thinking.clear_thinking=false、tool_stream=true 和 reasoning_content 回传 |
| 无效工具参数 | 通过 | 执行次数零，错误工具回执进入下一轮 |
| 缺少 finish_reason | 通过 | SDK返回error，保留已收到的正文 |
| length 截断 | 通过，需产品映射 | SDK返回带length的结果对象；业务适配必须按现有规则拒绝把它提交为完整正文或操作结论 |
| 缺少 usage | 通过，需产品映射 | SDK计数默认为零，产品必须同时跟踪原始usage尾帧是否存在，缺失时维持unknown |
| 取消、响应头前网络等待超时 | 通过 | 取消保留partial、stopReason=aborted；请求超时返回error；真实流中的空闲超时策略仍待产品接入验收 |
| 429且禁止重试 | 通过 | 只发一次请求，返回error |
| 自定义认证HTTP代理、环境HTTP代理 | 通过 | 每调用fetch注入，代理服务实际收到隧道请求，认证收到Basic头 |
| SOCKS5 | 合成代理通过 | undici 8.12.4 的SOCKS5支持标记experimental；SOCKS5H、认证SOCKS、HTTPS代理服务器、自定义CA、Windows代理设置仍待验证 |
| DeepSeek文本low | 首轮失败，独立复验通过 | 首轮TLS阶段ECONNRESET，未收到HTTP响应；复验正文精确匹配并有15条思考分片；原Atlas对照也通过，根因未定位 |
| DeepSeek工具low | 首轮通过 | 两次模型请求，一次实际加法，40；两次usage尾帧 |
| GLM文本low与工具low | 首轮通过 | 文本精确匹配，工具两次模型请求，一次加法；两次usage尾帧 |
| DeepSeek文本high | 通过 | 19条思考分片，正文精确匹配 |
| GLM文本max | 通过 | 102条思考分片，正文精确匹配 |

首轮真实4案为3通过、1失败。单独复验1案、补充high/max两案均通过。Pi共9次真实模型请求尝试，另有Atlas对照1次。原始失败、复验和补充各自留存，结果不合并成无失败批次。工具历史字段往返已验证；首轮工具探针只记录reasoning_content字段存在，非空推理历史的真实多轮覆盖仍需补验。

high只实测DeepSeek文本，max只实测GLM文本。其他模型与档位组合及对应工具组合待补验。探针开发初轮还有4项模拟失败，原因和修正分别保留在脱敏报告中，最终模拟15项全通过。

本批给自定义模型填入的contextWindow/maxTokens用于限制合成探针，cost填零用于满足SDK模型类型；所有公开结果标记cost_known=false。生产接入需映射原容量声明、输出参数绑定和实际价格来源，费用未知保持未知。

Pi模型API失败在事件流中形成error/aborted结果，Agent.prompt本身可正常返回。产品应检查最终消息stopReason、部分输出、实际工具回执及任务取消状态。原Python的异常分类与终态保护需在统一模型适配边界保留。

Pi提供fetch/onPayload/onResponse/onProviderStreamEvent，可用于传输配置与观察。现有agent_debug通过httpx.Client.send录制，迁到Node后要在新实际发送/接收边界记录原始资料，并关联task_id/call_id，原HTTPX钩子需随对应调用方切换。

## 迁移批次与验收表

| 批次 | 工作范围与前置 | 必须通过的验收 | 当前状态 |
| --- | --- | --- | --- |
| 0 兼容基线 | 本文固定SDK、Node、入口清单和探针 | 模拟15案；已有模型文本/工具实测；首轮失败与复验独立记录；列明代理与协议缺口 | 本批完成，有上述验证边界 |
| 1 HTTP/SSE与进程桥 | 复用TaskManager/SQLite/服务；定义Python↔Node私有协议；FastAPI绑定回环 | Tauri启动/健康/认证退出，桌面/桌宠/预览/Python调用；request_id去重与冲突；SSE补读、过期快照、断订阅任务继续；账号切换收回旧订阅；worker_rpc及terminal读取/输入/尺寸/offset | 已实现，逐项证据见[进程桥验收](HTTP_SSE_BRIDGE_293.md) |
| 2 工作流AI节点 | 批次1及模型边界具备；现有解释器/版本/回执持有业务状态 | 手动/定时、条件分支、逐节点确认；原保存版本及计划绑定；外部写入丢回执后按原操作查证；已确认节点跳过、目标侧写入一次 | 已接入通用AI节点，证据见[工作流Pi验收](WORKFLOW_PI_293.md) |
| 3 普通聊天 | Pi Agent Core替代普通Atlas Agent；映射工具与历史 | 桌面/浮动窗/飞书多轮；低高max与模型代理；工具白名单、预算发送前/执行前准入；思考和正文连续；取消后禁止工具及迟到终态覆写；历史与用户选择记忆可追溯 | 待实施 |
| 4 协作和开发团队 | 路由/计划/执行/交付与只读研究入口逐批接通 | 角色权限、父子取消、并发隔离、阶段恢复、来源/独立审阅；Python回执贯通；原#304伙伴事项实际变更后页面刷新；研究质量及原生跨issue门槛分别记录 | 待实施 |
| 5 剩余单次入口 | 笔记、知识库、压缩、视频、资讯、周复盘、模型配置和调试 | 笔记重连不重复保存问句；摘要仅接受完整正文；字幕章节覆盖；资讯真实错误与调度回执；模型输出参数探针/实际请求检查台；原版本/记忆与用量归属 | 待实施 |
| 6 Atlas退出与候选包 | 所有生产入口已切换，并补齐真实代理和打包矩阵 | 零生产Atlas导入/旧WebSocket引用；移除uv依赖、CI checkout、归档构建；打包Node/Pi来源与许可；无全局Node/Pi/Atlas的干净Windows启动；升级保留历史/工作流/回执；备份回退、完整CI | 待实施 |

每批都保留task/run/call/operation编号、实际失败、测试与候选版本。跨端共用契约与共同Agent验收要求继续见 [架构设计](CLOUD_MULTICLIENT_ARCHITECTURE.md)。

HTTP/SSE与进程桥的实施及边界见[进程桥报告](HTTP_SSE_BRIDGE_293.md)，工作流AI节点见[本批报告](WORKFLOW_PI_293.md)。下一批为普通聊天的Pi Agent Core工具循环。实际安装包的Node生命周期、授权工具取消和回执恢复必须在相应批次独立验收。
