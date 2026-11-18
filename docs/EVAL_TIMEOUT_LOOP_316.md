# Agent 测评覆盖与超时闭环（#316）

2026-11-19。沿用已确认的统一执行图与评测中心范围，回应“新界面是否实现、完备测评集和系统性超时分析”的要求。界面已在 main 提供设置→工具、设置→Agent调试与评测及各任务执行过程；源码浏览器验收与安装包实机验收分别报告。Promptfoo 固定0.125.1，继续调用原产品入口，不再另建Agent或评分执行器。

## 完备性与覆盖

内置用例由54条扩展为65条：原49条业务/组件合同、5条原审阅校准、7条传输故障注入、4条独立保留审阅样本。固定回归61条、保留4条；旧用例版本不变，原成绩不重评。覆盖矩阵按模型、聊天、路由、协作、工作流、研究、项目、日历、记忆/上下文、审阅、超时、保留集与图表分类，每个现有内置用例必须归属至少一个领域。

矩阵分别展示用例存在、模拟记录、真实记录与具体缺口，记录不等于通过。知识库召回/重排、笔记完整生成、资讯/视频/周复盘、研发完整多阶段交付仍缺独立黄金业务样本；已有服务单元回归不能替代这些端到端质量验证。`coverage.complete=false` 保留这些事实，不能仅凭65这个数量称为所有Agent已完整验收。

隔离评测使用紧凑的 `attempt-N/p` 私有目录及原子分配的短项目目录，避免 Windows 未启用长路径时，嵌套批次产生超过 MAX_PATH 的项目锁和网页快照临时文件。读原批次仍支持 `private-profile`。任务提交前的准备异常单列 `infrastructure_failure`，不归因于模型；任务已接收后的真实失败不改成跳过。框架冻结期间不能同时运行会在 `client/src` 写临时探针的前端 watcher 回归，否则源码变化保护会中止批次；保留该原始中断记录并串行复验。

## 超时观测

复用UsageStore与原PiObserver，记录模型准入请求、响应头、首个流事件、首次/最后正文与推理、最后流事件、片段与字符计数。每秒至多刷新一次，结束时结算；即使关闭完整请求录制仍可采集计数，不保存正文、推理文本或认证字段，不用字符估token。

七个隔离用例实际经过Pi进程桥和HTTP/SSE适配器，注入：响应头前等待、响应头后无事件、持续推理无正文、正文未结束、流中长间隔、空事件流、工具参数未结束。模型发送前的进程桥/准入超时另由测量标记识别，不能冒充服务商已执行请求。故障注入只可使用模拟模式，真实提交在费用发生前拒绝。

流间隔只在首个流事件后的时间窗内计算，不能让SDK启动时间稀释停滞比例。首轮六例注入中，停滞一例因此误分；原失败日志保留，修正后重新建立批次。分类表示可定位阶段，不能仅据此断言DNS、网关、断网或模型根因。旧记录没有测量字段则明确未知。

本次逐帧计数接在Pi实际传输边界；尚未提供`stream_progress`的Atlas兼容路径及旧记录只能显示缺少阶段证据，不能据此宣称所有SDK已具备相同定位能力。通用调用迁移继续归#293，统一图仍保留原任务与调用来源。

原任务排队、上下文准备、模型、工具与收尾复用performance.task_snapshot/task_timing和原预算停止原因；组件操作不伪造TaskManager状态。模型调用超时、整链预算到期、评测样本期限和业务验收各有独立来源。

## GLM审阅的受控对照

