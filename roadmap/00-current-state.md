# 00｜当前代码盘点与证据边界

> 目的：让下一位开发者明确“已有事实 / 计划 / 未验证”，防止把 67 项 JSON 测试误当成真实会议系统已可用。

## 1. 本次检查范围与状态

检查目标：Windows 本地 E:\work\05_ADP\03_Meeting_reservation，2026-11-04（北京时间）。

已实际读取：项目根 README、pyproject、docs/CONTRACT、docs/PHASE1、Python 入口和校验器、5 份 JSON Schema、3 个测试文件、具有代表性的示例。目录列表显示没有其他业务服务源码或正式的 ADP 画布文件；**“本目录未发现”不等于证明其他外部系统不存在**。

本项目及检查过的适用上级目录没有 AGENTS.md，项目根没有 CONTRIBUTING.md；本项目目录未找到 Git 仓库，故当前无 branch/HEAD/PR 证据。未初始化 Git，也未修改已有工程代码。

## 2. 已验证实现

| 能力 | 判断 | 当前唯一事实源 |
|---|---|---|
| Python 打包与 CLI 入口 | 已实现 | [pyproject.toml](../pyproject.toml)、[src/meeting_reservation/cli.py](../src/meeting_reservation/cli.py) |
| 5 种 JSON 消息的 Schema | 已实现，**未对外冻结** | [docs/CONTRACT.md](../docs/CONTRACT.md) 和 [src/meeting_reservation/contract.py](../src/meeting_reservation/contract.py) |
| CREATE、CHECK、UPDATE、OTHER 意图结构 | 已实现契约，不是业务执行 | [src/meeting_reservation/schemas/meeting-intent.v1.schema.json](../src/meeting_reservation/schemas/meeting-intent.v1.schema.json) |
| 相对时间偏移与字段修改合并 | 已实现契约 | [tests/test_unified_update.py](../tests/test_unified_update.py) |
| 契约校验、时间顺序判断、本地 URN 引用 | 已实现 | [src/meeting_reservation/contract.py](../src/meeting_reservation/contract.py) |
| JSON 示例与回归 | 已验证 | [tests/test_contracts.py](../tests/test_contracts.py)、[tests/test_cli.py](../tests/test_cli.py) |
| 阶段一设计与历史验证记录 | 已存在 | [docs/PHASE1.md](../docs/PHASE1.md) |

注意：现有 UPDATE 的真实结构是 **update.time_shift_minutes + update.changes**，可同时修改非时间字段；不是早期讨论过的 SHIFT/PATCH 双模式，开发时必须以现有 Schema 为准。

## 3. 本轮实际运行的新鲜证据

在本机使用 D:\python314\python.exe（报告版本 Python 3.14.7），环境变量 PYTHONPATH 指向项目 src：

~~~powershell
Set-Location -LiteralPath 'E:\work\05_ADP\03_Meeting_reservation'
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
& 'D:\python314\python.exe' -m pytest -q
& 'D:\python314\python.exe' -m ruff check src tests
& 'D:\python314\python.exe' -m meeting_reservation validate-examples --dir examples
~~~

**实际结果：** pytest 67 passed；ruff All checks passed；18 份示例均校验通过；命令各退出码为 0。

证据仅覆盖当前源码所实现的结构、CLI 和校验器；本轮未重新执行 wheel 打包，也未运行 MCP/ADP/企业微信/真实会议系统测试。过去的 wheel 检查记录在 [docs/PHASE1.md](../docs/PHASE1.md)，不扩张为本轮运行证据。

## 4. 还没有实现的能力

| 能力 | 当前结论 | 需要的最小下一步 |
|---|---|---|
| MCP 服务器启动、initialize、tools/list、tools/call | 未实现 | 测试 MCP + ADP 工具发现与调用 |
| 可信最终用户身份与会议权限 | 未实现 | 身份探针 + 鉴权链路决策 |
| 会议系统适配器与真实会议数据 | 未实现 | 对接真实 API/测试环境 |
| 会议室冲突判定和提交保护 | 未实现 | Provider 原子预订能力核对及测试 |
| 创建和修改会议的持久化副作用 | 未实现 | 核心业务模块和真实集成测试 |
| pending 状态、操作幂等、失败后恢复 | 未实现 | 状态机/存储/事务或等价机制 |
| ADP 意图提取、工具节点、状态路由 | 未实现 | 真实工作流配置和可导出证据 |
| 企微机器人接入及多轮对话 | 未实现 | 真实渠道联调 |

项目中存在对应的消息示例和结果状态，**只能说明定义了格式，不能证明这些状态已由实际服务产生**。

## 5. 已识别的设计/接口断口

**D01 — NEED_INPUT 不能直接在同一 pending 申请上补字段（高优先级）。**
当前 [src/meeting_reservation/schemas/meeting-result.v1.schema.json](../src/meeting_reservation/schemas/meeting-result.v1.schema.json) 支持 NEED_INPUT + pending ID；但 [src/meeting_reservation/schemas/meeting-continue.v1.schema.json](../src/meeting_reservation/schemas/meeting-continue.v1.schema.json) 只支持 SELECT_OPTION/CANCEL，无法上传“补充结束时间”等自由参数。因此未来业务流程若直接设计“追问后继续”，会在契约边界断开。**当前只是未来设计缺口，不是本轮 67 项测试失败。**

**D02 — COMMITTED 的可结构化回执不足。**
当前结果以 meeting_id/message 为主，无法由正式字段单独确定最终时间、会议室和参会人。后续应由会议系统已验证回读，或在结果契约增加经过后端确认的会议摘要，ADP 不得凭旧提取字段自行宣布最终时段。

**D03 — 幂等键的稳定来源未定义为实际实现。**
[docs/CONTRACT.md](../docs/CONTRACT.md) 明确禁止直接假设 SYS.RequestId 就是稳定业务操作 ID，但尚没有代码生成/保存/重用该 ID；没有这一事实不应打开写操作重试。

**D04 — 验证与外部事实缺失。**
真实会议 API、权限、资源 ID、提交原子性、ADP 的 $ref/structuredContent 适配、企微身份映射都未经过本地工程实测。

以上项在 [roadmap/02-contract-and-decisions.md](02-contract-and-decisions.md) 和 [roadmap/07-work-plan.md](07-work-plan.md) 给出闭环任务。请勿直接把“未实现”改成“已实现”；必须同时具备代码/配置事实和对应验证。
