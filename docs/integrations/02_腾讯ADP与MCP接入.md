# 腾讯 ADP 与 MCP 接入

## 目标与当前状态

本仓库实现官方 Python MCP SDK v2 的 Streamable HTTP 服务，提供 `initialize/tools/list/tools/call` 所需的 SDK 协议能力及业务工具。**尚未在用户的腾讯 ADP 租户上完成在线握手和结构化结果验证**，不能仅凭存在工具函数就宣称 ADP 接通。

腾讯 ADP 官方自定义 MCP 接入入口：[新建 MCP 工具](https://cloud.tencent.com/document/product/1759/117855)。具体传输、Header 和结果字段支持以当前租户与官方页面为准；静态 Header 自身不能证明每次企微请求的最终用户身份。

## 最小连接顺序

1. 在可信网络/TLS 反向代理后部署本服务，Streamable HTTP 地址为 `https://<host>/mcp`。禁止直接对公网开放无访问控制的服务。
2. 本地 MCP Client 先验证 `ping_meeting_server`，并检查 `tools/list` 能列出全部五个 Tool。
3. 在 ADP 测试应用通过“连接器与工具 → 自定义工具 → 基于 MCP 创建”，配置服务器 URL，测试工具发现和 ping。
4. 用固定无副作用测试消息验证入参与 `structuredContent.status` 的下游节点读取方式。当前 MCP Tool 外层参数名为 `request`；工具发现已从原有机器契约展开完整 Schema。服务端仍独立校验，ADP 能否按该结构生成与消费消息必须实测。
5. 测试不同企微成员的原始 UserID 能否经**可信网关动态签名**传给 MCP；静态 Header 或模型自报 `user_id` 都不合格。
6. 未验证可信身份之前，所有真实提交工具保持 `MEETING_WRITE_ENABLED=false`。身份通过后再使用独立会畅测试站点做受控真实预约。

## 多轮恢复

ADP 不得单凭模型记忆生成 pending ID。业务服务会返回 `pending_request_id`、`pending_revision`、`expires_at`，由可信调用层保存/关联到当前企微会话和用户。用户补时间、修改要求或选择候选后，以新 `operation_id` 调用 `continue_meeting_request`；用户要求查原执行结果时调用 `get_meeting_operation`。只有后端确认为 `COMMITTED` 才能发“已预约/已修改”的确定消息。

## 实际需要验证的接口边界

腾讯 ADP 能否展开/解析 MCP 生成的字典 Tool Schema、是否支持准确读取 `structuredContent`、超时与错误时是否正确路由、是否能够经可信网关携带每轮不同 UserID、对话状态是否能跨轮恢复。这些都是平台/租户的**实验任务**，不是本仓库现有单测的证明。

不在当前仓库直接修改生产 ADP 画布或企微消息网关。后续真实联调参照 [docs/testing/01_测试与联调验收.md](../testing/01_测试与联调验收.md)。
