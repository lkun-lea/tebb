# 确认资料与跨设备同步（#255）

用户已授权推荐方案并要求接管 Supabase 项目。同步范围为用户明确确认的画像、偏好、长期记忆；本机来源、聊天、项目文件和凭据不自动认领或上传。LangMem 提炼属于 #238 后续阶段。本批先提供可管理、可调试的确认内容同步闭环。

同一账号的记录、确认草稿、设备副本身份、离线操作与拉取游标由 PersonalizationStore 管理。记录与入队、整页与游标各在一个 SQLite 事务提交。当前进程所属账号固定，复制其他账号的数据库会被拒绝。设备 UUID 表示独立安装下的账号资料副本，不是硬件指纹或认证凭据。

同步不覆盖未同步意图。冲突保留云端观察值与本机意图，用户选择后才生成新操作；已发送且结果不明的请求先查询原回执，明确重试保持原编号。删除立即隐藏本机条目并清除该服务保存的正文，云端未确认仍显示待核对；未知创建之后的删除使用 v2 服务端围栏，墓碑阻止晚到创建和旧离线写入。删除不代表聊天、历史请求或云备份已全部清除。

AccountService 是会话和刷新唯一所有者。后台同步通过其公开云客户端作用域访问已有 PersonalizationCloud 接口；界面与调试 RPC 不获得令牌。记忆选择复用 memory_selection，新增个人资料来源与本机事实分开；实际任务继续冻结既有记忆清单，检查台展示采用/排除原因和实际请求。

2026-11-04 已创建独立 tebb 组织及新加坡区 tebb-personalization 项目，部署 PostgreSQL 17.11 迁移并回读迁移记录、三表强制 RLS、Data API 仅 public、六位/600 秒验证码和关闭自动注册的配置。首次数据库端口连接失败，本次使用官方 CLI 的 HTTPS 管理查询原子执行迁移和登记迁移历史；随后 CLI migration list 也核对本机/云端版本一致，没有放宽网络限制。真实 GoTrue/PostgREST 验收的两个合成账号与三个独立资料副本通过隔离、离线冲突、明确解决和删除同步；本批不等于两台实体设备或真实模型效果已验收。公开接入信息已写入当前开发客户端加密账号配置，服务端密钥与测试会话未进入客户端或仓库。用户明确暂无 SMTP，邮件模板和普通用户验证码送达仍待配置。

## 使用与调试

进入「设置 → 个人资料」。账号空间可新增画像、偏好和长期记忆，按所有对话、现有项目或伙伴限定范围。登录账号启动后复用现有后台调度器，每 60 秒检查同步；本机空间、需要重新登录和待切换账号不自动联网。点击「确认并同步」先原子保存本机意图，再开始有界后台同步；停用、删除、冲突均停止后续选择。同步单轮最多 25 个操作、5 页变化，更多内容显示暂停并可点击「立即同步」继续。「取消并暂停自动同步」停留在原账号，点击「立即同步」或明确保存新资料后恢复。退出/重启发出取消并等待当前有超时的网络请求收尾。

冲突卡片保留本机正文和已观察云端版本。先同步取得云端版本，再采用云端或明确更正本机内容。删除冲突仅可确认删除已观察的云端当前版本，原正文保持隐藏。断连后先点击同步查询原回执；云端未查到原编号时才出现「重试原编号」，正文/版本/操作编号保持原样。删除不会重放被清除的正文。

复用本机认证 `/ws` RPC，不开放给浏览器协作预览；接口不等待模型回合，也不返回账号令牌。

```json
{"method":"personalization_status","args":{"request_id":"可选原操作UUID","job_id":"可选同步UUID","include_scopes":true}}
```

返回账号绑定、设备副本、记录本机/云版本、同步状态、原修改回执、任务阶段/错误/处理数、游标与已观察云端序号。`include_scopes` 显式读取项目/伙伴目录；普通轮询不初始化协作调度。

```json
{"method":"personalization_action","args":{"payload":{"type":"save","request_id":"新UUID","confirmed":true,"payload":{"kind":"preference","category":"communication","text":"请先给结论再解释依据","scope":"user","scope_id":""}}}}
```

修改已有记录附上 `id` 和最新本机 `version`。类型为 `save/disable/delete/resolve_local/resolve_remote/retry`；save/resolve_local 需要完整 payload。原编号相同请求返回原保存回执，不重复修改；同编号不同请求拒绝。`sync` 仅需新 request_id，`cancel` 必须携带原 job_id，只取消该任务；取消回执不明时按原任务的 cancel_requested/终态核对，迟到取消不影响新任务。同步作业有 queued/running/complete/paused/needs_confirmation/failed/cancelled/interrupted，phase 指明 identity/publish/reconcile/pull/done。CLI/验收可调用 `PersonalizationService.wait(timeout=25)` 有界等待。

记忆检查台的同步来源显示账号和云版本，跳转「个人资料」由唯一存储所有者管理；本机事实编辑/清理接口拒绝同步 ID。现有下次预览、任务冻结和实际请求记录复用统一选择器。内容与元数据在模型发送前冻结，后续修改不改写旧请求；删除是逻辑移除当前资料正文，不承诺 SQLite 已释放页、历史调用、摘要或云备份的取证级擦除。

## 隔离验证

```powershell
python -m unittest tests.test_personalization tests.test_accounts tests.test_personalization_cloud tests.test_memory_inspector -v
npm ci --prefix supabase/tests/runner --ignore-scripts --no-audit --no-fund
npm test --prefix supabase/tests/runner
# client/ 中
pnpm test
pnpm exec tsc --noEmit
pnpm build
```

SQL 套件实际执行 PostgreSQL/PGlite 迁移/RLS，并用合成 HTTP 身份运行产品的 A/A2/B 三个 SQLite 副本，验证离线更新、冲突解决、删除和跨用户隔离；不等于 GoTrue、托管数据库或两台实体设备已验收。本次真实验收记录为 2026-11-04：GoTrue 身份核实、同账号副本读取/异账号隔离、版本冲突与回执查询、删除防复活、产品副本离线冲突解决与删除五组均通过；合成记录最终保留无正文墓碑。补充实测同时提交两次相同版本写入仅一次 applied、一次 conflict；真实 SDK 刷新与单设备退出确认，另一设备仍可读取。

独立真实验收沿用 `scripts/eval_personalization_cloud.py --live --report <新路径>`，前置与环境配置见 [部署说明](../supabase/README.md)。只使用专用测试项目和合成正文，不发送邮件、不调用真实模型。
