# 施工状态

本文件按 `DEVELOPMENT_EXECUTION_PLAN.md` 的完整范围记账。Gate 通过只证明对应范围，完整交付须通过全部适用 Gate、跨 Gate 回归和产品质量门槛。未通过的 Gate 保持未通过。

## 已验证

| 验收门 | 当前状态 | 证据 |
| --- | --- | --- |
| Gate 0 工程可启动 | 已通过本机验收 | Python、Node 锁文件；PostgreSQL/pgvector 与 Redis Compose；两个 Runtime `/health`；Web 页面；无模型密钥启动与明确 503；开发 User/Administrator 身份；结构化应用日志。 |
| Gate 1 合同、迁移与存储 | 已通过本机验收 | 核心 schema 在一次性空库完成 upgrade、downgrade、re-upgrade；数据库直接拒绝非法状态组合、turn 101、第二个未回答 turn、答题时间错配、重复自然键和非 opaque source handle。准备流程 repository 使用同一短事务；Pydantic/OpenAPI/TypeScript 合同已生成并通过 Web 编译。后续业务的事务 seam 按修订施工书归入各自 Gate。 |
| Gate 2 准备流程 | 代码与真实模型链路已验收；原生选择器手工核验后补 | 公开 HTTP 与 Web 已接入创建、Markdown 导入、macOS 本机目录选择、清单/脱敏位置、观察、范围、选择和计划；快照变化清空方向/范围/计划，同内容及同选择重放保留计划。Local handle 绑定 session；只读工具、Repository Map、迭代 Observer、预算与逐行引用校验已实现；Planner 经确定性校验后条件发布。受控测试、真实 Planner、真实 Observer 和双 Runtime 观察链路均已通过固定合成材料。用户要求把原生选择器的手工核验留到以后。 |
| Gate 3 题库、检索与首题 | 已通过本机验收 | 11 个白名单文件的 573 条一级题去重后导入 537 道，重复运行不覆盖已有行。在线 BGE-M3、pgvector、FTS、RRF、topic 软权重和本机 BGE reranker 已接通；固定种子真实检索命中。首题使用真实 Supervisor 发布，候选 ID 仅在服务端精确匹配；检索超时可降级为空候选，重复 start 只发布一题，PostgreSQL 提交先于 SSE 通知，通知丢失后 GET 当前视图可恢复。 |
| Gate 4 实时面试闭环 | 面试范围已通过本机验收 | LangGraph 编排回答、检索、Supervisor、条件发布与 Stage 切换；原始回答仅写 PostgreSQL，模型和 compact 使用过滤文本；Redis 保存 interrupt、未发布决策和累计 compact。重复回答、显式决策重试、可编辑更正确认、Stage 关闭后的下一 Stage 首题、100 题安全上限与欠决策恢复已有正式路径。受控集成回归、超过 40 个 turn 的 compact 重建、真实模型两 Stage 对话及浏览器回答/刷新路径已验证。 |
| Gate 5 结束、赛后处理与结果 | 已通过本机验收 | 自然结束、提前完成、强退、100 题安全上限的终止路径已验证；题库结算与冻结反馈并发、事务回滚和 ACK 丢失重放均只计一次。参考答案顺序互换、单支失败、评估失败、报告失败、事后核验原子追加、部分 fan-out 重启、过期租约和迟到结果均经 PostgreSQL/Redis 故障注入；报告输入隔离及三个 Markdown 导出与当前事实一致。真实赛后模型 1 passed，Local Runtime 授权目录与失效 handle 降级 2 passed；双进程 worker 自动赛后处理及 trace 转发 1 passed。 |
| Gate 6 用户 Web | 页面与 checkpointer 代码已接入，待独立回归验收 | 用户 Web 已接准备、面试、结果双页签、八维雷达图与标签、反馈、三个导出、提前完成与二次确认强退；SSE 已使用命名事件。Interview/Finalization Graph 接入 LangGraph Redis checkpointer，使用本机现有 Redis Stack 7.4。固定浏览器旅程和完整故障窗口回归待独立实例执行。 |
| Gate 7 策展、删除与完整质量回归 | 未完成 | 策展、删除和跨 Gate 故障窗口回归尚未验收。 |

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
- 2026-10-28 Gate 5 实现后基本检查：Gate 4 与 Gate 5 定向集成 15 passed；补充题库关联的已答题和未答题结算计数后 Gate 5 基本集成 2 passed；Python Ruff、OpenAPI 生成、Web TypeScript/生产构建和 `git diff --check` 通过。未运行完整故障窗口及真实赛后模型回放，本条不构成 Gate 5 完整验收。
- 2026-10-28 Gate 5 正式回归：新增 `test_gate5_regression.py` 覆盖正常结束、两种反馈/终止行锁顺序、强退与回答/提前完成/迟到赛后结果竞争、结算事务回滚及并发重放、项目答案逐项校验与事后核验事务中断、参考答案完成顺序、失败降级、部分 fan-out 恢复、worker 过期租约与报告 ACK 丢失。真实赛后模型回放 1 passed；双 Runtime 授权目录及失效 handle 降级 2 passed。全量 Python 92 passed、12 skipped；Ruff、格式、`git diff --check`、Web 生产构建通过。跳过项仍为其他显式开启的真实模型、检索、跨进程测试。
- 2026-10-28 双进程 worker 回放 1 passed：Application 与 Local Runtime 独立进程运行，worker 自动完成赛后处理，本地模型调用 trace 成功转发入库。本次本地模型给出的事后核验缺少已读取行引用，Local Runtime 返回错误，Application 按合同改用快照模型生成项目答案；因此本条验证的是 worker、trace 和降级路径，不把它记为本地定向取证成功。上述单独的授权目录测试已验证本地定向取证成功。
- 2026-10-28 Gate 5 审查收敛：确认追加共用同一事务函数；赛后模型和 Local Runtime 任务各有独立时限，跨 Runtime HTTP 时限由本地任务预算加传输余量得到；评估在参考答案屏障后一次读取最终 snapshot/turns。Finalization Graph 用显式 Redis 阶段游标恢复节点位置（当前未接 LangGraph 内置 checkpointer），游标丢失时从 PostgreSQL 业务事实幂等重跑；上游设计和施工书未改写。Gate 4/5 定向回归 35 passed，新增阶段游标保留/丢失两种恢复用例均通过；完整 Python 回归 94 passed、12 skipped。
- 2026-10-28 Gate 5 审查收敛三处偏离，代码回归设计文本：正常结束不再套用完成 Stage 门槛，全部 Stage 以 unresolved 收尾的正常耗尽同样进入 `post_processing` 并产出报告（实现设计 8.3）；本地项目答案接口回归 11.2 节 `POST /v1/project-answer-tasks`，`source_handle` 移入请求体，session 绑定校验不变；删除赛后事后核验的行号证据硬校验，评估与报告 Prompt 改为明示「事后核验」区块由模型追加、可能不准确（Observer 侧引用校验仍属 Gate 2 已验收范围）。新增全部 unresolved 正常结束回归（stash 验证改前必红）与本地端点契约测试；全量 Python 回归 96 passed、12 skipped；Ruff 与格式检查通过。上游设计文档未改动。
- Web 和两个 Runtime 均可启动且健康检查通过。Codex 内置浏览器会拦截跨端口的本机 8100 请求，故本轮未把新目录选择页面记为手工通过。
- 2026-10-28 Gate 5 独立代码审查（未运行新测试）：对照 `PRODUCT_DEVELOPMENT.md` 与 `IMPLEMENTATION_DESIGN.md` 复核终止、结算、赛后依赖链、降级规则与结果投影的代码及测试映射。结论：符合上游合同，FW-POST-01～08 均有对应自动化用例，未发现第二业务事实或过度设计；第 5、6、7 条记录的偏离经复核维持原评估。新发现两项待办与一项轻微重复，见“接下来的施工依赖”第 8～10 条。
- 2026-10-28 Gate 6 施工：补齐用户 Web 的结果、反馈、导出与结束交互；Interview/Finalization Graph 改用 LangGraph Redis checkpointer，Compose 指向本机已有 `redis/redis-stack-server:7.4.0-v8` 并按镜像默认入口加载模块。Gate 3 首题/重试 4 passed，Gate 4 非旧 checkpoint 注入用例 7 passed；Web 类型检查和构建通过。旧测试中的手写 Redis key/阶段游标故障注入尚需按新 saver seam 改写，完整恢复与浏览器固定旅程由独立实例回归。

