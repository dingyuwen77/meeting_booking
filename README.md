# 腾讯 ADP · 智能会议预订（Python）

这是 **阶段 1：ADP ↔ MCP 标准化接口契约** 的独立 Python 工程。契约用于后续企业微信 → ADP → MCP Server → 会议业务系统的接入。

**当前只完成契约层：JSON Schema、可复用校验器、示例和测试。** 未实现 MCP Server、真实会议创建/修改、身份认证或 ADP 工作流，不应据此声明已经完成预订能力。

## 工程结构

```text
03_Meeting_reservation/
├── pyproject.toml                         # Python 包与开发工具配置
├── src/meeting_reservation/
│   ├── __init__.py
│   ├── __main__.py                        # python -m meeting_reservation
│   ├── cli.py                             # 本地 JSON 校验命令
│   ├── contract.py                        # 唯一运行时校验入口
│   └── schemas/                           # 5 份版本化 JSON Schema（唯一机器契约）
├── examples/                              # 18 份合法消息样例（含组合 UPDATE 与 MCP 提交请求）
├── tests/                                 # 契约与 CLI 回归测试
└── docs/
    ├── CONTRACT.md                        # 字段与状态语义、接入边界
    └── PHASE1.md                          # 阶段 1 的范围与验收记录
```

## 环境

- Python **3.11 或更高版本**（本机已用 Python 3.14 实际测试；其他版本须单独验证）
- 运行依赖：`jsonschema>=4.21,<5`
- 开发依赖：`pytest`、`ruff`
- 本阶段无需 ADP 账号、MCP Server、数据库或业务系统凭据。

当前本机检测到 `D:\python314\python.exe` 可用，但 Windows 的 `py -3.11` 注册项仍指向不存在的 Python 3.11 路径。因此在这台电脑上先使用 **实际可运行的 Python 3.14**，无需修改系统配置。

## 本地运行（PowerShell）

```powershell
Set-Location -LiteralPath 'E:\work\05_ADP\03_Meeting_reservation'
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')

# 校验所有示例
& 'D:\python314\python.exe' -m meeting_reservation validate-examples --dir examples

# 单个消息类型支持：intent / request / continue / operation-query / result
& 'D:\python314\python.exe' -m meeting_reservation validate intent examples/create.intent.json
& 'D:\python314\python.exe' -m meeting_reservation validate request examples/submit-create.request.json

# 回归测试及风格检查
& 'D:\python314\python.exe' -m pytest -q
& 'D:\python314\python.exe' -m ruff check src tests
```

也可以在项目虚拟环境内执行 `python -m pip install -e ".[dev]"`，之后通过命令 `meeting-contract validate-examples` 调用；此安装路径是否可用需要在实际目标环境验证。

## 接口总览

| MCP Tool（阶段 2 计划） | 使用的入参 Schema | 统一出参 |
|---|---|---|
| `submit_meeting_request` | `meeting.request.v1` | `meeting.result.v1` |
| `continue_meeting_request` | `meeting.continue.v1` | `meeting.result.v1` |
| `get_meeting_operation` | `meeting.operation-query.v1` | `meeting.result.v1` |

ADP 首先输出 `meeting.intent.v1`，可信调用层再补充稳定的 `operation_id` 形成 `meeting.request.v1`。不将模型自报的用户 ID 当作认证凭据。

### 会议修改采用统一 update 结构

用户说“把产品评审会推迟一个小时，同时换到 A302”时，ADP 可以输出：

```json
{
  "schema_version": "meeting.intent.v1",
  "action": "UPDATE",
  "target": {"meeting_id": null, "search_text": "产品评审会"},
  "meeting": null,
  "update": {
    "time_shift_minutes": 60,
    "changes": {"room_query": "A302"}
  }
}
```

- 仅平移时间：`{"time_shift_minutes":60,"changes":{}}`。
- 仅修改字段：`{"time_shift_minutes":null,"changes":{"room_query":"A302"}}`。
- 可以组合非时间字段；但**平移与绝对起止时间修改互斥**，且不能提交空更新。
- 新格式不含 `mode`，旧 `SHIFT/PATCH` 互斥结构会被拒绝。两个键在非空 `update` 中都必须提供。
- `update:null` 表示意图提取不完整，并非允许立即写入会议。

契约示例详见 `examples/update-relative.intent.json`、`examples/update-fields.intent.json`、`examples/update-combined.intent.json`，以及包含组合更新意图的 `examples/submit-update.request.json`。

**机器契约唯一事实源：** `src/meeting_reservation/schemas/*.json`。正式 JSON Schema 通过 URN 本地注册和 `$ref` 复用，避免请求与意图重复定义。Python 校验器只负责格式及可独立计算的时间区间检查，不查询真实会议系统。

查看 [契约和扩展说明](docs/CONTRACT.md) 与 [阶段验收记录](docs/PHASE1.md)。

后续按阶段开发，请从 [roadmap/README.md](roadmap/README.md) 进入：这里记录当前已实现范围、接口待决问题、MCP 与 ADP 联通顺序、测试门禁和逐项任务进度。

## 后续扩展

阶段 2 首先完成 ADP 对测试 MCP 工具的连接、身份和结构化结果映射。阶段 3 再在独立的业务模块中实现工具适配、真实会议系统调用、冲突决策状态、并发与幂等保护。保留契约包与测试可复用，不应让大模型承担授权或最终冲突判定。
