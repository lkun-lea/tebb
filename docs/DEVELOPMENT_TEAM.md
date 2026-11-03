# tebb 开发团队

在桌面 **协作 → 开发团队 → 项目群开发** 输入需求，选择项目群并点击“开始团队开发”。通过 tebb 当前配置的模型、项目群负责人和该群成员运行。点击“打开项目群”可补充需求、停止任务或查看完整回执。

先在伙伴聊天中打开项目文件夹，在目录权限中为该项目开启编辑和终端，创建属于该项目的群。负责人以外至少有一位具备“文件编辑”和“终端”能力的编码伙伴。若要独立跑集成检查，再加入一位可用终端的验证伙伴。群成员的工具权限和项目目录授权同时生效。

负责人先确认需求是否清楚。一个编码伙伴加一个验证伙伴的分工已经确定时，直接进入实现和验收。其他组合使用现有规划流程。后续伙伴能看到交接时实际改动的文件、验证命令、退出码和失败输出摘要；历史命令只证明当时的版本。独立验收没有成功回执时不能宣称通过。

独立验证出现明确的非零退出码且预算允许时，负责人最多交回原编码伙伴一次，再由原验证伙伴重跑失败命令。首次失败留在任务记录中。取消、结果未知或验证过程改变工作区时不会自动重试写操作；没有合适的独立验证成员时，看实际分工与回执判断覆盖范围。

开发团队在登记时使用与单编码伙伴相同的编码根预算，继承用户设置的时限。实现、复查与续修共享已用量。原生工作区命令的实际退出状态可作为一次进展；同一物理任务、编辑版本和成功或失败状态只计一次，重复执行或变动标准输出不能持续刷新进展。

若编码子任务已修改文件并取得修改后的成功命令回执，随后因连续无进展停止新工作，可以在自己的剩余额度内作一次无工具交接。失败命令、无回执、未确认写入仍按缺口处理。交接仍需独立审阅，负责人保留额度不借给子任务。

本地机制验证可运行 `python -m unittest tests.test_native_development_team`。它使用受控模型、实际文件修改和 Python 子进程检查跨进程重复订单。使用已配置 tebb 模型做同题实测，可运行 `python -m scripts.eval_native_development --live --output <全新目录>`。两组从相同的 CLI、服务和 SQLite 存储代码开始，保留原生交付状态，并通过 tebb 终端独立检查重启、账户隔离、失败回滚及并发。该命令需要现有模型连接和可用的原生 WSL 沙箱。

## 在项目群中定位和修改源码

编码伙伴可用 `workspace_search` 按 Python 函数或类名搜索，结果包含路径、限定名和行号。非 Python 代码和日志常量可用 `mode=text` 搜索。用 `workspace_read_symbol` 传入路径和限定名，或用 `start_line`、`end_line` 读取原文。返回 `next_line` 时可从该行续读。每次最多返回 120 行、12,000 字符。搜索最多返回 25 个匹配，`limited` 表示还有结果或扫描达到了上限，可用 `path` 缩小范围。

小改动用 `workspace_patch`，传入路径、读取时的整文件 revision、唯一原文 old 和替换文本 new。版本变化或原文不唯一时，重读目标再改。成功会生成文件变更回执，使此前的验证失效。参考目录和验证伙伴均只能使用两个读取工具。新功能的本地检查为 `python -m unittest tests.test_workspace_source tests.test_native_development_team`。

### 复跑真实 #208

在两个独立进程中运行下列同一入口。每次将 `$engine` 指向对应版本的原生后端根目录，`$out` 指向仓库外尚不存在的结果目录。先结束旧组再启动新组。需要 tebb 已配置的模型、可用的 WSL 沙箱，以及包含 #208 历史提交的本地仓库。评测会实际使用模型额度。

~~~powershell
$repo = (Get-Location).Path
$env:PYTHONPATH = $engine
$env:DESK_COMPANION_DATA_DIR = $repo
python "$repo/scripts/eval_native_issue208.py" --live --repo $repo --output $out
~~~

两组都从 `1494d1c` 的完整归档起步，共用需求、团队成员和原生根预算。评测结束后才注入 `88bf758` 的四项缺陷检查和修复前的八项回归。候选代码在 `team/`，原生命令、实际输出、文件变更及距发单的秒数在 `events.jsonl`，终态、逐项结果和用量在 `result.json`。搜索命中不能计作复现。用量缺失看 `budget.consumed.input_unknown_calls` 和 `output_unknown_calls`。

2026-11-02 在旧控制器 `e049b57` 和本次工具版本各运行一次，模型均为 `mimo-v2.6-flash`。

| 原生团队 | 首次实际复现 | 首次业务源码修改 | 冻结缺陷检查 | 既有回归 | 已登记输入 / 输出 token |
| --- | --- | --- | --- | --- | --- |
| 旧工具 | 602.2 秒内未观察到 | 无 | 0/4 | 8/8 | 110,303 / 5,585 |
| 新工具 | 290.05 秒 | 无 | 0/4 | 8/8 | 178,245 / 4,897 |

旧组耗尽根时间预算。新组调用搜索 6 次，按函数读取 1 次未命中，仍整文件读取 5 次。复现命令打印了带控制序列的错误地址和来源登记、引用审阅的 IPv6 异常；下一次模型等待超时，未调用局部修改。两组各有一次调用缺少用量，已登记总量相差 67,254 token（新组多 58.0%）。此次对照只观察到了复现阶段的进展。

可给同一评测入口附加 `--repro-events <新工具冷启动组的 events.jsonl>`，从已观察到的 #208 复现开始。结果的 `starting_point` 为 `observed_reproduction`。事件流记录模型调用开始、结束、用量及工具回执；本地守卫拒绝的下一次调用可能只有开始和结束事件，没有计费用量。

