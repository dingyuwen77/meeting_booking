# meeting_booking 项目开发规范

本文件供进入本仓库工作的 Agent 定位事实源、遵守项目边界并选择验证入口，适用于全仓。详细业务解释、字段定义和验收状态继续由下述既有文件维护。

<!-- agent-skills:project-governance:v1 -->
## 项目治理校准状态

- 状态：已校准
- 首次校准日期：2026-11-10（Asia/Shanghai）。该状态仅表示项目规则已按真实文件校准，不表示产品测试、远程 CI 或生产联调通过。
- 后续按任务读取相关实现与规则；只有长期工程事实变化、入口漂移或明确要求刷新时，才定向更新本文件。
- 保留已有有效项目约束。实现或配置偏离正式要求时，不能通过弱化规则消除冲突；证据不足的外部能力保持未确认。后续新增子目录规则时，同时遵守其适用范围。

## 工程基线与事实入口

- 本仓库实现腾讯 ADP → MCP Server → 会畅智云账号模式 OpenAPI 的 Python 后端，同时保留本地契约 CLI。企业微信网关和 ADP 在线工作流不在仓库内实现；不包含前端或实体会议室日历。
- 语言支持 Python 3.11+，采用 setuptools 与 `src/` 包布局；依赖及开发工具以 [pyproject.toml](pyproject.toml) 为准，当前使用官方 Python MCP SDK v2、jsonschema、httpx、pytest 和 Ruff。仓库未维护依赖锁文件，不把某台机器已安装的精确版本当成项目版本约束。
- 安装与运行从 [README.md](README.md)、[docs/operations/01_本地运行与调试.md](docs/operations/01_本地运行与调试.md) 开始；当前文档导航见 [docs/README.md](docs/README.md)。
- 需求、已确认设计、验收范围和剩余外部门禁由 [roadmap/01_实施路线图与任务状态.md](roadmap/01_实施路线图与任务状态.md) 维护；历史归档不作为当前完成状态的证据。

主要链路：可信网关签名身份 → MCP 工具入口 → 身份与契约校验 → 业务服务与 SQLite 台账 → 会畅适配器 → 会畅详情回读 → 结构化结果。

| 事实源 | 责任边界 |
| --- | --- |
| [src/meeting_reservation/mcp_server.py](src/meeting_reservation/mcp_server.py) | Streamable HTTP、五个工具、正式 Schema 投影和连接生命周期；不是普通 REST 接口 |
| [src/meeting_reservation/contract.py](src/meeting_reservation/contract.py) 与 [src/meeting_reservation/schemas/](src/meeting_reservation/schemas/) | 五份 JSON Schema 的加载、引用展开和跨字段时间校验 |
| [src/meeting_reservation/service.py](src/meeting_reservation/service.py) | 创建、查询、修改、多轮补参、冲突、幂等与结果状态 |
| [src/meeting_reservation/identity.py](src/meeting_reservation/identity.py) | 可信网关 HMAC 身份验证和企业成员隔离 |
| [src/meeting_reservation/state.py](src/meeting_reservation/state.py) | SQLite 操作台账及待处理申请，首次运行建表 |
| [src/meeting_reservation/bizvideo.py](src/meeting_reservation/bizvideo.py) | 会畅端点、Token、表单、GMT 时间及供应商错误映射 |
| [src/meeting_reservation/settings.py](src/meeting_reservation/settings.py) | 环境变量配置与默认关闭的真实写入开关 |
| [src/meeting_reservation/cli.py](src/meeting_reservation/cli.py) | 本地 JSON 契约校验；保留 `meeting-contract` 与 `python -m meeting_reservation` 入口 |

架构与身份机制由 [docs/architecture/01_系统架构与业务边界.md](docs/architecture/01_系统架构与业务边界.md)、[docs/architecture/02_身份认证与操作状态.md](docs/architecture/02_身份认证与操作状态.md) 解释；按功能查找实现与测试请用 [docs/architecture/03_代码结构与调用链导航.md](docs/architecture/03_代码结构与调用链导航.md)。

## Contract 与业务不变项

五份版本化 JSON Schema 是唯一字段契约源；[examples/](examples/) 是示例，不另立定义。修改契约时同时检查校验器、MCP 投影、CLI、示例、测试及 ADP 消费说明，不手写第二套工具字段。当前 V1 仍是未完成租户联调的候选；正式冻结后的破坏性变化需要新版本。语义解释见 [docs/contracts/01_标准化会议协议.md](docs/contracts/01_标准化会议协议.md)、[docs/contracts/02_会议操作与状态语义.md](docs/contracts/02_会议操作与状态语义.md)。

