# tebb 官方网站

从仓库根目录运行 `python web/build.py`，再运行 `python -m http.server 8000 --directory web/dist`，打开 http://localhost:8000/ 。首页提供产品介绍、Windows 便携包和源码入口，栏目与文章均可直接通过各自的网址访问。

官方文章在 `web/build.py` 的 POSTS 中维护。更新下载入口时，在 GitHub Release 核对版本与 ZIP 文件名。合入 main 后由 Official website 工作流发布 web/dist。
