# 集中能力优化与真实模型验证（2026-11-05）

本轮落实恢复路由、引用审阅、日程提案阶段验收和内容覆盖基础修复，并根据首批真实失败追加预算控制消息修复。最终冻结代码的8个真实模型样本全部成功；样本量小，只证明这些固定场景，不估算总体任务成功率。机器可读成绩见[脱敏结果](evals/hardening-20261105-results.json)。

## 行为变化与职责

- #258：显式恢复执行时，路由负责判断是否可以开工；最终业务答案交给原根任务执行，不再因“简单计算可直接答”与强制开工提示冲突。普通聊天路由保留。
- #259：交付审阅接收原始候选及独立的引用编译结果，避免将内部引用编译后的展示编号误判成伪造来源。来源片段按当前snapshot_id和SHA筛选，不能拼入同URL旧版本；错误事实、虚构引用和摘要冒充正文仍拒绝。
- #260：日程领域校验真实提案回执、任务归属、稳定提案编号及未更改状态；明确当前交付是“待用户确认的提案”。生成提案不能声称已保存、同步或实际操作GUI；用户明确要求界面验证时仍需该层证据。
- #271（#269首批）：沿用原来源存储，派生累计读取区间、首个缺口和下一步；附件提供有效分页区间，越界读取拒绝；文件搜索声明扫描、跳过和结果限制，未命中不能扩大为全文不存在。研究工具和阶段交接保留覆盖信息，模型可看到有限补读建议及剩余额度，不自动扩预算。
- #274：预算与收尾控制由system角色传入，来源目录仍作为资料。首批失败显示模型把追加的预算user消息当成了用户问题；修复保留真实用户目标和补充，避免控制消息争抢最新请求。消息继续使用可序列化字典，兼容Atlas记录链。

没有另建来源库、Agent入口或预算系统，也未修改Atlas正式依赖。修复分别落在原领域、交付审阅、上下文和资料提供模块。已检查受影响调用链与差异，未保留临时调试分支。

## 真实模型成绩：按源码分组保留

均使用mimo-v2.6-flash、direct路由、每样本1次尝试、传输重试0、单案300秒及审阅预留60秒。各批事先固定案例/样本计划，运行期间捕获的64份源码SHA均未变；临时凭据和网络策略已删除，观测到的worker均退出，调用证据完整。

| 批次 | 冻结源码 | 样本 | 成功/失败/超时/假成功 | 模型调用 | 输入/输出tokens |
| --- | --- | ---: | --- | ---: | --- |
| 首批五场景各3次 | f773c2f | 15 | 14 / 1 / 0 / 0 | 103 | 617482 / 29275 |
| 最终五场景各1次 | 6da187d | 5 | 5 / 0 / 0 / 0 | 33 | 197203 / 8749 |
| 最终日程追加预定2次 | 6da187d | 2 | 2 / 0 / 0 / 0 | 6 | 12782 / 1287 |
| 最终普通公开网页引用 | 6da187d | 1 | 1 / 0 / 0 / 0 | 3 | 9255 / 405 |

最终同源码合计8成功、42次真实模型调用、18阶段任务，输入219240/输出10441 tokens，usage完整、费用未知。没有待补充、跳过或未完成。三个最终批次分别预定并独立保存，不将跨版本成绩混成一个成功率。

交付前合入同期main的0afbcf0（画像界面、资源及设计归档），64份捕获运行源码的SHA与上述最终冻结版本逐一相同。因共用前端测试加载器有变化，日程提案和本地日历15项组件回归再次通过，日志为`hardening-calendar-components-after-rebase.log`；没有新增模型采样，原报告源码提交号不改写。

| 最终场景 | 样本结果 | 实际验收 |
| --- | --- | --- |
| calendar_proposal | 3/3 | 真实只读提案、字段与任务归属、确认前无业务写入 |
| clarify_resume_root | 1/1 | 追问后沿原根任务实际执行并完成 |
| readonly_legacy_parallel | 1/1 | 真实模型、子任务与证据、根交付；冻结实际RFC正文 |
| readonly_atlas_parallel | 1/1 | Atlas路径相同职责链与独立验真；冻结实际RFC正文 |
| attachment_tail | 1/1 | 两份合成附件，目标在未直接注入的第二附件后页；实际工具正文、来源哈希和有效区间须覆盖目标 |
| research_public_source | 1/1 | 实际联网读取RFC2606正文，事实与最终Markdown引用核对 |

