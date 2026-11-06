# 标准开发服务与原生 UI 验收

对应 #290。用户接手原生界面验收；浏览器、构建或宿主启动成功均不代替原生交互通过。

## 标准服务修复

原配置在 Windows 输出 ready 后，`client.html` 请求6秒超时。3秒 CPU 采样中约98%的样本位于文件监听的 native start；Chokidar 诊断确认扫描进入 `src-tauri/target`。Vite 现在忽略整个 `src-tauri`，由 Cargo/Tauri 负责原生文件，不关闭前端监听。默认端口5180和 Tauri devUrl 保持一致。

相同配置仅覆盖验收端口1432后，请求返回200，重复请求约0.37秒。`tests/dev-server.test.cjs` 启动实际 Vite，验证页面响应、前端文件变更后的转换缓存失效，以及原生目录未进入监听集合。测试用临时模块和独立缓存，结束后清理。

完整前端回归默认固定4个 Node 测试进程：本机无限制并发时，真实 Vite 集成测试可能与大量 TypeScript 编译争抢资源并挂起；相同全部测试在4并发下通过，默认命令采用该方式，不跳过集成测试。

在 client/ 启动；已有该端口的服务时不重复运行：

```powershell
pnpm dev --host 127.0.0.1 --port 1432 --strictPort
# http://127.0.0.1:1432/client.html?debug=work
node --test tests/dev-server.test.cjs tests/ui-check-tools.test.cjs
```

开发态 `debug=work` 或 `ui-check=1` 挂载可见的“UI验收 · 合成数据”工具。工作台就绪前按钮禁用，随后可点击“打开合成资料”，使用真实 SideWorkspace 预览入口；资料内的 Example 网页链接继续走真实浏览器入口。它不依赖原生初始化脚本或快捷键，生产构建不包含该工具。

## 隔离 Tauri 宿主

`examples/verify_ui_checks.rs` 复用库内公开的生产 side_browser 模块与三个命令，不启动生产 run/后端，不调用模型或真实飞书。使用独立应用标识和新的临时 WebView 数据目录；关闭其主窗退出该验收宿主，不影响普通 tebb 窗口。宿主仅接受本机 HTTP 地址作为前端入口。Example 网页仍执行生产浏览器的 URL 与权限边界。

在 client/src-tauri/ 构建，显式嵌入已有 Common Controls v6 清单：

```powershell
cargo rustc --locked --example verify_ui_checks -- -C link-arg=/MANIFEST:EMBED -C link-arg=/MANIFESTINPUT:E:/Learn_Project/desk-companion/client/src-tauri/examples/verify_main_window.manifest
cargo check --locked --example verify_ui_checks
```

服务就绪后运行 `client/src-tauri/target/debug/examples/verify_ui_checks.exe`。可选参数为新的绝对输出目录、本机服务根地址；省略时使用新建的 `%TEMP%/tebb-ui-probe-*` 和 `http://127.0.0.1:1432/`。目录中的 host.json 记录 PID、隔离标识与未启动后端事实。

旧验收窗口若仍连接同一开发服务，刷新后也能看到新的合成资料按钮。旧快捷键入口不再作为验收步骤。普通发布包没有该调试按钮。

## 人工检查

1. 在“设置 → 界面外观”分别切换深浅色，检查卡片默认/悬停层次、文字和聚焦。
2. 看板拖动中按 Escape 再松手；快速二次拖动，核对最终列。
3. 日历拖动、缩放已有时间块，分别保存和取消；主动定位后再跨日拖动，关注右侧滚动位置。
4. 将左侧事项拖入可见时间轴，核对草稿可见、尚未保存，取消后不创建日程。
5. 点击“打开合成资料”，拖动分隔条，按 Escape 恢复；点击 Example 网页后缩放侧栏、最大化/还原窗口，检查网页边界和点击位置。
6. 切换资料标签及收起侧栏，网页应同步隐藏。将窗口缩窄，检查重叠和遮挡。

反馈记录主题、视口、操作、实际表现及错误原文。真实网络访问失败与网页布局错误分别记录。2026-11-06 原生人工反馈的三项问题、修复和浏览器证据见 [第四批验收记录](design/ui-phase4/VERIFICATION.md)；原生复测仍待用户结果。
