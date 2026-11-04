# 云端个性化接入与部署包（#241）

本目录提供 #238 的 Supabase Auth、PostgreSQL/pgvector 与确认资料同步契约。账号登录和空间隔离见 [账号模块](../docs/ACCOUNTS.md)，离线队列、冲突处理和资料界面见 [确认资料同步](../docs/PERSONALIZATION_SYNC.md)。2026-11-04 已完成独立托管项目、迁移、受控配置与真实云端同步验收，邮件通道待 SMTP；LangMem 提炼与相关性选择属于后续阶段。本地测试不会上传既有 tebb 资料。

## 内容和配置

- `config.toml`：Supabase CLI **3.0.0** 的本地开发配置；仅 `public` 暴露为 Data API，`tebb_private` 不列入暴露 schema。邮箱登录开启，自动注册及匿名登录关闭，先使用运营者准备的测试账号。
- `config.hosted.toml`：本批实际托管配置，声明必要 API/Auth 字段，保留远端其他设置；未声明 SMTP 和邮件模板，适用于先部署数据库与同步的阶段。
- `templates/email-otp.html`：邮件中使用 `{{ .Token }}`，让用户输入六位验证码；验证码十分钟过期。这里只准备模板，不发送邮件。
- `migrations/20261103000000_personalization.sql`：云端独立迁移，启用 pgvector、私有表 RLS 和四个公开受控函数。没有前端 service_role，也不公开本机文件/终端 RPC。
- `.env.example`：开发者接入的公开项目配置。实际 `.env` 不入 Git。短期用户访问令牌只从进程环境读取，不打印、不写报告、不要求在聊天粘贴。
- `tests/runner`：固定版本 PGlite/PostgreSQL 与 pgvector 验证；开发依赖不进入客户端运行时。

测试默认使用 PATH 中的 `python`；需要指定隔离解释器时，设置 `TEBB_CLOUD_TEST_PYTHON` 为完整可执行文件路径。

配置项：

| 项目 | 用途 | 保存位置 |
| --- | --- | --- |
| `TEBB_CLOUD_URL` | HTTPS 项目地址，本机测试可使用 loopback HTTP | 开发环境公开配置 |
| `TEBB_CLOUD_PUBLISHABLE_KEY` | publishable key；也识别旧版 anon JWT | 开发环境公开配置，拒绝 secret/service_role |
| `TEBB_CLOUD_ACCESS_TOKEN` | 单个已登录测试用户的短期访问令牌 | 可选，仅进程环境，用于只读预检 |
| `TEBB_CLOUD_TEST_TOKEN_A` / `A2` / `B` | 后续两账号、两设备验收的三个独立登录会话 | 仅显式测试的进程环境 |
| `TEBB_CLOUD_TEST_PROJECT=1` | 声明验收目标为专用可清理测试项目 | 仅显式验收 |

不要把本机 `BackendInfo.token`、模型 Key 或飞书凭据填入上述访问令牌。PersonalizationCloud 单个客户端不管理刷新；其上层 AccountService 通过官方 Auth SDK 统一管理加密会话和刷新。每个云客户端固定一份会话，先向 GoTrue `/auth/v1/user` 核实身份，再使用该身份对应的云端回执。

## 创建项目后的部署顺序

1. 用户完成 Supabase 账号授权后，由开发执行创建独立免费测试项目，核对地域、组织和免费额度；不自动开通付费资源。项目配置不是每个 tebb 使用者各自创建一套数据库。已部署项目由拥有者账号管理，具体公开配置保存在未入库的本机连接记录。
2. 获取 Project URL 和 publishable key。数据库密码、管理 token、SMTP 密钥仅保留在运营者受控环境，不能放进客户端。
3. 安装/运行官方 CLI 3.0.0，在仓库根目录核对目标及迁移。CLI v3 的数据库命令默认指向本地，必须显式写 `--remote`；下面的 dry-run 不代表已部署。

```powershell
npx --yes supabase@3.0.0 login
npx --yes supabase@3.0.0 link --project-ref YOUR_PROJECT_REF
npx --yes supabase@3.0.0 migration list --remote
npx --yes supabase@3.0.0 db push --dry-run --remote
# 核对目标与变更后执行，CLI 会要求确认。
npx --yes supabase@3.0.0 db push --remote
```

