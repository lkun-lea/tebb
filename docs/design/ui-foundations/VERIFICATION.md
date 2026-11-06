# UI 基础样式首批验收

关联 [#285](https://github.com/lkun-lea/tebb/issues/285)，规范见 [UI 开发规范](../../UI_DEVELOPMENT.md)。2026-11-06 在 Windows 上对 Vite 的 `/client.html?debug=work` 进行真实 Chromium 无头渲染，使用既有内存看板和日程示例；未调用模型或真实飞书写入。

## 通过的检查

- 1440×1000 深浅主题：基底分别为 rgb(11,11,10) / rgb(245,245,243)，表面为 rgb(21,21,21) / rgb(252,252,251)。正文计算字重 360 / 400，按钮 460 / 500，数字为 tabular-nums。
- 输入可编辑；普通和错误字段聚焦均为内环 1px、外环 3px，outline 为 none；错误字段保留 aria-invalid 和帮助/错误关联。组合搜索框只在外层显示双环，内部不重复着色。
- 按下、禁用、忙碌、危险按钮与七种反馈保留；三种告警使用 alert。正文 pretty 和行内图标规则已接入基础层。
- 深浅主题真实日程时间轴可渲染。600×900 样板自动换列，根文档 scrollWidth=innerWidth，无全局横向溢出；窄窗不要求把所有纵向内容塞入一屏。
- 浏览器模拟 prefers-reduced-motion 及手动 data-reduce-motion 时新增过渡归零；forced-colors 模拟下字段使用实体边框和系统可见 outline。高对比是去边框和无 outline 规则的可访问性例外。
- 桌面 skill 原版 clip-audit：共享样板收起、展开聚焦、hover 最终态和窄窗聚焦以及深浅主题原生 dialog 阴影共 9 组，均 cut=0、hidden=0；控件 root 为样板容器，dialog root 为其所在日程页，均检查子元素的阴影。没有将局部通过外推为全站通过。
- 页面脚本异常为 0，详细计算样式、检查和裁切结果见 [results.json](results.json)。

## 截图

| 场景 | 深色 | 浅色 |
| --- | --- | --- |
| 共享控件与实际看板 | [查看](dark-controls.png) | [查看](light-controls.png) |
| 实际日程 | [查看](dark-calendar.png) | [查看](light-calendar.png) |
| 同步预览弹窗（未提交） | [查看](dark-dialog.png) | [查看](light-dialog.png) |

[600px 窄窗](light-600.png) / [高对比模拟](forced-colors.png)。截图均为合成数据；历史页面仍有待迁移描边、小字号等，不代表全站规范已完成。

## 自动化与验证边界

- `pnpm exec tsc --noEmit` 通过，`pnpm build` 通过；保留既有大于 500kB chunk 提示，未扩大为打包优化。
- 工作区完整 `pnpm test`：290 项，289 通过、1 失败。失败来自任务开始前已修改的 `client/src/builtin-pet.ts`：测试替身没有 dataset，设置 mood 时抛错。本批未修改此文件。
- 在测试进程中仅用 Git HEAD 的 builtin-pet 源码替代上述未提交版本，完整 290 项全部通过；没有覆盖或回滚工作区桌宠改动。此对照结果不等于原工作区全绿。
- 本机窗口自动化遇到浏览器激活失败，内嵌浏览器连接超时，因此实际渲染验证使用独立无头 Chromium，而非用户日常浏览器或 Tauri 真窗。
- 未验证原生 Tauri、真实 IME、系统实际高对比切换与字体细分字重的栅格化效果。未发布安装包。
- 十条规则已全部沉淀；逐字流式、Grid 折叠、指定弹簧、复制自熄及逐页控件迁移仍待后续批次。

复验：在 client/ 运行 `pnpm dev --host 127.0.0.1 --port 1425`，打开 `/client.html?debug=work` 并展开“共享控件状态样板”。基础类型/回归命令见 [UI 契约](../../UI_CONTRACT.md)。本次浏览器脚本和原始日志留在工作区外 `E:/Learn_Project/output/ui-foundations-285/`。
