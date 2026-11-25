# 单用户 Linux 任务执行节点

云端新建任务由服务器上的 tebb 调度。服务器的 SQLite 数据和工作区保存在 `/var/lib/tebb`，应使用持久磁盘。已有 Windows 会话、已启动的子进程和仅存在于 PC 的文件需要单独处理。此部署使用 SSH 隧道访问个人后台，不向公网开放后台 RPC。

## 安装与启动

在可使用 systemd 的 Ubuntu 主机上，将本次源码放入 `/opt/tebb`，用 Python 3.11 或更高版本准备 `/opt/tebb/.venv` 并安装项目依赖。模型连接需要在服务器的独立工作区配置。本次阿里云 ECS 使用独立 Python 3.12 虚拟环境。Ubuntu 22.04 的 systemd 通过 CREDENTIALS_DIRECTORY 向服务传递凭据目录。

```sh
cd /opt/tebb
sudo install -d -m 0700 /etc/tebb
sudo sh -ec 'if [ ! -e /etc/tebb/rpc-token ]; then umask 077; openssl rand -hex 32 > /etc/tebb/rpc-token; fi'
sudo install -m 0644 deploy/tebb-cloud.service /etc/systemd/system/tebb-cloud.service
sudo systemctl daemon-reload
sudo systemctl enable --now tebb-cloud
systemctl is-active tebb-cloud
curl --fail http://127.0.0.1:8765/health
```

在管理电脑使用 `ssh -N -L 8765:127.0.0.1:8765 ubuntu@主机地址` 建立临时访问通道。安全组仅允许管理端访问 SSH。关闭 SSH 或关闭管理电脑后，systemd 继续运行调度进程。业务 RPC 还需要独立的 Bearer 凭据。该凭据具有整个个人后台的权限，不应随 APK 分发。

## 验证

用隔离数据执行 `python -m unittest tests.test_execution_flow`，覆盖澄清、回答后恢复同一任务、重启读取和取消。模型由测试替身提供。服务器启动时会主动打开原任务库并启动调度；中断的外部动作按原执行器的恢复规则处理。

远端冒烟检查包括健康检查返回 200、匿名 `POST /rpc` 被拒、经授权的 `load_collaboration` 返回成功。正式验收应再用已授权的模型创建真实云端任务，管理电脑离线后，从另一台设备核对原运行编号和完成结果。当前 Android 的局域网配对协议只适用于局域网电脑。

## Docker 沙箱运行环境

阿里云 ECS 可以在实例详情的「扩展程序」中安装 Docker 社区版。宿主机上的 tebb 后端仍由 systemd 管理；Docker 供后续任务沙箱使用。安装后可在实例上用 `sudo docker version` 检查客户端与服务端，再用 `systemctl is-active docker` 检查守护进程。沙箱执行器接入前，普通 tebb 任务仍沿用现有执行方式。Docker 套接字只供受信任的宿主管理组件使用。

## PC 云端聊天

PC 主聊天在模型旁选择本地或云端，Android 在输入框下方选择执行位置。绑定电脑目录的会话固定在本地，手机回答 Windows 待确认问题时沿用原任务。云端发送使用当前空间的登录会话。桌面后台只向固定的 HTTPS 地址发送访问令牌。服务器通过 Supabase 的用户接口验证令牌，并与这台服务器配置的单个用户 UUID 比对。服务端的 systemd 环境需配置 TEBB_CHAT_OWNER、TEBB_CLOUD_URL 和 TEBB_CLOUD_PUBLISHABLE_KEY。免费文本对话调用 ECS 回环地址上的 Ollama，使用 qwen3:0.6b，不需要 PC 的模型密钥。

公网入口参考 tebb-chat.nginx.conf。安装该站点后，用 nginx -t 检查配置，启用 HTTPS，并为 Certbot 配置成功续期后的 nginx reload。桌面通过 POST /cloud/v1/messages 提交消息，每次重试复用请求 UUID。GET /cloud/v1/events 通过 SSE 返回最近 20 轮的持久化状态与回复，客户端按 conversation 订阅，重新打开同一云端会话可以看到离开后的结果。GET /cloud/v1/tools 使用相同的账号鉴权，返回工具名称、说明和参数。PC 只注册本版本内置且能执行的工具。

部署免费模型时，将 Ollama 的 11434 端口绑定到宿主机 127.0.0.1，持久化模型目录，拉取 qwen3:0.6b。用实际账号提交一条消息并核对 SSE 中同一 run_id 的 succeeded 和回答，可同时验证登录、调度和模型推理。

