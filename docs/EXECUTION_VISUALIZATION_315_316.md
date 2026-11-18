# AI 执行图、工具监控与评测闭环

关联 [#315](https://github.com/lkun-lea/tebb/issues/315)、[#316](https://github.com/lkun-lea/tebb/issues/316)。实施基线 main `f447eac8a33cc16daa80815f66c7dc77d130893b`。2026-11-18 用户确认“统一实时执行图与任务操作”。决策见 [ADR 0045](adr/0045-execution-observation-and-evaluation.md)。

## 使用与职责

设置增加「工具」「Agent 调试与评测」正式入口，无需打开开发者模式。聊天、任务监控、浮动伙伴、协作运行、研发团队和工作流运行提供「执行过程」入口；展开后自动读取同一根任务的图与时间线，关闭后停止轮询。模型节点打开原调用与脱敏载荷。停止、确认、补充和继续仍由原任务服务执行，手工工作流保留原编辑器。

TaskManager、协作服务和工作流服务持有业务终态。UsageStore 保存实际适配器调用，ToolMonitor 保存定义和生命周期元数据。图只投影记录；边表示已有父子关系、实际模型→工具或明确的独立评测关系。时间相邻只用于时间线。工具成功与任务验收分开，缺少历史阶段、Skill 内容版本、检索版本、费用或缓存保持未知，不推测模型内部思考。

| 产品入口 | 记录与定位 | 兼容边界 |
| --- | --- | --- |
| 工作台、普通任务、飞书普通任务 | PiChatAgent、原根预算、实际模型/工具 UUID、会话；聊天和监控可展开 | 本批普通 Pi 循环按需加载，不改变飞书授权 |
| 浮动伙伴、协作子任务、研发团队 | 原协作根、阶段/轮次、子任务、ExecutionLLM 和实际工具 | 保留原协作循环；整体 Pi 迁移属于 #293 后续 |
| 可视化工作流 | 原节点回执、物理任务、PiInference 模型 | 原解释器持有确认、取消和外部操作回执 |
| 笔记、知识库、压缩 | 公共模型边界，优先已有父任务，否则独立 operation 根 | 只显示实际记录的来源/检索阶段 |
| 视频、资讯、周复盘、审阅 | 公共模型边界和已有任务/operation 根 | 原检查点、归档和审阅持有业务状态 |
| 记忆试验、模型参数诊断、调用解读 | 既有诊断 scope 或独立 operation 根 | 与用户任务及验收分开 |

代码版本为进程首次模型调用时的源码内容标识；改代码后需重启对应进程。评测另在前后验证当前完整内容，漂移记基础设施失败。实际载荷保存提示、工具、输入和运行参数内容标识；配置标识不代表远端模型权重被冻结。

## 工具发现与兼容性

定义保存名称、集合、来源、说明、Schema 和内容版本。按既有命名归类为项目环境、工作区、工作流、日程、记忆、飞书、GitHub、网络资料、工具发现和产品工具。未运行的目录不补造历史登记。

普通 Pi 初始提供 `tebb_tools_search`、`tebb_tools_load`，以及原授权 Toolkit 中的澄清、委派、计划、交付和当前时间等基础工具。搜索最多返回30项，单次加载最多20项；只检索当前授权目录，不扩权。新定义按首次加载顺序追加，下一轮实际请求生效。会话恢复只恢复仍获授权且版本匹配的定义，改版或撤权的工具不会从历史恢复权限。

发现与加载占用现有只读工具预算；首次加载新定义记录一次进展，重复加载不延长无进展额度。执行继续检查本请求范围、账号、任务、目标、参数、取消、预算和外部操作状态。监控页不引入第二套配额。

| 能力 | 当前行为 |
| --- | --- |
| 固定运行时 | Pi Agent Core / AI / Schema 1.5.2、Node 24.22.3、undici 8.12.4 |
| Completions 回退路径 | 公开 `agent.state.tools` 与 `prepareNextTurnWithContext`，已加载定义在后续请求按顺序重新发送 |
| 禁止全部 / 允许子集 | 产品准入与实际目录控制，发送前/执行前校验；SDK 拒绝不计适配器尝试 |
| 延迟发现 / 追加 | 实际 SDK 载荷验证两集合、未使用工具不提供、追加位置和恢复后的声明 |
| 历史声明 | 只重建产品拥有、版本匹配的加载回执；缺失时在当前位置声明，不补造历史 |
| 原生 tool_choice:none / allowed_tools | 当前未启用，需按具体模型、协议、网关验证 |
| 原生 tool_search / defer_loading / developer additional_tools | 当前适配器未发送，不宣称支持 |
| 缓存与费用 | 仅使用 provider 实际回报；缺失未知，不保证按需加载带来缓存或费用改善 |

工具登记、当时名称授权、已加载、本请求允许是不同事实。连接和目标权限不从名称推断。筛选根任务或会话可查看当时目录、加载与实际 offer；历史授权不代表当前授权。

生命周期为 catalog、discovery、load、definition_effective、offer、request、intercept、attempt、outcome。稳定编号去重，实际重试独立保留。按名称汇总所有版本，明细保留实际版本。JSON 字符串中的 ok:false、success:false 和原操作失败进入业务错误；参数、权限、预算拦截不虚增执行尝试。超时、取消、未知、缓存和已有回执分别统计。

工具页支持集合、名称、时间、模型、物理任务、会话、根任务和状态筛选、分页、耗时与最近错误。原异常、参数和正文不写工具元数据库；错误摘要来自受控分类。详细载荷复用原认证调试器，统一脱敏密钥、Bearer、认证字段、带凭据或签名的 URL，并保留 Schema 与公共来源。没有归属依据的工具费用保持未知。

## 黄金集与评测

Promptfoo 固定 **0.125.1**，依赖与 Pi 独立锁定。固定 Python provider 经 `scripts/eval_agent.py` 提交正常产品任务；框架只编排和评分，不持有产品权限或另建 Agent 循环。用户用例只有数据，不提供任意代码、Shell、远端 provider 或可执行断言。

框架关闭遥测、更新、分享和缓存，并阻断框架进程的所有 TCP。该版本关闭遥测后仍尝试发送 opt-out 确认，集成验证其被阻断。产品子进程仍用正常网络策略；早期探索运行不能充当零网络证据。

黄金集映射现有合同28的固定用例，保留原判定器与历史报告。开发集可新增不可变版本；固定回归集和保留集不可原地改题，须独立新编号。UI 支持历史版本、复制/修订、分组、原因和权重。同批不能混用分组或同题不同标准。

| 层 / 场景 | 首版用例与验收依据 |
| --- | --- |
| 模型与确定性处理 | extract_record、sort_unique、filter_rows、unit_conversion、invoice_total：JSON、数值、类型 |
| 路由与来源指令 | route_json_*、clarify_calendar、clarify_target、ignore_source_instruction：路由与禁止虚构操作 |
| 工具选择、参数和发现 | pi_tools_discovery：真实 Pi 任务、两个模拟集合、参数/回执和未使用工具不加载 |
| 检索与来源覆盖 | research_*、attachment_tail、context_*：实际读取范围、来源和原操作编号 |
| 工作流与产物 | workflow_*、chart_from_evidence、calendar_*：原节点、产物和回执 |
| 交接、恢复和取消 | delegate_deliver、clarify_resume_root、cancel_active_*、readonly_*：原状态与子任务 |
| 记忆、搭建、项目 | 既有 memory/authoring/project：隔离状态与原服务验收；SDK/Docker 不具备时保留跳过原因 |
| 审阅校准 | feedback_supported、unsupported、instruction_data、partial_read、incomparable、missing_artifact：正例、反例与缺证据 |
| 失败回归 | source_failure 冻结原工具/定义/模型/提示标识；来源缺失明确 unverified |

自定义用例默认完整 JSON 与任务状态核验，可添加带权 JSON 路径检查。开放式任务最多6项 rubric，逐项复用 `feedback_review.review`、无工具 PiInference 和原 simple 预算；记录 judge 模型配置、提示版本、代码合同和逐项实际引句。参考答案是给定材料，不证明外部操作。缺失或无效证据保持未知，不能算通过。所有条件均必需，权重只计算部分达成率。不同合理表达可由明确 rubric 接受；确定性条件优先程序断言。

已有受控正反例和无效引句校准；假模型只证明合同和数据链，真实 judge 仍需经复核样本校准，不能据此宣称语义准确率。

批次冻结题目、规则、样本数、超时、加载策略、代码内容和模型配置。默认1样本，最多20题×5样本，超时20–300秒，一次一批。UI 默认隔离假模型；真实模式须显式 `live_authorized:true`，可固定 `model_id` 和独立 `judge_model_id`。评测采用私有 profile，结束/取消/恢复后清理临时凭据。停止沿原 TaskManager.cancel，宽限后回收所拥有进程树；关页面不取消，宿主重启记 interrupted，不自动重做操作。失败、批次、定义和历史版本本机持续保留，本批不自动清理。

真实批次仅复制所选模型与 judge 的容量、已核验输出参数绑定和价格配置，不复制账号业务数据。配置签名包含这些策略，前后变化会使批次失败；费用只在实际用量及单价都有记录时估算。日常假模型不继承真实价格。

## 指标与比较

- 成功率：独立验收通过数 / 全部计划样本；失败、超时、取消、准备失败、未启动、跳过及缺证据单列，均不移出分母。
- 达成率：通过的目标检查权重 / 全部计划检查权重；无细分条件时用整题必需检查。部分达成不等于成功。
- 假成功：执行声明完成而独立回执、产物或目标检查未通过；与模型/工具结果分开。
- 耗时：样本数与p50；至少20个有效样本才给p95。首段正文从模型适配器入口计时，不含纯推理片段；无记录未知。
- 用量：实际调用 UUID 去重，输入、输出、cacheRead/cacheWrite 和未知覆盖。费用按原输入/输出单价估算，不代表账单，也不假定缓存折扣。
- 重复可靠性：逐题首次成功、成功分布及完整样本计划下的不放回 pass@k / pass^k 估计；不完整计划不估计，取消按失败计。

比较要求完整结算、相同题目/模式/预算/样本/评分合同。候选代码、模型或加载策略差异单列；修改 judge 或规则需新建同合同基线。原成绩不重评、不覆盖，改善/退化逐案呈现。模拟通过不代表真实模型质量提升。

## AI 接口与复现

正常本地 HTTP 完整 token 访问，preview 凭据禁止。查询复用原 RPC allowlist；批次私有调用必须属于该批计划，不接受任意路径。

- `execution_inspect`：list、trace、locate、tools、capabilities。
- `agent_evaluation`：runtime、cases、save_case、draft_failure、start、get、分页 list、cancel、trace、debug_call、failures、compare。

UI 与 CLI 读同一记录；JSON 返回可直接结构化导出。环境变量来自已启动的隔离后端，不要在报告中输出 token。

```powershell
$env:DESK_COMPANION_API_URL = 'http://127.0.0.1:18769'
$env:DESK_COMPANION_API_TOKEN = '<隔离后端的完整 token>'
uv run --locked python scripts/agent_inspect.py execution list --payload '{"limit":20}'
uv run --locked python scripts/agent_inspect.py execution tools --payload '{"filters":{"root":"task:实际根编号"}}'
uv run --locked python scripts/agent_inspect.py evaluation cases
uv run --locked python scripts/agent_inspect.py evaluation start --payload-file E:/temporary/frozen-plan.json
uv run --locked python scripts/agent_inspect.py evaluation get --payload '{"ident":"实际批次编号"}'
uv run --locked python scripts/agent_inspect.py evaluation failures --payload '{"ident":"实际批次编号"}'
uv run --locked python scripts/agent_inspect.py evaluation compare --payload '{"baseline":"基线编号","candidate":"候选编号"}'
```

计划文件示例，版本从 cases 查询，不接受题目正文或命令：

```json
{"request_id":"isolated-eval-001","case_versions":["实际不可变版本"],"mode":"fixture","samples":1,"timeout":120,"tool_loading":"demand","candidate":"本次策略"}
```

运行前需要源码评测脚本、固定 Node、Pi 和 Promptfoo npm 依赖。runtime 返回前置状态，缺失如实失败。当前独立安装包尚未分发这套评测源码与依赖；干净 Windows 仍待发布运行时验收，不能用源码环境通过代替安装包通过。

```powershell
$env:TEBB_PI_NODE = 'E:/temporary/node-v24.22.3-win-x64/node.exe'
Push-Location desk_companion/evaluation/promptfoo
& 'E:/temporary/node-v24.22.3-win-x64/node.exe' 'E:/temporary/node-v24.22.3-win-x64/node_modules/npm/bin/npm-cli.js' ci --ignore-scripts --no-audit --no-fund
Pop-Location
uv run --locked python -m unittest tests.test_execution_center tests.test_execution_http tests.test_evaluation_center tests.test_reference_judge tests.test_promptfoo_integration tests.test_diagnostic_redaction -v
```

运行批次时不要修改代码或模型配置；FrozenCodeChanged / FrozenModelConfigurationChanged / FrozenJudgeConfigurationChanged 保留为原失败，重新创建批次。

## 验收记录与限制

隔离证据位于 `E:/Learn_Project/_work/tebb-315-316-evidence`，保留开发首轮失败：工具更新时机错误、前端测试加载器、Windows 断言路径解析、运行中源码漂移、judge 宿主 PID 被误当未退出 worker。修正后分别复验，不抹去原失败。

已通过专项包括两集合 Pi 实际载荷与恢复、授权范围与拒绝、去重与业务错误、真实记录图与多分支、完整 token/preview、CLI/RPC 同记录、脱敏、不可变用例、混合状态分母、Promptfoo→产品任务、取消与重启查询，以及失败→固定 rubric 用例→eager/demand 比较。受控模拟 reviewer 不代表真实语义验收。

两集合的隔离 Promptfoo 对照保存在 `strategy-comparison.json`：同一固定样本全量3次模型调用、按需6次，后者实际请求未包含无关的 `github_fixture_unused`。两者验收均通过，比较为 unchanged=1；发现步骤有额外开销，模拟 token 回报和未知缓存不能证明真实成本改善。报告关联各自源码标识，不覆盖后续批次。

浏览器使用隔离后端与真实 React 组件、正式设置导航验证图节点、编号、键盘、390px 窄窗、深浅主题、减少动效、强制颜色和无横向溢出。页面提交、排队、完成、同合同比较与私有调用下钻已验证；发现并修正 start 缺少 metrics 导致的排队渲染崩溃。临时 HTML、浏览器、Vite 和隔离后端已清理。Windows UI 自动化读取失败后改用独立 headless Edge，不宣称 Tauri 窗口或安装器已验收。

本机前端最终318项通过，类型检查和生产构建通过。后端一轮1565项、13项条件跳过，唯一失败是旧清单仍断言48条，已更新为49条并核对双集合用例的实际条件；修正后的判定、指标、权限与脱敏定向检查通过。完整冻结版本与候选 CI 的最终结果另行交付，保留前轮失败记录。新增框架安装与完整回归共用单次 CI，Python 作业时限由35调整到45分钟，不自动重试。

真实模型、缓存收益、真实 judge 校准、真实飞书写入、干净安装包未在本批运行。#293 协作迁移、原生能力矩阵和发行运行时继续独立跟踪；#315/#316 保留这些验收边界，不以模拟通过替代真实或发行环境验收。
