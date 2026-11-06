# 桌宠过程气泡（#153）

单击宠物上方的后台执行过程气泡，调用既有 PetFeedback.dismiss，关闭当前根任务整条链的提示；后续子任务和轮询不立即重弹。后台任务继续，新的独立任务仍可提示。选中文字用于复制时不触发关闭。普通动作气泡、错误恢复提示和浮动聊天窗保持原有行为。

AI 验证优先复用 `client/tests/pet-chat.test.cjs` 的根任务屏蔽回归。真实浏览器开发页 `/` 的 `window.__petDebug.feedback(progress,runs)` 可注入隔离展示快照：先传空列表，再传新 running 根任务，单击 `#bubble`，随后注入同根子任务应继续隐藏，另一新根应显示。该入口仅开发模式存在，不派发任务、不取消任务、不连接生产 RPC。

2026-10-28：真实 Edge 已验证上述点击、同根屏蔽与下一独立任务显示。历史日程及桌宠批次前端完整172项、类型和生产构建通过。验收材料见 `E:/Learn_Project/output/search-orchestration-2026-10-28/pet-ui.log`。


## 内置表情与测试同步（#288）

2026-11-06 修复此前 UI 验收中保留的桌宠测试失败。原因为测试 DOM 没有 dataset/querySelector/toggleAttribute，且仍检查旧 data-reacting；现按当前七种表情的 data-mood 协议验证。此前未提交的 builtin-pet.ts 表情实现与测试一起落地，修复过程未更改其实现内容或行为。

`pet-settings.test.cjs` 的最小 DOM 替身支持 data-* 与 dataset 对应、眼睛节点更新、动态边界和节点移除；可控时钟覆盖：

- 初始 Idle；active(true) 进入 Busy，active(false) 恢复 Idle；工作状态不覆盖显式 Talk 表情。
- Done 900ms、Tap 700ms、Fail 2600ms 到期恢复 Idle；Talk/Wish 持续呈现，不设自动恢复。
- 重复 Tap 重置期限，切换 Busy 取消上一表情计时，未知动作按现有约定使用 Tap。
- destroy 清理定时器和 DOM，恢复 canvas 可见性；推进时钟不再修改已移除的桌宠。每项测试后恢复全局 document 与计时 API。

在 client/ 运行：

```powershell
node --test tests/pet-settings.test.cjs
pnpm test
pnpm exec tsc --noEmit
pnpm build
```

本轮桌宠专项5/5、当前工作区完整前端回归298/298通过，未使用HEAD桌宠源码替换。类型检查、构建通过，保留既有大于500kB chunk提示。

另在独立 Chromium headless 1228 中加载当前源码，使用真实 DOM/SVG 验证初始化、Busy切换、Tap自动恢复、48×48边界、眼睛节点及销毁清理，页面异常为0；不使用 Core、WebGL 或后端。原生 Tauri 窗口和具体动效的视觉品质未做实机验收，不将这些检查称为已验证。没有发布版本。

原始完整回归、构建和真实DOM记录保存在 `E:/Learn_Project/output/pet-mood-test-fix/`。UI首批与第二批报告中的失败是修复前的历史结果；当前状态以本节为准。