## 接下来的施工依赖

1. Gate 2 的原生目录选择器手工核验依用户要求后补。本地 operation ID 只在当前进程内短期合并重复观察；重启后可再次调用模型，业务发布仍由 Application 的内容比较与条件写入保障。
2. 独立回归 Gate 6 的固定浏览器旅程、Redis checkpoint 丢失/恢复与旧故障注入用例；继续 Gate 7 策展、删除，并逐项扩充 `tests/fault_windows` 中尚未自动化的跨 Gate 异常窗口回归。
3. 终态路径 Redis checkpoint 删除失败窗口仍待跨 Gate 故障回归。
4. Compact 持续失败时，Supervisor 的 `recent_turns` 可能随已回答 turn 增长；后续上量与 P95/P99 测试需验证上下文上限与恢复延迟，再决定符合“历史不遗漏”合同的处理方式。worker 扫描的 `SKIP LOCKED` 只在短扫描事务内生效，处理期间仍由 session execution lock 和 PostgreSQL 条件发布保障。
5. 赛后 `post_tasks.attempt_count` 最多领取 3 次，每次逻辑模型调用由 adapter 最多尝试 3 次；明确失败不再领取，崩溃和租约过期重领时物理调用最多可能达到 9 次，业务发布仍至多一次。`terminate` 当前用 PostgreSQL session 行锁与发布前状态复验串行化，没有额外取得设计文档 6.5 节所写的 Redis 执行锁；Gate 6～7 审查该偏离时应以故障窗口结果判断，不机械加锁。
6. LangGraph Redis checkpointer 已接入 Interview 与 Finalization 两图；旧手写 checkpoint 故障注入需要改用 saver seam 后重跑全部恢复回归。
7. 赛后 task 的 `work()` 内任何异常都会把任务置为 `failed` 且不可再领取：模型失败已有 adapter 预算，但瞬时基础设施错误（如复用题库理想答案时的数据库读抖动）也会永久烧掉该可空参考产物。租约 20 分钟为硬编码，与可配置任务上限（900 秒）的不变式没有断言保护；saver 目前每次打开新 Redis 连接。三者待后续 Gate 一并硬化。
8. 报告门槛规则（`normal` 结束或至少一个 `complete` Stage）目前在 `finalization.terminate_locked` 与 `finalization.result_view` 两处各实现一遍，违背施工书 3.5“一个业务不变量只保留一套权威实现”；应收敛为 `domain/rules.py` 中的单一判定，避免两处漂移导致“进入赛后但结果页判为不合格”之类的矛盾展示。
9. 强退未实现设计 6.5 步骤 6 的“提交后取消可取消的在途调用”（产品文档表述为“尽力取消”）：当前没有取消机制，迟到模型结果完全由发布前状态复验拒绝，`_run_task` 的 `stopped` 路径与三个强退竞争测试已覆盖该行为。与第 5 条执行锁偏离同类，正确性由条件发布保障；Gate 6～7 故障窗口审查时与第 5 条一并判定是否需要真实取消，此前不机械补建。
10. 轻微重复，触及相关文件时顺手收敛即可：`put_feedback` 的差评原因白名单在 router Schema 与 service 各校验一次；`full-qa` 投影复用 `ResultView` 顺带携带 report 字段造成轻微超取。均无行为影响。

以上剩余项仍属于同一交付范围。当前版本是可审查的施工进度，尚不是完整产品。
