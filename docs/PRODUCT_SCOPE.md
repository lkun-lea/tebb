# tebb 产品边界与 MyAgentDesk 联动

tebb 聚焦 Windows 桌面个人 Agent、本机项目与文件、现有工具和日程。已确认的 [FastAPI、Pi SDK、云端运行与手机接续](CLOUD_MULTICLIENT_ARCHITECTURE.md) 继续作为 tebb 的架构路线。原 [#314](https://github.com/lkun-lea/tebb/issues/314) 的多成员协作实施移至 [MyAgentDesk](https://github.com/lkun-lea/myagentdesk)，原型与讨论保留供追溯。已有开发团队代码与历史记录按现有产品契约维护，未来的协作迭代由 MyAgentDesk 路线图管理。

首版联动通过 GitHub Issue、PR、提交和构建链接。用户可在 tebb 打开本机项目执行，经本人选择后把候选或验证证据链接挂回 MyAgentDesk 的原需求。MyAgentDesk 持有阶段状态、人员分派与交付结论，tebb 持有本机环境、目录授权与执行回执。

后续如需一键交接，由 MyAgentDesk 传递任务引用和候选版本，tebb 让用户明确授权目录和执行，用户预览后选择回传的证据。两端按自己的账号和权限处理，使用请求 ID 去重。详见 [MyAgentDesk 联动设计](https://github.com/lkun-lea/myagentdesk/blob/main/docs/design/TEBB_INTEGRATION.md)。
