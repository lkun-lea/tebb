# v27四项失败调查与优化方案（#258–#260）

本报告只读分析 `output/failure-v3-live-20261104-v1` 的原始请求、SSE、持久任务和当前代码。真实运行源码为 `d10cf755`，61个执行文件整轮哈希一致；设计基线 `33129bb` 另含结果文档和#261的流程事件投影/视图变更，核对后不改变本文定位的路由门槛、引用编译与提案审阅调用链。没有重放任务、调用新模型或实施以下方案。

可上传的最小合成证据在 [failure-investigation-v27.json](evals/failure-investigation-v27.json)：只含合成案例ID、调用ID、阶段/结束信息、审阅结论与少量结构事实；不含Key、完整请求、私人对话或个人目录。完整私有profile继续仅保留本地。

## 结论和边界

| 失败项 | 本次直接原因 | 确认程度 | 推荐优先级 |
| --- | --- | --- | --- |
| clarify_resume_root | 显式执行恢复仍要求真实开工申请，路由两次只返回正确计算JSON | 入口、持久request、两次响应均可核对 | P0，#258 |
| readonly_legacy_parallel | 审阅拿到渲染后链接，却用原始引用编号提交规则拒绝正确候选 | 候选阶段、规则检查和审阅结论直接可核对 | P0，与Atlas共修#259 |
| readonly_atlas_parallel | 与legacy相同的审阅阶段冲突；模型还混淆了审阅excerpt编号与业务source_id | 同上，两个runtime均实际执行 | P0，与legacy共修#259 |
| calendar_proposal | 真实提案已生成；审阅将本阶段交付扩成必须取得实际GUI打开/调整观察 | 原始提案/两次审阅可核对，GUI本轮未执行 | P0，#260 |

四题共30次模型调用；其中8次审阅都有正常 `finish_reason=tool_calls` 和usage帧，审阅推理字符为0。不能再把这些拒绝归为缺少流终止信号、余额不足或审阅超时。Atlas并行的一个活动业务调用随整链收尾被中断，应与其上游引用拒绝分别记录，不能据此声称全部30次都正常完成。

## 1. 追问恢复：执行意图没有丢，阶段职责仍冲突

证据链：

- `agent_eval_lifecycle.execute` 通过 `service.submit_execution` 建立原题，不是普通聊天；`Collaboration.create_execution` 将 `require_execution=True` 持久化。
- 根任务确实进入needs_input，并在补充7、11后保持同根恢复；原始队列request继续包含 `require_execution=True`。
- 调用 `b6dbcf74cc92499ea1fb1964af9dbdc0` 和纠正后的 `33224bfa4a764f44af55d155b7b05f0d` 都返回 `{"total":18,"checked":true}`，无工具调用、正常stop。该结果数学正确，但处在route阶段，未产生实际task阶段。
- worker拒绝显式执行的普通正文结束。纠正提示又允许“计算示例可直接按用户格式回答”，与显式执行限定形成混合信号；用户的“补齐后只返回JSON”也和route的控制动作共处同一目标上下文。

因此不应将#258改为“放开所有正确JSON直接完成”。如果来自事项执行/自动化，任务申请是必须可观测的事实，不能依据答案碰巧正确就造出开工回执。普通auto聊天则不应被迫为7+11创建后台任务。现有原题从显式入口进入是合法压力场景，不通过改成auto入口来消掉失败。

**推荐方案**：恢复request明确携带由控制器拥有的 `intent=explicit_execution`、`resume_from=needs_input`、原问题及本轮补充；route指令只核对是否具备开工条件，最终JSON约束明确归task交付阶段。显式路由的纠正语不能继续提供“直接回答”分支；仍只允许实际 `start_background_task` 或必要的 `request_clarification`。保留原根、预算、权限和request_id，不重建执行。

`tool_choice=required` 可作为后续强化，但固定Atlas的 `ChatOptions` 当前没有该公开选项；若采用，应在Atlas通用模型契约中增加并验证，再更新固定提交与产品适配。不要绕开共享传输私自注入未验证参数，也不要把不支持该参数的供应商失败藏成重试。本轮建议先做阶段上下文与提示冲突修复，再以真实样本判断是否需要这一通用能力。

