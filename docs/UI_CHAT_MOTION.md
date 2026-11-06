# 聊天动效与反馈

对应 [#287](https://github.com/lkun-lea/tebb/issues/287)，承接 [UI 开发规范](UI_DEVELOPMENT.md) 第二批。修改只涉及前端呈现与复制交互；模型事件、业务执行、停止与核对流程保持原职责。

## 流式文字

`stream-arrival.ts` 拥有字素分段与有界到达时间表，`StreamText` 保持整份 Markdown 输入，`Markdown` 只包装新到且仍在动画时间窗中的文本字素。

- 采用 Intl.Segmenter 字素边界，组合音标、肤色与 ZWJ emoji 不按 UTF-16 单元拆开。跨批次补齐一个字素时立即呈现完整字素，不重播其旧部分。
- 初次挂载已有正文、切换查看历史和非追加的内容重写直接显示，不从头打字；active=false 时立即展示最终内容并移除流式光标。
- 90ms 从 blur(6px) 到清晰，cubic-bezier(.215,.61,.355,1)，相邻计划起点相隔30ms。时间表只保留最多8个活跃字素，最长计划延迟210ms；大量或高速到达时，较早部分立即清晰，末尾继续错峰，不把正文排成无限等待队列。
- 动画重挂载时按原到达时刻续播，不能因刷新重播前缀。Markdown 语法结构发生变化时仍由解析器正常重解析；已完整的代码块、图表与来源披露保持原组件身份。
- 代码、图表及源文本位置不明确的实体/转义节点直接清晰呈现，不猜位置，不执行原始 HTML。正文全部可复制，不因动画窗口限制被截断。
- 系统或手动减少动效时不模糊或晕开。动画计时只控制视觉，不产生任务成功或伪造模型进度。

## 折叠面板

复用 `InspectorDisclosure`，覆盖聊天执行过程、工具/文件/命令回执、图稿检查、调用检查台与已有上下文/记忆检查入口。

外层 Grid 在0fr与1fr之间过渡，内层 min-height:0/overflow:hidden，不用 JS 测量内容高度。首次展开才挂载内容，避免预先渲染大 JSON；之后关闭保留节点、输入与子折叠状态。关闭态同时设置 inert、aria-hidden 和延迟 visibility，阻断隐藏控件的键盘访问；按钮通过 aria-controls/aria-expanded 关联内容。关闭时内部焦点回到触发按钮，反复操作可中断过渡。

运行状态保留在折叠标题中，用户无需展开才能知道“尚未开始执行”或失败。内容裁切层给焦点留出空间；旧流式光标发光已移除，避免被折叠裁切。

## 复制反馈

`CopyButton` 唯一拥有复制动作、异步请求序号、反馈与定时器；调用方提供完整文字或读取函数。已接入助手回复、普通 Markdown 代码块、沙箱终端、项目终端和工作流输出引用。

- 剪贴板真正写入成功后显示对勾，stiffness=380/damping=18/mass=1；2.5秒后对勾以150ms透明度过渡消失，恢复复制图标，按钮文案保持稳定。
- 连续操作使旧定时器失效；迟到的旧成功/失败不能覆盖新状态。卸载后清理计时器和忽略回调；异步读取文本在卸载后返回时不再写入剪贴板。
- 错误用持久 alert 展示，只有后续复制成功才清除；不把“复制失败”改成成功，不自动重试。未选择项目终端文字时明确提示选择文字。
- 图标不代替可读名称；成功以 status 通知，业务失败、冲突与未知回执不套用2.5秒自熄。减少动效时省去弹性和淡出。

## 隔离调试与验收

```powershell
# client/，使用既有 Vite、真实 ChatPrototype 和合成状态
pnpm dev --host 127.0.0.1 --port 1425
# http://127.0.0.1:1425/client.html?preview=motion
node --test tests/ui-chat-motion.test.cjs tests/chat-prototype.test.cjs tests/pet-chat.test.cjs tests/report-charts.test.cjs tests/terminal.test.cjs
pnpm test
pnpm exec tsc --noEmit
pnpm build
```

`preview=motion` 仅在 import.meta.env.DEV 下可用，不经过账号启动、不连接后端。页面可切换深浅主题、追加字素、高速更新、追加长回复、完成和重置；复制按钮仍是实际组件，人工点击时会请求本机剪贴板权限。自动化验收使用受控剪贴板替身，不改用户剪贴板。

验证覆盖字素、前缀不重播、队列上限、Markdown与图表身份、折叠状态/焦点/inert、复制竞态/失败/重置/卸载、深浅主题、600px、减少动效与阴影裁切。报告与合成截图见 [第二批验收](design/ui-chat-motion/VERIFICATION.md)。

拖拽1200/80弹簧、其他业务页面的小字号、硬编码颜色和剩余原生详情折叠仍按后续批次推进，不宣称全站已迁移。
