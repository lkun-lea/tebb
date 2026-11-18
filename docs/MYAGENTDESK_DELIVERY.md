# MyAgentDesk 桌面交付

在 MyAgentDesk 的需求群展开「配对 tebb 设备」，为当前桌面生成一次性配对信息。打开 tebb「设置 → 连接与网络 → MyAgentDesk 交付」，粘贴信息并配对。后续本机自动轮询工作台。配对和派发由工作台账号授权，本机授权随 tebb 当前数据空间保存，设备凭据由 Windows DPAPI 保护。 [实施需求](https://github.com/lkun-lea/myagentdesk/issues/14)

看到派发后点「核对并授权」，核对需求、仓库、固定提交和验收条件，再填写本机克隆路径与本机命令清单。研发清单使用 `implementation`，独立验收按冻结条件使用 `criterion:1`、`criterion:2` 等，发版必过项使用 `check:1` 等。清单的值是参数数组。候选从固定提交生成隔离快照，所有命令在已有 tebb 终端沙箱执行，回传有界原始输出、退出码和本次获准的补丁。 [命令清单示例](https://github.com/lkun-lea/myagentdesk/blob/feat/11-executor-release-pilot/tests/fixtures/delivery-pilot.json) · [沙箱约定](TERMINAL.md)

每个命令用派发与用例合成稳定请求编号。tebb 先持久记录启动意图，再调用终端。重启时按编号查原终端运行，有终态则整理原证据，找不到记录或原运行中断则进入「待核对」。待回传记录保存在当前数据空间的 `memory/myagentdesk`，工作台重新可达后按原派发补传。工作台按绑定设备与现行阶段授权确认回执，已入档请求重放时返回原结果。

开发验收可以在隔离环境通过已有本地认证 RPC 调用 `myagentdesk_delivery`。`status` 返回设备状态、待领取任务和原运行编号，`pair` 接受一次性信息，`approve` 接受派发编号、绝对目录和 JSON 清单。启动与补传由后台轮询统一推进。使用以下命令回归本机恢复和终端规则。

```powershell
uv run --locked python -m unittest discover -s tests -p test_myagentdesk_delivery.py -v
uv run --locked python -m unittest discover -s tests -p test_terminal.py -v
```

打开「待核对」时先查看原本机终端记录，工作台负责人可取消本次尝试并另发。桌面试点执行已经准备的 Git 提交，支持一个补丁文件整体回传。自动编码和分片补传属于后续阶段。