- ADP 负责提取意图和多轮界面；真实成员身份来自每次工具调用的可信签名 Header。企微 UserID 原样作为会畅 userId，但模型参数、昵称或静态 Header 不能代替认证；不能为了联通关闭身份验证。
- CREATE 需要标题和起止时间；会议方数来自受控服务配置。CHECK 只检查会畅资源与本人预约重叠，不创建或修改会畅会议；经业务 Tool 执行时仍写本地操作台账（缺参可产生 pending）。查询可用不等于最终提交成功。
- UPDATE 先读取原会议并校验归属和状态，再更新同一会议。保持 `time_shift_minutes + changes` 的统一结构；相对与绝对时间互斥，未指定字段保持原值，不恢复旧 SHIFT/PATCH 模式。
- 会畅 `roomId` 是虚拟资源；仅接受明确的 `bizvideo-room:<roomId>`，不能把 A301 等实体会议室名称映射过去。当前不支持自动邀请、会议描述写入或取消已创建会议；不支持的写入必须明确拒绝，不静默丢弃。
- 只有写后回读完整、归属与会议 ID 核对正确且结果契约有效，才能返回 COMMITTED。超时、断连或写后确认失败产生 UNKNOWN 时，禁止自动重放或换操作号碰运气重建；通过原操作查询及受控人工核实恢复。
- 可信调用层提供稳定 `operation_id`；同一操作号必须绑定同一身份与同一请求。pending 必须检查持有人、revision、有效期及单次消费；补参仍须重新校验原意图。CANCEL 只取消待处理申请，不影响真实会议。
- 输入时间保持 Schema 要求的显式数值时区偏移，并按真实瞬时比较；会畅适配边界使用 GMT/UTC，不把协议时间直接改为本地时间。具体供应商映射见 [docs/integrations/01_会畅智云OpenAPI适配.md](docs/integrations/01_会畅智云OpenAPI适配.md)。

## 开发与验证入口

按本地运行文档安装并激活项目虚拟环境后，现有验证命令为：

```bash
python -m pytest -q
python -m ruff check src tests
python -m compileall -q src
python -m meeting_reservation validate-examples --dir examples
```

按实际改动选择验证范围；仅变更研发说明时检查事实、引用、格式与变更范围，不把产品测试写成已执行。涉及业务、身份、持久化、SDK 或打包时，按 [docs/testing/01_测试与联调验收.md](docs/testing/01_测试与联调验收.md) 补相应证据。

| 现有测试 | 主要证明范围 |
| --- | --- |
| [tests/test_contracts.py](tests/test_contracts.py)、[tests/test_unified_update.py](tests/test_unified_update.py) | 正式 Schema、示例、时间与统一 UPDATE |
| [tests/test_cli.py](tests/test_cli.py) | CLI 输入校验、错误与退出码 |
| [tests/test_booking_service.py](tests/test_booking_service.py) | Fake Provider、真实 SQLite、受控并发、身份、多轮及 HTTP Mock 适配 |
| [tests/test_mcp_runtime.py](tests/test_mcp_runtime.py) | 真实 SDK HTTP 协议入口，经身份、业务、SQLite 到适配器的接线；供应商网络被隔离 |

Fake、HTTP Mock、本地 SDK 测试不能证明真实会畅、ADP 或企业微信已接通，也不能证明供应商提交原子性或严格 exactly-once。源码测试不代替正式包、容器及目标环境验证。

## 文档、CI 与 Git 边界

- 当前说明维护在 [docs/README.md](docs/README.md) 导航的架构、契约、集成、操作和测试专题中。行为变化时同步直接相关说明、示例与验收状态；机器字段留在 Schema，不在本文件复制完整定义。
- 沿用项目按主题分类、中文阅读编号的文档结构；当前入口以 [docs/README.md](docs/README.md) 为准。阶段一历史原文位于 [docs/archive/](docs/archive/) 与 [roadmap/archive/](roadmap/archive/)；不保留重复的历史跳转壳文件，不将新需求写回历史归档。
- 沿用路线图承载需求和验收状态、任务记录及获授权 PR 承载实施与验证证据的现有方式；当前没有独立 Change/RFC/ADR 制度，不为日常开发并行增设一套。
- 仓库当前没有 GitHub Actions 工作流或自动部署，不因治理引导新增 CI。没有工作流或检查结果不能写成“CI 通过”，也不能据此推断远程分支保护、Review 或合并门禁不存在。
- Git 操作遵守当前任务授权与实际平台门禁。历史路线图中的单次 Review 豁免不延续到后续任务；本地验证、提交和推送均不等于合并、发布或生产启用。

## 配置、部署与未确认事项

- [.env.example](.env.example) 只作脱敏配置模板。Python 不自动加载 `.env`，实际值由运行环境注入；Compose 使用环境文件。不得把 API Key、Token、身份签名、会议密码、敏感入会链接或完整原始请求写入治理文档、日志、fixture 或 Git；本地文件忽略规则见 [.gitignore](.gitignore)。
- 真实写入默认关闭。只有完成真实站点、可信网关、ADP 与企微验收并取得目标环境授权后，才允许开启 `MEETING_WRITE_ENABLED`；治理校准和本地测试不能解除该门禁。
- 现有 [Dockerfile](Dockerfile)、[compose.yaml](compose.yaml) 面向单机部署，Compose 指定 `linux/arm64`、宿主回环端口及 SQLite 持久卷。保持保守单实例与共享持久化边界，不把互不共享台账的多副本当成受支持部署。
- 修改台账结构、升级或恢复前核对现有数据与备份；当前只有启动建表，没有独立版本化 Migration 工具。回滚保留操作历史并关闭写入，不会撤销已在会畅创建的会议；UNKNOWN 仍需核实。具体操作由 [docs/operations/02_部署配置与运行维护.md](docs/operations/02_部署配置与运行维护.md) 和 [docs/operations/03_故障排查与恢复.md](docs/operations/03_故障排查与恢复.md) 维护。
- 未确认：供应商原 PDF 未入库；仓库记录的 v1.0.10 映射仍需原文与真实站点复核。真实权限、容量、提交原子性、特殊字段保留、并发及超时恢复，以及 ADP 动态身份透传和企微端到端，均不能从本地测试推导为通过。后续按 [docs/testing/01_测试与联调验收.md](docs/testing/01_测试与联调验收.md)、[docs/integrations/02_腾讯ADP与MCP接入.md](docs/integrations/02_腾讯ADP与MCP接入.md) 取得证据。
