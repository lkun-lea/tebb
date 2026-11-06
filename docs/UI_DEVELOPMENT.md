# UI 开发规范

适用于 tebb / desk-companion 的 React 工作台、桌宠聊天和新增界面。2026-11-06 用户确认，首批关联 [#285](https://github.com/lkun-lea/tebb/issues/285)。本规范是当前要求，历史截图和旧功能文档不得覆盖这里的参数。

## 优先级与职责

用户明确要求优先于外部 skill。桌面参考 [desktop-agent-ui](https://github.com/Ludi-Herry/desktop-agent-ui/blob/main/SKILL.md)，业务页面参考 [B 端规范](https://github.com/Ludi-Herry/b-end-design-system-skill/blob/main/SKILL.md)，实际移动/触控入口参考 [移动端规范](https://github.com/Ludi-Herry/mobile-design-system-skill/blob/main/SKILL.md)。本项目默认去边框，不因 skill 推荐微边框恢复整页描边；暗色字重固定减 40，不采用外部规范的减 100。

复用 React、reend-components、Lucide、Framer Motion、dnd-kit 与 FullCalendar，不引入第二套 UI 库。`client/src/client/ui-foundations.css` 唯一拥有语义 token、基础排版和字段外观；`ui-controls.tsx/css` 拥有公共控件及状态；页面拥有布局和业务状态。`--wb-*`、`--cp-*` 只引用语义 token，不建立独立色板。控件不发业务请求、不自行判定任务成功。

## 十条铁律

| # | 强制要求 | 实现与验收 |
| --- | --- | --- |
| 1 | 默认去边框，靠约 1%–3% 微明度差分层，禁纯黑 #000 / #000000 | 浅色基底 #f5f5f3、表面 #fcfcfb；暗色依次 #0b0b0a、#151515、#1a1a19、#20201e。指定基底与表面的色差按色板本身执行，hover 再做微变化。普通卡片禁用嵌套描边和左彩条。 |
| 2 | 输入框聚焦不加 outline，加深双环 box-shadow | 内环 1px、外环 3px，深浅主题均清晰；错误字段采用危险语义双环。鼠标和键盘聚焦均可辨，不丢失 label、帮助、错误和焦点语义。 |
| 3 | 暗色字重全量减 40 | 400→360、500→460、600→560。CSS 使用 --ui-weight-*，Tailwind 使用对应字重 token，禁止新增裸字重。系统静态字库可能映射到邻近字重；连续视觉效果须用支持细分字重的字库实测，不能仅凭 computed style 声称字体精确呈现。 |
| 4 | 流式新增文字逐字从 blur(6px) 到清晰 | 单字 90ms，cubic-bezier(.215,.61,.355,1)，相邻字错开 30ms。按 Unicode 字素处理组合字符；仅动画实际新到文本，不重播前缀，不伪造进度。代码与图表保持可读布局，长批次不可无限积压动画队列。 |
| 5 | 行内图标 vertical-align:-0.125em | 使用 .ui-inline-icon，仅用于文本行内 SVG；flex/grid 图标保留容器对齐，不对所有 SVG 全局偏移。图标按钮提供可读名称。 |
| 6 | 数字 tabular-nums | 正文全局继承等宽数字，耗时、token、调用数、金额、表格核验实际计算样式。覆盖字体时不能丢失此规则。 |
| 7 | 折叠使用 Grid 0fr→1fr | 内层 min-height:0、overflow:hidden，不用 JS 测量高度。关闭态防止隐藏控件被聚焦，aria-expanded 同步。输入框自适应并非折叠，沿用其高度逻辑。 |
| 8 | 正文 text-wrap:pretty | 标题可用 balance，代码与终端保留原始换行。不用裁掉正文、缩小字号实现防孤字。 |
| 9 | 拖拽过阻尼、确认反馈欠阻尼 | Spring：拖拽归位/吸附 stiffness:1200,damping:80,mass:1，零回弹；点赞/对勾 stiffness:380,damping:18,mass:1，微弹。跟手阶段不叠加落点动画，不争抢拖拽库的 transform。 |
| 10 | 复制成功对勾 2.5s 后淡出恢复 | 真正写入剪贴板后出现，连续复制重置期限，卸载清理计时器。失败、冲突、权限问题、结果未确认等业务状态不自动消退。 |

## 基础样式与共享控件

- 继续使用 hsl(var(--token) / alpha)。指定 HEX 在基础 token 转为 HSL 通道，禁止把 HEX 填入 HSL 通道变量，禁止页面重复定义主题。
- 默认控件低反差表面、无描边，按钮 hover 使用 3% 前景混色。一个操作区域最多一个主按钮；危险操作保留明确文字、确认与真实回执。
- 标准字号 12 / 14 / 16px，页面主标题可有独立大标题档；同页控制 3–4 档，最小 12px。历史页面未迁移的小字号不算已修复。
- 按钮覆盖默认、主要、危险、按下、禁用、忙碌与 focus-visible。busy 保留可读文字、原生 disabled 和 aria-busy，不自行增加重试。
- 字段 label/help/error 与既有 aria-describedby 保持关联；修正错误不替换输入节点或清空内容。checkbox、radio、range、文件与颜色选择器保留专属呈现。
- 反馈分 loading、empty、no_results、success、error、conflict、unconfirmed；后三种为 alert，其余为 status。文字传达状态，不只依赖颜色。持久状态不套用复制自熄。
- 圆角与阴影服务于层级，嵌套圆角按 R内=max(0,R外-padding) 校准，不增加装饰性发光或大阴影。
- prefers-reduced-motion:reduce 与 [data-reduce-motion=true] 均关闭新增过渡。forced-colors 使用系统色、实体边框和 Highlight outline；系统高对比是边框/outline 的必要例外。
- 保留真实任务状态、未保存保护、焦点返回、停止与核对、输入法和独立滚动契约，装饰调整不能改变业务状态机。

## 本批范围与后续

#285 落地规范、根主题、基础排版、暗色字重 token 接入现有 CSS 与 Tailwind、字段焦点、共享控件和可交互隔离样板。主导航及共享表面去边框，其他页面按后续批次迁移。

第二批 #287 已在聊天链路落地第4、7、10条及第9条的复制确认微弹，具体范围与调试入口见 [聊天动效与反馈](UI_CHAT_MOTION.md)。第三批 #289 将拖拽1200/80归位应用于看板、日历与侧栏，取消/中断和验证入口见 [拖拽、归位与撤销](UI_DRAG_MOTION.md)。其他业务页面、历史小字号、左彩条和硬编码颜色继续按首轮审查逐页处理；看板普通卡片去边框不代表其他页面卡片已迁移。

第四批 #291 统一日历与看板的12/14/16px字档、普通表面/控件去边框、事件去左彩条及状态语义色，浅色悬停保持表面抬升。#292 修复保存后重复定位与同周重建；范围和边界见 [业务页面视觉](UI_BUSINESS_PAGES.md)。#290 恢复标准 Vite 监听并提供 [原生手动验收入口](UI_NATIVE_CHECKS.md)，生产构建不包含合成资料工具。

## 验收入口

在 client/ 运行：

```powershell
pnpm dev --host 127.0.0.1 --port 1425
# http://127.0.0.1:1425/client.html?debug=work
pnpm test
pnpm exec tsc --noEmit
pnpm build
```

页面为内存示例，不调用真实模型或外部写入。展开“共享控件状态样板”，输入文本并切换焦点，检查普通/错误输入、select、禁用、按下、危险和忙碌按钮及七种反馈；下方为真实看板与日程组件。在设置中切换深浅主题，600px 窄窗检查换行、横向溢出与焦点可见性。

有阴影的元素在默认、hover、展开与落点检查裁切；桌面 skill 的 clip-audit 应以受检元素的父容器为 root，记录 cut/hidden 和必要复核。减少动效与 forced-colors 应用浏览器模拟或真实系统分别验证，不能只凭 CSS 声称通过。

记录运行时、视口、状态、截图与计算样式，区分浏览器通过、原生 Tauri、系统字体与 IME 未验证。证据见 [基础样式验收](design/ui-foundations/VERIFICATION.md)。
