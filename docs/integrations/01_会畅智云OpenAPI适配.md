# 会畅智云账号模式 OpenAPI 适配

## 依据与前提

Provider 依据用户提供的《会畅智云账号模式 Open API》**v1.0.10（2026-03-27）**实现，不是另一套公共业务协议。正式使用前必须向会畅申请站点、开通 OpenAPI 权限，获得 `siteSign`、`APIKey` 并使用隔离测试账号测试；当前仓库没有这些凭据。

## Token 与网络格式

每次请求使用 `token = MD5("UserId|APIKey|timeStamp").upper()`，`timeStamp` 为毫秒级时间戳；`UserId` 直接取已验签企业微信 UserID。会畅传入/返回的时间按 **GMT/UTC** 处理；POST 用 `application/x-www-form-urlencoded`，GET 用 Query，不是 JSON POST。真实结果需以 `status == 100` 为成功依据，HTTP 200 不能替代业务状态。实现见 [src/meeting_reservation/bizvideo.py](../../src/meeting_reservation/bizvideo.py)。

## 已实现的端点映射

| 能力 | 会畅端点 | 供应商章节 | 本项目规则 |
| --- | --- | --- | --- |
| 预约视频会议 | `confReservation` | 2.1 | userId/userName、confName、UTC startTime、duration、confParties |
| 指定会畅虚拟资源预约 | `confReservationByRoomId` | 2.14 | 使用已验证 roomId |
| 普通修改 | `confModify` | 2.2 | 只改会议名称等不涉及时间/方数的字段 |
| 修改时间/时长/方数 | `confModify2` | 2.15 | 先读旧详情，再提交完整所需字段 |
| 指定虚拟资源修改 | `confModify2ByRoomId` | 2.29 | 必须再次检查目标资源 |
| 会议详情 | `getConfDetailByConfId` | 2.3 | 读取原会议、确认提交结果 |
| 当前用户预约列表 | `getScheduledConfListByUserId` | 2.6 | 计算同用户会议时段重叠、名称定位 |
| 站点资源状态 | `getAvailableRoomsBySiteSign` | 2.20 | 根据容量和时段查询可用资源数量 |
| 站点会议室及会议列表 | `getRoomListAndConfListBySiteSign` | 2.13 | 指定 roomId 的会议时段占用 |

明确不支持：实体办公室 A301/A302 的自动映射、直接通过预约接口批量邀请与会者、直接写会议描述、PSTN/录制/纪要、已创建会议取消、会中延期等范围外操作。会畅 PDF 另有这些能力的接口章节，但**尚未纳入当前业务范围**。

## 修改语义与数据保留

`confModify` **不能**改开始时间、时长、方数；需要这些能力时使用 `confModify2`。对于相对平移，先读取原开始时间与 duration，做时间运算后再提交；同时保留已知密码、入会选项、入会静音等字段。提出 `keepConfNo=1` 以保持会议号，实际行为必须在测试租户核实。

当前 Provider 仍不能证明所有供应商可选字段均会在不同会议配置下完整回读；在未验证特殊直播/渠道会议前，应限制真实写入于普通预约会议场景。

## 错误与部分失败

会畅 `100` 成功、`202` 时间冲突、`205` 无资源、`401` 会议不存在或无归属、`102` Token/权限失败。具体错误含义以原 PDF 为准。网络超时、远端已经成功但丢失响应、回读缺失必要详情时必须进入 `UNKNOWN`，不能重新调用创建 API。

**尚未确认的服务端事实：** 提交原子性、第三方幂等键、供应商是否允许乐观版本更新、不同模式下可选字段语义。这些必须经测试 API 验证，不能由 Fake 或静态 PDF 文档推导为已成立。
