> 历史方案快照（阶段一，2026-11-04）。此页仅保留原决策与证据；当前能力/命令/状态以 [roadmap/README.md](../README.md) 和 [docs/README.md](../../docs/README.md) 为准。

# 02｜接口契约补缺、版本与冻结门禁

> 本篇是“契约如何接通业务”的实施说明，不是第二份 JSON Schema。精确字段与合法值以 [docs/CONTRACT.md](../../docs/CONTRACT.md) 和包内 5 份 Schema 为准。

## 1. 当前五种消息（代码已实现）

| 消息 | 实际用途 | 机器来源 |
|---|---|---|
| meeting.intent.v1 | ADP 语义提取：CREATE/UPDATE/CHECK/OTHER | [src/meeting_reservation/schemas/meeting-intent.v1.schema.json](../../src/meeting_reservation/schemas/meeting-intent.v1.schema.json) |
| meeting.request.v1 | 可信调用层补 operation_id，提交意图 | [src/meeting_reservation/schemas/meeting-request.v1.schema.json](../../src/meeting_reservation/schemas/meeting-request.v1.schema.json) |
| meeting.continue.v1 | 待处理申请选项选择/取消 | [src/meeting_reservation/schemas/meeting-continue.v1.schema.json](../../src/meeting_reservation/schemas/meeting-continue.v1.schema.json) |
| meeting.operation-query.v1 | 查询原操作状态 | [src/meeting_reservation/schemas/meeting-operation-query.v1.schema.json](../../src/meeting_reservation/schemas/meeting-operation-query.v1.schema.json) |
| meeting.result.v1 | 返回状态、会议 ID、冲突、候选、错误等 | [src/meeting_reservation/schemas/meeting-result.v1.schema.json](../../src/meeting_reservation/schemas/meeting-result.v1.schema.json) |

当前真实的 UPDATE 格式为 **time_shift_minutes + changes**：例如“推迟一小时并换会议室”可以组合；相对平移与在 changes 中修改绝对起止时间互斥；只改变显式字段。不要恢复历史 SHIFT/PATCH 双结构。示例见 [examples/update-combined.intent.json](../../examples/update-combined.intent.json) 和 [tests/test_unified_update.py](../../tests/test_unified_update.py)。

## 2. 契约从哪里来到哪里去

~~~text
企微自然语言
  ↓
ADP 意图提取 → meeting.intent.v1
  ↓ 当前只有语义，不可认证身份
可信调用层：语义校验、获取/复用稳定 operation_id、绑定可验证身份
  ↓
submit_meeting_request（meeting.request.v1）
  ↓
MCP runtime Schema + 身份/权限 + 资源解析 + 会议系统
  ↓
meeting.result.v1 → ADP 按 status 分支回复
  └─ CONFLICT / NEED_* → pending 状态 → continue_meeting_request
  └─ IN_PROGRESS / UNKNOWN → get_meeting_operation
~~~

注意：5 种“业务消息”不是要求 MCP 暴露 5 个工具。正式工具仍建议是 submit、continue、get_operation 三个，输入输出可重用当前 5 份 Schema。

## 3. 冻结前必须闭合的契约缺口（均未实现）

### C01：补充参数不能继续旧申请（最高优先级）

**已确认冲突：** [examples/need-input.result.json](../../examples/need-input.result.json) 要求用户补“结束时间”，却带有 pending_request_id；而现有 continue Schema 只接受 SELECT_OPTION 或 CANCEL，不接受用户新补充的时间/会议室。未来按此契约搭 ADP 多轮流程必然出现接口断点。

**推荐解决：** 在尚未发布的 V1 候选上，与 MCP 负责人确认增加一种“补字段/修改待处理申请”的动作（如 SUPPLY_FIELDS），入参保留 pending_request_id、expected_revision、新 operation_id，携带*受限制且可校验*的会议字段变化。服务端合并到原申请并重新执行业务校验/冲突检查；不允许调用端通过补字段修改 actor/tenant/权限。

