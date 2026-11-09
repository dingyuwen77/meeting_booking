# 腾讯 ADP · 会畅智云智能会议预订

本仓库提供 **腾讯 ADP → MCP Server → 会畅智云账号模式 OpenAPI** 的 Python 后端。企业微信消息的自然语言理解由 ADP 负责；本服务负责机器契约、可信身份、真实会议读写、冲突处理及结果恢复。

**实现边界（请先读）：** 本仓库已有 MCP 代码、会畅 Provider、SQLite 操作台账与 Fake Provider 测试。代码存在不等于已验证真实会畅/ADP 联通；生产写入默认关闭，需要按 [docs/testing/01_测试与联调验收.md](docs/testing/01_测试与联调验收.md) 完成实际联调后开启。无企业 API Key、siteSign、受信网关和测试环境不能宣称已能真实订会。

## 从哪里开始

- [docs/README.md](docs/README.md)：按推荐顺序阅读架构、契约、集成、操作和测试文档。
- [roadmap/README.md](roadmap/README.md)：当前实现与后续实测门禁，历史路线图单独存档。
- 会畅账号模式 API 依据：供应商提供的《会畅智云账号模式 Open API》v1.0.10（2026-03-27），不将原始文档默认为可公开分发。

## 代码入口

| 入口 | 用途 |
| --- | --- |
| [src/meeting_reservation/mcp_server.py](src/meeting_reservation/mcp_server.py) | MCP Streamable HTTP，提供五个 Tool |
| [src/meeting_reservation/service.py](src/meeting_reservation/service.py) | 会议创建、修改、CHECK、多轮、幂等与错误状态 |
| [src/meeting_reservation/bizvideo.py](src/meeting_reservation/bizvideo.py) | 会畅 API 的 HTTP、GMT 和 Token 映射 |
| [src/meeting_reservation/identity.py](src/meeting_reservation/identity.py) | 验证可信网关签名的企业微信 UserID |
| [src/meeting_reservation/state.py](src/meeting_reservation/state.py) | 单机 SQLite 持久化 |
| [src/meeting_reservation/schemas/](src/meeting_reservation/schemas/) | 五份机器 JSON Schema；以文件为唯一字段契约 |
| [src/meeting_reservation/cli.py](src/meeting_reservation/cli.py) | 原有本地 Schema CLI，仍可单独运行 |

## 首次本地安装

Python 3.11+；新服务基于官方 Python MCP SDK **v2**，并依赖 jsonschema、httpx。建议使用虚拟环境：

```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# Linux/macOS: source .venv/bin/activate
python -m pip install -e ".[dev]"
python -m pytest -q
python -m ruff check src tests
python -m meeting_reservation validate-examples --dir examples
```

复制 [.env.example](.env.example) 作为部署配置参考，真实环境变量从服务管理器或 Secret 管理系统注入，**不提交 .env**。先保持 `MEETING_WRITE_ENABLED=false`。

```bash
python -m meeting_reservation.mcp_server
# 本机默认 http://127.0.0.1:4561/mcp
```

使用 MCP Client/Inspector 验证 initialize、tools/list、tools/call 的只读 `ping_meeting_server`。企微身份必须由可信网关签发 `X-Meeting-Actor` 与 `X-Meeting-Signature`，ADP 自填 UserID 不被信任；见 [docs/architecture/02_身份认证与操作状态.md](docs/architecture/02_身份认证与操作状态.md)。

## 已实现的业务边界

- `CREATE`：会畅视频会议，不是公司实体 A301 等会议室预订。必须有标题、起止时间；会议容量来自显式受控配置。
- `CHECK`：仅查询会畅资源及当前用户自身预约重叠，不创建会议。
- `UPDATE`：先读取并验证原会议信息，再做相对时间平移或绝对时间、名称、会畅虚拟资源修改。原 `SHIFT/PATCH` 已统一为 `time_shift_minutes + changes`。
- `continue_meeting_request`：支持补字段 `SUPPLY_FIELDS`、已保存候选 `SELECT_OPTION` 与取消待处理申请 `CANCEL`。
- `get_meeting_operation`：同一用户可查询已存结果；`UNKNOWN` 必须人工或受控核实，不自动重放会畅写请求。
- 会畅普通预约接口未证实能直接处理 `attendee_queries`（邀请名单）和 `description`，当前明确拒绝此类写入，**不静默忽略**。
- 会畅 `roomId` 是虚拟会议资源标识；只有 `bizvideo-room:<roomId>` 可直连指定虚拟资源，文本 `A301` 被拒绝。

真实权限、并发提交原子性、会畅连接稳定性和 ADP 身份透传仍需独立实测。部署注意事项与安全限制见 [docs/operations/02_部署与故障恢复.md](docs/operations/02_部署与故障恢复.md)。

## 开发限制

没有新增 CI 工作流，也没有自动部署。所有生产凭据保持仓库外部。用户 ID **原样复用企微 UserID**，但绝不因此跳过身份真实性验证。