首批唯一失败是calendar_proposal样本2：返回预算说明而非提案，审阅拒绝了这些不受用户目标支持的数字。其余14条成功；原始失败完整保留，推动#274后另立最终批次，未覆盖原成绩。最终日程3/3不能替代真实桌面操作验收。

本地原始报告位于仓库旁的`output/`，不上传原始调用/对话/配置：

- `hardening-live-20261105-v1/report.json`及`hardening-live-plan-20261105-v1.json`。
- `hardening-final5-live-20261105-v1/report.json`、`hardening-final-calendar-live-20261105-v1/report.json`及共同计划`hardening-final-plan-20261105-v1.json`。
- `hardening-public-source-live-20261105-v1/report.json`及`hardening-web-plan-20261105-v1.json`。
- 每批同目录`source-validation.json`记录源码与退出/清理核对；首批另留`stream-analysis.json`。全部成功与失败、usage未知值均保留。

## 确定性回归

以下是分阶段受影响回归，集合有重叠，不能相加为独立测试数量。源码改动前建立了引用阶段、恢复路由、提案、覆盖缺口、版本混用、控制消息和附件越界的失败信号；具体日志留在仓库旁`output/hardening-*.log`。

| 回归 | 结果 | 日志名 |
| --- | --- | --- |
| 初始受影响完整回归 | 358项，0失败，1项因OS不支持创建符号链接跳过；出现临时worker清理的BrokenPipe/已删除SQLite告警 | hardening-affected-full-v1.log |
| 引用版本等最终聚焦回归 | 98通过 | hardening-final-focused-v1.log |
| 控制消息/上下文/Atlas记录链 | 145通过 | hardening-274-affected-full.log |
| 附件区间与独立证据验真 | 30通过 | hardening-local-range-regression.log |
| API、记忆及清理回归 | 85通过；日志含异步慢任务提示 | hardening-final-api-memory-regression.log |
| 实际日程产品组件、受控RPC | 15通过；不是实际桌面GUI | hardening-calendar-components.log |

统一fixture：原固定失败集24/24、最终五场景5/5、两附件后页1/1通过。真实与fixture成绩分别保存。正确JSON但未读目标、伪造正文/哈希、跨任务或篡改提案等反例仍拒绝。

## 复跑入口

在仓库根目录准备已安装的Python运行时、正式Atlas固定依赖及技能；真实模式需已配置可用模型，研究并行需既有冻结RFC来源语料。入口自行创建隔离profile；不要重放历史外部业务操作。输出目录每轮用新名字，先声明计划，不重试到通过。

```powershell
# 默认fixture，无真实模型调用
python scripts/eval_agent.py --suite failures --samples 1 --timeout 300 --output ../output/new-failure-fixture
python scripts/eval_agent.py --case attachment_tail --samples 1 --timeout 300 --output ../output/new-tail-fixture

# 最终五场景真实模型，统一案例原输入/验真；先确认模型配置及语料目录
python scripts/eval_agent.py --live --case calendar_proposal --case clarify_resume_root --case readonly_legacy_parallel --case readonly_atlas_parallel --case attachment_tail --samples 1 --timeout 300 --research-corpus ../output/research-171-corpus-real --output ../output/new-final5-live
# 相同冻结源码，另行预定日程2次
python scripts/eval_agent.py --live --case calendar_proposal --samples 2 --timeout 300 --output ../output/new-calendar-live
# 普通网页为实际HTTP，不传冻结语料
python scripts/eval_agent.py --live --case research_public_source --samples 1 --timeout 300 --output ../output/new-public-source-live
```

## 覆盖边界与后续

原固定24案和v27的20成功/4失败历史保持独立；本轮没有重跑整套真实24案。全业务164条加内容覆盖10条共174条仍是设计目录；当前统一质量执行器48题，契约28，不代表174条已自动化或实测。COV-06已接入并真实验收：首批3/3，最终同源码1/1；其余9条专项没有本轮独立的真实执行器成绩。

#269继续开放：首批元数据、模型提示及诊断基础已实现，完整来源UI、动态JS/登录页面读取和其余覆盖专项接入仍待完成。静态抽取正文的complete不表示完整界面；网页补读也不等于修复SSE异常终止。此次没有官方沙箱、真实外部业务写入、实际桌面GUI或发布包验收，没有正式发布。
