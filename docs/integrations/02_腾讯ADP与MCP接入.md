# 腾讯 ADP 与 MCP 接入

## 目标、当前能力与外部缺口

本仓库使用 Python MCP SDK v2 提供 Streamable HTTP 服务，具备 MCP `initialize`、`tools/list`、`tools/call` 的协议入口和 5 个 Tool；[tests/test_mcp_runtime.py](../../tests/test_mcp_runtime.py) 中有真实 SDK HTTP/ASGI 接线测试（会畅网络被 Mock）。**尚未有腾讯 ADP 租户真实握手、动态身份 Header 和企业微信端到端证据**，不能据此宣称在线应用已接入。

ADP 端自定义 MCP 的配置方式请核对官方 [新建 MCP 工具](https://cloud.tencent.com/document/product/1759/117855) 文档及当前租户实际能力；本仓库不维护在线 ADP 画布或企微网关。

## 本仓库实际暴露的工具

| 工具 | 用途 | 身份要求 |
| --- | --- | --- |
| `ping_meeting_server` | 服务可用性探针，不访问会畅 | 不需要 |
| `whoami_probe` | 验证动态签名身份是否到达服务 | 需要 |
| `submit_meeting_request` | CREATE/CHECK/UPDATE；外层参数名 `request` | 需要 |
| `continue_meeting_request` | 按 pending 与 revision 补参、选项或取消申请 | 需要 |
| `get_meeting_operation` | 读取同用户原操作状态，不重复执行会畅写入 | 需要 |

五份机器消息契约来自 [src/meeting_reservation/schemas/](../../src/meeting_reservation/schemas/)，MCP `tools/list` 的业务 Tool Schema 是自动展开引用后的投影；`structuredContent` 返回业务结果。实现见 [src/meeting_reservation/mcp_server.py](../../src/meeting_reservation/mcp_server.py)。

## 按依赖顺序的联调流程

1. **本地独立测试**：启动 Streamable HTTP MCP，用客户端/Inspector 完成 `initialize`、`tools/list` 和免身份 `ping_meeting_server`。不要直接把 `/mcp` 当自定义 REST JSON 接口。
2. **网关与可达性**：为 ADP 调用方提供符合安全要求的 HTTPS 地址及访问控制；先核对服务、反向代理与 SDK 的 Host/Origin 策略。
3. **ADP 工具发现**：在测试应用配置 `/mcp` URL，检查 5 个工具、展开后的 `inputSchema/outputSchema` 和业务工具的外层 `request` 是否实际被识别。
4. **结构化结果消费**：用无远端写副作用的输入验证 ADP 是否能读取 `structuredContent.status`、错误与 pending/确认摘要字段，避免把模型自造值当成成功结果。
5. **可信身份链**：企微可信网关核验原始事件身份，每次调用生成短时签名 `X-Meeting-Actor`/`X-Meeting-Signature`。先用 `whoami_probe` 验证不同测试用户的 UserID，且无法跨用户冒用。静态 Header、模型参数或昵称不是动态认证。
6. **跨轮关联**：调用层保存原 `operation_id`、pending ID、revision、有效期和实际会话/用户关联；在继续处理时提供新操作号和原 pending。错误重试使用**同一业务操作号**，不能盲目重新创建。
7. **受控真实写入**：只有身份、站点权限、会畅、ADP 结果和目标环境授权满足后，才在隔离资源验证 CREATE/UPDATE 并考虑开启写开关。

如果当前腾讯 ADP 接入方式**无法动态转发可信签名 Header**，必须先由上游可信代理/网关形成可验证的身份传递方案。这是外部架构前置，不允许为连通而关闭认证。

## ADP 结果分支应如何消费

- `NEED_INPUT` / `NEED_SELECTION` / `CONFLICT`：展示可理解的问题或候选，保留真实 `pending_request_id`、`pending_revision` 和 `expires_at`，下一轮调用 `continue_meeting_request`，不能只靠模型“记住”候选 ID。
- `AVAILABLE`：只说明资源目前看起来可用，不发送“已预约”。
- `COMMITTED`：仅使用后端 `confirmed_meeting` 表示已确认的会畅事实。
- `IN_PROGRESS` / `UNKNOWN`：使用**原 operation_id** 查已存状态；UNKNOWN 不会因查询自动消除，应由有权限人员核实远端。
- `DENIED`/`INVALID`/`FAILED` 等：按安全错误提示，不向用户泄露 APIKey、Token 或签名内容。

真实验收矩阵与记录范围在 [docs/testing/01_测试与联调验收.md](../testing/01_测试与联调验收.md)。本仓库不直接修改生产 ADP 配置或企微网关。