**验收**：B-READY-01/02成对比较相同7+11目标：auto聊天可直接答；显式执行须真实派发并在原根完成。再覆盖缺参继续追问、错误表单、重启恢复、口头“已执行”零工具仍拒绝。原 `clarify_resume_root` 保持不变，预定3个真实样本分别记录。

代码位置：[执行入口](../desk_companion/collaboration.py)、[生命周期评测](../desk_companion/agent_eval_lifecycle.py)、[route及纠正分支](../desk_companion/collaboration_worker.py)。具体定位：create_execution约441行、require_execution约459行，worker route定义约247行、正文门槛约716行；以当前提交为准。

## 2. 并行研究：原始提交与显示成品没有分清

两条链实际创建两名独立读者、执行区间重叠，并取得固定RFC8259/7159正文。编号8259/7159和年份2017/2014均获审阅支持；最终根未交付，不能因此说整题事实/汇总已经通过。

`delivery_feedback.assess` 先调用 `render_citations` 将原始 `[实际source_id]` 编译为 `[1](<实际URL>)`，worker随后把返回的text传给 `feedback_review.review`。审阅请求中已有 `candidate_stage=after_citation_resolution` 及 `citation_provenance=pass`；但当前叶子goal仍要求“citation提交时使用[完整实际证据id]”。原始候选没有作为独立审阅对象保留在这份payload中，模型被要求解释两个不同阶段的格式。

legacy的审阅 `f8f63fa3e15046b5960fdd90c5de8a03` 与再次审阅 `e3626c07de2646c5b64f3bda88935c5b` 明确支持编号/年份，却因链接缺内部id给contradicted。另一个读者审阅反而将 `[1]` 解释为符合要求，说明相同阶段规则判断不稳定。Atlas的 `b19244f73fc14e5b88cd34436c1ba5b9`、`de5f3e59242f49fc80f6dd1d5dd416dd` 及再次审阅 `eb9331ec52d54b3ca8def526385093c4` 同样误拒。

审阅有时举 `[E4.0.0]` 作为应填写的引用，这是第二层混淆：`E4.0.0` 是审阅excerpt编号，不是业务正文引用的source_id。不能按这个建议修改正确业务候选。仅追加“系统会渲染”说明在本轮已经存在且未奏效，不建议继续依赖更长提示词。

**推荐方案**：在产品当前候选流程保留两个对象：`submitted_candidate`（模型原始业务文本）与 `rendered_delivery`（系统显示成品），同时保留产品生成的引用解析映射。原始提交规则对前者检查，最终链接/归属规则对后者检查；事实审阅以原始业务断言及实际正文为依据，不从显示成品倒推模型是否提交过内部id。证据excerpt编号继续只用于审阅取证，不出现在业务citation中。

最小实施可在原调用方保留原text，沿用assess做解析和确定性检查，再将原候选/明确阶段传给同一个review模块；若review增加双候选字段，必须同步所有当前调用方（legacy、Atlas收尾、独立review入口、测试），不加旧协议回退。审阅保留自然语言事实目标，不能靠删掉用户要求、全局忽略task_acceptance或把contradicted自动改pass来放行。

**验收**：同一真实正确候选的原始/渲染阶段应得到一致事实结论；对象/数组/完整JSON围栏的键和值不因引用编译改变。伪source_id、未读URL、错误年份、snippet冒充body、跨run来源、代码示例中的编号都保留拒绝或不渲染边界。先用本轮保留数据零调用复核确定性部分，再对legacy与Atlas各3个真实样本同时测，保留原两项失败。

代码位置：[引用编译](../desk_companion/delivery_feedback.py)约20行、[共同审阅payload](../desk_companion/feedback_review.py)约111–119行、[worker收尾](../desk_companion/collaboration_worker.py)约724–756行。通用Atlas工具循环无需为本产品引用规则增加第二套实现。

## 3. 日程提案：缺少产品阶段验收，不是已经证实界面有错

真实 `calendar_propose` 成功返回合法proposal及稳定save_request_id，`change_state=not_changed`。第一候选只报告提案生成、实际字段和“点击打开日程草稿”的下一步，没有声称已保存或实际点击过界面。