另一可行方案是新建带 parent_pending_id 的 request，但需要额外明确旧申请失效、幂等和选项版本语义。**在两者之间先决定一个权威恢复路径，不并存两个随意等价的方案。**

完成判断：用户说“帮我订 A301，下午两点”，收到 NEED_INPUT 后回复“到三点”，必须能在**同一已绑定用户的 pending 请求**上补齐并完成下一步；过期、跨用户、旧 revision 均被安全拒绝。

### C02：自由文本冲突决策无法表达

当前 continue 的 SELECT_OPTION 只能选服务端生成的 option_id。用户说“不要选项，我想改到四点”时不能强行解释成 opt_1。

建议复用 C01 确定的“修订申请”机制，但将新的时间/会议室视为**新提案**，必须重新检查冲突，不得宣称候选仍有效。若业务方不批准这一能力，V1 至少要显式引导“重新发起申请”并使旧 pending 失效。

### C03：正式会议回执没有结构化最终详情

当前 [examples/committed.result.json](../../examples/committed.result.json) 只有 meeting_id 与 message。ADP 若照抄提交前的时间/会议室，可能在后端归一化或处理冲突后错误播报。

建议：与 Provider 确认提交成功后能否读取真实会议详情；可在 result 中增加后端确认的摘要，也可在 COMMITTED 后通过受控查询读取。由一个**权威已提交详情**供 ADP 展示，不维护两套数据。

### C04：operation_id 来源及去重语义只有文档约束

当前 [docs/CONTRACT.md](../../docs/CONTRACT.md) 已要求可信调用层生成稳定操作标识，但没有实现。必须明确：首次事件如何生成、ADP 节点重试如何复用、用户下一轮操作如何生成新 ID、断网后如何查回原操作，以及 same ID + 不同 payload 必须拒绝。不能仅凭 SYS.RequestId 名字就认定它跨重试稳定。

### C05：MCP 的 $ref/结构化结果兼容性尚未验证

现有 request 通过 URN $ref 引用 intent；[src/meeting_reservation/contract.py](../../src/meeting_reservation/contract.py) 使用本地 Registry 解析成功，不证明腾讯 ADP 会按相同方式消费 MCP inputSchema/outputSchema。联通阶段必须实测。必要时从**同一份 Schema 生成**可内联的 tool Schema，不复制维护新的手写定义。

## 4. 冻结门禁与兼容政策

1. 会议系统拥有者明确实际字段、时间/时区、参加人、资源唯一 ID、修改语义及权限。
2. C01、C02、C03、C04 决策有一致的端到端消费路径和对应测试，C05 被真实 ADP PoC 验证。
3. 对五种消息均具备合法样例、非法样例、版本/错误/时区/条件字段校验；禁止把格式合法等同业务可提交。
4. ADP 与 MCP 消费者读取同一机器契约，正式冻结后破坏性变更使用 v2 + 迁移，而不是静默改写 v1。
5. 未经过双方对接确认前，当前 V1 **只称“契约候选”，不能称“生产已冻结”。**

**实施时的最小修改路径：** 编辑对应已存在的 Schema、[src/meeting_reservation/contract.py](../../src/meeting_reservation/contract.py)（若跨字段约束需要）、[tests/test_contracts.py](../../tests/test_contracts.py) 与示例、[docs/CONTRACT.md](../../docs/CONTRACT.md)。先新增能证明新场景的失败测试，再修改生产契约并复验。没有代码修改授权的本轮仅记录这些需求。

## 5. 本阶段不做的事

不在 JSON 中添加由模型自报的可信 user_id/is_admin；不让 ADP 计算真实会议冲突；不在 roadmap 手写另一套全字段定义；不提前引入与实际 Provider 不符的字段；不因为文档看起来完整就声称接入完成。

下一阶段：[roadmap/03-adp-mcp-spike.md](03-adp-mcp-spike.md)。执行顺序与阻塞项：[roadmap/07-work-plan.md](07-work-plan.md)。