4. 在托管项目的 Auth 控制台同步设置：Email provider 开启、自动注册/匿名登录关闭、邮箱确认开启、验证码 6 位/600 秒、刷新令牌轮转开启；具备自有 SMTP 后，Magic Link 邮件正文使用本目录 OTP 模板。`config.toml` 是本地配置，`db push` **不会**自动同步这些托管 Auth 设置；不要对现有项目盲目执行 `config push`。

   本阶段可把 `config.hosted.toml` 复制为独立部署目录下的 `supabase/config.toml`，使用官方 CLI `config diff --remote=<项目编号> --workdir <部署目录>` 检查，再 `config push` 应用并再次 diff 回读。只管理显式声明字段，不用本地完整栈配置重置远端；SMTP 准备好后再独立配置模板。
5. 确认 Data API 仅暴露 `public`，不暴露 `tebb_private`。在管理后台准备两个可登录的测试账号，不通过客户端下发管理密钥。
6. 对非项目团队用户发送邮件前配置自有 SMTP 并验证送达、限流和发件域名。Supabase 默认邮件服务限制收件对象；2026-06-03 起新建 Free 项目在使用默认 SMTP 时不能自定义邮件模板，默认链接邮件不等同六位验证码。用户已确认暂无 SMTP，先完成数据库与同步，邮件通道保留待配置；不要绕过该限制改模板。
7. 配置公开接入信息后执行下述只读预检，再进行显式合成数据验收。新部署目标未准备好时保留缺失状态，不把本地测试视为真实云端通过。

本批没有启动 Supabase 完整本地栈。PGlite 0.5.14 中实际执行的是 PostgreSQL 18.6；本地 Supabase 配置目标为 17，本次托管实际为 PostgreSQL 17.11。该测试不替代 GoTrue、PostgREST、令牌验证、目标数据库版本、连接池及生产并发验证。

## 同步协议

| RPC | 参数 | 返回与边界 |
| --- | --- | --- |
| `tebb_personalization_status` | 无 | `contract=tebb.personalization.v2`、当前 `user_id`、`revision`、pgvector 是否启用 |
| `tebb_personalization_apply` | `p_operation_id`、`p_record_id`、`p_expected_version`、`p_action`、可选 `p_payload` | 原子 CAS，返回 `applied/conflict/gone/not_found` 回执；这些业务状态不是 HTTP 失败 |
| `tebb_personalization_operation` | `p_operation_id` | 查询原操作回执，避免断连后换新编号重写 |
| `tebb_personalization_pull` | `p_after=0`、`p_limit=100` | 当前账号变更后的记录与墓碑；`cursor`、`has_more`、`head`，每页 1–100 条 |

所有入口拒绝匿名用户，`user_id` 由服务端 `auth.uid()` 派生，不能在写入参数指定。私有表只允许 authenticated 按 RLS 读自己的数据，普通客户端不能直接增删改表。写函数是固定空 search_path 的 security definer，写入时仍显式按登录身份限定，不信任调用方任意填的身份或数据库主键。

`put` 只用于用户已经确认的内容，示例：

```json
{
  "kind": "preference",
  "category": "communication",
  "text": "先给结论，再补依据",
  "scope": "user",
  "scope_id": ""
}
```

支持的 kind 为 `profile/preference/memory`，category 为 `communication/knowledge/goal/project/other`，不接收 personality/emotion 类型。text 1–4000 字符。scope 为 `user/project/companion`；非 user 范围需要明确、稳定的 scope_id（最多 128 字符）。它只是同一账号的记忆范围，不是项目文件访问授权。可选 `source_device_id` 是设备 UUID，`source_ref` 是最多 256 字符的稳定不透明引用，不上传聊天原文/引用正文。候选与模型推断应先留在本机，服务端不接收候选 state；客户端通过明确的“确认并同步”保存内容；模型工具仍只写原本机来源，不能借此自动上传。API 参数本身不代表模型取得用户确认。

新建预期 version 为 0；更新必须携带当前 version。`disable` 和 `delete` 不带 payload。停用可经新的明确确认 `put` 恢复；删除清除正文和来源字段、保留版本与无正文墓碑；即使记录尚不存在也创建删除围栏，针对同一 ID 的写入均返回 gone。重新确认要创建新记录身份，不能重放旧离线操作。操作表仅保存请求摘要与技术回执，不保留第二份记忆正文。

同一操作编号/同一请求返回原回执，不推进版本；同编号换请求被拒绝。conflict 回执也保持幂等，明确解决后用新编号。`revision` 按账号在数据库短事务中串行分配，不以客户端时钟判定覆盖；不同账号游标不能混用。pull 是当前状态增量，允许多次更改合并为该记录的最新状态，不是完整历史事件日志。没有更多页时游标推进到 head；有更多页时推进到本页最后一条。未来客户端必须在持久保存整页后才能提交游标。

