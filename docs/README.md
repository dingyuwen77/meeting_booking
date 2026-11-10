# meeting_booking 文档导航

本目录解释**当前实现和使用方式**；按阅读先后编号，不以编号推断创建时间。新接手项目先读“总览 → 身份/状态 → 契约”，需要开发、部署或联调时再按任务阅读后续专题。

## 推荐阅读顺序

| 顺序 | 读者问题 | 当前说明 |
| --- | --- | --- |
| 1 | 系统负责哪一段，其他组件是否已经实现？ | [docs/architecture/01_系统架构与业务边界.md](architecture/01_系统架构与业务边界.md) |
| 2 | 企微 UserID、可信身份、幂等和 pending 为什么需要？ | [docs/architecture/02_身份认证与操作状态.md](architecture/02_身份认证与操作状态.md) |
| 3 | 想修改功能应该读哪个文件和测试？ | [docs/architecture/03_代码结构与调用链导航.md](architecture/03_代码结构与调用链导航.md) |
| 4 | ADP/MCP 的 JSON 消息由什么定义？ | [docs/contracts/01_标准化会议协议.md](contracts/01_标准化会议协议.md) |
| 5 | CREATE/CHECK/UPDATE/补参/UNKNOWN 如何分支？ | [docs/contracts/02_会议操作与状态语义.md](contracts/02_会议操作与状态语义.md) |
| 6 | 会畅请求如何映射，哪些仍待真实验收？ | [docs/integrations/01_会畅智云OpenAPI适配.md](integrations/01_会畅智云OpenAPI适配.md) |
| 7 | ADP 如何连接 MCP，动态身份怎么传？ | [docs/integrations/02_腾讯ADP与MCP接入.md](integrations/02_腾讯ADP与MCP接入.md) |
| 8 | 如何本地安装、调试 CLI 与 MCP？ | [docs/operations/01_本地运行与调试.md](operations/01_本地运行与调试.md) |
| 9 | 如何部署、配置网络、备份和回滚？ | [docs/operations/02_部署配置与运行维护.md](operations/02_部署配置与运行维护.md) |
| 10 | 遇到错误从哪一层查、如何安全恢复？ | [docs/operations/03_故障排查与恢复.md](operations/03_故障排查与恢复.md) |
| 11 | 什么测试证明什么；缺哪些外部验收？ | [docs/testing/01_测试与联调验收.md](testing/01_测试与联调验收.md) |

## 事实来源与状态

- **字段与格式**：五份版本化机器 Schema 在 [src/meeting_reservation/schemas/](../src/meeting_reservation/schemas/)；运行校验在 [src/meeting_reservation/contract.py](../src/meeting_reservation/contract.py)。Markdown 和示例不复制第二份机器定义。
- **现有行为**：以当前 [src/meeting_reservation/](../src/meeting_reservation/) 实现、[tests/](../tests/) 回归及对应 revision 为准。代码与已确认需求冲突时先报告实现缺陷，不通过改文档合法化错误。
- **外部能力**：会畅原 PDF 尚未入库且需要与真实站点复核；腾讯 ADP、企微可信网关和全链路用户行为未经真实验收。文档里的操作流程不是平台已接通的证据。
- **当前计划与验收**：[roadmap/01_实施路线图与任务状态.md](../roadmap/01_实施路线图与任务状态.md) 是状态 Owner；具体执行证据由关联 PR/测试记录承担。
- **历史快照**：[docs/archive/01_阶段一契约验收记录.md](archive/01_阶段一契约验收记录.md)、[docs/archive/02_阶段一协议候选快照.md](archive/02_阶段一协议候选快照.md)、[roadmap/archive/README.md](../roadmap/archive/README.md)。其中的“当前、下一步”只描述当时，不参与当前能力判断。

维护规则：当前专题只保留一个完整解释 Owner；其他页面提供必要上下文和链接。人读文档采用各英文分类目录内独立的 `NN_中文主题.md` 阅读编号；稳定入口 `README.md`、工程规则 `AGENTS.md` 和机器文件不为编号改名。