第一次审阅 `a4d4711c6fdd43f0ba417b97e772d4c1` 支持字段和未保存事实，但将“可在界面打开和调整”作为必须有GUI观察的unverified项。候选随之重写、主动强调unknown；第二次审阅 `2ace53232beb4c2cbf810d5cea5148b8` 再次要求GUI观察。5次调用共106秒，重写正文不可能产生界面观察证据。

两份审阅payload的 `verified_checks=[]`、`candidate_stage=unspecified`。当前产品收尾只做通用输出/引用/回执检查，没有传入已存在的日程提案领域验证及本阶段职责；评测器末端的 `agent_eval_tools.verify` 才核对提案事件和零写入，并明确写 `ui_confirmation=not_exercised_by_model_case`。评测器知道的边界没有成为产品交付审阅的结构事实。

**推荐方案**：由 `calendar_proposals` 领域拥有提案交付检查，复用已有validate和任务事件归属校验，将“合法提案字段/来源task/稳定保存编号”和“生成前后无业务写入事实”作为当前阶段的确定性条件。生产执行器应使用可获得的真实服务观察，不能把评测器的before/after快照伪装为生产证据，也不能只凭read_only声明证明全局从未写入。审阅载荷显式列明交付阶段是“待用户确认的提案”，已保存/已同步/已在界面操作均不是该阶段已发生的事实。

另用真实产品组件连接隔离认证API验证“打开→修改→取消→重开→保存→再次打开”完整链，按同一原提案验证0→1条日程和关联，不另造提案绕过失败。若UI实际有错则保持该层失败，独立修复；模型题通过也不能替代这层。用户明确要求“请实际操作界面验证”时应产生待核验缺口，不能套用提案阶段规则删掉该真实要求。

**验收**：B-CAL-01/02/03/04和J-03覆盖真实表单、明确保存一次、consumed/unknown不重建、篡改来源拒绝。模型题检查字段/引用实际回执和保存前零写入；真实GUI检查按钮、可编辑性、取消与重开。禁用提案能力、自由正文假提案、归档事项、缺失保存回执全部保留反例。原题完整保留，改动题意时另立契约，不回填本轮分数。

代码位置：[提案领域](../desk_companion/calendar_proposals.py)、[通用交付检查](../desk_companion/delivery_feedback.py)、[评测独立验真](../desk_companion/agent_eval_tools.py)约172–180行，以及 `client/tests/calendar-proposal.test.cjs`。现有 [提案文档](CALENDAR_PROPOSALS.md)曾记录隔离真实UI验收，但不等于本轮运行了GUI，也不保证任意新代码版本已通过。

## 实施顺序和验证边界

2026-11-05新增跨场景问题：网页取材、文件检索和阶段交接的信息覆盖不足，历史证据、责任分层与有限补读方案见 [内容覆盖修复方案](CONTENT_COVERAGE_PLAN.md)，实际实施跟踪[#269](https://github.com/lkun-lea/tebb/issues/269)。该问题与引用阶段修复配套处理，不能用扩大模型输出上限代替取材/覆盖核对，也不能将静态正文当完整界面。新增10条专项设计独立于v27四项原成绩。

推荐先处理#259（两个runtime共用的阶段错配），再处理#260（提案阶段领域检查和真实GUI链），最后处理#258（恢复路由职责与显式开工）。三者可以分别提交、分别验收；共同原则是让产品拥有阶段和确定性规则，让模型只判断仍需语义核对的业务目标。

本报告原调查轮次完成的是调查和可实施设计。原定后续修复先建立正反例失败信号，再通过受影响层确定性回归、冻结源码并预定采样；任何原始失败、unknown和供应商故障均不得回写成通过。

2026-11-05实施进展：#258/#259/#260及#269首批内容覆盖基础已实现。首批五场景各3样本为14成功/1失败，预算控制消息误当用户问题的失败推动#274；最终源码另立预定批次，共8样本成功，其中日程3/3。原v27整套24案未重跑，原分数保持不变。代码职责、逐批结果、复跑命令和未覆盖边界见[集中优化验收记录](CAPABILITY_HARDENING_20261105.md)。#269的完整来源UI、动态页面及其他专项仍开放。