这台 CPU 实例使用 Alpine 3.23 仓库中的 Ollama CPU 包。可从仓库根目录复现服务：

```sh
docker build -f deploy/ollama-cpu.Dockerfile -t tebb-ollama-cpu:alpine .
docker run -d --name tebb-ollama-cpu --restart unless-stopped \
  --cpus=1.5 --memory=2g -p 127.0.0.1:11434:11434 \
  -e OLLAMA_HOST=0.0.0.0 -e OLLAMA_NUM_PARALLEL=1 -e OLLAMA_CONTEXT_LENGTH=2048 \
  -v tebb-ollama:/root/.ollama tebb-ollama-cpu:alpine
docker exec tebb-ollama-cpu ollama pull qwen3:0.6b
```

### 免费模型实测（2026-11-24）

个人 ECS 上的 Ollama 使用 CPU、单路推理、2048 token 上下文，容器限额为 1.5 CPU 和 2 GiB。重启容器后仍可读取模型。以下服务内测量从请求发起算到首个可见字及生成结束，不含公网往返。

| 中文问题 | 首字 | 完成 | 观察 |
| --- | ---: | ---: | --- |
| 一句自我介绍 | 4.54 秒 | 8.55 秒 | 给出了中文问候 |
| 总结手机登录和电脑扫码的测试 | 1.55 秒 | 3.81 秒 | 一句话保留两项测试 |
| 解释确认与取消覆盖文件 | 1.49 秒 | 32.53 秒 | 128 token 测试上限截断了答案。另一次通过产品接口复测，把取消覆盖错误地解释成移除文件 |

生成期间后台健康检查三次均返回 200，耗时约 21 毫秒。两条公网任务并发提交后，第二条排队 11.23 秒，两条都成功结束。复用请求编号返回了原任务，断开 SSE 再订阅可以取回结果。这轮每秒采样一次，观察到容器内存最高 856.2 MiB。三条单独的 PC 转发测试从提交到读回耗时 10.0–32.5 秒。

当前规格适合体验免费文本聊天和简单总结。涉及文件修改的确认应展示原任务的问题及选项，由用户作答。上述测试关闭了提交客户端，未实际关闭 Windows 主机，也未验证 Android 真实账号从手机收取回复。

### 日志排查

1. 在 PC 发送失败提示中复制请求编号，或在云端会话里复制任务编号。
2. 在 ECS 执行 journalctl -u tebb-cloud --since today --grep '请求编号或任务编号'。accepted 将请求编号关联到任务编号，observed 表示订阅端读取到的状态。鉴权故障可按 auth_failed 或 owner_denied 查询。
3. 任务库中的 tasks 和 events 保存运行状态、事件顺序和错误；即使订阅中断也可通过任务编号查询。模型调用详情的记录范围见 docs/AGENT_DEBUG.md。请求未到达服务端时查看 nginx 错误日志和 PC HTTPS 连接错误。此配置关闭通用访问日志，未设置集中告警、归档或保留期。

开发验证：在仓库根目录执行 python -m unittest tests.test_http_api。云端聊天用例使用临时 SQLite、替代身份校验和独立测试 worker，覆盖跨账号拒绝、去重、SSE 回复和重新订阅。

PC 打开会话时先显示该账号及会话的本机缓存。SSE 历史回放和实时更新按任务编号合并。服务每次订阅回放最近 20 轮，此前在本机收到的记录可继续显示。返回创建时间的任务与本地消息按时间排序。切换时旧订阅取消，延迟到达的提交回执只更新原会话。在 client/ 执行 `node --test tests/cloud-chat.test.cjs` 可验证缓存首屏、重复回放和延迟回执。


### 配对手机加密状态中转（2026-11-26）

个人 ECS 已增设 `GET/POST /cloud/v1/device-snapshot`，复用聊天服务的 Supabase 账号校验。服务仅在内存保留每台设备两个方向的最新密文，45 秒自动清除。密钥在用户批准配对时派生，AES-GCM 将设备与方向绑定；ECS 不持有解密密钥。Windows 核对账号、设备、新鲜度和原问题版本后才执行改期或回复，手机以 Windows 业务回执判断成功。重新配对取得新密钥。

本次只为线上现有 Python 服务安装中转模块、注册路由，并在原有 nginx 站点添加单一路径。配置检查、重启后健康检查以及匿名拒绝均已验证。使用已登录的真实账号测试了随机设备发布与取回、授权原文、原运行回复、重复请求、撤卡和过期清理。执行命令及范围见[移动端路线](../docs/MOBILE_AGENT_ROADMAP.md)。
