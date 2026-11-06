# 飞书知识库分组与本地附件

知识库页按飞书真实空间 ID 分组，显示空间名称、文档数量和入库状态，可折叠并按标题或知识库名称搜索。普通云文档单独展示。归属或名称暂时无法获取时保留未识别提示或空间 ID，不猜测归属。旧索引无需删除，刷新目录后会补上已识别的分组信息；该功能不移动飞书文档。

顶部「文件」「文件夹」、聊天底栏「＋ 附件」和 `/` 菜单的「附件」打开同一资料窗口。在 Windows 上使用系统对话框；也可输入绝对路径。支持 UTF-8/GB18030/带 BOM 的 UTF-16 文本与常见代码文件、CSV、PDF、DOCX、XLSX、PPTX。不执行文件内容。PDF 需要可提取文字，扫描件不做 OCR；表格显示单元格值和已有公式，不重新计算公式或渲染样式。

顶部入口采用紧凑文字菜单，移除按钮边框和发光。Agent 执行期间也能打开附件面板。面板是独立悬浮窗，没有全屏遮罩，不抢聊天焦点、不限制 Tab 焦点；标题栏可拖动、收起，加载中也可关闭。打开面板不会立即弹出系统选择器，点击「选择文件」或「选择文件夹」后再选择。

Windows 使用独立 Python 进程打开 Common Item Dialog（IFileOpenDialog，文件夹使用 FOS_PICKFOLDERS），窗口创建前启用 Per Monitor V2 DPI；不设置顶、不以桌宠为模态 owner，也不依赖旧式 WinForms 文件夹树或便携版缺失的 Tk。可通过 `python -m desk_companion.desktop.local_picker --probe folder` 验证 COM 初始化和 DPI，不显示选择器、不读取文件。

关闭／停止等待会取消对应的选择器进程，并停止扫描和后续文件读取。迟到的返回不会加入附件；不取消 Agent 任务。入库过程中已完成的文件保留，当前正在入库的单个文件会完成，其余文件不继续。收起保留后台工作和当前勾选状态。关闭面板不会删除原文件，也不会撤销已完成入库。

交互调研参考：[VS Code 布局](https://code.visualstudio.com/docs/configure/custom-layout)、[Claude Code 的面板布局与文件引用](https://code.claude.com/docs/en/vs-code)、[Cline 文件与文件夹上下文入口](https://cline.bot/ide)。这里采用可与聊天并行的轻量面板，是针对桌宠界面的设计选择。系统选择器依据 [Microsoft Common Item Dialog](https://learn.microsoft.com/en-us/windows/win32/shell/common-file-dialog) 和 [线程 DPI 设置](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setthreaddpiawarenesscontext) 实现。

文件夹递归扫描，跳过隐藏目录、依赖/构建目录和链接，列出各文件的相对路径。一次最多 300 个可读取文件，单文件最多 20 MB、提取正文最多 200 万字，一批合计最多 600 万字；遇到限制或读取失败时给出原因。可附整个文件夹让 Agent 按需读取，也可只勾选个别文件。

选择资料后生成本地只读快照，存于用户数据目录的 `memory/local_sources/`。正文不会写入聊天记录的用户消息。发送时最多直接附入 16000 字，其他资料通过 `read_local_source` 分页读取。目录或部分读取必须说明覆盖范围，不能当成已读完全篇。附件内容在用户发送该轮问题后进入模型调用。

「加入知识库」将选中文件加入本地向量索引，不上传到飞书，使用知识库页已配置的向量模型。开启知识库检索时先入库；直接问附件则关闭知识库开关。入库后重建索引会重新读取原文件，因此原路径需保留。移除索引或附件不会删除原文件；快照保留供历史任务继续读取。
