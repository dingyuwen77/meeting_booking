# 会畅智云账号模式 OpenAPI 适配

## 为什么将会畅接口放在 Provider 内

业务层使用统一的时间、身份和会议状态，不能直接依赖会畅各端点的表单格式、GMT 时间与供应商状态码。[src/meeting_reservation/bizvideo.py](../../src/meeting_reservation/bizvideo.py) 是这些差异的唯一适配入口，业务统一结果由 [src/meeting_reservation/service.py](../../src/meeting_reservation/service.py) 生成。

当前代码依据此前记录的《会畅智云账号模式 Open API》**v1.0.10（2026-03-27）**编写；原 PDF 未在仓库中可复核，**以下接口名称、状态含义和字段仍需供应商原文与真实租户核验**。HTTP Mock 只证明本项目发送了这些请求，不证明远端服务器在当前租户接受它们。

## 认证、时间和 HTTP 格式

1. 使用已验签的企微 UserID 作为会畅 `userId`，不是另建业务身份；服务器配置提供 `siteSign`、`APIKey`，不把密钥传给 ADP 模型。
2. 每次请求生成毫秒 `timeStamp`，Token 算法为 `MD5("UserId|APIKey|timeStamp").upper()`；单个 Provider 实例通过锁保持所生成时间戳单调不重复。此机制不是跨多实例的分布式唯一性保证。
3. 传入业务时间要求带时区偏移，Provider 对会畅使用 GMT/UTC 字符串；返回的无时区供应商时间按 GMT 解读。不要直接按北京时间字符串发送。
4. GET 的参数在 Query；POST 使用 `application/x-www-form-urlencoded`，**不是 JSON POST**。HTTP 成功还要验证供应商业务 `status == 100`。

部署变量见 [.env.example](../../.env.example)；配置解析见 [src/meeting_reservation/settings.py](../../src/meeting_reservation/settings.py)。

## 代码中的端点与实际用途

| 业务行为 | 会畅端点 | 本项目方式及用途 |
| --- | --- | --- |
| 创建普通视频会议 | `confReservation` | POST；名称、GMT 开始、duration、容量等 |
| 指定虚拟资源创建 | `confReservationByRoomId` | POST；明确的 `roomId` |
| 仅名称修改 | `confModify` | POST；避免误用不允许改时间的旧接口 |
| 修改开始时间/时长 | `confModify2` | POST；端点携带会议方数参数，当前业务仍保留原会的方数；同时保留已知选项并请求保留会议号 |
| 指定虚拟资源修改 | `confModify2ByRoomId` | POST；校验所选虚拟资源 |
| 会议详情及写后确认 | `getConfDetailByConfId` | GET；核对会议 ID、归属、会议号、开始和时长 |
| 本人已预约会议列表 | `getScheduledConfListByUserId` | **POST**；分页查询本人时段冲突、名称候选 |
| 资源池空闲状态 | `getAvailableRoomsBySiteSign` | GET；容量/数量是否满足 |
| 虚拟资源和其占用会议 | `getRoomListAndConfListBySiteSign` | GET；按 roomId 校验容量与时间冲突 |

`scheduled` 和 `rooms` 当前最多读取 20 页，每页请求 100 条；超过边界返回 `PAGE_LIMIT`，而不是静默只看前一部分。真实接口分页结构和供应商各端点行为须在站点验收。实体 A301 不是会畅 roomId，不得混用。

## 更新与写后回读边界

- UPDATE 在业务层先读取原会议信息、检验归属与是否未开始；仅改名使用 `confModify`，时间/资源变化使用 `confModify2` 相关路由。
- Provider 在修改请求中携带原详情中**已知且存在**的若干密码/入会/静音/渠道字段，并设置 `keepConfNo=1`。这是代码尝试保留信息的方式，不能证明特殊会议的所有可选字段都能无损往返。
- 会畅返回成功后，`service._complete` 再读详情并检查身份、会议 ID、会议号、名称、时间、时长及链接等结果约束，最后才能返回 `COMMITTED`。
- 暂不支持在当前会议预约/修改链路写入邀请名单、会议描述；这些字段即使可在 Schema 表达，也会被业务层明确拒绝。

## 失败与待核实

| 场景 | 本项目处理边界 |
| --- | --- |
| 明确业务拒绝（例如冲突相关状态） | 返回 ProviderError；业务层对已识别的 `202`/`205` 走冲突分支 |
| 只读查询的网络/响应异常 | 返回明确的读取失败，不视为远端写入未知 |
| 写入超时、断连、服务器不确定响应、无法解析返回值 | `ProviderUnknown` → `UNKNOWN` |
| 写后响应会议 ID 非法、与原会议不符，或详情回读不完整 | `UNKNOWN`，不得用新操作号盲重试 |

既有文档记录的 `100`、`202`、`205`、`401`、`102` 等供应商代码**必须以供应商原 PDF 和实际站点为准**。不能从 HTTP 200 推导业务成功，也不能从本地一次 CHECK 可用推导提交原子性、外部幂等或全站并发安全。

实际核对与外部试验见 [docs/testing/01_测试与联调验收.md](../testing/01_测试与联调验收.md)，异常恢复见 [docs/operations/03_故障排查与恢复.md](../operations/03_故障排查与恢复.md)。
