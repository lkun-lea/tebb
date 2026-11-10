# 设置窗口

关联 #296。设置从主窗口的一个 pane 迁移为独立 Tauri 窗口（`settings.html`），外壳为左侧分组导航 + 右侧内容区；业务表单沿用原有组件，只做外壳与分组整理。

## 结构

- 入口 `client/settings.html` → `settings-main.tsx`（AccountBootstrap → SettingsApp）。Vite 多页入口见 `client/vite.config.ts`。
- 外壳 `settings-app.tsx`：左侧搜索框（按分类名称与关键词过滤导航）+ 三个大分组（通用 / 连接与数据 / 账号与关于），共 7 个分类；右侧为分类标题与内容卡片。样式在 `settings-window.css`，语义 token 与字段外观复用 `ui-foundations.css`（其字段选择器已包含 `.settings-window` 根类）。
- 状态归属：模型与人设、飞书连接状态由 `settings-state.ts` 的 `useModelSettings` / `useFeishuConnection` 持有，仅设置窗口使用；主窗口只保留对话所需的模型列表与切换（聚焦时重新读取 `load_models` 同步设置窗口的增删）。主题与背景写本地存储，主窗口通过 `storage` 事件同步呈现。
- 壳层命令（`src-tauri/src/settings_window.rs`）：`open_settings_window(section?, profile?)` 创建或唤起窗口并定位分类（新窗口经 `take_settings_target` 取暂存目标，避免事件竞态）；`main_window_inner_size` 提供背景截取所需的主窗口纵横比。窗口导航白名单与 pet-chat 一致，capabilities 仅信任本地 webview（`pet/main/pet-chat/settings`）。
- 使用引导整体迁入设置窗口：模型与飞书阶段锚点就在本窗口；终端步骤把主窗口带回前台。首次启动 `load_onboarding.show` 为真时主窗口自动打开设置窗口。
- 主窗口 `client.html?debug=settings|usage|profile|feishu|video` 重定向到 `settings.html?debug=…`，调试样本行为不变。

## AI 调试与验收

```powershell
# client/；隔离样本，不连后端、不写真实数据
pnpm dev --host 127.0.0.1 --port 1425
# 浏览器打开 http://127.0.0.1:1425/settings.html?debug=settings
node --test tests/settings-window.test.cjs
pnpm test
pnpm exec tsc --noEmit
pnpm build

# client/src-tauri/
cargo check --locked
```

- `settings.html?debug=…` 页面可使用 `window.__deskDebug.settingsSnapshot()`、`seedFeishu`、`seedStatus`、`openSettings(section)` 等桥接（设置窗口注入的子集）；`data-settings-shell`、`data-settings-section`、`data-settings-nav-item`、`data-settings-search` 供 DOM 断言。
- 组件测试覆盖分组导航、搜索过滤（含无匹配状态）、分类切换、模型列表读取与选中、后端未连上的可读错误。
- 浏览器验收：深浅主题切换同步主窗口、600px 窄窗堆叠布局、搜索键盘可达性。Tauri 实机窗口打开、`take_settings_target` 定位与 `storage` 跨窗口同步已通过 cargo check 与组件测试，实机端到端尚未逐项验证。
