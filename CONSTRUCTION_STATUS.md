# 施工状态

本文件按 `DEVELOPMENT_EXECUTION_PLAN.md` 的完整范围记账。Gate 通过只证明对应范围，完整交付须通过全部适用 Gate、跨 Gate 回归和产品质量门槛。未通过的 Gate 保持未通过。

## 已验证

| 验收门 | 当前状态 | 证据 |
| --- | --- | --- |
| Gate 0 工程可启动 | 已通过本机验收 | Python、Node 锁文件；PostgreSQL/pgvector 与 Redis Compose；两个 Runtime `/health`；Web 页面；无模型密钥启动与明确 503；开发 User/Administrator 身份；结构化应用日志。 |
| Gate 1 合同、迁移与存储 | 已通过本机验收 | 核心 schema 在一次性空库完成 upgrade、downgrade、re-upgrade；数据库直接拒绝非法状态组合、turn 101、第二个未回答 turn、答题时间错配、重复自然键和非 opaque source handle。准备流程 repository 使用同一短事务；Pydantic/OpenAPI/TypeScript 合同已生成并通过 Web 编译。后续业务的事务 seam 按修订施工书归入各自 Gate。 |
| Gate 2 准备流程 | 代码与真实模型链路已验收；原生选择器手工核验后补 | 公开 HTTP 与 Web 已接入创建、Markdown 导入、macOS 本机目录选择、清单/脱敏位置、观察、范围、选择和计划；快照变化清空方向/范围/计划，同内容及同选择重放保留计划。Local handle 绑定 session；只读工具、Repository Map、迭代 Observer、预算与逐行引用校验已实现；Planner 经确定性校验后条件发布。受控测试、真实 Planner、真实 Observer 和双 Runtime 观察链路均已通过固定合成材料。用户要求把原生选择器的手工核验留到以后。 |
| Gate 3 题库、检索与首题 | 已通过本机验收 | 11 个白名单文件的 573 条一级题去重后导入 537 道，重复运行不覆盖已有行。在线 BGE-M3、pgvector、FTS、RRF、topic 软权重和本机 BGE reranker 已接通；固定种子真实检索命中。首题使用真实 Supervisor 发布，候选 ID 仅在服务端精确匹配；检索超时可降级为空候选，重复 start 只发布一题，PostgreSQL 提交先于 SSE 通知，通知丢失后 GET 当前视图可恢复。 |
| Gate 4 实时面试闭环 | 面试范围已通过本机验收；赛后 worker 分支随 Gate 5 继续 | LangGraph 编排回答、检索、Supervisor、条件发布与 Stage 切换；原始回答仅写 PostgreSQL，模型和 compact 使用过滤文本；Redis 保存 interrupt、未发布决策和累计 compact。重复回答、显式决策重试、可编辑更正确认、Stage 关闭后的下一 Stage 首题、100 题安全上限与欠决策恢复已有正式路径。受控集成回归、超过 40 个 turn 的 compact 重建、真实模型两 Stage 对话及浏览器回答/刷新路径已验证。 |
| Gate 5～7 | 未完成 | 赛后结算与产物、策展、删除、完整结果 Web 和跨 Gate 故障窗口回归尚未验收。 |

## 最近验证

- `ruff check .`、`ruff format --check services packages tests scripts`、`git diff --check` 通过。
- `pytest -q --tb=short`：57 passed，7 skipped；一次性测试库迁移往返另行通过。跳过项是需显式开启的真实模型、真实检索或跨进程测试。
- Gate 0～2 边界修复回归：目录切换后的迟到观察不能覆盖当前快照；Observer 与 Application 共用代码块感知的 Markdown 标题扫描；模型适配器在各 Runtime 内共享并发上限。OpenAPI 输出未变化。
- OpenAPI 与 Web TypeScript 客户端已重新生成；`npm run build --prefix apps/web` 通过。
- 新模型渠道沿本机代理调用：真实 Planner 1 passed，真实 Observer 1 passed，双 Runtime 的 handle 隔离和真实观察 2 passed。新增 `max_completion_tokens` 参数已在真实 Observer 调用中通过。
- 题库导入首次写入 537 条，第二次写入 0 条；再运行索引完整性检查为 537/537。受控入库测试验证已存在行不会被覆盖。
- Gate 3 受控 HTTP 回归 4 passed；真实本机混合检索 1 passed，真实 Supervisor 首题发布 1 passed；Web 生产构建通过。首题模型失败只进入显式 `decision_retry`，重复 start 不暗中重试。
- Gate 4 受控 HTTP/PG/Redis 回归覆盖同答重放与并发、不同答冲突、Stage 推进、更正确认和拒绝、脱敏后二次确认、显式重试、回答及 Stage 关闭后的进程恢复、SSE 丢失重读、20/40 turn 累计 compact 与 Redis 全丢重建，以及第 100 题后停止。真实 Supervisor 回放完成一次追问和一次 Stage 关闭；Web 从创建会话到第二题、刷新恢复均已手动走通。全量 Python 回归 68 passed、8 skipped；Web 构建与类型检查通过。新 Application 进程的首次检索遇到本机 BGE 资源加载失败，按合同降级为空候选，面试继续发布问题。
- 2026-10-28 Gate 4 回归复查：受控集成新增模型返回后、Stage checkpoint 写入后两个中断点，共 13 passed；真实 Supervisor 两阶段回放 1 passed；跨 Gate Python 71 passed、8 skipped；Web 生产构建及 TypeScript 检查通过。计划资产加载与校验已在 Planner 和面试启动间共用；重复校验的受控 adapter 屏障补注释，题库向量检查和目录数量上限收敛为单一来源。二次审查移除了不可靠的问号数量校验，明确 interrupt 中新题号的 `operation_in_progress` 与已答题不同答案的 `answer_conflict`；真实 Supervisor 回放复测通过。
- Web 和两个 Runtime 均可启动且健康检查通过。Codex 内置浏览器会拦截跨端口的本机 8100 请求，故本轮未把新目录选择页面记为手工通过。

## 接下来的施工依赖

1. Gate 2 的原生目录选择器手工核验依用户要求后补。本地 operation ID 只在当前进程内短期合并重复观察；重启后可再次调用模型，业务发布仍由 Application 的内容比较与条件写入保障。
2. 依 Gate 5 完成终止命令、反馈冻结、题库结算和赛后依赖链，并让同一 Application worker 承接 `post_processing` 与终态未结算 session；当前 worker 只恢复欠下的面试决策。
3. 依 Gate 6～7 完成结果、策展、删除和完整 Web，并逐项扩充 `tests/fault_windows` 的异常窗口回归。
4. Gate 5 终态路径需删除 interview checkpoint，并验证 Redis 删除失败窗口；Gate 6 需将当前通用 `current_changed` 通知对齐设计文档列出的命名 SSE 事件。
5. Compact 持续失败时，Supervisor 的 `recent_turns` 可能随已回答 turn 增长；Gate 5 上量与 P95/P99 测试需验证上下文上限与恢复延迟，再决定符合“历史不遗漏”合同的处理方式。worker 扫描的 `SKIP LOCKED` 只在短扫描事务内生效，处理期间仍由 session execution lock 和 PostgreSQL 条件发布保障。

以上剩余项仍属于同一交付范围。当前版本是可审查的施工进度，尚不是完整产品。
