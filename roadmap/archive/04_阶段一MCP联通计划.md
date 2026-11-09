> 历史方案快照（阶段一，2026-11-04）。此页仅保留原决策与证据；当前能力/命令/状态以 [roadmap/README.md](../README.md) 和 [docs/README.md](../../docs/README.md) 为准。

# 03｜ADP ↔ MCP 最小联通、协议与身份探针

> 目标：在正式写完会议业务服务之前，用一个最小 MCP Server 证明“ADP 真的能调用它”，并确认能否获得可信最终用户身份。**当前未实施。**

## 1. 为什么要提前做

JSON Schema 在 Python 中能通过测试，并不保证 ADP 能发现工具、解析 $ref、读取 structuredContent 或将企微成员身份传到 MCP。先做一个受控小实验，可以避免后续 MCP 研发完成才返工平台适配。

官方资料（执行时再次确认页面/租户实际功能）：
- [腾讯 ADP：新建 MCP 工具](https://cloud.tencent.com/document/product/1759/117855)
- [腾讯 ADP：新建连接器](https://cloud.tencent.com/document/product/1759/115873)
- [腾讯 ADP：连接器与工具节点](https://cloud.tencent.com/document/product/1759/115748)
- [腾讯 ADP：将应用发布到企微机器人](https://cloud.tencent.com/document/product/1759/121473)
- [MCP 工具规范](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)

腾讯 ADP 的文档明确需要 initialize、tools/list、tools/call；具体传输版本、工具输出结构及多轮企微行为必须在本项目的测试租户验证，不预先假定全部支持。

## 2. 环境与安全准备

- 使用隔离的测试 MCP 服务地址，ADP 从云端能够访问；HTTPS、服务访问控制、无公网敏感调试信息。
- 明确测试身份和测试会议系统（当前仅探针，可以不连接真实会议系统）。
- 记录所选 MCP SDK 版本、transport（优先试 Streamable HTTP）、实际握手协议版本。
- 本阶段绝不启用真实会议创建；不把密钥、token、原始敏感 Header 或人员信息记录到文件。
- 不用生产密钥做随意公网抓包；若需要用户级 OAuth，在可信授权链中验证，不以 API Key 证明最终用户身份。

## 3. 实施步骤与可观察结果

| 步骤 | 动作 | 需要保留的证据 |
|---|---|---|
| P01 | 最小测试 MCP Server 暴露 ping_meeting_server | 服务实际启动、initialize/tools/list/tools/call 返回 |
| P02 | 在 ADP 创建自定义 MCP 工具/连接器 | 工具成功拉取及实际输入 Schema |
| P03 | 单工作流用工具节点传固定参数 | MCP 收到准确参数，ADP 读取准确结果 |
| P04 | 输出 status、嵌套字段、错误对象 | ADP 后续条件节点可取到明确字段 |
| P05 | 用现有嵌套 request/$ref 验证 | 若 ADP 不接受 URN 引用，记录差异并生成等价内联 Schema |
| P06 | 测试超时/业务失败/协议错误 | ADP 能区分真实错误与成功，不盲目触发写操作 |
| P07 | 只读 whoami_probe 验证最终用户 | 两位企微测试成员能被可信地区分，并能阻止身份伪造 |
| P08 | 校验请求去重所需事件/操作标识 | 确认一次业务请求的稳定 ID 从何处来、如何跨重试恢复 |

**身份风险：** SYS.RequestId、企微昵称、模型的 user_id、群聊会话 ID 都不能自动作为最终用户认证凭据。必须建立可验证身份的传递/映射/授权机制。若当前 ADP 渠道不能安全透传最终成员身份，应评估用户级 OAuth 或可信代理/网关；在此门禁通过前禁止真实写操作。

## 4. ADP 最小画布示意

~~~text
开始（手动输入测试参数）
  ↓
连接器与工具：ping_meeting_server
  ↓
逻辑判断：success = true ?
  ├─ 是：回复测试成功 + echo
  └─ 否：输出测试失败（不要吞掉错误）
~~~

本阶段**不使用大模型替代身份验证**，也不接真实会议 API，不依赖完整多轮流程。后续正式画布见 [roadmap/archive/06_阶段一ADP与企微计划.md](06_阶段一ADP与企微计划.md)。

## 5. 什么时候算 PoC 通过

- 真正看到 ADP → MCP 的初始化/工具发现/一次成功调用/一次失败调用结果。
- 能在 ADP 的下游节点取到期望的结构化字段，而不只是整段文本。
- 认证和网络边界明确；最终用户身份方案具备可验证的链路证据或标记未通过。
- stable operation_id 的生成、重试及跨轮查回方案已确定，不是假设平台自动提供。
- 记录平台实际版本与发现的限制，并反馈 [roadmap/archive/03_阶段一契约与决策.md](03_阶段一契约与决策.md) 的契约冻结门禁。

**未通过如何处理：** 仅阻塞依赖该能力的后续操作；可以继续本地 Schema/业务 Fake 测试，但不能声称已完成 ADP 对接或开启真实会议写入。