此前两次GLM-5.3超时均收到HTTP200和持续推理，没有正文。官方模型卡说明省略`reasoning_effort`默认max，支持low/high/max：[GLM-5.3官方模型说明](https://huggingface.co/zai-org/GLM-5.3/blob/main/README.md?code=true)。这提供排查线索，不单独证明原超时根因。

评测冻结`review_effort`：默认provider_default保留原服务商设置；显式选择实验auto时只对GLM-5.3审阅设置low，其它模型保留原行为，也可显式选择实验low。只影响独立审阅，不修改用户模型配置或普通任务采样。原题、参考、候选、评分规则、样本与60秒审阅上限不变；模型和代码配置冻结；不延长时限、自动重试或改标签。

固定5例做原设置/候选对照，4例保留集只在候选冻结后运行。有限真实验证计划最多14次调用，保留所有失败及未知用量；未知费用不当0，不将小样本结果当总体准确率或p95。实际结果另存独立报告，旧21次调用记录持续保留。

真实14次实验已完成：基线4/5、1次超时；轻推理候选4/5、0次超时；独立保留4/4。基线的未知证据样本收到HTTP响应头后持续推理13826字符、正文0字符，最后流活动距结束约0.2秒；不是已证实的断流。候选修复该例，但把基线通过的等价概念表达误归为需外部证据，导致该例待核验。闭环门槛因“候选必需条件不全、存在退化”明确拒绝推广，即使超时从1降到0且保留集通过，也不改成成功。因此最终默认保留provider_default，实验策略由用户显式选择；不削弱审阅规则，不增加真实调用去筛选一个更好成绩。

这14次原始实验冻结在源码内容标识`bc44d5e57bd7747099451ad272cea96b6b16fb92355ff888bc26283b9eb2be57`。随后仅收回实验策略的默认启用并补充回归，原实验批次及判定合同不重写；最终默认配置的验收另建批次。

逐案结果、阶段计数、固定规则标识、原始中断批次与最终复验分别保存在[结构化报告](evals/timeout-loop-316-20261119.json)，不能合并为一个“总通过率”。14次实验的可执行源码已按上述内容标识核对并另行归档，未包含模型凭据或依赖目录。

本地完整回归1580项为0失败、0错误、13项条件跳过；收回默认启用后另跑完整评测子系统、前端及固定黄金集。日志保留了临时数据测试期间后台线程的BrokenPipe、SQLite不可用及pipe.close Errno22警告；疑似测试清理竞态，触发用例尚未隔离，不能把它归为远端模型超时。unittest未将该线程警告计入错误，不把“零失败”表述为“日志无异常”。12项实机沙箱与1项系统不允许创建符号链接的测试未在本地验证；源码浏览器验证不替代安装包实机验收。

## 闭环门槛与AI入口

1. 查询coverage选择固定集合；diagnose按原调用和任务阶段取证。
2. 冻结基线后修改候选参数，保留相同评分合同与预算；compare逐案展示改善和退化。
   自定义业务样本采用独立rubric评分时，审阅推理策略属于评分合同，换策略不能仍作为同标准改善比较；审阅器校准样本的固定预期标签不变，审阅策略才是被测候选参数。
3. gate要求全部候选必需检查通过、基线与候选模型证据完整、基线有真实超时、候选无超时且无退化。
4. 同模型/审阅策略/工具加载/审阅预算/代码/模式/时限的独立保留集必须通过；保留集和调优集不得重叠。缺证据或无保留集不通过，不重写历史。
5. 门槛只对固定样本负责，不自动发布，也不将模拟闭环当真实模型质量提升。

正常完整token认证的agent_evaluation RPC和既有CLI提供coverage、diagnose、gate，原trace/debug_call/compare继续使用。设置页可选择冒烟/超时/审阅/保留集合，查看覆盖缺口、超时与原任务耗时，选择原始对照与候选策略，并核对独立保留集。真实模式选择已配置模型并明确授权本批费用；故障注入禁用真实模式，未配置密钥的模型不可选择。

```powershell
uv run --locked python scripts/agent_inspect.py evaluation coverage
uv run --locked python scripts/agent_inspect.py evaluation diagnose --payload-file E:/temporary/batch.json
uv run --locked python scripts/agent_inspect.py evaluation gate --payload-file E:/temporary/gate.json
```

batch.json为`{"ident":"原批次编号"}`；gate.json为`{"baseline":"基线编号","candidate":"候选编号","holdout":"独立保留批次编号"}`。源码、固定运行时、认证和隔离环境说明见[统一执行与评测](EXECUTION_VISUALIZATION_315_316.md)。

## 全目录模拟复验

在已安装固定Node/Pi/Promptfoo的仓库根目录执行以下命令。输出目录必须全新；不会读取用户模型或调用真实服务。超时专项、三批业务回归、保留集分别冻结，逐批保留原结果；运行期间保持源码不变，不并行运行前端watcher测试。每个单样本上限120秒，驱动另有批次总等待上限；取消未完成会明确报出批次，不冒充通过。

```powershell
$env:TEBB_EVAL_OUTPUT = 'E:/temporary/agent-eval-new'
@'
import json, os, time, uuid
from pathlib import Path
from desk_companion.evaluation.evaluation_center import EvaluationCenter
from desk_companion.evaluation.golden_store import GoldenStore

output = Path(os.environ['TEBB_EVAL_OUTPUT']).resolve()
output.mkdir(parents=True)  # Existing evidence is never overwritten.
os.environ['DESK_COMPANION_DATA_DIR'] = str(output)
center = EvaluationCenter(GoldenStore(output/'memory/evaluation.sqlite3'))
catalog = center.store.cases()
faults = [c for c in catalog if c['spec'].get('executor') == 'timeout_probe']
business = [c for c in catalog if c['split'] == 'regression' and c not in faults]
held = [c for c in catalog if c['split'] == 'holdout']
groups = [faults, *[business[i:i+20] for i in range(0,len(business),20)], held]
assert sum(map(len,groups)) == 65
results = []
try:
    for cases in groups:
        batch = center.start('all-fixture-'+uuid.uuid4().hex,
            [c['version'] for c in cases], mode='fixture', timeout=120)['batch']
        deadline = time.monotonic() + len(cases)*250 + 60
        while True:
            original = center.get(batch['id'])['batch']
            if original['state'] not in {'queued','running','cancelling'}: break
            if time.monotonic() >= deadline: raise TimeoutError(batch['id'])
            time.sleep(1)
        results.append(original)
        (output/'batches.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),'utf-8')
        print(batch['id'], original['state'], original['metrics']['success'])
        if original['state'] != 'completed': raise RuntimeError('Original partial evidence retained.')
finally:
    stopped = center.shutdown()
    (output/'shutdown.json').write_text(json.dumps(stopped),'utf-8')
    if not stopped['complete']: raise RuntimeError(stopped)
assert all(r['outcome'] == 'success' for b in results for r in b['results'])
'@ | uv run --locked python -
```
