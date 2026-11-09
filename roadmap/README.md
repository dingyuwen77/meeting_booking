# 智能会议预订 Roadmap（从这里开始）

> 目标：按可验证的依赖顺序，完成企业微信 → 腾讯 ADP → 固定 MCP Server → 会议业务系统的创建、修改、冲突决策闭环。
>
> 本文档是**开发导航和阶段进度入口**，不是第二套 JSON Schema。盘点基线：2026-11-04（北京时间）。尚未完成的能力均标明“计划”，不得称为已实现。

## 先读这三句话

1. **当前能做：** 校验 5 种会议消息的 JSON Schema、运行 CLI、执行现有单元/契约测试；不能真的订会。
2. **下一步先做：** 确认真实会议系统接口/业务规则，并补齐当前契约中“用户补充参数后继续原申请”的断口；随后做 ADP ↔ 测试 MCP 的最小接入。
3. **正式开发顺序：** 契约候选与依赖核对 → 最小连通及身份验证 → MCP 业务闭环 → ADP 流程 → 企业微信 E2E → 受控交付。不先在 ADP 画复杂流程，也不让模型做会议冲突的最终决策。

## 按阅读目的打开文档

| 想知道什么 | 阅读入口 |
|---|---|
| 当前究竟做到了哪一步，哪些是证据 | [roadmap/00-current-state.md](00-current-state.md) |
| 整体架构、业务边界与上游决策 | [roadmap/01-product-and-boundaries.md](01-product-and-boundaries.md) |
| 已有 JSON 契约、必须完善的缺口和冻结门禁 | [roadmap/02-contract-and-decisions.md](02-contract-and-decisions.md) |
| 先在 ADP 中验证 MCP 能不能连、用户身份能不能可信传递 | [roadmap/03-adp-mcp-spike.md](03-adp-mcp-spike.md) |
| MCP 如何真正创建/修改会议、处理冲突与并发 | [roadmap/04-mcp-domain.md](04-mcp-domain.md) |
| ADP 节点怎么连线，企业微信如何多轮回复 | [roadmap/05-adp-wecom-workflow.md](05-adp-wecom-workflow.md) |
| 什么测试才算证明业务可交付 | [roadmap/06-test-and-release.md](06-test-and-release.md) |
| 逐项开发任务、依赖、验收与更新方法 | [roadmap/07-work-plan.md](07-work-plan.md) |

## 统一实施路线

~~~text
G0：真实会议系统和业务规则确认（待确认）
  ↓
G1：JSON 契约 V1 候选补缺 + 双方复核（现有基础已实现，尚未冻结）
  ↓
G2：ADP ↔ 测试 MCP 工具发现、调用、身份探针（未开始）
  ↓
G3：MCP 业务闭环 + 会议系统真实集成测试（未开始）
  ↓
G4：ADP 工作流与多轮会话（未开始）
  ↓
G5：企业微信真实 E2E（未开始）
  ↓
G6：安全、并发、失败恢复、受控发布验收（未开始）
~~~

**依赖原则：** G0/G1 是后续写入业务的前置条件；G2 应在完整 MCP 研发前做最小连通试验；G3 未验收，不应把 ADP 流程测试当业务成功；G4/G5 可以有局部并行准备，但正式验收不得跨越门禁。详细操作见 [roadmap/07-work-plan.md](07-work-plan.md)。

## 本项目当前事实源

- **机器契约：** [src/meeting_reservation/schemas/meeting-intent.v1.schema.json](../src/meeting_reservation/schemas/meeting-intent.v1.schema.json)、[src/meeting_reservation/schemas/meeting-request.v1.schema.json](../src/meeting_reservation/schemas/meeting-request.v1.schema.json)、[src/meeting_reservation/schemas/meeting-continue.v1.schema.json](../src/meeting_reservation/schemas/meeting-continue.v1.schema.json)、[src/meeting_reservation/schemas/meeting-operation-query.v1.schema.json](../src/meeting_reservation/schemas/meeting-operation-query.v1.schema.json)、[src/meeting_reservation/schemas/meeting-result.v1.schema.json](../src/meeting_reservation/schemas/meeting-result.v1.schema.json)。
- **契约解释：** [docs/CONTRACT.md](../docs/CONTRACT.md)；**现有代码入口：** [src/meeting_reservation/contract.py](../src/meeting_reservation/contract.py)。
- **阶段一历史与验证说明：** [docs/PHASE1.md](../docs/PHASE1.md)；**运行教程：** [README.md](../README.md)。

新开发时先读目标项目自己的 AGENTS/规范（若以后出现），再由当前 GitHub canonical 的 dingyuwen77/Agent_Skills 根 AGENTS.md → ENTRY → Router 加载当前任务适用的 Skill 与 references。**不把本 roadmap 当成 Agent_Skills 的规则副本，也不把计划状态当成代码/测试证据。**

## 维护方法：避免“文档孤岛”

- 只有 [roadmap/07-work-plan.md](07-work-plan.md) 管理任务状态与阶段门禁；其他专题只解释方案、决策、失败机制和对应的唯一事实源。
- 任何公共字段调整都修改真正的 JSON Schema、测试与 [docs/CONTRACT.md](../docs/CONTRACT.md)；roadmap 只更新决策与影响，不复制完整字段定义。
- 每完成一项任务：记录受影响的代码/Schema、真实测试命令和结果、未验证边界；相关当前事实同步回 [README.md](../README.md) 或 [docs/CONTRACT.md](../docs/CONTRACT.md)。
- **状态定义：** 已验证＝当前证据直接证明；已实现待验证＝有代码但缺对应证据；未实现＝没有对应生产能力；待决策＝需要业务 Owner 或真实 Provider 事实；阻塞＝缺少必要前置而不能进入下一步。
- 这个目录是实施导航，不独立承诺 CI、Git、PR、部署；真正的交付门禁由项目规则和 Agent_Skills 当前 canonical Source 决定。

## 一次行动建议

从 [roadmap/07-work-plan.md](07-work-plan.md) 的 T01、T02 开始：首先和会议系统负责人核对真实接口/安全边界，再解决多轮补参数契约和身份来源，不要直接开始编写 ADP 全量节点。
