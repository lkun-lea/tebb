# Python 包结构

本次按用户确认的业务能力分类整理 Python 模块（#282）。包内共同放置该能力的服务、存储、规则和工具适配；仅跨业务复用的基础能力进入 infrastructure。业务行为、用户数据位置、持久化格式与权限保持原样。

| 包 | 负责内容 |
| --- | --- |
| bootstrap | 账号绑定、启动和首次使用引导 |
| local_api | 认证 RPC、事件传输、查询组装及无头组合根 |
| desktop | 桌面组合根、桌宠、托盘、窗口及 Windows 界面适配 |
| chat | 普通对话、会话选择、助手组装及配置 |
| collaboration | 伙伴协作、执行策略、澄清和交付检查；工作区事务接口 |
| tasks | 持久任务队列、worker、进程保护及根预算 |
| memory | 历史、长期事实、选择策略、上下文与检查工具 |
| knowledge | 资料身份、索引、来源和笔记 |
| projects | 授权目录、文件操作、终端和隔离项目环境 |
| planning | 工作事项、本地日程、远端日程适配及安排时间 |
| automation | 定时作业、工作流定义、节点和执行回执 |
| content/video、content/news、content | 视频学习、资讯及周复盘 |
| integrations/feishu、github、web | 飞书、GitHub 和公开网页接入 |
| integrations | Skill 目录和工具、配置的 MCP 接入 |
| models | 模型清单、网络、生成参数、容量和 tokenizer |
| accounts | 账号认证、注册表及个性化同步 |
| reports | 图表输入契约、构建与渲染 |
| observability | 调用调试、用量、日志和性能 |
| evaluation | 质量评测、基准及开发实验只读入口 |
| infrastructure | 路径、锁、原子 JSON 写入、配置及运行时生命周期 |

## 依赖与状态所有权

- 各子包的 `__init__.py` 保持轻量，调用方显式导入所属模块，不通过包根目录转发旧模块。
- `local_api/host.py` 与 `desktop/app.py` 分别组装后台与桌面服务；业务服务和 worker 不依赖桌面窗口。Bridge 位于 local_api，由两个组合根复用。
- `infrastructure/storage.py` 提供原子 JSON 替换；文件格式、业务校验、写入准入及锁仍由各存储所有者负责，原子替换不替代业务事务。
- `collaboration/store.py` 提供工作区路径和原有 SQLite 事务接口；协作服务负责初始化结构，工作事项等调用者通过同一事务维持跨业务原子性。没有复制数据库或改变提交行为。
- `planning/calendar_adapter.py` 暂与日程业务同包，属于日程专用外部适配。跨日程和工作事项的安排规则也留在 planning。
- 模型内核仍归 Atlas，本次不改动 Atlas 接口或固定发布提交。目录重组不代表现有业务依赖已完全解耦。

## 入口与资源

```powershell
# Tauri 实际启动的账号绑定后台
python -m desk_companion.bootstrap.account_server --port 8770 --token <token>

# 已绑定账号环境中的本机服务与独立任务 worker
python -m desk_companion.local_api.server --port 8770 --token <token>
python -m desk_companion.tasks.worker

# 现有桌面入口
python -m desk_companion
```

worker 沿用父进程 stdin/stdout 协议，日常调试使用现有任务接口提交输入；不要直接给 worker 发未认证业务操作。接口调试见 [AGENT_DEBUG.md](AGENT_DEBUG.md)。

资源定位集中在 `infrastructure/paths.py`：`package_root()` 定位已安装 Python 包，`source_root()` 定位源码仓库或打包的 site-packages，`ui_root()` 定位包内 ui。`data_root()` 与 `asset_root()` 的环境变量及默认语义保持不变。模块搬家后不得通过增加 `parents[n]` 猜测资源位置。

Rust 启动参数、安装清理入口、扩展安装命令、生成的 sitecustomize、测试替身、源码证据清单与导入检查同步使用新路径。复现冻结历史提交的评测脚本仍使用那些提交中的文件路径。

## 验证

使用匹配项目依赖的 Python 3.13 解释器、隔离数据和假模型运行；真实终端、外部写入及发布另按对应文档执行。

```powershell
$env:DESK_TEST_ATLAS_SOURCE = 'E:\path\to\Atlas'
python scripts/ci_checks.py test --output E:\isolated-output\python-regression
python -m pip wheel . --no-deps --no-build-isolation --wheel-dir E:\isolated-output\wheels
# client/src-tauri 目录
cargo check --locked
```

完整回归包含递归模块导入、无 GUI 服务、认证后台、任务子进程、视频及资料来源行为。检查 wheel 内的模块和包内资源后，从解压安装目录以独立进程导入，核对源码来源及资源位置，避免源码 editable 安装掩盖打包问题。
