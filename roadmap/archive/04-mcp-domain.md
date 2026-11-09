> 历史方案快照（阶段一，2026-11-04）。此页仅保留原决策与证据；当前能力/命令/状态以 [roadmap/README.md](../README.md) 和 [docs/README.md](../../docs/README.md) 为准。

# 04｜MCP 业务闭环：创建、改会、冲突、幂等

> 当前状态：**计划，未实现。** 本篇解释真实业务代码将承担的逻辑，不把结果 Schema 或 Fake 测试当成真实会议提交。

## 1. 三个固定 MCP Tool

| Tool | 职责 | 消息类型 |
|---|---|---|
| submit_meeting_request | 校验、查询、创建/修改提交；返回冲突或追问状态 | meeting.request.v1 → meeting.result.v1 |
| continue_meeting_request | 继续同一用户的 pending 请求：选项、取消、补参/修订（需先完成 C01/C02 契约） | meeting.continue.v1 → meeting.result.v1 |
| get_meeting_operation | 查询原业务操作的最终/中间状态 | meeting.operation-query.v1 → meeting.result.v1 |

输入 Schema、输出 Schema 必须取自当前项目已维护的机器契约（详见 [docs/CONTRACT.md](../../docs/CONTRACT.md)），不是在 MCP 实现中再手写一份不一致的类型。

## 2. 单次提交的正确顺序

~~~text
1. MCP 调用 / Schema 校验
2. 可信身份认证：调用者、最终用户、租户
3. 幂等台账：同一 operation_id 是否已有同等请求/结果
4. 意图检查与业务字段完整性判断
5. 会议/会议室/参会人名称 → 唯一真实 ID
6. CREATE：目标会议参数；UPDATE：读取原会议 + 校验版本/权限 + 应用差量
7. 按组织规则检查时间冲突、资源可用性
8. 有冲突/需要确认：生成绑定用户的 pending + revision + TTL + 真实候选
9. 无冲突：在权威会议系统的受保护写入边界提交
10. 回读/确认真实最终结果；保存状态并返回 COMMITTED 等结果
~~~

不变量：
- **CHECK 只读；OTHER 不写入。**
- UPDATE 只能更新明确声明的字段；没有修改权限、原会议不唯一或版本过期时不修改。
- 会议室和人员重名必须先让用户选择，不能猜 ID。
- 提交成功以会议系统结果为准；响应丢失时使用 operation_id 查询而不重复建会。
- 冲突后用户重新选择时要**再次校验资源**，旧候选不是资源锁。

## 3. 为什么查询后不能直接创建

假设两人同时查询 A301 14:00–15:00 都空闲，再分别创建。如果“检查空闲”和“写入日历”没有统一提交保护，两个请求可能都成功。

正确保障优先由**共享的权威会议系统**提供：事务、资源时段唯一约束、乐观版本或等价原子预订 API。如果 Provider 本身不能保证，则先明确可行的共享协调/提交方案并验证所有写入者都遵守；单台 MCP 本地锁不能阻止外部渠道绕开。

验证要用可控并发交错来证明“最多一个成功”，不可只用顺序调用的两个测试伪装并发。

## 4. 修改会议的特有规则

1. 先通过 meeting_id 或检索条件定位会议；多匹配返回 NEED_SELECTION。
2. 校验用户对目标会议的读取/修改权限，不能让自然语言“我要修改”提升权限。
3. 读取原 start/end、room、参会人、业务版本；相对平移基于原值计算，保留原持续时长。
4. 应用 update.changes 里的差量，不出现的字段不修改；参会人名单替换/清空语义由当前 [docs/CONTRACT.md](../../docs/CONTRACT.md) 负责。
5. 排除原会议自身占用进行冲突检查，使用条件更新或等价版本保护，失败时不覆盖其他人的新修改。
6. 成功时返回**原会议更新后**的真实 meeting_id 和确认过的详情，不创建第二场会议。

## 5. pending 状态与幂等状态是两类不同信息

**pending_request**：代表“这位用户还欠一次选择/补充”，至少记录可信用户绑定、原申请、候选及版本、过期时间、状态。重启后仍可恢复；过期、跨用户、旧 revision 必须拒绝或重新检查。

**operation ledger**：代表“一次业务写操作最终有没有执行”，稳定 operation_id 对应相同 payload 摘要和真实结果；同 ID + 不同 payload 拒绝；原操作处理中返回 IN_PROGRESS，结果未知返回 UNKNOWN 并核实；COMMITTED 不能再次写入。

优先复用会议系统或现有工程正式持久化，不为模板引入 Redis/数据库组合；只有确认现有系统不能可靠保存两类状态时才选最小持久化方案。pending 的取消只取消**本次待处理申请**，不是取消已有真实会议。

## 6. 关键失败与回退

| 真实问题 | MCP 必须怎么做 |
|---|---|
| A301 被占用 | 保存 pending，返回 CONFLICT + 真实可行选项 |
| 方案被别人抢先占用 | 重新检查，返回新 CONFLICT，不能越过校验 |
| 重名会议/重名参会人 | 返回 NEED_SELECTION |
| 缺少结束时间 | 返回 NEED_INPUT；通过 C01 修订机制补齐 |
| 修改了别人的会议 | DENIED，不泄露非授权会议详情 |
| 两人并发提交同资源 | 权威数据源保护，最多一个提交成功 |
| 创建已成功但回包丢失 | 根据 operation_id 核实真实状态，不能盲重试 |
| 待决策申请过期/旧版本 | EXPIRED 或明确的版本冲突处理，不使用旧选项 |
| Provider 限流/超时 | 返回明确错误/UNKNOWN；重试有界且不重复副作用 |
| 远端成功但本地台账写失败 | 必须有恢复/对账办法，不能把不一致假装成功 |

**原子性声明的边界：** 如果跨了 MCP 本地存储和第三方会议 API，普通数据库事务不能把两边自动变成单一原子事务；设计时明确以哪个系统为最终事实源，以及如何在部分失败后恢复。

## 7. 真实调试顺序

A. 先用现有 Schema + Fake Provider 测合法/非法入参、变更语义、冲突、候选和状态机；不要复制第二套业务规则。

B. 接入真实测试会议 API，验证查询、创建、修改、权限、幂等及版本语义，确认真实 provider 能力是否满足 [roadmap/01-product-and-boundaries.md](01-product-and-boundaries.md)。

C. 用本地 MCP Client/Inspector 调用三正式 Tool 并检查 structuredContent、输入输出 Schema、失败映射、可恢复状态。

D. 上述独立闭环通过，才交给 [roadmap/05-adp-wecom-workflow.md](05-adp-wecom-workflow.md) 配置正式 ADP 工作流。

验收场景与分层证据见 [roadmap/06-test-and-release.md](06-test-and-release.md)；任务与依赖见 [roadmap/07-work-plan.md](07-work-plan.md)。
