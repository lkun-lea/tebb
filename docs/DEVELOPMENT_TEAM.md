# 开发团队实验

在工作台左侧打开 **协作 → 开发团队**，选择 issue。实验组由需求审查、开发、独立验收、监督角色协作，对照组由一名持续工作的开发者完成。两组运行同一个预先固定的测试。团队页在可见时每五秒读取一次本地记录，显示每轮交接、失败原因、测试名称、代码版本与成本。

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
