# meeting_booking 实施进度与设计决策

本目录仅保存**当前实现与尚需完成的外部联调**；历史阶段一设计资料在 [roadmap/archive/](archive/) 中，不再作为当前仓库已实现能力的依据。

## 当前交付范围

本仓库已新增：会畅 BizVideoProvider、MCP Server、企微 UserID 签名验证、标准化创建/修改/空闲检查、多轮 pending 及 SQLite 操作台账、Fake Provider 测试、部署样例和重新分类后的文档。

**尚需取得新鲜验证证据：** 完整本地测试、Python MCP SDK v2 真正运行的 initialize/tools/list/tools/call、腾讯 ADP 结构化结果消费、真实企微用户身份传递、会畅测试站点创建/修改/冲突和并发/超时行为。没有这些证据不应称生产链路已上线。

## 从哪里继续

- [roadmap/01_实施路线图与任务状态.md](01_实施路线图与任务状态.md)：本次完整要求、设计取舍、验收矩阵和阶段状态。
- [docs/README.md](../docs/README.md)：代码及文档的阅读路线。
- [docs/testing/01_测试与联调验收.md](../docs/testing/01_测试与联调验收.md)：各层能证明什么、不能证明什么。
- [roadmap/archive/00-current-state.md](archive/00-current-state.md)：初始阶段一历史盘点；原计划文件继续保留在 archive，不再被当成当前设计。
