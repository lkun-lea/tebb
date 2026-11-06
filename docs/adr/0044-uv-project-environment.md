# uv 管理 Python 项目环境与发布依赖

项目使用 pyproject.toml 和 uv.lock 管理依赖及 Atlas 正式 Git 提交（#283），开发默认 Python 3.13，由 uv 同步项目 .venv，Tauri 调试入口直接使用它。用户已确认基础依赖默认安装，sentence-transformers / PyTorch 为 knowledge 可选依赖；不把模型权重纳入环境同步。嵌入式发布 Python 仍固定独立补丁版本及官方摘要。

发布 requirements 从 uv.lock 导出并校验，包含原有 runtime 工具组、排除 Atlas 本体和可选模型依赖；Atlas 继续从同一个正式提交归档。宿主 uv 负责构建安装，终端用户扩展层仍使用随包 pip。独立开发任务优先使用候选自己的 uv.lock，显式源码依赖从发行包安装清单排除，避免覆盖批准的源码目录；非 uv 项目沿用其自身依赖声明。
