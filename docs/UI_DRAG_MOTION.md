# 拖拽、归位与撤销

对应 [#289](https://github.com/lkun-lea/tebb/issues/289)，承接 [UI 开发规范](UI_DEVELOPMENT.md) 第9条。范围是工作看板、日历时间块/边缘缩放、侧边工作区宽度。继续使用真实组件、既有业务控制器、dnd-kit、FullCalendar 与 Framer Motion。

## 参数与职责

`client/src/client/drag-motion.ts` 唯一拥有拖拽归位参数：stiffness 1200、damping 80、mass 1。Framer Motion 直接使用弹簧；只接受 CSS easing 的 dnd-kit/FullCalendar 使用同一零初速度弹簧的解析曲线：

```text
progress(t) = 1 - (3·exp(-20t) - exp(-60t)) / 2
```

以10ms间隔采样为 `linear()`，500ms收尾，末帧归一；结束前剩余误差小于0.007%。曲线单调、不越过终点。跟手阶段没有额外缓动；归位只在松手/取消后执行。不覆盖库拥有的 transform、top、left 或缩放几何。

- 看板：dnd-kit 拥有跟手和落点，Framer Motion 拥有未抓起卡片的布局归位。左右方向键一次移动一列；空格抓取/放下，Escape取消。窄窗网格按内容确定行高，防止两行重叠；碰撞优先实际交叠，键盘跨行自动展示目标列，并通过 dnd-kit modifier 将键盘浮层限制在视口内。指针拖动仍直接跟手。原菜单仍可推进事项。去掉抬起时的旋转；普通卡片用表面与3%混色悬停分层，避免滚动边缘裁切旧阴影，悬浮卡片保留层级阴影。
- 日历：有效落点向时间轴预览位置归位，无效落点/取消回到原处。FullCalendar 独占原生边缘缩放；镜像继承共享归位缓动，不注入第二套位移。Escape先标记取消、立即隐藏缩放镜像并显示原始几何，持有的原生手势在指针松开时结束且不写入。自定义拖动的 Escape 继续传给 dnd-kit，立即撤下落点预览。旧手势的延迟清理不能清掉新手势的取消标记。
- 侧栏：`use-workspace-resize.ts` 只拥有宽度、动画和指针监听。直接按指针位移更新，保留抓取偏移；宽度范围280–680px，并为主区预留386px。松手距两端24px内吸附；方向键20px，Home最窄，End最宽。原生separator语义报告宽度、方向和范围。Escape、pointercancel、失去捕获和窗口失焦恢复拖前宽度；重新抓取停止旧动画，卸载清理捕获与监听。可用宽度改变时停止旧动画并按新边界约束，避免旧终点越界。资料、标签、会话与原生浏览器布局仍由 SideWorkspace 拥有，沿用 ResizeObserver 同步。

`useUiReducedMotion` 同时读取系统设置与根节点 `data-reduce-motion=true`，用于以上三处，手动开关可实时变化。减少动效时保留直接跟手与所有操作，归位/侧栏宽度直接到终点。forced-colors 沿用系统焦点与边框例外。

## 保存与取消

取消只作用于尚未放下的手势，不撤回已提交操作。动画不等待网络，也不自行生成成功回执。WorkBoardController、ScheduleWeekController 与 LocalCalendarController 保持原职责：快速重抓保留最新意图；最新明确失败回到确认状态；冲突或结果未确认保留原编号、阻止新写入，等待明确核对。日历事项拖入仍先开草稿，未经确认不保存或同步。

## AI 验收入口

在 client/ 运行：

```powershell
pnpm dev --host 127.0.0.1 --port 1425 --strictPort
# http://127.0.0.1:1425/client.html?debug=work
node --test tests/ui-drag-motion.test.cjs tests/work-board.test.cjs tests/schedule-week.test.cjs tests/workspace.test.cjs
pnpm test
pnpm exec tsc --noEmit
pnpm build
```

看板直接使用内存示例；“日程安排”打开真实日历。已有 `desk-open-preview` 事件可打开合成引用侧栏，无需文件或外部写入：

```js
window.dispatchEvent(new CustomEvent('desk-open-preview', {detail: {
  kind: 'quote', quote: {n: 1, doc: '合成来源', title: '拖拽验收', text: '保留引用内容'}
}}));
```

自动化覆盖曲线、侧栏撤销/中断/卸载/窗口变窄、快速重抓、手动减少动效、落点/取消写入边界及既有失败/未知回执回归。浏览器验收需实际拖动、按键并检查几何、焦点、动画采样、深浅主题、600px与高对比；记录见 [界面验收](design/ui-drag-motion/VERIFICATION.md)。原生 WebView、真实飞书写入与系统触控需要单独实机验证，不由内存验收替代。
