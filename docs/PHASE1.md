# 阶段 1：契约工程初始化与验收记录

## 上游需求、目标和范围

**来源：** 用户提出在 `E:\work\05_ADP\03_Meeting_reservation` 内创建工程化、可扩展的 Python 项目并实现此前制定的阶段 1（ADP ↔ MCP JSON 契约）。

**目标：** 提供可复用、机器可校验、易于扩展的 `intent`、`request`、`continue`、`operation-query`、`result` 契约，以及合法样例与错误校验。

**非目标：** 当前不部署 MCP Server、不接入 ADP、不调用真实会议系统、不存储用户会话或认证信息、不执行会议写入、不初始化用户未授权的远程 Git 操作。

**保持不变：** 不修改 E 盘其他工程；所有新文件位于本次授权的目标目录；不依赖新建全局 Python 环境；不复制并维护第二套 Schema。

## 设计选择与权衡

1. **JSON Schema 为公共 Contract 的 Owner。** 相比手写 Pydantic 模型再导出 Schema，可供 ADP 和其他语言的 MCP 实现直接引用，也降低模型/Schema 重复维护风险。Python 仅补 Schema 无法独立表达的起止时间不变量。
2. **区分语义意图与可信请求。** 相比让 LLM 输出身份和操作 ID，可将信任边界控制在程序内。实际身份链路仍需下一阶段验证。
3. **一个版本、一处 Schema 源。** `request` 通过本地 URN `$ref` 引用 `intent`，避免双份数据结构漂移。CLI/测试读取同一包内资源。
4. **允许缺失而不虚构。** 意图 Schema 允许缺少关键业务值并返回 `NEED_INPUT`，但不表示会议信息已达到提交条件。
5. **不在阶段 1 提前固化会议业务适配器。** 先完成公共边界，等待真实会议 API 和身份/并发能力明确后再实现。
6. **版本化语义。** 此版本作为候选协议；兼容扩展可以保留 V1，破坏性变更应通过 V2 实现。

## Requirement Traceability

| 要求 | 当前实现与直接验证 | 当前状态 |
|---|---|---|
| Python 工程目录可扩展 | `pyproject.toml`、`src/`、`examples/`、`tests/`、`docs/` | satisfied：目录及打包检查 |
| ADP 语义 JSON 结构 | `meeting-intent.v1.schema.json`、意图示例 | satisfied：契约测试 |
| MCP 请求/继续/查询契约 | 对应 Schema 与示例 | satisfied：契约测试 |
| 统一返回 JSON、错误和状态 | `meeting-result.v1.schema.json`、结果示例 | satisfied：条件状态测试 |
| 机器验证 | `contract.py`、CLI、pytest 目标行为测试 | satisfied：67 项测试及 18 份示例（见最新验证） |
| 不越界实现实际订会 | 未提供业务写入实现，仅契约 | satisfied：源文件与目录核对 |

## Validation Matrix

| 层级 | 选择 | 证明范围 |
|---|---|---|
| Unit / Component | required | 各类 Schema、跨字段时间、错误语义校验 |
| Contract | required | 生产校验器真实加载包内 Schema，示例符合声明 |
| CLI / Workflow | required | 用户按 README 命令执行时能够得到准确成功/失败码 |
| Build / Package | required | 包内 JSON Schema 能随 Python 包分发 |
| Provider / Persistence | not_applicable | 阶段 1 无外部会议系统和数据库 |
| Real ADP/MCP E2E | not_applicable | 属于阶段 2 及以后 |
| Docs | required | README 和 CONTRACT 与实际机器事实一致 |

## 当前阶段交付条件

- 目标目录与上级项目规则已检查；
- 所有文件真实存在、可读取、无意外覆盖；
- 全部示例与 Schema 测试通过；
- Python 代码静态检查通过；
- 实际安装/打包或替代包资源验证完成；
- 本文的状态和验证命令根据真实结果更新；
- 无法验证的环境、真实 ADP/MCP 集成和后续接口冻结仍明确标记。

## 初版阶段 1 验证（历史基线：北京时间 2026-11-04）

