# 后台命令沙箱

PC 工作区通过任务进度、结果和错误反馈展示命令执行状态。项目文件和权限设置仍从「打开文件夹」进入。项目运行的日志与预览从聊天中的项目执行回执打开。

每会话独立持久 `/workspace`。每条命令使用新的 Bash 环境，`cd` 或环境变量不延续到下一条；工具参数 cwd 可指定 `/workspace` 下的已有目录。

## 连接与边界

Windows 使用本机 WSL 发行版（默认 Ubuntu）中的 `/usr/bin/python3` 和 `/usr/bin/bwrap`。需支持非特权 user namespace 和 bubblewrap `--disable-userns`。缺少环境或自检失败时拒绝执行，不自动安装系统组件，不回退到宿主执行。

沙箱使用独立用户、进程、IPC、网络、UTS 与挂载命名空间；禁用进一步创建 user namespace，清空环境，移除 capabilities。根目录只读，只读挂载 WSL `/usr` 运行库，可写当前会话 `/workspace` 和临时 `/tmp`。Windows 磁盘、个人 home、桌宠 API token、模型密钥和 WSL 互操作入口不可见，网络关闭。本版支持 Linux 命令，不能执行宿主 PowerShell 或访问未导入的文件。

用户时限 15～300 秒，Agent 最多 60 秒；同时最多 3 条，每会话最多 1 条。每进程地址空间 256 MiB、CPU 时间 60 秒、进程数限制 64、单文件写入限制 32 MiB；`/tmp` 64 MiB。工作目录每秒检查，超过 128 MiB 或 10000 个条目时停止，可能短暂超过阈值；这些限制不是容器总内存或磁盘硬配额。

沙箱使用 WSL 的 Linux 内核，不等同于独立虚拟机；隔离强度取决于具体策略及内核。实现依据 [bubblewrap 官方说明](https://github.com/containers/bubblewrap) 与 [WSL 安全说明](https://github.com/microsoft/WSL/blob/master/doc/docs/technical-documentation/security.md)。

## 记录与停止

每条命令输出最多 4 MiB，达到限制停止并保留此前输出。Agent 初次回执只附前 16000 字符，可以调用 `read_terminal_output` 继续按字节读取。输入按序发送，结束清除输入控制文件。

列表接口返回最近 100 条记录，历史原始记录保留在磁盘；已知命令编号仍可由工具分页读取。

`execute_command` 禁用自动重试，UI 提交带唯一请求编号，重试同一请求不重复执行。任务恢复需核对原记录。工具调用同时保留在任务时间线和 LLM 调试记录中。

任务取消/超时/完成和正常关闭客户端会停止对应命令与后代；后端异常退出时，Linux 监督进程在最后一次租约更新约 8 秒后停止。重启后端不会重放命令。

工作文件和记录位于用户数据目录 `memory/terminal/`，源码默认在仓库下，发布版在 `%LOCALAPPDATA%/DeskCompanion`。工作目录满时，停止命令后可在对应 `workspaces` 子目录清理结果。本次源码已验证开发机已有 Ubuntu 环境；公开安装包需另行安装这些可选依赖。

## 验证

AI 可直接复用认证 RPC：`terminal_status`（自检）、`terminal_start`（明确 command/session/cwd/timeout/request_id）、`terminal_list`（按 request_id 查重）、`terminal_read`（按 job_id/offset 读实际输出）、`terminal_input`（输入/尺寸）和 `terminal_cancel`（按 job_id 停止）。模型使用现有 `execute_command` / `read_terminal_output`，将 task_id、job_id、输入命令、原始输出、退出码关联保存。验证真实模型任务时，必须确认它实际调用工具、取得真实执行结果并正确报告失败/超时，不能以页面演示或假 RPC 成功代替。

PC 界面回归见 client/tests/workspace.test.cjs，覆盖旧终端请求、侧栏显隐和草稿保留。

```powershell
$env:DESK_TEST_SANDBOX='1'
python -m unittest tests.test_terminal -v
python -m unittest tests.test_local_api tests.test_tasks -v
cd client
pnpm test
pnpm exec tsc --noEmit
pnpm build
```

真实测试覆盖目录、网络及环境隔离，只读根和运行库，中文交互输入，WSL 符号链接拒绝，时限、退出码、输出上限，停止后后台子进程回收。未设置测试开关时跳过真实沙箱组，普通单元测试仍运行。