首次定向实验沿用原生团队和原预算，输入了上轮失败命令、输出及源码路径。132.4 秒后，编码伙伴执行了四次搜索和一次目录查看，未读取函数或提交修改。根预算报告 `budget_no_progress`，共四次有用量的模型调用，输入 21,041、输出 1,117 token。独立验收为缺陷 0/4，回归 8/8。搜索回执标记为成功只说明工具执行完成；本轮留存事件没有命中条数，无法判断各次搜索找到了什么。

在单个 Python 文件中，`workspace_search` 的 `symbol` 模式精确匹配唯一函数名或限定名时，回执包含正文首段和整文件 revision，可直接调用 `workspace_patch`。`text` 模式同样支持简单函数名，如 `urls`。它保留原来的文本匹配和行数统计，并在唯一精确匹配函数时附上源码。目录搜索、多义匹配或含标点的文本查询只返回候选。通过 `next_line` 续读长函数。搜索和按函数读取共享文件指纹和正文去重，重复读取不会刷新守卫。搜索完成事件记录模式、查询词、已观察命中数、是否附带正文和是否新增进展。扫描受限时，命中数可能小于实际总数。

2026-11-03 用同一模型、复现输入和预算再次运行定向实验。三次文本搜索分别命中 10、8、16 处，均未附带正文；编码伙伴另行整读了源码和测试文件。任务在 602.6 秒结束，根账本停止原因为 `budget_time_ms`。无业务源码改动，缺陷 0/4、既有回归 8/8。六次模型调用用量完整，合计输入 67,449、输出 11,018 token。受控测试覆盖了唯一命中直接修改及重复读取仍触发守卫；本轮真实模型没有使用该唯一路径。

随后重放上一轮对 `desk_companion/web_sources.py` 的 `text` 查询 `urls`。原有 10 处文本命中全部保留，额外返回第 24–35 行及 revision，已在副本验证局部修改。相同输入和预算的下一次真实团队实验中，`urls` 和 `url_key` 两次文本搜索都返回了正文并登记新进展。团队仍未发起补丁，601.9 秒到达根时间预算。候选中 673 个原文件逐字节未变，缺陷 0/4、回归 8/8。8 次模型调用有完整用量，输入 81,312、输出 13,391 token。

## 外部流程实验记录

展开“外部开发流程实验记录”后可选择已登记的 issue，比较外部实验组及单开发者的固定测试、返工和用量。

## 为后续 issue 建立对照

先选择有明确行为和可重复测试的真实 issue，记录选题再开始开发。每组从同一 Git HEAD 开始并单独生成候选。建议先积累三个满足条件的新 issue，再比较同等质量下的成本和返工。用本地 CLI 发起，默认不会自动领取全部事项。

从仓库根目录执行，Python 需要项目已有的 psutil、jsonschema。真实开发需要已登录的 Codex CLI、Git 和任务依赖。以下变量对应当前 issue 的四份输入和新的实验目录，实验目录必须位于源码仓库外。

~~~powershell
python -m scripts.dev_team init --repo $repo --pair $pair --issue $issue --contract $contract --plan $plan --model $model --openai-https
python -m scripts.dev_team prepare $pair
python -m scripts.dev_team run $pair --live
python -m scripts.dev_team status
~~~

- issue 为 JSON 对象，含 title 和 text 或 body。contract 为已确认需求，含 status（ready）、summary、scope、non_goals、constraints、questions 及 criteria。每条 criterion 含 id、requirement、verification。
- plan 为固定测试计划，包含 argv 参数数组及 files（验收脚本绝对路径到 SHA-256 的映射）。脚本接收 {candidate} 和 {result}，将 status、failure_type、逐项 checks 写入结果。每项必须有 name、passed、observed、failure_type 和对应 criterion_ids。两组共用此计划，控制组要求通过的固定检查覆盖全部契约条件。
- 可在 init 时重复指定 --dependency-path 指向已固定的本地源码依赖。prepare 支持 --wheelhouse 和 --offline。环境预检失败可补齐依赖再继续。两组分别使用 direct 和 workflow 子目录保存状态、封存代码、验收日志、模型事件与用量。
- 初始化、准备、查询不调用模型。run --live 按顺序运行两组。已结束的组再次运行时会跳过。用 python scripts/dev_cycle.py progress 或 cancel 加上对应组的任务目录查询或取消。进程中断且存在未核对写入时，检查现场后使用 recover 任务目录 --acknowledge 收尾。
- 可用 python -m scripts.dev_team import-history 已有对照目录 登记包含 direct 和 workflow 的成对历史记录。仅接收已结束且输入一致的历史运行，显示原流程版本。历史案例与本轮新开发分别分析。

## 解读结果

先核对功能测试、独立验收与交付状态，再比较返工、证据补交及模型调用数。单组只完成一部分时，已经消耗的 token 仍可见。未知费用或人工干预量用“未知”展示。对已核实的附加成本，可执行下列命令分别登记每组的累计值。

~~~powershell
python -m scripts.dev_team account $pair workflow --interventions 1 --maintenance-tokens 1200
~~~

缓存输入包含在输入总量中，输出包含推理用量。模型用量仅计入有回执的调用。当前试点固定模型和验收资源，外部环境、缓存命中和运行顺序仍会影响结果。不要单凭一组调用较少或一次成功推算整体收益。

桌面和 CLI 必须共用数据目录。源码开发桌面默认使用仓库目录，便携或安装版使用独立用户数据目录。若分别运行，请将 CLI 的 DESK_COMPANION_DATA_DIR 指向桌面相同的数据目录。登记信息存于该目录内的 .dev-team，原始证据保留在实验目录。调试入口为已认证本地 RPC development_team，返回 experiments，包括两组的状态、时间线、客观检查与用量。
