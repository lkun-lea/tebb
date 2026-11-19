# MyAgentDesk 桌面交付

在 MyAgentDesk 的需求群展开「配对 tebb 设备」，为当前桌面生成一次性配对信息。打开 tebb「设置 → 连接与网络 → MyAgentDesk 交付」，粘贴信息并配对。后续本机自动轮询工作台。配对和派发由工作台账号授权，本机授权随 tebb 当前数据空间保存，设备凭据由 Windows DPAPI 保护。 [实施需求](https://github.com/lkun-lea/myagentdesk/issues/14)

看到派发后点「核对并授权」，核对需求、仓库、固定提交和验收条件，再填写本机克隆路径与本机命令清单。研发清单使用 `implementation`，独立验收按冻结条件使用 `criterion:1`、`criterion:2` 等，发版必过项使用 `check:1` 等。清单的值是参数数组。候选从固定提交生成隔离快照，所有命令在已有 tebb 终端沙箱执行，回传有界原始输出、退出码和本次获准的补丁。 [命令清单示例](https://github.com/lkun-lea/myagentdesk/blob/feat/11-executor-release-pilot/tests/fixtures/delivery-pilot.json) · [沙箱约定](TERMINAL.md)

每个命令用派发与用例合成稳定请求编号。tebb 先持久记录启动意图，再调用终端。重启时按编号查原终端运行，有终态则整理原证据，找不到记录或原运行中断则进入「待核对」。待回传记录保存在当前数据空间的 `memory/myagentdesk`，工作台重新可达后按原派发补传。工作台按绑定设备与现行阶段授权确认回执，已入档请求重放时返回原结果。

在工作台选择「从固定规格提交自动编码」后，tebb 会展示冻结的需求正文和验收条件。本机授权时每行填写一个允许 Agent 读写的仓库相对路径。Pi SDK 使用 tebb 已配置模型修改隔离快照中的已有 UTF-8 文本文件，由 Git 生成补丁。研发仍需要提供单独授权的自测命令。独立验收者在另一个隔离快照上应用回传补丁，再运行自己的验收清单。

自动编码开始前保存稳定的编码运行编号。重启后只有启动意图时，原尝试进入「待核对」。自测通过后将补丁和回执保存在本地待回传记录中。桌面按 32 KiB 切分补丁，登记分片和完整文件的 SHA-256，再按服务端返回的缺失序号上传。即使某片已保存、其确认响应丢失，重启后也只上传服务端仍缺的分片。

开发验收可以在隔离环境通过已有本地认证 RPC 调用 `myagentdesk_delivery`。`status` 返回设备、运行编号与分片进度，`pair` 接受一次性信息，`approve` 接受派发编号、绝对目录和 JSON 清单；自动编码另外接受 `sources`。启动与补传由后台轮询统一推进。使用以下命令回归本机恢复、补丁生成和终端规则。

```powershell
uv run --locked python -m unittest discover -s tests -p test_myagentdesk_delivery.py -v
uv run --locked python -m unittest discover -s tests -p test_terminal.py -v
```

打开「待核对」时先查看原本机记录，工作台负责人可取消本次尝试并另发。自动编码的候选以固定基准和补丁摘要标识。发布需要另行集成为真实提交并核对该提交的 CI。
