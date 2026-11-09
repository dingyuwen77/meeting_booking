# meeting_booking 文档导航

本文目录按**推荐阅读顺序**而非历史创建顺序组织：先理解当前边界，再理解契约，之后查会畅适配、ADP 集成、部署和测试。

| 阅读顺序 | 主题 | 入口 |
| --- | --- | --- |
| 1 | 系统为什么拆成 ADP / MCP / 会畅 | [docs/architecture/01_系统架构与业务边界.md](architecture/01_系统架构与业务边界.md) |
| 2 | 企微 UserID、可信身份和幂等恢复 | [docs/architecture/02_身份认证与操作状态.md](architecture/02_身份认证与操作状态.md) |
| 3 | 五个 JSON Schema 的分工 | [docs/contracts/01_标准化会议协议.md](contracts/01_标准化会议协议.md) |
| 4 | 创建、修改、CHECK、继续处理的状态语义 | [docs/contracts/02_会议操作与状态语义.md](contracts/02_会议操作与状态语义.md) |
| 5 | 会畅 v1.0.10 各接口映射 | [docs/integrations/01_会畅智云OpenAPI适配.md](integrations/01_会畅智云OpenAPI适配.md) |
| 6 | 腾讯 ADP 的实际 MCP 连接要求 | [docs/integrations/02_腾讯ADP与MCP接入.md](integrations/02_腾讯ADP与MCP接入.md) |
| 7 | 首次本地安装和调试 | [docs/operations/01_本地运行与调试.md](operations/01_本地运行与调试.md) |
| 8 | 环境、密钥、单机持久化和回滚 | [docs/operations/02_部署与故障恢复.md](operations/02_部署与故障恢复.md) |
| 9 | Fake/契约/Provider/ADP/企微分层验收 | [docs/testing/01_测试与联调验收.md](testing/01_测试与联调验收.md) |

历史： [docs/archive/01_阶段一契约验收记录.md](archive/01_阶段一契约验收记录.md)、[roadmap/README.md](../roadmap/README.md)。

**事实分层：** 当前功能应从源码和测试确认；字段机器契约只以 [src/meeting_reservation/schemas/](../src/meeting_reservation/schemas/) 为准；会畅真实能力以供应商文档与实际测试为准。未实测的外部能力不能因本地 Fake 测试通过而标为已完成。