- `D:\python314\python.exe -m pytest -q`：**43 passed**。
- `D:\python314\python.exe -m ruff check src tests`：**All checks passed**。
- `D:\python314\python.exe -m meeting_reservation validate-examples --dir examples`（设置 `PYTHONPATH=src`）：**16 份示例全部通过**。
- `D:\python314\python.exe -m compileall -q src`：退出码 **0**。
- `uv build --wheel --out-dir .build_verify`：隔离式构建 **成功**；wheel 可从压缩包导入并加载 **5 个 JSON Schema**，示例通过校验。
- 开发时 TDD 验证：先运行到 **33 pass / 3 fail**（结束时间不晚于开始时间），随后实现统一跨字段时间检查，最终 **43 pass**。
- **证据边界：** 这里只证明 Python 契约工程与打包资源；没有连接真实 ADP、MCP、企微或会议系统，没有进行真实创建/修改操作。

## UPDATE 统一契约调整与本轮验证（北京时间 2026-11-04）

**变更范围：** 只修改尚未正式冻结的阶段 1 契约候选及其消费者测试、示例和说明，不实现真实 MCP Server 或会议写入。用户已明确选择删除 `SHIFT/PATCH` 互斥模式，统一为 `update.time_shift_minutes + update.changes`。原双模式结构被新候选 Schema 拒绝；目前不存在已发布消费者，故未增加双格式兼容或新版本迁移机制。

- `meeting-intent.v1.schema.json`：统一 UPDATE 对象，必填 `time_shift_minutes` 与 `changes`；允许非零时间偏移搭配非时间字段；拒绝偏移与绝对时间混用、无操作和未知字段。
- `contract.py`：删除 `mode` 分支，继续按真实时区比较显式起止时间；不实现基于原会议的修改提交逻辑。
- `examples/`：将旧示例更名为 `update-relative` 和 `update-fields`；新增 `update-combined.intent.json` 与 `submit-update.request.json`，合计 18 份。
- `tests/`：新增 `test_unified_update.py`，同步调整原始契约与 CLI 回归断言，覆盖正负平移、字段变更、组合修改、互斥、空更新、旧结构拒绝及嵌套 MCP Request。
- `README.md`、`CONTRACT.md`：明确统一结构和阶段边界，不再将双模式描述为正式接口。

**本轮实际验证：**

- Red：针对新结构新增的专项测试在旧 Schema 下 **10 failed / 12 passed**，失效原因与模式合并要求一致。
- Green：`D:\python314\python.exe -m pytest -q`：**67 passed**。
- `D:\python314\python.exe -m ruff check src tests`：**All checks passed**。
- 设置 `PYTHONPATH=src` 后执行 `python -m meeting_reservation validate-examples --dir examples`：**18 份示例全部通过**。
- `python -m meeting_reservation validate request examples/submit-update.request.json`：**通过**。
- `python -m compileall -q src`：退出码 **0**。
- `uv build --wheel --out-dir .build_verify`：**构建成功**；从 wheel 直接加载新契约并校验真实 `submit-update` 示例通过，确认包中包含全部 **5 份 JSON Schema**。

**验证范围说明：** 证明的是本地 Python 机器契约、示例、CLI 与 wheel 包资源。未进行腾讯 ADP、企业微信、MCP 服务端或真实会议系统的联调；修改后的协议仍需对接方正式确认。

## 阶段完成核对

上游要求与当前实现逐项核对后，阶段 1 的源码、契约、样例、CLI 和 Python 运行时检查满足本阶段范围。契约仍需会议系统/MCP 对接方复核，**尚未作为跨团队生产接口冻结**。阶段 2 的 ADP ↔ 测试 MCP 握手、身份传递和工具响应兼容性均未运行，不得据此声明联调已完成。

## Git、上线和后续

阶段 1 不包含 Git 初始化、提交、PR、部署或生产数据操作。后续阶段先通过 ADP → MCP 最小连通性和真实身份验证，然后接入会议业务逻辑，最后配置 ADP 工作流与企微机器人。
