# tebb 今日看板

宽屏工作台左侧保留主聊，右侧显示看板；窄窗使用单栏。工作台侧栏的「今日」和原个人资料设置入口使用同一组件。点「个人资料」仍可补充、更正、停用已有记录。「等你决定」读取 Windows 原任务的待答投影，与 Android 待答入口共用会话、运行和问题版本。点桌面卡片回到原会话。手机离线时沿用待答草稿规则。

「定制看板」可以选一个本地项目。时间线按有时间记录的原任务开始和结束排序，点击进入来源会话。早报、晚报可分别关闭，或选择每天、工作日与周末。每份简报可以设置生成时间、内容范围和可选关注词。多个词用空格分开，命中任一词即保留。项目简报取最近 24 小时的事件，待答简报取生成时仍需处理的问题。没有来源时显示空状态。

首次打开后，已启动的 Windows 协作服务按本机时区检查到期简报，查看看板也会补齐当天已到时间的简报。每个账号工作区按日期、早晚时段保存一次。已生成简报保留当时的记录，下一份使用新偏好。PC 关闭时手机可查看此前缓存。Windows 重新上线后按当天情况更新。首版在看板内交付简报。

Windows 的认证 RPC `today_board` 提供当前待答、项目、时间线、简报与偏好。传入带原版本的 `preferences` 可更新设置；过期版本被拒绝。已配对手机只收到显式共享会话对应的简报和时间线行，沿用原设备密文快照及本机缓存。手机上的「今日看板」条目可以定位共享原文。

## 复验待答卡

对应 [#331](https://github.com/lkun-lea/tebb/issues/331)、[#332](https://github.com/lkun-lea/tebb/issues/332)、[#333](https://github.com/lkun-lea/tebb/issues/333)、[#334](https://github.com/lkun-lea/tebb/issues/334)。

使用 Windows 与同账号登录的独立 MuMu 测试包。任务和模型使用隔离夹具，配对、HTTPS、ECS 加密中转、答复与回执使用产品协议。首次配对使用 MuMu 可达的 Windows 地址，随后经 ECS 回复。用新的输出目录及临时二维码文件运行：

```powershell
uv run --locked python scripts/check_today_mumu.py --live --address <Windows地址> --qr "$env:TEMP/tebb-qr.png" --observation <新验收目录>
```

在 MuMu 从图片读取本次二维码，在脚本中核对并输入手机显示的配对确认码。「今日验收：评审需要多少分钟？」出现后，从原任务回复 `45min`。手机应显示「Windows 已接收」，问题卡消失。打开「已共享方案」中的原会话可见一次对应答复。脚本同时核对 Windows 原任务、原文和待答投影，并清理本机临时配对。验收后从测试包移除本次配对，删除传入模拟器的临时二维码。

要同时核对桌面组件，先启动 `pnpm --dir client exec vite --host 127.0.0.1 --port 14793`，在发送前运行下面的浏览器检查。它从同次运行的隔离观察文件提供 RPC 响应，使用产品 React 组件轮询并截图。浏览器启动与替身 RPC 独立于真实手机中转。可用 `UI_PLAYWRIGHT_CORE_PATH` 和 `UI_CHROMIUM_PATH` 指定浏览器依赖。浏览器输出「Windows 已显示原问题」后再从 MuMu 发送。

```powershell
node client/tests/today-mumu.browser.cjs <同一验收目录的绝对路径>
uv run --locked python -m unittest tests.test_today_board tests.test_mobile_status_relay_demo tests.test_local_api.LocalApiTests.test_today_board_preferences_use_authenticated_desktop_rpc
```

Android 原生仪器测试 `PersonalAgentAcceptance` 另用合成快照核对看板、早报、定位原会话和引用草稿；构建与运行方法见 [移动端验收](MOBILE_AGENT_ROADMAP.md)。
