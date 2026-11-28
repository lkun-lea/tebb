# tebb 官方网站

从仓库根目录运行 `python web/build.py`，再运行 `python -m http.server 8000 --directory web/dist`，打开 http://localhost:8000/ 。首页提供产品介绍、Windows 便携包和源码入口，栏目与文章均可直接通过各自的网址访问。

官方文章在 `web/build.py` 的 POSTS 中维护。更新下载入口时，在 GitHub Release 核对版本与 ZIP 文件名。合入 main 后由 Official website 工作流发布 web/dist。

首页三帧来自桌面提交 `ae4ba24b24afbed4ced4af3ebd61ecc6fb325a46`。在同一 checkout 构建 Vite 正式前端和 Tauri 调试壳，后端从该目录加载；通过独立数据目录的本机笔记控件创建示例内容并点击加入草稿。图像只采集主窗口客户区。播放由用户启动，减少动效时支持手动逐帧。技术文章存放在 `web/engineering.py`，源码链接固定到取证版本。
