# 会前提醒与飞书待办完成（#9）

应用运行期间默认提前 10 分钟提醒本地和已连接的飞书主日历定时安排。在「设置 → 模型与人设 → 会前提醒」单独开关；旧随机 nudge 和任务进度开关不控制这一功能。主窗口用非模态提示，桌宠用可点击气泡；自动提醒不显示隐藏窗口、不抢焦点、不取消 Agent，也不申请系统通知或声音权限。

## 来源与投递

提醒复用 SchedulingService 的合并日程投影和已知本地／远端映射，不按标题猜测重复。稳定日程身份加标准化开始时间确定一次提醒；改期为新开始时间，标题修改不重复。全天、取消、已过开始时间、类型异常及未核实的远端缓存不投递。本地未同步日程不因远端失败而失效。启动位于提醒窗口可补一次，睡眠后不刷已经过去的安排。

后台扫描每 5 秒独立于自动化和模型队列运行。远端正常读取间隔和有效性均为 5 分钟，失败后 30 秒重查；跨周午夜检查两个周视图。后台 CalendarAdapter 使用 5 秒单命令上限，退出设置停止标记，不再发起后续读取；不假装取消正在执行的 Python 线程。

新投递还要求最近30秒内成功完成扫描；重新启用先清候选并等待扫描，睡眠恢复先核对新状态。同一窗口正在显示的记录可在扫描期间保留，不把过期扫描当作新投递依据。

`memory/calendar-reminders.json` 由 CalendarReminderService 拥有，通过 ResourceLock 和原子写保存设置、扫描阶段／错误／跳过原因、别名、候选、投递及确认记录。合并已知身份保留历史和已有确认。可见窗口先登记投递再返回；同一活跃窗口响应丢失时，以原 consumer_id 只读核对已有投递。每次窗口实例使用新编号，所以重启和其他窗口不重复领取。投递不等于用户已读：渲染前异常关闭可能留下未确认记录，可在设置中核对，不能当作用户确认。

## 明确完成飞书待办

「日程 → 更多 → 飞书待办」的「完成待办」只读核对当前可见 GUID 对应的服务端任务，并在读取前后核实当前用户、应用和品牌。确认框展示服务端标题与账号；只有「确认完成」才调用原生 `task +complete --task-id <GUID> --as user`。核对两分钟有效，列表已变化、跨日或身份无法核实则不开始写入。取消确认不完成或删除任务，不推进本地事项。

FeishuTaskCompletionService 在 `memory/feishu-task-completions.json` 拥有独立持久回执：request_id、GUID、账号事实、可见快照、stage/state、执行结果、观察结果及缓存结果。先保存 calling 再调用 CLI；只有 `status=done`、非零 `completed_at` 和布尔 `already_completed` 完整时确认。`already_completed=true` 表示官方 shortcut 已跳过 PATCH，不额外例行 GET。

超时、断连、字段缺失及中断保留 unconfirmed。相同编号、同一未决 GUID 不自动再次完成。恢复后「核对原结果」仅调用原生 `task tasks get --params '{"task_guid":"<GUID>"}' --as user`：查询到完成记为 observed_done，原 execution_result 仍未知；仍开放也不自动重放。换号停止原操作的核对与提交，恢复原账号后再核对。身份校验覆盖调用前后；若外部 CLI 在调用期间切换身份，结果记为未知，不能声称原子绑定了账号。

远端确认与本地缓存 CAS 分开。仅移除原可见快照的目标 GUID，保留其他任务和日程；缓存变化／保存失败时明确提示刷新，不再完成一次。已确认任务被重新打开，必须经过新的可见快照、只读核实和新的明确确认。

## 认证 RPC 与 AI 调试

所有方法沿现有本地认证 WebSocket 白名单。检查外层派发与内层业务 `ok`；这些方法不等待模型宿主 turn_lock，不提供任意命令或可由客户端更改的时钟。

| 方法 | args | 结果要点 |
| --- | --- | --- |
| calendar_reminder_status | `{}` | enabled、lead_minutes、scan、候选、最近 100 条投递／确认与 merged_into |
| calendar_reminder_scan | `{}` | 主动扫描真实配置来源；不写日程，不调用模型 |
| calendar_reminder_settings | `{"enabled":false}` | 独立设置与当前快照 |
| calendar_reminder_claim | `{"consumer_id":"<本次可见窗口编号>","known_ids":[]}` | 原子领取或核对本窗口投递，reminders、recovered_ids |
| calendar_reminder_ack | `{"consumer_id":"<同一编号>","ids":["<提醒ID>"]}` | 持久且幂等确认；仅本窗口已领取记录 |
| task_completion_prepare | `{"guid":"<可见GUID>","request_id":"<新稳定编号>"}` | 只读 prepared 预览、身份与 expires_at；可能返回原未决编号 |
| task_completion_confirm | `{"request_id":"<预览原编号>"}` | 仅明确确认后调用；state、stage、execution_result、remote_state、cache_state |
| task_completion_status | `{"request_id":"<原编号>"}` 或 `{}` | 原回执或最近 100 条；恢复孤立 calling 为未知，不重放 |
| task_completion_inspect | `{"request_id":"<原编号>"}` | 只读核对；observed_done 不冒充原写入已确认 |

示例帧：`{"type":"rpc","id":"reminder-read-1","method":"calendar_reminder_status","args":{}}`。调用真实 confirm 需要用户对该任务的明确意图；自动验收应注入假身份、CLI 和临时数据。

```powershell
# 固定 Atlas 环境中，服务/假时钟/身份/CLI 与真实本地投影
python -m unittest discover -s tests -p 'test_calendar_reminders.py' -v
python -m unittest discover -s tests -p 'test_feishu_identity.py' -v
python -m unittest discover -s tests -p 'test_feishu_task_completion.py' -v
python -m unittest tests.test_local_api.LocalApiTests.test_reminder_and_completion_rpc_keep_authentication_and_bypass_model_turn_lock -v

# client/：实际 React 按钮和共享通知控制器
node --test tests/reminders.test.cjs tests/task-completion.test.cjs
```

确定性的提醒和完成动作按真实状态验收，不需要付费模型替代；测试不得向真实飞书写入、发消息或重放历史操作。真实 Windows 桌宠表面与真实飞书账号写入应和隔离服务／组件验证分别报告。
