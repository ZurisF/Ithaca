# 施工状态

本文件按 `DEVELOPMENT_EXECUTION_PLAN.md` 的完整范围记账。Gate 通过只证明对应范围，完整交付须通过全部适用 Gate、跨 Gate 回归和产品质量门槛。未通过的 Gate 保持未通过。

## 已验证

| 验收门 | 当前状态 | 证据 |
| --- | --- | --- |
| Gate 0 工程可启动 | 已通过本机验收 | Python、Node 锁文件；PostgreSQL/pgvector 与 Redis Compose；两个 Runtime `/health`；Web 页面；无模型密钥启动与明确 503；开发 User/Administrator 身份；结构化应用日志。 |
| Gate 1 合同、迁移与存储 | 已通过本机验收 | 核心 schema 在一次性空库完成 upgrade、downgrade、re-upgrade；数据库直接拒绝非法状态组合、turn 101、第二个未回答 turn、答题时间错配、重复自然键和非 opaque source handle。准备流程 repository 使用同一短事务；Pydantic/OpenAPI/TypeScript 合同已生成并通过 Web 编译。后续业务的事务 seam 按修订施工书归入各自 Gate。 |
| Gate 2 准备流程 | 代码与真实模型链路已验收；原生选择器手工核验后补 | 公开 HTTP 与 Web 已接入创建、Markdown 导入、macOS 本机目录选择、清单/脱敏位置、观察、范围、选择和计划；快照变化清空方向/范围/计划，同内容及同选择重放保留计划。Local handle 绑定 session；只读工具、Repository Map、迭代 Observer、预算与逐行引用校验已实现；Planner 经确定性校验后条件发布。受控测试、真实 Planner、真实 Observer 和双 Runtime 观察链路均已通过固定合成材料。用户要求把原生选择器的手工核验留到以后。 |
| Gate 3 | 题库种子导入已完成，检索与首题待施工 | README 白名单只覆盖 11 个直接主题文件；573 条一级题目有 36 条精确重复，导入 537 条不同正文。BGE-M3 本机模型生成 1024 维向量，中文/技术词分词写入 PostgreSQL FTS；重复运行插入 0 条且不覆盖已有行。在线 Retrieval、Reranker 与首题发布尚未实现。 |
| Gate 4～7 | 未完成 | 面试 Graph 闭环、断线恢复、赛后、策展、删除、完整 Web 和故障窗口回归尚未验收。 |

## 最近验证

- `ruff check .`、`ruff format --check services packages tests scripts`、`git diff --check` 通过。
- `pytest -q --tb=line`：53 passed，5 skipped；一次性测试库迁移往返另行通过。跳过项是需显式开启的真实模型或跨进程测试。
- Gate 0～2 边界修复回归：目录切换后的迟到观察不能覆盖当前快照；Observer 与 Application 共用代码块感知的 Markdown 标题扫描；模型适配器在各 Runtime 内共享并发上限。OpenAPI 输出未变化。
- OpenAPI 与 Web TypeScript 客户端已重新生成；`npm run build --prefix apps/web` 通过。
- 新模型渠道沿本机代理调用：真实 Planner 1 passed，真实 Observer 1 passed，双 Runtime 的 handle 隔离和真实观察 2 passed。新增 `max_completion_tokens` 参数已在真实 Observer 调用中通过。
- 题库导入首次写入 537 条，第二次写入 0 条；再运行索引完整性检查为 537/537。受控入库测试验证已存在行不会被覆盖。
- Web 和两个 Runtime 均可启动且健康检查通过。Codex 内置浏览器会拦截跨端口的本机 8100 请求，故本轮未把新目录选择页面记为手工通过。

## 接下来的施工依赖

1. Gate 2 的原生目录选择器手工核验依用户要求后补。本地 operation ID 只在当前进程内短期合并重复观察；重启后可再次调用模型，业务发布仍由 Application 的内容比较与条件写入保障。
2. 依 Gate 3 落地在线检索、Reranker 与首题发布；继续补齐当前需要的事务 seam。
3. 依 Gate 4～7 实现面试、恢复、终止、赛后、策展、删除和正式 Web，并逐项映射 `tests/fault_windows`。

以上剩余项仍属于同一交付范围。当前版本是可审查的施工进度，尚不是完整产品。
