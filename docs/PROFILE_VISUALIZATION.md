# 个人画像地图

关联 [#280](https://github.com/lkun-lea/tebb/issues/280)。用户已取消三角色和人物动画方向，采用最初的静态“我”字标识；本轮角色设计稿不保留。

## 界面与职责

“个人画像”提供画像总览与已有资料两个视图。地图中心是代表当前账号的圆形“我”字，四周按沟通方式、知识背景、长期目标、项目背景展示已确认资料；其他资料独立保留入口。不根据资料数量推断了解程度、性格或能力。

点击类别和条目查看原文、来源、范围、更新时间、版本和冲突内容。地图与列表共用 `ProfileRecordCard` 的编辑、停用、删除确认和冲突解决；`PersonalizationController` 拥有查询、保存、同步、账号绑定及原回执核对。模型调用仍通过既有调用检查台查看，不将地图资料当成某次实际发送的全部上下文。

`profile-overview.tsx` 只拥有类别和选中条目的界面状态，“我”字不读写外观缓存，不加载角色图片或动作库。旧角色选择、动画模块、准备脚本和发布资源复制逻辑已移除。无需为已取消的外观设置建立迁移或兼容路径。原始界面参考见 [设计说明](design/personal-profile/README.md)。

## AI 调试与验收

```powershell
# client/ 内：实际组件与隔离的资料运输层
node --test tests/profile-visualization.test.cjs tests/personalization.test.cjs
pnpm test
pnpm exec tsc --noEmit
pnpm build
pnpm dev --host 127.0.0.1
```

开发模式打开 `http://127.0.0.1:5180/client.html?debug=profile`，可检查“我”字、分类、冲突与来源详情。该入口使用合成资料，资料写入按钮禁用，不修改真实账号。生产构建不接受此调试参数。

`window.__deskDebug.profileSnapshot()` 只读返回 `marker`、`category` 和所选 `records` 编号。例如中心标识为 `我`；切换类别后可核对实际组件选择，记录编号来自当前显示的卡片。生产构建不安装调试对象。

正式构建 `DESK_RELEASE=1` 继续跳过一般 public 目录，只复制原有启动脚本，不再复制画像角色资源；普通与正式构建均不应出现 `dist/profile-avatars/`。不引入桌宠 Core 或私有皮肤。

资料服务仍通过认证 `personalization_status` 查询和 `personalization_action` 修改；云端同步、原操作核对与失败恢复见 [个人资料同步](PERSONALIZATION_SYNC.md)。本次没有修改 Python/SQL 契约，也没有重新验收真实模型个性化效果或 SMTP。
