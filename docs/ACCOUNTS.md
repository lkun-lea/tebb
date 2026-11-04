# 客户端账号与本机空间（#244）

承接 [#238 方案](USER_PERSONALIZATION.md) 和 [部署准备](../supabase/README.md)。本阶段接入邮箱登录、加密会话、账号空间和重启切换。没有云项目时明确显示未配置，不能把合成身份测试称为真实 Supabase 登录通过。确认资料、离线队列和检查台接入见 [#255 同步模块](PERSONALIZATION_SYNC.md)；LangMem 提炼仍由 #238 后续实施。

## 使用方式

进入「设置 → 账号与空间」。初始仍是本机空间，原聊天、配置和记忆保持原位置。账号服务未配置时可以继续本机工作；由部署方提供项目地址和 publishable key 后才能申请验证码。正式部署可通过 `TEBB_CLOUD_URL` / `TEBB_CLOUD_PUBLISHABLE_KEY` 管理公开连接配置，界面不接收 service_role / secret key。

验证码仅在明确点击后通过官方 Supabase Auth SDK 2.33.0 申请，`should_create_user=False`，不会顺便注册账号。配置自有 SMTP 后使用部署包的六位邮箱验证码模板；新建 Free 项目的默认邮件服务不能自定义该模板，尚未配置 SMTP 时不能宣称普通用户验证码已可用。验证后调用 GoTrue `get_user` 核对真实身份，再在本机保存会话；不以自行解码的 JWT 内容识别人。项目连接变化会废弃原验证码请求，避免把旧验证码转发给另一个项目。

验证码校验失败时，输入框下方就地显示错误、标记无效并返回焦点；保留邮箱与当前验证码请求，便于检查后重新输入。网络结果不明时仍先核对原操作，不将断连当作验证码错误或自动重发。

登录成功后先显示「待重启切换空间」。点击「重启并切换」才结束当前客户端任务、收尾并退出原后台，然后启动目标空间。切换不自动拷贝模型 Key、飞书凭据或聊天，新账号需要配置本机所需连接。关闭/重启失败时原进程继续归属原空间；不会热改其 data_root。

已保存账号切换前在线核实登录，接近过期时由官方 SDK 刷新一次。刷新结果不明时不复用旧刷新令牌，而要求重新输入验证码。当前已选空间可离线重开；离线缓存可读不等于云端会话有效。退出账号先移除本机令牌，并单独报告远端会话撤销是否确认；已发出的访问令牌可能有效至到期，不承诺立即撤销。保留的本机资料不会因退出而删除。

当前面向一个部署项目。已有账号后不能在界面直接换成其他项目，避免同一目录与会话错绑。程序内置素材继续作为安装资源共享；账号选择、背景、日程核对状态等业务偏好分别保存。

## 状态与文件归属

- 安装根下 `account-control/accounts.json` 是唯一账号注册表，包含公开配置、已核实用户、会话、下次启动选择和操作回执。整体使用 Windows 当前用户 DPAPI 加密，没有明文降级；`.gitignore` 排除整个控制目录。
- 本机空间沿用原数据目录；账号空间为 `accounts/<项目和用户身份摘要>/data/`。聊天、模型/飞书配置、记忆、任务、用量、调试记录、扩展和日志均在各自目录中。账号目录不接受别名/符号链接转到其他位置；整个 accounts 目录不入 Git。
- Windows 同一用户环境的加密用于本机凭据保存，不将不同云账号误称为不同 Windows 用户。登录与账号选择由真实认证和受控界面处理，云端数据仍依赖服务端身份和 RLS。
- 原本机资料不自动认领、移动或上传。返回本机空间是显式切换；将旧资料导入某个账号需要后续独立的预览和归属操作。
- 浏览器缓存使用当前账号前缀；本机空间保留原命名空间。背景、主题、开发偏好、日程未确认标记和演示草稿不会进入另一个账号；浏览器协作预览能力仍绑定原后台进程令牌，不获得账号管理 RPC。

## 启动与切换边界

Rust 启动 `desk_companion.account_server` 并标记账号引导。引导先取得安装目录级运行权、读取已确认选择并固定环境，再导入后台服务。发布运行时的 sitecustomize 在启用本机扩展之前完成同样的绑定；工作进程继承已固定环境，引导标记已移除，不重新查询全局选择。初始化错误保持失败，不回退到本机或其他账号。

账号选择只影响下一次启动。运行中的会话/工作进程、项目环境、任务回执和迟到写入仍拥有原目录。重启命令复用既有关闭流程，确认原后台退出后才请求客户端重启；关闭失败返回明确错误。进程运行权在原进程真正结束后由操作系统释放。

## AI 调试接口

复用带本机 token 的 `/ws` RPC；不公开到 Supabase 或浏览器协作预览。`account_session` 为短时只读，不等待模型回合；`account_action` 使用独立账号操作预留，网络等待不持模型或数据写锁。

```json
{"method":"account_session","args":{"operation_id":"可选原操作UUID"}}
```

状态包含当前运行空间、下次选择、公开连接状态、账号列表、版本和指定回执，不返回访问/刷新令牌、验证码、请求摘要或完整加密注册表。

```json
{
  "method":"account_action",
  "args":{"payload":{"type":"send_code","request_id":"新UUID","version":2,"email":"合成测试邮箱"}}
}
```

操作类型：`configure`（url、publishable_key）、`send_code`（email）、`verify_code`（challenge_id、code）、`activate`（account_id 或 local）、`check_session`、`logout`、`cancel_switch`、`acknowledge`（原 operation_id）。每项携带新 request_id 和最新 version。前端写入前先保存不含邮箱/验证码/密钥的操作编号；同编号同请求只读取原回执，同编号不同请求拒绝。

网络断开先查询原编号。仍 pending 或原请求未送达时，明确选择「结束核对并重新登录」可以登记原编号不再执行；它不会撤销远端已完成的认证动作，也不会重放验证码。刷新处于未知状态的账号需要重新登录。版本冲突先刷新状态，不能换编号盲目重发写入。更改登录环境、存储失败和损坏均显式报告。

## 验证入口

建议使用 Python 3.13，并安装当前依赖。所有临时数据必须设独立 `DESK_COMPANION_DATA_DIR`，不使用真实聊天或发验证码。

```powershell
python -m unittest discover -s tests -p test_accounts.py -v
python -m unittest discover -s tests -p test_account_runtime.py -v
python -m unittest discover -s tests -p test_account_api.py -v
# client/ 内
node --test tests/accounts.test.cjs
pnpm test
pnpm exec tsc --noEmit
pnpm build
# client/src-tauri/ 内
cargo test --locked --lib
```

Auth 测试通过 httpx.MockTransport 执行实际官方 SDK；运行时测试覆盖真实 Windows DPAPI、两账号进程运行权、迟到写入、启动失败防回退和扩展加载顺序。RPC 测试验证实际 WebSocket、原进程 token 以及协作预览无法访问账号。前端测试覆盖分区、断连恢复、迟到读取、无法保存编号、初始化之前不挂载工作区。2026-11-04 #255 已另行在真实托管项目验证 SDK 刷新和单设备退出确认，另一设备会话保持有效。真实邮件与两台实体设备仍待 #263；普通回归不触发真实邮件。

参考：[Supabase Python OTP](https://supabase.com/docs/reference/python/auth-signinwithotp)、[会话](https://supabase.com/docs/guides/auth/sessions)、[Windows DPAPI](https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata)。
