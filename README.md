# 腾讯 ADP · 会畅智云智能会议预订

本项目是 **腾讯 ADP → MCP Server → 会畅智云账号模式 OpenAPI** 链路中的 Python 会议执行后端。它接收已结构化的会议意图，执行身份与业务校验、会畅资源检查及会议创建/修改，并记录操作结果以支持查询与多轮补参。

**当前边界：** 本仓库包含 MCP 服务、会畅适配器、SQLite 台账、JSON Schema 和测试；**不包含**企业微信网关、ADP 在线工作流或公司实体会议室日历。已有本地 Fake/HTTP Mock/SDK 测试，**尚无真实会畅站点、腾讯 ADP 租户及企业微信端到端验收证据**。真实写入默认关闭。

## 快速开始

要求 Python 3.11+，依赖和入口以 [pyproject.toml](pyproject.toml) 为准。

```bash
python -m venv .venv
# Windows PowerShell：.\.venv\Scripts\Activate.ps1
# Linux/macOS：source .venv/bin/activate
python -m pip install -e ".[dev]"
python -m meeting_reservation validate-examples --dir examples
python -m meeting_reservation.mcp_server
```

本地默认 MCP 地址为 `http://127.0.0.1:4561/mcp`；这是 **MCP Streamable HTTP**，不是自定义 REST JSON 接口。使用 MCP Client/Inspector 调用不依赖会畅凭据的 `ping_meeting_server`。本地 Python **不会自动加载** `.env`；参考 [.env.example](.env.example) 配置环境变量，保持 `MEETING_WRITE_ENABLED=false`。

也可用 `meeting-contract validate intent examples/create.intent.json` 校验单份示例。**CLI 仅校验契约，不负责订会**。完整操作见 [docs/operations/01_本地运行与调试.md](docs/operations/01_本地运行与调试.md)。

## 已实现的功能与限制

- `CREATE`：校验必要字段、会畅资源与本人时段冲突，启用写入时提交并回读确认。
- `CHECK`：不对会畅执行写操作；通过业务工具调用时仍会记录本地操作状态或待补参申请。
- `UPDATE`：先查原会议和归属，再执行标题、绝对时间、相对时间平移或会畅虚拟资源变更；不支持旧 `SHIFT/PATCH` 双模式。
- 支持待处理申请的补字段、候选选择与取消，以及按 `operation_id` 查询已存结果。`UNKNOWN` 不是成功，也不能盲目重放。
- `roomId` 是会畅虚拟资源，仅接受 `bizvideo-room:<roomId>`，不将 A301 等实体会议室名称自行映射；不支持邀请参会者、会议描述写入、已创建会议取消。

业务操作必须经可信网关签发的动态身份 Header 验证；**企微 UserID 原样作为会畅 userId，不代表 UserID 本身可用来认证**。真实写入须在独立环境完成权限、身份、会畅、ADP 与企微验收后按授权启用。

临时身份参数 POC 可单独开启 `identity_binding_probe`，通过专用静态 Header 校验后回显 `actor_user_id`，不访问业务台账或会畅。它默认关闭，不能用于员工身份认证；开启、调用和关闭方式见 [docs/operations/01_本地运行与调试.md](docs/operations/01_本地运行与调试.md)。

## 文档入口

| 需要做的事 | 从这里开始 |
| --- | --- |
| 按顺序理解系统 | [docs/README.md](docs/README.md) |
| 定位功能代码、调用链与测试 | [docs/architecture/03_代码结构与调用链导航.md](docs/architecture/03_代码结构与调用链导航.md) |
| 配置会畅与 ADP 连接 | [docs/integrations/01_会畅智云OpenAPI适配.md](docs/integrations/01_会畅智云OpenAPI适配.md)、[docs/integrations/02_腾讯ADP与MCP接入.md](docs/integrations/02_腾讯ADP与MCP接入.md) |
| 部署、备份和回滚 | [docs/operations/02_部署配置与运行维护.md](docs/operations/02_部署配置与运行维护.md) |
| 故障定位与 UNKNOWN 核实 | [docs/operations/03_故障排查与恢复.md](docs/operations/03_故障排查与恢复.md) |
| 确认本地与外部验收门禁 | [roadmap/01_实施路线图与任务状态.md](roadmap/01_实施路线图与任务状态.md)、[docs/testing/01_测试与联调验收.md](docs/testing/01_测试与联调验收.md) |

当前仓库没有 GitHub Actions 工作流或自动部署；没有自动检查不能写作“CI 通过”。任何真实会畅写入、发布或部署都需要单独授权与环境证据。
