# 个人画像地图与可选形象（#272）

## 使用

进入「设置 → 个人资料」，默认显示「画像总览」。地图按沟通方式、知识背景、长期目标和项目背景组织已有确认资料；点击类别后在详情中选择条目，查看原文、真实来源、范围、资料更新时间和本机/云版本。其他类别有单独入口。「已有资料」保留原类型筛选和已删除记录。

「更换形象」提供漫画分身、几何小机器人、原创小兔。选择和动作开关使用现有 `accountStorage()` 保存在当前账号的本机浏览器缓存中；本机空间单独保存，重启或返回页面后保留。读写失败就地提示，不把未保存选择冒充已生效。外观不进入模型上下文，也不替换 AI 伙伴或桌宠。当前云端同步协议只包含确认资料，形象选择暂不跨设备同步。

点击角色挥手，切换地图类别时指向对应方向。展开「角色动作」可预览待机、挥手、点头、指向，或暂停/恢复。Framer Motion 使用同一组分层图片连续插值，动作首关键值使用当前姿态，不换整张角色图；暂停和后台隐藏停止播放，系统减少动态效果保持静态。形象本身的切换会采用新角色的基础姿态。

编辑、停用、删除和版本冲突继续使用原 `PersonalizationController` 和认证 RPC；删除有明确确认步骤。断连保留原操作编号核对，不另建保存或重试路径。「查看模型调用」打开既有调用调试；某次采用/排除及完整发送上下文仍由聊天的调用检查台提供，地图不冒充模型已经使用全部资料。

## 职责与素材

- `profile-appearance.ts` 拥有受限角色清单、外观序列化与存储错误处理；只依赖注入的账号缓存。
- `profile-avatar.tsx` / `profile-character-motion.ts` 拥有层级布局与动作计划，复用已安装的 Framer Motion，不增加动画库或帧循环。
- `profile-overview.tsx` 按真实记录投影地图；`profile-record-card.tsx` 为地图和列表共用来源详情及操作控件。
- `PersonalizationController` 继续拥有资料查询、修改、未知回执、版本及账号绑定；没有修改 Python/SQL 同步契约。
- 设置页按需加载，避免主工作区启动时引入角色动画代码。运行资源在 `client/public/profile-avatars/`；设计原图、分层稿及被替代方案见 [设计归档](design/personal-profile/README.md)。

在 Windows PowerShell 运行 `./scripts/prepare_profile_avatars.ps1` 可从仓库内的原稿重新准备透明 PNG。脚本只裁取固定分层格并缩小打包，不再生成或改变角色；manifest 记录每部分来源矩形、尺寸和 SHA-256。部署使用已提交资源，不依赖本机 imagegen 路径、模型或在线图片服务。

## AI 调试与验收

```powershell
# client/ 内：真实组件、隔离缓存与模拟资料运输层
node --test tests/profile-visualization.test.cjs tests/personalization.test.cjs
pnpm test
pnpm exec tsc --noEmit
pnpm build
pnpm dev --host 127.0.0.1
```

开发模式打开 `http://127.0.0.1:5173/?debug=profile`，可检查三种形象、地图、冲突及来源详情。该入口使用合成资料与独立内存外观缓存，不改真实账号；资料写入按钮禁用，真实写入与未知回执由隔离运输层测试覆盖。生产构建不接受 debug 参数。

复用现有开发调试对象调用 `window.__deskDebug.profileSnapshot()`，只读返回当前角色、类别、暂停开关、所选条目编号和各关节的计算后 transform。AI 可在点击前后或动作进行中读取真实组件状态，不需要读取账号缓存或新增命令执行权限。生产构建不安装此调试对象。

无需调用真实模型或写入飞书即可验收本功能：测试导出的 `loadAppearance/saveAppearance`、`profileGroup/profileUsable` 和 `characterMotionPlan`，再由实际 React 组件验证切换、确认删除、暂停、减少动态效果与过期动画回调。账号 A/B/本机缓存分别读取，模型资料 RPC 不包含 avatar 字段。图片 manifest 验证透明格式、尺寸与内容摘要。

资料服务仍可通过认证 `personalization_status` 查询和 `personalization_action` 修改，调试命令及失败恢复见 [个人资料同步](PERSONALIZATION_SYNC.md)。本批没有重新验收真实模型个性化效果、SMTP、云端外观同步或原生窗口的实际帧率；这些与组件回归分开记录。