删除墓碑不代表云数据库备份、Supabase 日志或已有历史请求全部物理清除。长期保留/账号删除策略、记录到期、按字段画像唯一性、向量索引、召回与维度将在后续集成固定，当前只启用 pgvector 扩展，没有宣称已实现向量检索。

若数据库端口不可达，可使用官方 CLI 3.0.0 `db query --file <部署SQL> --remote=<ref> --yes` 经 HTTPS 管理 API 执行。需在同一事务中执行已核对的迁移、写入 supabase_migrations.schema_migrations 并通知 PostgREST；执行后回读版本与源 SQL 摘要。结果不明先查原迁移记录，不换编号重复建表，也不通过放宽网络规则解决。

## AI 可调用的验收入口

以下命令在仓库根目录执行。Python 接入只使用现有 httpx，不加载 tebb 数据目录或业务宿主。

```powershell
# 默认不发网络请求；未配置返回 needs_configuration（退出码 2）。
python scripts/check_personalization_cloud.py

# 显式只读连接：无登录令牌为 needs_login（退出码 3）。
# 有令牌时核对 GoTrue 身份、迁移版本、pgvector 与同步页，不发送邮件或写记录。
python scripts/check_personalization_cloud.py --connect

# 本地 HTTP 替身、接入边界与脱敏回归
python -m unittest discover -s tests -p test_personalization_cloud.py -v

# 实际执行迁移、RLS 与同步规则，并经合成 HTTP 身份服务运行 Python 验收入口
npm ci --prefix supabase/tests/runner --ignore-scripts --no-audit --no-fund
npm test --prefix supabase/tests/runner
```

`configured` 只表示静态格式正确；`ready` 只表示当前用户可以读取此后端契约，不证明邮件送达、跨设备完整客户端、真实模型个性化或生产环境已验收。预检失败不会自动补迁移、换密钥、重试写入或回退为本机全局记忆。

真实测试项需配置专用项目和三个短期登录令牌：A/A2 属于同一账号的独立会话，B 属于另一账号。默认运行不联网并返回 not_run（退出码 2）；显式测试仅创建合成记录，验证读取、隔离、版本冲突、回执查询、删除与防复活。

```powershell
python scripts/eval_personalization_cloud.py
# 配好上述 TEBB_CLOUD_* 环境变量，并明确授权专用测试项目后：
python scripts/eval_personalization_cloud.py --live --report E:/Learn_Project/output/cloud-acceptance/report.json
```

脚本在写前保存操作/记录编号，不保存令牌或真实用户身份；只处理本次随机创建的合成记录。验收还运行三个独立产品资料副本（A/A2/B），经过真实 PersonalizationService 和 SQLite 队列验证离线冲突、明确解决与跨副本删除；副本和任务回执保留在报告旁，不保存令牌。失败保留原操作与 cleanup 状态，结果不明先用 `PersonalizationCloud.operation()` 查询；不要直接删报告后换编号重试。清理以无正文墓碑结束，不删除真实资料。已有报告路径会被拒绝覆盖。本地合成 HTTP 身份测试不证明 GoTrue 生产鉴权通过。本批另行通过真实 GoTrue/PostgREST/PostgreSQL 17.11 验证两账号三个资料副本、同版本并发写入、SDK 刷新和单设备退出；SMTP 投递、两台实体设备与真实模型效果仍待验收（#263 / #238）。

## 后续顺序

客户端账号、加密会话、固定账号目录见 #244；确认资料存储、离线同步与记忆检查台接入见 #255。本批已部署真实 Supabase 并验证两个账号、三个独立资料副本；接下来配置邮件通道并做两台实体设备验收；再按 #238 适配候选提炼、相关性选择与效果评测。旧本机资料的明确导入仍需独立预览，不会自动认领。

参考：[Supabase CLI v3](https://supabase.com/docs/guides/local-development/cli/migrating-to-v3)、[数据库迁移](https://supabase.com/docs/guides/deployment/database-migrations)、[邮箱验证码](https://supabase.com/docs/guides/auth/auth-email-passwordless)、[SMTP](https://supabase.com/docs/guides/auth/auth-smtp)、[Free 邮件模板限制](https://supabase.com/changelog/46599-changes-to-email-template-customisation-on-free-tier)、[RLS](https://supabase.com/docs/guides/database/postgres/row-level-security)、[PGlite](https://pglite.dev/docs/about)。
