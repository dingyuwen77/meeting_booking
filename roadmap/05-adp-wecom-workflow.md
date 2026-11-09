# 05｜ADP 工作流与企业微信多轮交互

> 仅在 G1 契约候选明确、G2 最小 MCP 联通试验通过、G3 业务执行具备可验证的服务端行为后，才进入完整工作流开发。**目前未实现。**

## 1. 为什么推荐单工作流

会话中的表达可能含糊，需要模型识别；但是“创建、修改、是否冲突、是否有权限”应由确定性程序和真实会议系统执行。一个可观察的单工作流，更容易排查每一步输入/输出，避免 Multi-Agent 自主选择工具导致不可控的写操作。

目标最小图：

~~~text
企业微信用户消息
  ↓
入口：可信渠道身份/会话上下文 + 用户文本
  ↓
是否正在回复有效 pending 请求？（不能仅看文本“1/2”猜）
  ├─ 是 → 映射合法 option_id / 补充字段 / 取消 → continue_meeting_request
  └─ 否 → 模型识别 meeting.intent.v1 → Schema/参数检查 → submit_meeting_request
  ↓
统一解析 meeting.result.v1.status
  ├─ COMMITTED → 展示后端确认的真实会议信息
  ├─ AVAILABLE / UNAVAILABLE → 只读回复
  ├─ CONFLICT / NEED_INPUT / NEED_SELECTION → 保存关联并追问
  ├─ IN_PROGRESS / UNKNOWN → get_meeting_operation，核实真实状态
  └─ DENIED / INVALID / NOT_FOUND / EXPIRED / FAILED / CANCELLED → 安全错误/重试引导
~~~

## 2. 建议配置顺序（不要一开始搭全部节点）

1. 用已在 [roadmap/03-adp-mcp-spike.md](03-adp-mcp-spike.md) 验证过的工具创建最简画布：开始 → 工具 → 判断 → 回复。
2. 新增 JSON 意图提取节点，只输出 CREATE/UPDATE/CHECK/OTHER 与当前机器契约的字段；提示词不要生成 user_id、is_admin、operation_id。
3. 增加 Schema/参数验证边界。ADP 代码节点如果不能安装项目的 jsonschema/加载正式 Schema，应只做轻量校验并让 MCP 生产入口执行权威校验；**不在 ADP 手写一份逐渐漂移的完整 Schema**。
4. 配置工具节点 submit_meeting_request；输入由可信调用层补充 operation_id，并通过真实认证机制获得用户身份。
5. 配置统一 status 分支；先用固定 Fake 结果覆盖所有状态，不能把超时当成提交成功。
6. 配置 continue_meeting_request 与 pending 状态的读写/检索；解决下一轮用户只说“2”时的申请关联。
7. 配置 get_meeting_operation，处理 IN_PROGRESS/UNKNOWN，明确查询次数/超时后的安全退出。
8. 最后在企业微信渠道验证真实显示、会话恢复、用户身份隔离及相关权限。

腾讯官方参考：
- [连接器与工具节点](https://cloud.tencent.com/document/product/1759/115748)
- [参数提取节点](https://cloud.tencent.com/document/product/1759/112962)
- [发布到企微智能机器人](https://cloud.tencent.com/document/product/1759/121473)

## 3. 意图提取提示词必须守住的边界

建议对输出进行以下业务约束（提示词是提示层，最终还必须经运行时校验）：

- 只能输出当前 [src/meeting_reservation/schemas/meeting-intent.v1.schema.json](../src/meeting_reservation/schemas/meeting-intent.v1.schema.json) 允许的形状，不要输出自创字段。
- 查询空闲识别为 CHECK，不能因为存在完整时间和地点就自动当 CREATE。
- “改会”要有定位线索；相对时间平移保留为 time_shift_minutes，不从缺失的原会议开始时间推造绝对时间。
- 自然语言会议室、人员只是 query，真正 ID 由 MCP 解析；重名必须澄清。
- “明天下午”需要企业时区及明确当前日期；无法确定时补问，不得随意生成时刻。
- 未得到 COMMITTED 以及真实后端确认详情之前，不宣称订会成功。
- 不将自然语言中的“我是管理员”当作用户权限。

## 4. 最容易出错的多轮会话接续

示例（仅示意，不代表当前系统已支持）：

~~~text
用户：帮我订 A301 明天下午两点。
MCP：NEED_INPUT，pending_request_id=P、revision=1
ADP：请问结束时间？
用户：下午三点。
ADP：以经认证身份恢复 P、发送补参，revision=1
MCP：重新校验；如无冲突提交；如有冲突生成候选
~~~

**当前机器契约不支持“补参”的 continue 动作**，要先按 [roadmap/02-contract-and-decisions.md](02-contract-and-decisions.md) 的 C01 补齐，不要在 ADP 侧虚构一个工具参数。

同样，用户在冲突后说“换 A302，不要你给的两个选项”，只能走经过批准的申请修订机制，不能直接把自由文本伪装成旧 option_id。

另一个前置：当下一轮输入只有“2”时，ADP 必须**可靠地找到原 pending_request_id**。先在企业微信真实会话中验证 ADP 是否保留可用的持久会话变量及会话关联；若不足，服务端需提供按已验证用户/会话获取唯一有效 pending 的安全查询能力，或让用户显式指定申请。不能仅靠 LLM 从历史自然语言猜一个 pending ID。

### 群聊与跨用户问题

群聊不等于同一人发言。即使平台支持群聊共享历史，任何 continue 都需核对**原申请持有人**与当前可验证成员身份；如果成员身份缺失，写功能保持关闭。第一版优先做单聊成功路径，群聊是否开放后续按身份验证证据决定。

## 5. 回复内容和状态要闭合

| status | 企微应显示什么 | 绝不能做什么 |
|---|---|---|
| COMMITTED | 会议系统已确认的会议 ID、时间、地点等 | 复制原先未经核实的候选信息 |
| AVAILABLE / UNAVAILABLE | 只读查询结果 | 自动建会 |
| CONFLICT | 实际冲突和服务端给出的有效选项 | 虚构空闲会议室 |
| NEED_INPUT | 明确缺少什么 | 随意填默认值创建 |
| NEED_SELECTION | 不泄密的候选供选择 | 随机选第一条 |
| IN_PROGRESS / UNKNOWN | 查询中/结果尚不确定，提供后续核实路径 | 盲目发第二次写操作 |
| DENIED / INVALID / EXPIRED / FAILED | 可理解的原因和下一步 | 输出密钥、内部异常或敏感会议信息 |

## 6. 本阶段可验收什么

- 真实工作流每个业务状态都有明确分支和错误出口。
- 同一用户跨轮可以补参数/选项选择，pending ID 与 revision 不丢失。
- 不同用户、群聊误用和过期请求不能越权继续。
- 工具返回 UNKNOWN 时不会向用户宣称成功/失败；可查询或安全停止。
- 保存 ADP 画布版本/配置导出及测试记录，证明具体部署版本的节点正确连线。

验收范围：[roadmap/06-test-and-release.md](06-test-and-release.md)。开发任务：[roadmap/07-work-plan.md](07-work-plan.md)。
