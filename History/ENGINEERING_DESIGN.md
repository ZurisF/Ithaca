# 项目模拟面试 Bot：工程设计

> 状态：Draft v0.2，可用于建立正式工程骨架  
> 日期：2026-10-28  
> 产品基线：[PRODUCT_DEVELOPMENT.md](./PRODUCT_DEVELOPMENT.md)，Draft v0.5  
> 依据范围：仅当前产品文档，未参考历史文档。本文不修改产品文档。

本文先说明系统如何划分职责、各模块如何完成一场面试，再展开数据、接口与恢复机制，最后给出验证和实施顺序。前 3 节用于理解整体设计，第 4～6 节用于实现，第 7～8 节用于验收与交付。

这里给出首版默认实现决定；表字段中的操作标识、租约、计数器和配置引用都是工程内部字段，不扩散到 Agent 输出或用户产品字段。

产品中的 Markdown 快照、线性 Stage、三个动作、上下文隔离、授权策展、单层有界重试和数据采集边界继续成立。实现遇到与产品规则冲突的情况时，应修正本设计，不能通过增加隐藏状态或隐式调用改变产品行为。

## 1. 设计目标与关键取舍

### 1.1 设计目标

首版需要在同一套正式工程中完成项目准备、实时面试、赛后复盘与授权策展。架构优先保证目录访问受控、业务事实可恢复、模型结果不会重复推进流程，以及各 Agent 的上下文隔离。

| 关键决定 | 设计依据 |
| --- | --- |
| 将目录能力放在独立 Local Runtime，通过任务接口协作 | 原始路径与读取权限留在本机，Application Runtime 只处理授权结果；两个进程的边界可独立测试 |
| PostgreSQL 保存业务事实，Redis 保存执行现场 | checkpoint 丢失后仍可根据问答、Stage 结果和操作回执恢复；跨存储恢复不依赖两者同时提交 |
| 领域服务控制业务效果，LangGraph 组织执行顺序 | 模型输出、节点重放与并发任务都经过相同的状态检查和事务约束 |
| 实时提问与赛后处理隔离 | Supervisor 的职责和上下文保持有限；双答案、逐题评估和报告按明确依赖并行或汇合 |
| 采用数据库任务表与无正文业务通知 | 任务入队与业务变更可同事务提交，断线后可从当前业务视图继续，通知不会形成另一份内容存储 |

### 1.2 技术路径

| 项目 | 首版决定 |
| --- | --- |
| Web | Next.js + TypeScript；浏览器只消费经过校验的业务视图，不消费模型 token 流 |
| 服务 | 两个独立 FastAPI 进程：Local Project Runtime 与 Application Runtime；Demo 都绑定 loopback |
| 编排 | LangGraph；所有业务写入通过 Application Runtime 的领域服务 |
| 业务存储 | PostgreSQL；SQLAlchemy + Alembic 管理访问与迁移 |
| 执行现场 | Redis checkpointer，外加适配器处理执行代次隔离和终态清理 |
| 后台任务 | PostgreSQL 任务表 + 应用 worker；与业务变更同事务入队，不引入 Celery |
| 检索 | BGE-M3 dense + pgvector；词法通道选 PostgreSQL FTS；RRF 后使用 Reranker |
| 事件传输 | SSE 发送业务变更通知；客户端重新读取当前视图，数据库保留无正文通知游标 |
| 模型 | 统一 Adapter；供应商、模型 ID、上下文容量、输出上限和价格来自受控配置，初始化时验证 |
| 配置 | Topic、五类 Planner 模板、Prompt、Schema、预算组成不可变配置包；一场会话固定引用同一包 |

精确依赖版本在建立工程时锁定，随后由集成测试验证兼容性。本文不把尚未验证的库版本、模型容量或响应时延当作产品保证。

### 1.3 首版行为口径

1. **问题发布时点**：模型输出校验通过后，事务把问题写入 `turns` 并使其可被会话视图读取，这就是服务端的“展示”。浏览器重连展示同一 `turn_no`，不再创建问题；不采集页面曝光或渲染确认。尚未发布的模型候选不计 turn。数据库提交与浏览器实际绘制无法组成原子事务。
2. **未作答的尾题**：提前完成时保留 `answer = null`。满足报告门槛时仍可生成该题参考答案；评估必须说明“未作答，不据此判断能力”，报告不得把它当成错误答案。只请求澄清的消息同样不能直接解释为能力不足，由评估 Prompt 和回归样本约束，不新增持久化行为标签。
3. **提问结束与处理完成分开**：`termination_reason` 一旦写入，回答与反馈立即冻结；`status = finalizing` 表示赛后尚未完成。赛后自动尝试耗尽后进入 `completed`，界面根据任务结果明确显示“处理未完成”，不伪造报告，也不提供用户手动重跑赛后的入口。
4. **指标采集**：遵守产品第 16 节。查看率、展开率等无法从现有业务事实得到的指标，只用于另行组织的验证实验，首版不加点击流。
5. **策展首版**：提供已授权材料筛选、编辑、隐私处理建议、查重、理想答案补充和人工发布；整理 Agent 只在管理员选择材料后执行。Phase 2 的自动批处理与更完整工作台不进入本次骨架。
6. **范围选择**：有解析结果时至少选一个范围；用户希望覆盖全部时选中全部。仅在没有可解析范围且明确确认继续时，`selected_sections = []`。不增加一个含义不同的“未限定范围”隐式分支。

## 2. 系统边界与模块职责

### 2.1 运行边界与身份

首版预置一个 User 身份和一个独立 Administrator 身份，不实现注册、组织或成员管理。运行配置把两个本地登录凭据分别映射到数据库 principal；凭据不进入前端构建产物或会话表。浏览器使用 HttpOnly 会话 cookie，写请求检查 CSRF 与 Origin；身份和角色只能由服务端解析。

Local Runtime 的目录选择、授权和原始路径处理全部在本机完成。Application Runtime 只保存绑定本场会话的不透明 `source_handle`。即使两个服务物理同机，也只通过 HTTP 合同通信。双方使用受控服务凭据，Local Runtime 校验会话绑定；`source_handle` 本身不能作为万能 bearer 凭据。

### 2.2 模块协作

| 模块 | 主要职责 | 对外边界 |
| --- | --- | --- |
| Web 与 API | 组织用户输入、展示当前视图、认证和请求校验 | 发送业务命令，读取已提交结果；不直接采用模型候选 |
| Local Project Runtime | 目录授权、清点、过滤、受限取证、Observer 与有目录的项目版答案 | 接受绑定会话的本地任务，返回安全文本与结果 |
| 领域服务与持久化 | 检查状态和权限，执行追加、发布问题、结束与结果采用事务 | 对所有调用者提供统一的业务写入入口 |
| Graph 与任务执行器 | 装配上下文、安排节点、等待用户、并行任务与汇合恢复 | 通过领域服务提交效果，通过 Adapter 调用模型 |
| 检索服务 | 题库索引、候选检索、冷却与实际问题匹配 | Supervisor 只收到题目正文；统计与答案路由使用内部匹配结果 |
| 共享合同、安全过滤与模型 Adapter | 校验结构、过滤文本、控制预算与重试、记录无内容 trace | 两个 Runtime 复用相同规则，不因此共享目录权限 |

一次面试的协作顺序见第 3 节。业务写入以第 4 节的事务合同为准，进程间通信以第 5 节的 API 合同为准。

### 2.3 工程目录与依赖方向

```text
apps/web/                         页面、业务视图、SSE、同源 API 代理
services/application/api/         认证、请求校验、HTTP/SSE
services/application/domain/      状态转换、业务不变量、事务服务
services/application/graphs/      State、节点、路由、恢复入口
services/application/jobs/        任务领取、租约、调度与清理
services/application/retrieval/   召回、融合、重排、冷却、严格匹配
services/application/persistence/ 表、查询、事务、迁移
services/local_project/           授权目录、受限工具、Observer、项目版答案
packages/contracts/              API/Agent 的 JSON Schema 与生成类型
packages/text_safety/             两个 Runtime 共用的纯文本过滤器
packages/model_adapter/           预算、请求、重试、结构化输出、无内容 trace
config/bundles/                   Topic、模板、Prompt、Schema、预算配置包
tests/{unit,integration,faults,e2e,quality}/
```

Application Runtime 禁止依赖 `services/local_project` 的文件读取模块；通过静态依赖检查验收。`text_safety` 不包含目录访问、数据库写入或网络权限。

## 3. 核心流程与 Agent 编排

### 3.1 端到端执行顺序

```text
准备：
  create session → local observe / import → accept snapshot
  → review + optional opinion → confirm snapshot
  → parse/select ranges → plan → accept plan → ready

开始/恢复：
  load authoritative facts
  ├─ 已终止 → 赛后/结果视图/结束旧执行
  ├─ 已有未回答问题 → wait_for_answer
  ├─ 已回答但没有 decision receipt → question_rag → supervisor_decision
  └─ 当前 Stage 尚无首题 → question_rag(goal) → supervisor_decision

决策：
  validated output
  → [correction interrupt → append or skip]
  → apply decision
      ├─ continue → publish one question → compact if due → wait_for_answer
      └─ close stage → compact if due
           ├─ next Stage → load → RAG(goal) → new Supervisor call
           └─ exhausted → finish(normal)

赛后：
  [whole-session project answers || per-question ideal answers]
  → final snapshot barrier
  → per-question evaluations
  → all evaluations succeeded ? report : incomplete
  → completed → checkpoint cleanup
```

子任务结果落库并唤醒 graph_runner；它们不能直接同时 resume 同一个图。graph_runner 对 session 独占租约，负责汇合和继续。赛后并行任务只写自己的结果列，通过共享事务服务检查 session/epoch/fence。

节点等待子任务时可以让执行任务进入 waiting 并释放 worker，由完成通知唤醒后重查数据库；等待用户使用 interrupt。图的继续位置是 checkpoint，业务完成证据是 receipt/产物/任务结果，两者职责分开。

### 3.2 Graph State

下面是字段合同，类型名在 `packages/contracts` 定义；示例不表示要把整个状态透传给任一模型。

```python
class InterviewState(TypedDict):
    session_id: str
    execution_epoch: int
    current_stage_index: int
    snapshot: str                         # 从 PostgreSQL 装载的工作副本
    current_stage: Stage | None
    call_context: CallContext | None      # stage_first 或 answer + 业务定位
    compact: str | None
    compacted_through_turn: int           # 最近已折叠的已处理 turn
    recent_turns: list[TurnView]
    rag_candidates: list[str]             # 最多 3 条，只有题目正文
    pending_decision: SupervisorOutput | None
    pending_correction: CorrectionDraft | None
    pending_post_verification: str | None
    reference_job_ids: list[str]
    evaluation_job_ids: list[str]
```

```text
CallContext =
  {kind: "stage_first", stage_index: int}
  | {kind: "answer", turn_no: int, stage_index: int}

CorrectionDraft = {
  candidate_id, turn_no, sanitized_text,
  preview_token, disposition: "pending" | "accepted" | "skipped"
}

SupervisorOutput = {
  user_acts: UserAct[],
  interviewer_message: string | null,
  plan_action: "continue" | "complete" | "unresolved",
  question: string | null
}
```

State 中不放权限凭据、真实目录、原始未过滤输出、反馈、两版参考答案全文或另一套业务状态。worker fence 属于执行上下文，每次接管重新取得，不能信任 checkpoint 中旧 worker 的 fence。

`thread_id` 由 `session_id + execution_epoch` 组成。普通浏览器断线保持同一代；仅发生终止失效或无法使用 checkpoint 的重建时切换代次。终态清理必须枚举本场所有代次。

每个模型节点在内存中完成调用、JSON 解析、Schema 校验和内容过滤后，才返回可持久化 State 更新。不能先把原始输出交给 LangGraph，再由下一节点过滤；checkpoint 同样是敏感内容边界。

### 3.3 节点职责与重放约束

| 节点 | 读取 | 输出/效果 | 重放规则 |
| --- | --- | --- | --- |
| `load_session_context` | session、plan、stage_results、turns | 刷新 snapshot、Stage、近期历史 | 每次入口重读业务库；遇到终止或 epoch 变化停止旧路径 |
| `observe_project` | 本场 source_handle、预算 | 本地 Observer 任务引用 | 稳定任务 ID；成功结果只接受一次 |
| `accept_initial_snapshot` | 导入/Observer 的安全 Markdown | 初始 snapshot、receipt | 已接受不覆盖；导入无范围不在此拒绝 |
| `review_snapshot` | 当前 snapshot | interrupt，等待审阅确认 | 意见追加单独事务；节点不做重复副作用 |
| `plan_interview` | 完整 snapshot、选择、方向、Topic、模板 | 合法计划候选 | 一次生成、最多一次格式修复；不生成兜底通用计划 |
| `accept_plan` | 已校验候选 | 持久化 plan、模板引用 | `plan.accept` 唯一；start 后不可替换 |
| `question_rag` | 当前回答或 Stage goal、topic | 0～3 条正文 | 超时/失败降级为空；没有额外流程决策权 |
| `supervisor_decision` | 固定白名单上下文 | 安全的 pending_decision | 先检查 decision receipt；只产生一个有效决策 |
| `review_correction` | 已过滤候选 | interrupt，确认/编辑/跳过 | 一个候选确认点；不调用第二次 Supervisor |
| `persist_snapshot_append` | State 中已确认安全文本 | snapshot 追加、receipt | 先确认数据库结果，再刷新 State；未知结果阻塞 |
| `apply_supervisor_decision` | pending_decision、业务当前状态 | 发布题目或关闭 Stage | 领域事务 + 唯一 decision receipt |
| `compact_history` | 旧 compact + 新 20 个完整已处理 turn | 新 compact、覆盖位置 | 原文不改；重复生成不产生业务效果 |
| `wait_for_answer` | 当前已发布、未回答 turn | interrupt | 回答先在业务库持久化；resume 只传定位信息 |
| `finish_interview` | 结束原因、Stage 结果 | 冻结、任务入队或无报告完成 | 单事务，强制退出具有撤销旧执行权 |
| `start_reference_jobs` | 冻结的全部实际问题 | 整场项目版 + 逐题理想版任务 | 稳定 job_key，存在则复用，不再创建一批 |
| `join_references` | 任务终结状态、已写入答案 | 最终 snapshot | 两类处理都到有界结果才放行；post-verification 必须先提交 |
| `start_evaluations` | 最终 snapshot、本题 Q/A、可空双答案 | 每题一个任务 | 不给评估器整场对话；失败只影响本题 |
| `join_evaluations` | 全部 comment 与任务状态 | 报告就绪或处理未完成 | 有永久失败时不伪造 comment，也不调用报告补评 |
| `generate_report` | 最终 snapshot、按序 stage/Q/A/comment | 固定 JSON 报告 | 所有逐题评价成功后执行；不读取双答案 |
| `complete_session` | 赛后成功/失败结果 | completed、清理 checkpoint | 已成功结果保留；缺失明确显示，不提供赛后人工重跑 |

准备阶段任务、面试推进和赛后汇合都由 Application Runtime 编排。Local Runtime 只执行本地任务，不持有另一个能推进业务会话的 LangGraph。

### 3.4 对话上下文与 compact

同一 turn 的真实对话顺序为 `question → answer → interviewer_message`。compact 在该 turn 的决策完成后、下一次需要模型上下文前执行；每累计 20 个已回答且已处理的 turn，折叠旧 compact 和这 20 个 turn。尚未回答的下一题保留在近期原文中。

待处理的第 20 条回答仍以原文供本轮 Supervisor 使用；其决策完成后压缩。容量检查因此必须容纳这一边界上的 20 条完整 turn，不能只按“平时不足 20 条”估算。

compact 内容只总结既有对话，不产生新问题、评分、答案或控制动作。辅助调用使用统一 Adapter，首版最大 2 次尝试；失败时保留原文并阻塞需要该上下文的下一次调用，允许重试，不丢弃历史或无界扩充上下文。

Supervisor 只收到产品规定的六部分；`current_stage_index`、job、fence、receipt、反馈、匹配结果和执行错误不作为额外 Prompt 元数据注入。当前回答在历史中只出现一次，RAG 单独读取同一回答文本。

### 3.5 赛后并行与结果采用

项目版答案输出外层为 `{answers: [{turn_no, project_answer}], post_verification: string|null}`。外层只是传输合同，快照仍是一份 Markdown。顶层 JSON 不可解析时整批作废；可解析时采用通过校验的唯一 turn 项，无效或重复项不采用，缺失项保留 null。

项目版答案依赖目录新增事实时，必须先提交经过过滤的 post_verification，再采用本批答案。为避免增加逐题依赖字段，存在核验追加的批次整体等待追加成功；追加被拒绝或无法安全使用时整批项目版答案不采用，按缺失降级。未知数据库提交结果不能当成失败绕过汇合屏障。

本地 handle 失效时由 Application Runtime 使用同一项目版答案合同执行 snapshot-only 降级，不访问文件。这仍是同一个整场任务，不改成逐题项目调查。旧本地任务的结果凭 task fence 失效，不能与降级结果双重采用。

理想版每题独立：已复制合法题库答案则直接成功，否则调用生成器。项目版任务结束和每题理想版任务成功/失败都形成有界结果后，再启动评估。任何一种答案缺失都不直接降低用户评价。

逐题评估输入只包含最终快照、本题 Q/A 和可空双答案，输出 `{comment: string}`。某题评价耗尽重试后，保留其他成功产物、整场标为处理未完成；报告不接收伪造占位 comment。报告失败同样保留完整问答结果。

### 3.6 检索与严格匹配

在线检索顺序固定为：Topic 软权重 → dense/FTS 双路召回 → RRF → Reranker → 最近 3 个 turn 冷却 → 0～3 条正文。冷却读取会话最近问题，仅做结果过滤，不把这些问题拼入查询文本。

FTS 对中文和技术词先做受控分词，使用 PostgreSQL simple 配置承载词项；用固定样本检验中文术语、英文标识符、错误码和带符号技术名。ideal_answer 不参与任何查询索引。

赛后 `match_actual_question` 复用召回和重排组件，但使用更严格的身份匹配规则：相关问题不等于同一道题。首批允许规范化后的精确匹配；语义匹配阈值、候选间距和对象/约束一致性规则必须经过已标注正反例校准后启用。未经校准的语义高分只能用于候选，不能结算统计或复用理想答案。

Reranker、召回参数、匹配阈值均在配置包内；内部返回分数和 question_id，面向 Supervisor 的适配层只输出正文数组。RAGAS 只在离线回归环境运行。

## 4. 数据模型与一致性

### 4.1 存储约定

- 主标识使用 UUID；`turn_no` 从 1 开始，`stage_index` 从 0 开始。
- 数据库时间使用带时区时间；前端负责按用户时区显示。
- 所有会话内容查询先检查 owner；管理员内容查询额外检查 `curation_review = true`。
- 下表未标可空的业务字段均非空；准备阶段的可空字段见明确说明。
- 会话子表外键默认 `ON DELETE CASCADE`。删除会话采用第 6.4 节的清理协议，不能只执行单表删除。
- 跨行、跨 JSON 的不变量由领域事务服务检查；CHECK、UNIQUE、FK 兜住能在数据库表达的部分。不能把“写了 JSON Schema”当成数据库并发保证。
- 本文的完整性检查全部针对脱敏后的工作内容。数据库、checkpoint、任务载荷和错误详情均不保存未过滤文本。

### 4.2 业务数据模型

#### `principals`

| 字段 | 类型/约束 |
| --- | --- |
| `id` | UUID PK |
| `role` | `user \| administrator` |
| `display_name` | text |

不允许从请求 body 指定角色或把任意 `user_id` 当作当前用户。

#### `interview_sessions`

| 字段 | 类型/约束 |
| --- | --- |
| `id` | UUID PK，即 `session_id` |
| `user_id` | UUID FK → principals；创建时必须是 User |
| `create_command_id` | text；UNIQUE `(user_id, create_command_id)`，用于创建请求重传 |
| `status` | `preparing \| interviewing \| finalizing \| completed \| aborted \| deleting` |
| `interview_direction` | 可空；五种方向枚举 |
| `selected_sections` | JSONB，默认 `[]`；元素为 `{kind, title}` |
| `snapshot` | 可空 text；准备阶段接受一次初始全文，之后只允许追加 |
| `snapshot_confirmed_at` | 可空 timestamptz；准备流程确认点 |
| `source_handle` | 可空 text；不含真实路径 |
| `interview_plan` | 可空 JSONB；结构为有序 Stage 数组 |
| `termination_reason` | 可空；`normal \| early_finish \| force_exit \| safety_cap` |
| `curation_review` | boolean，默认 false |
| `config_bundle_id` | text；不可变配置包引用，包括 Topic/模板/Prompt/Schema/预算版本 |
| `planning_template_ids` | JSONB，默认 `[]`；Planner 实际使用的已审核模板 ID |
| `execution_epoch` | bigint，默认 1；终止、删除或 checkpoint 重建时递增，用于拒绝旧执行者 |
| `view_seq` | bigint，默认 0；本场已提交业务通知序号 |
| `created_at / updated_at` | timestamptz |

`deleting` 是清理过程的内部状态，不是新增面试阶段。`execution_epoch` 不是快照版本；不维护快照历史、源文件哈希或持久化范围 ID。

关键约束：

- `interviewing` 要求 snapshot 已确认、方向与合法 plan 存在，且 `termination_reason IS NULL`。
- `finalizing / completed / aborted` 必须有 `termination_reason`；`aborted` 的 reason 必须是 `force_exit`。
- plan 开始面试后不可改；初始 snapshot 已接受后不可替换。用户需要替换来源时创建新 session，不偷偷覆盖原文。
- 不存 `current_stage`、`current_stage_index` 或 `completed_stage_count` 的业务副本。当前索引由已关闭 Stage 的连续前缀重建。
- 不存 report 状态、反馈冻结标记等重复真相：冻结条件是 reason 非空或 status 为 deleting；结果可用性从产物和任务状态计算。

#### `stage_results`

| 字段 | 类型/约束 |
| --- | --- |
| `session_id` | UUID FK |
| `stage_index` | integer，CHECK ≥ 0 |
| `result` | `complete \| unresolved` |
| `closed_at` | timestamptz |
| 主键 | `(session_id, stage_index)` |

只能关闭当前 plan 中存在且尚未关闭的 Stage。事务锁定 session 后检查已关闭索引是 `0..k-1`，只接受 index `k`。`count(result = complete)` 即报告门槛所需的临时值。

#### `turns`

| 字段 | 类型/约束 |
| --- | --- |
| `session_id` | UUID FK |
| `turn_no` | integer，CHECK `1 <= turn_no <= 100` |
| `stage_index` | integer，CHECK ≥ 0 |
| `question` | 非空 text |
| `answer` | 可空 text；仅接收一次过滤后的用户消息 |
| `interviewer_message` | 可空 text；回复归属于被回应的 turn |
| `published_at / answered_at` | timestamptz；answered_at 可空 |
| 主键 | `(session_id, turn_no)` |

```sql
CREATE UNIQUE INDEX one_unanswered_turn_per_session
    ON turns (session_id) WHERE answer IS NULL;

ALTER TABLE turns ADD CONSTRAINT answer_timestamp_consistent
    CHECK ((answer IS NULL) = (answered_at IS NULL));
```

发布下一题时锁定 session，并使用现存最大 `turn_no + 1`，同时检查不存在未回答问题、Stage 匹配、会话仍允许提问。单靠 `MAX + 1` 或自增序列不能保证业务连续性。

同一 turn 的相同回答重传返回已有状态；不同回答返回 409。首版没有回答修改接口。空字符串不算有效提交；“不知道”、拒答和澄清请求都是合法非空消息。

#### `turn_feedback`

| 字段 | 类型/约束 |
| --- | --- |
| `session_id / turn_no` | 复合 PK/FK → turns |
| `vote` | `upvote \| downvote` |
| `reason` | 可空；`duplicate \| irrelevant \| unclear \| other` |
| `updated_at` | timestamptz |

CHECK：upvote 的 reason 必须为空。PUT 可以覆盖现有选择；不提供未定义的收藏或任意评论字段。反馈更新与终止流程都锁同一 session 行，保证冻结边界可判定。

#### `turn_results`

| 字段 | 类型/约束 |
| --- | --- |
| `session_id / turn_no` | 复合 PK/FK → turns |
| `project_answer` | 可空 text |
| `ideal_answer` | 可空 text |
| `comment` | 可空 text |

三个字段分别由对应任务写入。UPDATE 只能填写本任务拥有的空字段，不能以整行 upsert 覆盖其他并行任务的成功结果。失败原因和执行进度放在任务表，不向这些产品字段加入置信度、来源数组或状态 flag。

#### `reports`

| 字段 | 类型/约束 |
| --- | --- |
| `session_id` | UUID PK/FK |
| `body` | JSONB；严格遵循产品 6.8 节的固定报告合同 |
| `created_at` | timestamptz |

写入前校验固定键、八个维度、`score` 为 0～5 整数。JSON Schema 固定并拒绝额外结构字段，正文不做自动事实判定。Markdown 和 UI 都从该记录渲染，不再调用模型。

#### `question_bank`

| 字段 | 类型/约束 |
| --- | --- |
| `id` | UUID PK，内部键 |
| `question / topic_path` | 非空 text；topic 必须属于正式 Topic 树 |
| `ideal_answer` | 可空 text |
| `usage_count / upvote_count / downvote_count` | bigint，默认 0，CHECK ≥ 0 |
| `embedding` | pgvector；维度按锁定的 BGE-M3 配置验证 |
| `lexical_document` | tsvector，索引实现字段 |
| `search_ready` | boolean；索引未完成的条目不进入 RAG |
| `updated_at` | timestamptz；用于并发编辑校验，不是题目版本号 |

embedding 和词法索引只能由 question 生成，不能混入 ideal_answer。编辑题目时先置 `search_ready = false`，索引任务写回前核对 question/topic 仍与本次输入相同，成功后一起开放检索。老索引结果不能覆盖新编辑。

Topic 与模板保存在配置包中，不为 Agent 的每个概念分别建表。

#### `question_matches` 与 `question_settlements`

| 表 | 字段与约束 |
| --- | --- |
| `question_matches` | PK/FK `(session_id, turn_no)`；可空 `question_id` FK → question_bank；`matched_at`。记录存在且 question_id 为空表示已完成匹配但无可靠归属；没有记录表示尚未完成 |
| `question_settlements` | `session_id` PK/FK；`settled_at`。只在整场计数事务成功时写入 |

不向 Supervisor 或 turn 增加题库来源字段。结束后的匹配结果是统计与理想答案路由共用的内部业务依据；不能由两条流程各自匹配一次并得到不同归属。

在接受可靠匹配的事务中读取并锁定当前题库条目，核对 question/topic 与计算匹配时相同；已改变则放弃该次匹配并重查。有理想答案时将其经过安全处理后复制到本题 `turn_results.ideal_answer`。复盘不受之后题库编辑影响。强制退出和无报告会话只匹配、结算，不复制答案、不启动赛后 Agent。

### 4.3 执行、幂等与通知模型

#### `operation_receipts`

| 字段 | 类型/约束 |
| --- | --- |
| `session_id / operation_key` | 复合 PK；session FK |
| `id` | UUID UNIQUE；可按 session/operation_key 确定性生成，用于查询写入结果 |
| `request_fingerprint` | 可空 text；仅用于比较同一命令键的规范化请求，不用于项目文件一致性或快照版本 |
| `result_ref` | JSONB；仅业务位置，如 turn_no、stage_index、任务键；不存模型原始输出 |
| `committed_at` | timestamptz |

记录只与业务效果在同一事务提交。未完成的工作不能先写一条“成功 receipt”。请求指纹使用服务端 HMAC，避免把短敏感文本的裸哈希放入存储；仅对已过滤请求计算。

| 业务效果 | 稳定 operation_key |
| --- | --- |
| 初始快照接受 | `snapshot.initial` |
| 审阅意见追加 | `snapshot.opinion:{client_command_id}` |
| 计划接受 | `plan.accept` |
| 回答接收 | `answer:{turn_no}` |
| 应用回答后的 Supervisor 决策 | `decision:answer:{turn_no}` |
| 某 Stage 首题发布 | `decision:stage-first:{stage_index}` |
| 确认的事实更正追加 | `snapshot.correction:{turn_no}` |
| 更正确认卡选择跳过 | `snapshot.correction.skip:{turn_no}` |
| 赛后核验追加 | `snapshot.post-verification` |
| 逐题结果采用 | `result:{kind}:{turn_no}` |
| 整场报告采用 | `report.accept` |

Supervisor 应用 receipt 不存 user_acts 或 plan_action，只存已发生业务后果的位置。正常 replay 先查 receipt；存在就重装业务状态，不能再次问模型或推进 Stage。

#### `runtime_jobs`

| 字段 | 类型/约束 |
| --- | --- |
| `id` | UUID PK |
| `session_id` | UUID FK；非会话索引维护任务可空 |
| `job_key` | text；会话内唯一；全局任务使用独立 namespace 唯一键 |
| `kind` | observer、planner、graph_runner、project_answers、question_match、ideal_answer、evaluation、report、settlement、index 等白名单 |
| `subject_ref` | JSONB；只存 turn_no、题目 ID 等定位信息，不复制快照或对话 |
| `status` | `queued \| running \| waiting \| succeeded \| failed \| cancelled` |
| `execution_epoch` | bigint；本任务所属执行代次 |
| `lease_owner / lease_until / fence` | worker 标识、租约期限、递增隔离号 |
| `wake_seq / handled_seq` | graph_runner 使用的唤醒序号；避免工作期间的新唤醒丢失 |
| `retry_generation` | integer；仅实时/准备失败的显式人工重试创建新代次，赛后禁止人工重跑 |
| `available_at / created_at / updated_at` | timestamptz |
| `error_code` | 可空受控错误码；不保存原始异常 body |

每场只有一个 `graph_runner` 行。领取任务使用短事务、行锁和 `FOR UPDATE SKIP LOCKED`；领取或接管时增加 fence，执行期间续租。运行模型和等待用户时不持有数据库事务锁。

graph_runner 处理开始时记录 wake_seq，结束时只把这一值写入 handled_seq；如果后来出现新的 wake_seq，任务重新排队。waiting 可以释放租约，下一次回答、确认或完成通知会唤醒。

#### `model_call_slots`

| 字段 | 类型/约束 |
| --- | --- |
| 主键 | `(job_id, retry_generation, call_key)` |
| `attempts_reserved` | integer；已预留的物理请求尝试数 |
| `max_attempts` | integer；配置决定的本逻辑调用上限 |
| `outcome` | `pending \| succeeded \| exhausted \| cancelled` |

发请求前先原子预留尝试，崩溃后的不确定请求也消耗预算。格式修复使用同一 call slot 的剩余尝试。图重放、worker 接管、SDK 重试不能重置计数。Observer 和项目版 Agent 正常的多步工具推理使用不同 call_key，同时受整场工具次数、模型调用总数和 token 总预算约束；这不是额外的重试层。

调用 trace 另存于只允许元数据的 trace 存储，默认保留 30 天。`model_call_slots` 只是进行中与失败恢复所需的执行账本，不保存输入、输出或诊断正文；随 session 删除。

#### `session_notifications`

| 字段 | 类型/约束 |
| --- | --- |
| `session_id / seq` | 复合 PK；session FK |
| `kind` | `session_changed \| turn_published \| correction_required \| results_changed \| processing_failed` |
| `ref` | JSONB；仅 turn_no 等位置，不含正文 |
| `created_at` | timestamptz |

业务事务锁 session、递增 view_seq，并在同事务插入通知。禁止以全局自增 ID 的分配顺序假定跨事务提交顺序。SSE 只传通知；内容从授权 GET 读取，因此不需要在通知表复制问答。

通知按配置清理；客户端游标已过期时发送 `resync_required`，重新获取全量业务视图。此表是可靠传输机制，不是页面事件或用户行为采样。

### 4.4 策展与配置发布

`curation_items` 保存 UUID 主键 `id`、`session_id/turn_no` 复合外键、`administrator_id` 外键、`status(draft|published)`、经过过滤的 text 字段 `edited_question/topic_path/ideal_answer`、`privacy_review_notes`、`duplicate_review_notes`、可空 `published_question_id` 外键、`updated_at`。同一 session/turn 只允许一个 draft，使用部分唯一索引；源材料通过引用读取，不复制原始 Q/A。

创建、查看、编辑、整理 Agent 执行以及最终发布都重新验证授权，不能只在创建草稿时检查一次。发布事务锁 session 和 curation item，确认仍有授权、审核已完成、Topic 合法后插入题库和索引任务，并把草稿标为 published；重复发布返回同一 question_id。

撤销授权与发布争用同一 session 锁。撤销生效后取消整理任务、清除策展草稿及其中的私有内容；已发布且完成泛化的公共题目可以保留，源会话引用必须断开。会话删除采用同样规则。审计只保留动作、操作者、公共题目 ID、时间和成功状态，不保存原始内容。

Prompt、Schema、Topic 与模板修改走配置包发布：生成新包、固定回归、人工确认、生效于新 session。已有 session 继续使用原包，配置升级不在进行中的面试中改变合同。首版控制台可以产出受控修改建议，不获得直接改写正在运行配置或代码的权限。

`config_proposals` 保存 UUID 主键、administrator_id、配置类型枚举、经过过滤的建议文本、目标配置包引用、`draft|reviewed|rejected` 状态与时间。`config_proposal_sources(proposal_id, session_id)` 保存唯一的授权来源关联。读取建议需验证全部来源仍获授权；任一来源撤销或删除时，清除可能包含该会话内容的建议全文及关联。与会话无关的普通配置建议不需要虚构来源。正式发布的配置包不得携带私人项目内容。

### 4.5 统一写入事务

```text
BEGIN
  锁定 session，核对 owner / status / execution_epoch
  对任务结果另核对 job.fence、retry_generation 和 lease
  查询 operation_receipt
    已存在 → 核对请求一致性，返回当前业务结果
  检查该业务操作的 Stage、turn、授权与前置结果
  写业务变化
  写唯一 operation_receipt
  必要时写/唤醒 runtime_job
  增加 view_seq，写无正文 notification
COMMIT
```

数据库唯一约束冲突时回读已提交效果，不能忽略冲突后继续推进。事务结果未知时查询 receipt；数据库不可查询时显示状态未知并阻塞，不盲目执行第二次。

允许写入的状态按效果单独检查：准备材料/计划只在 preparing；回答/决策/纠错只在 interviewing 且 reason 为空；答案/评价/报告只在 finalizing；反馈只在提问未冻结时；统计允许 finalizing/completed/aborted 且 reason 非空；所有内容写入在 deleting 时拒绝。统计任务在退出后由独立权限重新领取，不能复用旧生成任务的 epoch/fence。

快照更正确认先把最终安全文本保存到 checkpoint；持久化节点在上述事务中只增追加。提交成功后重新读取数据库全文覆盖 State。`## 用户意见` 与 `## 事后核验` 的追加用 Markdown 解析结果判断文末区块，不能用全文字符串查找决定修改位置。

### 4.6 回答、Stage 与结束事务

**接收回答**：先识别已有回答的幂等重传；新回答再锁 session → 核对当前未回答 turn 和同代 `wait_for_answer` 等待点 → 写过滤后的 answer 与 answered_at → 记 receipt → 唤醒 graph_runner。只检查 status 不够：确认卡、compact 失败或恢复尚未完成时不得接收新回答。不会在 HTTP 请求中直接调用模型。

**应用 continue**：核对该用户消息的 decision receipt 不存在、当前 Stage 未关闭 → 把 interviewer_message 写到被回应 turn → 检查 100-turn 上限 → 发布下一题 → 写 decision receipt。如果是 Stage 首题，必须输出 continue，且 user_acts 为空、interviewer_message 为空。

**应用 complete/unresolved**：核对 question 为 null → 写被回应 turn 的 interviewer_message → 插入当前 stage_result → 写 decision receipt。下一 Stage 首题由独立节点和独立模型调用产生；关闭调用绝不预先创建新 turn。

**结束提问**：锁 session → 写 termination_reason → 根据原因、Stage 结果决定 status → 原子入队匹配/结算及允许的赛后任务。正常耗尽计划总是进入 finalizing；提前完成和安全停止只有存在 complete Stage 才进入 finalizing；其他情况直接 completed。冻结反馈与结束提交是同一边界。

第 100 题允许回答；处理该回答后可以关闭 Stage。任何路径准备创建第 101 题时改走安全停止，不展示也不保存第 101 题文本。

**强制退出**：用户取消弹窗不发送命令。确认请求提交后，事务将 status 置 aborted、reason 置 force_exit、递增 execution_epoch、取消执行任务并唤醒清理。此后所有迟到结果都因 epoch/status 检查失败而丢弃；已经提交的问答仍作为历史保留。

并发优先级以服务端提交边界判定：确认退出生效后，回答和 finish-early 不得再生效。为处理 finish-early 刚进入 finalizing 的竞态，持有本次提问阶段有效确认凭据的退出请求仍可抢占 finalizing，并清除已产生的答案/评估/报告，不展示赛后结果；已提交的快照追加保持只增不改。completed 后不再接受旧退出请求。不能承诺撤销在确认请求到达前已经展示的问题。

### 4.7 匹配与统计事务

1. 所有已发布 turn 都参与匹配，包括未回答尾题；只生成过但没发布的候选不参与。
2. `question_matches` 逐题唯一。无可靠匹配也是成功结果；检索基础设施失败不是“无匹配”，应保留可重试状态。
3. 同一场全部匹配形成成功/无匹配结果后，锁 session 并确认反馈已冻结。
4. 同事务插入唯一 settlement，按 question_id 聚合 usage、upvote、downvote 后更新题库。中途失败全部回滚。
5. 匹配服务不可用时统计可以延后，不阻塞面试结果展示；有报告会话的理想答案处理在有界等待后直接生成，不等统计恢复。后来得到匹配结果不能覆盖已生成的理想答案。

强制退出可继续确定性的检索与结算；不得因此运行生成式答案或评估模型。结算任务不使用被退出取消的提问/赛后执行权限，而只允许读取冻结的 question/feedback 并更新统计。

## 5. 接口合同

### 5.1 通用协议

- API 路径统一以 `/api/v1` 开头，下文省略前缀。Local Runtime 使用独立 `/local/v1` 前缀。
- OpenAPI 与 JSON Schema 从服务端合同生成 TypeScript 类型，前后端不各手写一套枚举。
- 会话创建使用 `Idempotency-Key`；其他有自然键的业务动作使用 session/turn/operation 定位。审阅意见追加等可重复不同内容的命令必须携带新的命令键。
- 非自然键请求的重复键、不同安全文本或参数返回 `409 idempotency_conflict`。相同请求返回已有结果，不唤醒已完成任务。
- `200/201` 表示已提交业务效果；`202` 只表示任务已经持久化入队，不能显示为“分析完成”或“已写入快照”。
- `400` 为无效命令，`401/403` 为身份/权限，`404` 为不可见资源，`409` 为状态/幂等冲突，`413` 为大小限制，`422` 为安全处理或结构校验失败，`503` 为依赖不可用或结果暂不可确认。
- 权限检查先于返回处理状态，避免借错误差异枚举他人 session。错误详情只含受控字段，不回显请求正文、SDK 原始错误或模型输出。

```json
{
  "error": {
    "code": "snapshot_write_unknown",
    "message": "尚未确认写入结果，请保持当前页面并重试查询。",
    "retryable": true,
    "operation_id": "op-opaque-id"
  }
}
```

`retryable` 只是前端动作提示，不能覆盖第 6.2 节的模型预算。访问 API 使用独立请求 ID 便于定位元数据；不把原始 URL 查询参数或 body 自动写 trace。

异步动作统一返回以下 OperationView；operation_id 是带类型的任务/效果不透明标识，分别映射 runtime_jobs.id 或 operation_receipts.id。查询结果未知的写入时，服务端也能按确定性 receipt ID 查找提交效果，不依赖已经丢失的 HTTP 响应。

```json
{
  "operation_id": "job-opaque-id",
  "status": "queued",
  "result_ref": {"turn_no": 4},
  "error": null,
  "allowed_recovery_actions": []
}
```

status 为 `queued | running | waiting | succeeded | failed | cancelled | unknown`；unknown 仅表示暂不能确认结果，不允许前端据此创建另一份工作。result_ref 只包含本场允许读取的定位信息。

### 5.2 项目准备

| 接口 | 输入 | 成功输出/规则 |
| --- | --- | --- |
| `POST /interviews` | 空对象，Idempotency-Key | 201 `{session_id, status:"preparing"}`；owner 来自认证 |
| `GET /interviews` | cursor、limit | 仅本人的 session 摘要；不返回所有快照正文 |
| `GET /interviews/{id}` | 无 | 当前 SessionView，见下节 |
| `POST /interviews/{id}/snapshot:observe` | `{source_handle, cloud_processing_accepted:true}` | 202 OperationView；同一来源任务重复请求复用 |
| `POST /interviews/{id}/snapshot:import` | `{markdown, source_handle?:string, cloud_processing_accepted:true}` | 200 安全快照视图；body 在进入持久化前过滤，原文件不上传为附件保存 |
| `GET /interviews/{id}/snapshot` | `format=json\|markdown` | 当前安全快照；json 可附结构警告，不附原文副本 |
| `POST /interviews/{id}/snapshot:append-user-opinion` | `{text, preview_token}` + Idempotency-Key | 200 当前完整快照；仅确认初始快照前可用 |
| `POST /interviews/{id}/snapshot:confirm` | `{confirmed:true}` | 200；确认后不能再用审阅接口改准备材料 |
| `POST /interviews/{id}/snapshot:parse-ranges` | 空对象 | `{sections:[{kind,title}], warnings:[], requires_full_document_confirmation:boolean}` |
| `POST /interviews/{id}/plan` | PlanRequest | 202 OperationView；设置方向/范围并入队 Planner |
| `GET /interviews/{id}/plan` | 无 | 合法 plan、方向、所选范围；尚未生成时返回准备状态 |
| `POST /interviews/{id}/start` | 空对象 | 202；计划存在后才启动首题；重复请求不再生成首题 |

会话创建的键以 `(principal_id, Idempotency-Key)` 唯一映射 session，由 `interview_sessions.create_command_id` 的复合唯一约束保证。键不承担身份认证功能。

```json
{
  "interview_direction": "core_thread",
  "selected_sections": [
    {"kind": "thread", "title": "User Query to Final Answer"}
  ],
  "confirm_full_document": false
}
```

方向枚举固定为 `project_tour | core_thread | cross_cutting | pressure | contribution_review`。`confirm_full_document` 只在解析无范围时可为 true；前端不能借此忽略存在的范围选项。服务端从当前 snapshot 重新解析和校验 title/kind，不能直接信任客户端传来的正文片段。

自动生成的快照若标题重复或结构不合法，走 Observer 的有界修复或明确失败。用户导入的 Markdown 不因正文自由而拒收；重复标题给出结构警告、禁止生成歧义的同区域选项，提示返回修改；若最终无可用选项，则按产品规定确认后整文规划。代码块、引用块或用户意见中的示例标题不作为顶层范围标题。

### 5.3 会话视图与回答

```json
{
  "session_id": "uuid",
  "status": "interviewing",
  "termination_reason": null,
  "view_seq": 17,
  "phase": "asking",
  "stage": {"index": 1, "title": "设计动机", "total": 5},
  "current_turn": {"turn_no": 4, "question": "为什么选择这一种召回方式？", "answer": null},
  "pending_correction": null,
  "allowed_commands": ["answer", "finish_early", "force_exit", "feedback"],
  "force_exit_token": "opaque-confirmation-token",
  "results": {"report_available": false, "full_qa_available": true, "processing_incomplete": false}
}
```

`phase`、allowed_commands、结果可用性均由事实与执行现场派生，不在数据库另建一套状态。phase 可为 `source_selection | observing | snapshot_review | planning | ready | asking | processing | correction_required | write_unknown | turn_failed | finalizing | results | deleting`。

`force_exit_token` 在提问阶段签发，绑定身份、session、epoch 和时效，仅供确认命令使用。打开/取消弹窗不更新服务端状态。SSE 更新后，前端依据最新视图替换按钮与表单，不推测模型是否已经完成。

| 接口 | 输入 | 输出/行为 |
| --- | --- | --- |
| `POST /interviews/{id}/answers` | `{turn_no, answer}` | 202 `{operation:OperationView,accepted_turn:{turn_no,answer}}`；返回已持久化的安全文本，模型后台处理 |
| `POST /interviews/{id}/retry` | `{target:"current_turn"\|"compact"\|"snapshot_write"\|"plan"\|"observe"}` | 202；只允许当前失败操作，重复请求不再增加重试代次 |
| `POST /interviews/{id}/finish-early` | 空对象 | 200/202 当前状态；按已 complete Stage 数决定报告 |
| `POST /interviews/{id}/force-exit` | `{confirmed:true, confirmation_token}` | 200 aborted；非确认请求拒绝，重复确认返回已退出 |
| `PUT /interviews/{id}/turns/{turn_no}/feedback` | `{vote, reason:null或枚举}` | 200 最终反馈；提问冻结后 409 |

重试接口必须携带 Idempotency-Key。它只能为失败的实时/准备任务建立一次新的 retry_generation；pending/running 状态返回现有操作。snapshot_write 重试只是确认数据库并再次提交同一追加，不调用模型；没有任何 target 可以重跑赛后答案、评价或报告。

普通回答在服务端过滤后接收，前端按 accepted_turn 显示实际保存的安全文字；若发生替换，可显示替换类型提示，不回显敏感值。普通回答不额外增加确认卡；只有项目事实更正同步到共享快照时走下述确认流程。

### 5.4 文本过滤与更正确认

| 接口 | 输入 | 输出 |
| --- | --- | --- |
| `POST /interviews/{id}/text:preview` | `{purpose, text, candidate_id?:string}` | `{text, changed, findings:[{type,location}], preview_token}` |
| `POST /interviews/{id}/snapshot-corrections:confirm` | `{candidate_id, decision:"accept"\|"skip", text?:string, preview_token?:string}` | 200 `{applied, snapshot?}`；接受成功表示数据库已提交 |

purpose 只允许 `initial_opinion | snapshot_correction`。preview_token 与 purpose、对象和文字绑定，不可跨接口复用；findings 不含命中的敏感值。

如果确认的更正文字再次过滤后变化，返回新的最终文本，前端必须展示并再次获得确认，不能自动勾选继续。skip 不要求文字或 preview_token，但仍须 candidate_id 匹配当前待处理卡。

### 5.5 事件、产物与删除

| 接口 | 输入 | 输出 |
| --- | --- | --- |
| `GET /interviews/{id}/events` | Last-Event-ID，可选 | SSE 通知，连接本身不启动/重试图 |
| `GET /interviews/{id}/operations/{operation_id}` | 无 | OperationView：status、受控 error、可执行恢复动作 |
| `GET /interviews/{id}/full-qa` | `format=json\|markdown` | 按 Stage/turn 排序的完整已持久化问答；字段缺失显示实际状态 |
| `GET /interviews/{id}/report` | `format=json\|markdown` | 已完成报告；缺失返回明确 unavailable 状态 |
| `DELETE /interviews/{id}` | Idempotency-Key | 202 `{deletion_id,status:"deleting"}` |
| `GET /deletions/{deletion_id}` | 无 | 仅本人可读的清理回执，不返回内容 |

```text
id: 18
event: turn_published
data: {"session_id":"uuid","turn_no":5,"view_seq":18}
```

SSE 可以重放通知，客户端按 seq 去重；读取当前视图后按 turn_no 渲染唯一问题。新连接先要求同步当前视图，再继续通知，避免确认卡保存在 Redis 但通知尚未写出时漏显示。前端不得根据重放的旧 turn_published 在终态重新开放回答框。

完整问答 JSON 包含实际题目、回答、interviewer_message、可空双答案和 comment；反馈由独立字段/查询合并到视图，始终不喂给 Agent。强制退出视图只返回历史问答。报告 Markdown 严格排除 score、标签、雷达图和 UI 说明，结构由程序生成。

### 5.6 授权与管理员接口

| 接口 | 输入 | 输出/约束 |
| --- | --- | --- |
| `PUT /interviews/{id}/curation-grant` | `{granted:true}` | 仅 owner；200 当前授权 |
| `DELETE /interviews/{id}/curation-grant` | 无 | 仅 owner；撤销并取消未发布整理工作 |
| `GET /admin/curation-sessions` | 分页/结束状态筛选 | 仅已授权的结束会话；不返回所有私人 session |
| `POST /admin/curation-items` | `{session_id,turn_no}` | 从指定材料创建草稿，重复选择复用未发布草稿 |
| `GET /admin/curation-items` | 分页/草稿状态 | 每次查询重新关联授权 |
| `GET /admin/curation-items/{id}` | 无 | 草稿及允许读取的源材料 |
| `PATCH /admin/curation-items/{id}` | edited_question、topic_path、ideal_answer、审核说明；If-Match | 200 最新草稿；并发编辑冲突返回 409 |
| `POST /admin/curation-items/{id}:prepare` | 空对象 | 202；泛化、隐私处理、查重建议，不发布 |
| `POST /admin/curation-items/{id}:add-to-question-bank` | `{privacy_confirmed:true,quality_confirmed:true}` | 201 question_id；发布事务重新验证授权与草稿版本 |
| `GET /admin/question-bank` | 查询/Topic/分页 | 题目与累计统计，不包含私人反馈原因 |
| `PATCH /admin/question-bank/{id}` | 经审核的 question/topic/ideal_answer；If-Match | 200；变更后重新索引，记录无私有内容的审计 |
| `POST /admin/config-proposals` | 配置类型、编辑建议、已授权证据引用 | 202/201 修改建议；不直接改变当前配置 |
| `GET /admin/config-proposals` | 分页 | 只返回来源授权仍有效的建议；不暴露被撤销的证据 |

配置建议记录于管理员工作区，若包含会话证据则始终通过授权引用读取，撤销/删除时清理关联私有说明。正式包发布由回归 runner 与人工审核入口执行，禁止通过普通 PATCH 绕过质量门槛。

### 5.7 Local Runtime 任务协议

浏览器只在 Local Runtime 上提交原始目录路径。Application Runtime 发出的项目任务只能使用 handle，不能传一个任意路径代替授权。

| 本地接口 | 输入 | 输出/约束 |
| --- | --- | --- |
| `POST /local/v1/authorizations` | `{session_id,root_path,exclude_rules,cloud_processing_accepted:true}` | `{source_handle,expires_at,inventory_summary}`；验证真实根、排除规则和本地用户授权 |
| `GET /local/v1/authorizations/{handle}/inventory` | 分页 | 相对路径、类型、大小、跳过原因、脱敏命中类型/行号；不回显敏感值 |
| `DELETE /local/v1/authorizations/{handle}` | 无 | 撤销，后续文件读取拒绝 |
| `POST /local/v1/tasks` | LocalTaskRequest | 202 `{operation_id,status}`；同一有效任务 ID 返回已有任务 |
| `GET /local/v1/tasks/{operation_id}` | 任务凭据 | running/succeeded/failed + 安全结果或受控错误 |
| `POST /local/v1/tasks/{operation_id}:cancel` | 有效执行凭据 | 尽力取消；业务采用权由 Application Runtime 决定 |
| `POST /local/v1/tasks/{operation_id}:ack` | 已采用结果标识 | 清除本地临时结果，保留短期无内容回执防重复 |

```json
{
  "operation_id": "stable-task-id",
  "kind": "project_answers",
  "session_id": "uuid",
  "source_handle": "opaque-handle",
  "execution_epoch": 1,
  "task_fence": 3,
  "config_bundle_id": "bundle-id",
  "input": {
    "snapshot": "已脱敏的完整 Markdown",
    "turns": [{"turn_no": 1, "question": "实际问题", "answer": "用户回答"}]
  }
}
```

Observer input 只需要授权 handle 和预算，不接收任意工具列表。项目版 input 不包含理想答案或反馈。Observer 输出 `{snapshot_md,inventory_summary,warnings}`；项目版输出使用第 3.5 节合同，warnings 不变成新的事实数据库。

本地授权与任务缓冲绑定 Runtime 启动代次并有期限；不承诺重启后 handle 仍有效。任务 ID 在 Application Runtime 持久化；本地重启导致任务丢失时，Observer 明确提示重新授权/重试，赛后项目版自动降级 snapshot-only。不会在应用服务里通过相同路径偷偷重开目录。

本地 Adapter 发送模型请求前，通过受保护内部接口预留 Application Runtime 的 call slot；任务凭据绑定 job、epoch、fence、call_key 和预算。接口只接受预置调用角色，不允许本地任务扩大预算或改写业务状态。本地断连无法获得有效调用许可时不继续发模型请求。

文件工具在每次调用时验证 handle、租约、授权相对路径、排除规则和真实路径；打开文件时还需处理符号链接替换竞态，不能只在建立清单时校验一次。日志只记录路径/行号等允许元数据，不记录源码。

## 6. 故障恢复与运行约束

### 6.1 interrupt、确认卡与恢复

LangGraph 恢复 interrupt 时会从所在节点开头重新执行，因此模型调用和业务写入必须位于独立节点，或有独立幂等检查；不能在确认节点的 interrupt 前重新问模型。这一约束来自 [LangGraph interrupt 文档](https://docs.langchain.com/oss/python/langgraph/interrupts)。

确认卡处理顺序：

1. Supervisor 输出在进入 State 前过滤候选文字；把合法决策和候选写入 checkpoint。
2. 生成绑定 session、epoch、candidate_id、安全规则版本、最终文本和有效期的签名 preview_token；前端只展示这份文字。
3. 用户编辑时调用统一 preview 接口重新过滤。发生替换时展示替换后的文本，用户再次确认；不得拿旧 token 确认新文字。
4. confirm 请求携带匹配 token，经过校验后把安全文本作为 accepted 内容写入 State，再执行追加事务。
5. 只有数据库追加成功，confirm 才返回成功。响应丢失时通过 receipt 查询；尚未提交的请求不能显示“已写入”。
6. 暂不写入记录本次 review 已跳过的无正文操作回执，清空待写项，沿用同一决策继续；不把候选文字写入业务库。

确认结果未知时前端保持阻塞，允许查询和重试同一命令。epoch 或候选变化导致旧确认凭据失效时，明确要求重新审阅；不能自动批准新模型生成的另一份候选。

**checkpoint 丢失后的恢复算法：**

1. 锁 session，确认非终态，增加 epoch，撤销旧 graph_runner 的写入权；保留已提交业务效果。
2. 从 plan 和 stage_results 重建当前索引，从 turns 找到未回答问题或尚未应用决策的回答。
3. 检查快照追加、decision 和结果 receipts；已完成部分跳过。
4. 从原始已处理 turns 重建 compact。未确认候选允许丢失并重新生成；已确认且已提交的追加从数据库恢复。
5. 已提交更正但决策尚未应用时，可以在剩余预算内重新生成决策；已有更正 receipt 阻止重复追加，不再次要求确认同一更正。
6. 已消费的模型尝试继续计入预算；耗尽则显示本轮处理失败，等待显式“重试本轮”。

正常 replay 优先利用 checkpoint 中的有效决策；只有执行现场确实不可恢复时才走上述重建。外部模型调用可能重复执行，业务效果必须最多生效一次，遵循 [LangGraph 持久执行说明](https://docs.langchain.com/oss/python/langgraph/durable-execution)。

### 6.2 预算与重试

| 配置 | 首版工程初值/规则 |
| --- | --- |
| `planner.max_stages` | 20；最小值固定 5 |
| `interview.max_turns` | 100，产品硬上限 |
| `compact.batch_size` | 20 |
| `snapshot.max_tokens` | 16,000，包含用户追加；为事后核验预留其中 2,000 |
| `answer.max_tokens` | 2,000；提交前告知超限，不能静默截断 |
| `question.max_tokens` | 400；同时受单一主要问题的语义规则约束 |
| `compact.max_tokens` | 3,000 |
| `project_answer.target_max_tokens_per_turn` | 400；用于整场输出预算与 Prompt，不截取损坏 JSON |
| `ideal_answer.max_output_tokens` | 800 |
| `evaluation.max_output_tokens` | 600 |
| `report.max_output_tokens` | 6,000 |
| 理想答案/评估并发 | 各 4，全局模型请求并发 8 |
| 单逻辑调用尝试数 | RAG/Supervisor/Planner/compact 最多 2；赛后生成最多 3；含格式修复 |

以上 token 数和并发数是待回归校准的配置初值，不是对用户的质量或吞吐承诺。Observer 文件、地图、工具次数、累计读取和总耗时另设配置上限；不因没有填写某个预算而默认无限。

每次调用计算：

```text
输入 token + 预留输出 token + 安全余量 <= 所选模型已验证的上下文容量
预留输出 token <= 供应商已验证的最大输出限制
```

首次确认快照、每次接收回答与追加意见时都做全链路容量检查，覆盖 Supervisor、整场项目答案、逐题评估和报告；必须为剩余可能问题、核验追加、逐题 comment 与整场答案输出留出预算。累计 Q/A 上限由四类模型容量的最小可用空间计算，不只看当前 Supervisor 是否放得下。

超过限制返回明确的输入超限错误和可接受长度，不裁剪完整快照、不把整场项目版偷偷拆成逐题调用。启动时配置若连最低计划规模都无法容纳，直接报告配置不兼容；不得让用户完成一场必然装不进赛后上下文的面试。

超时值在工程配置中必须显式提供，作为取消和租约上界；具体秒数经本机集成测量后锁定，不在本设计假定已测得 P95。统一 Adapter 处理 Retry-After、指数退避与抖动，SDK 和节点层自动重试关闭。

### 6.3 Checkpointer 与 trace 写入门禁

Redis 的 session guard 保存当前允许的 epoch 与 runner fence；只有经 PostgreSQL 领取成功的协调器可以更新 guard。checkpoint 写操作通过原子检查拒绝旧代次和旧 fence，普通节点不能自行重建已撤销的 guard。

强制退出或删除先在 PostgreSQL 撤销执行权，再设置 Redis 撤销 guard 并删除内容。清理任务覆盖延迟写入；撤销元数据保留到所有旧租约和请求的有界存活期结束，随后清除。Redis 不可用时数据库状态仍立即阻止业务写入，恢复后先执行 guard 恢复/清理，再允许图继续。

trace exporter 只允许调用元数据字段。关闭框架自动 Prompt/response/body 采集；删除中的或已删除的 session 不允许 exporter 重建 trace。普通已退出会话可以记录在途请求的无内容完成/取消元数据，以如实统计成本，但不能采用返回文本。

### 6.4 删除与数据保留

DELETE 先把 session 置 deleting 并递增 epoch，所有内容接口立即拒绝读取和写入。清理任务依次处理 Redis 全代 checkpoint、会话 trace、Local Runtime 的临时任务结果与授权撤销，然后在 PostgreSQL 删除会话业务与执行数据。Local Runtime 不可达时，其短期租约必须自然过期；不得把本地源文件列为清理对象。

清理进度保存在独立 `deletion_jobs(id, session_id, user_id, status, completed_steps, error_code, created_at, completed_at)`，不使用指向 session 的级联 FK，且不保存内容。完成后只短期保留删除回执，按 30 天清理。失败只重试清理，不恢复会话可见性。

删除前若已结算，按冻结的 match/feedback 贡献在同一数据库事务中扣回相应计数并删除 settlement，保证被删除会话不再贡献可归属统计。撤销策展授权、清除私有草稿与断开已发布题目的源引用也在清理范围内。

普通 trace 30 天到期清理；session 默认保留到用户删除。已由用户导出的本地 Markdown、项目源文件和导入原文件都不属于系统删除范围。工程维护若需清理本机生成文件，应遵守工作区的 macOS Trash 规则。

## 7. 测试与质量验收

### 7.1 测试装置与断言原则

集成与故障测试使用独立 PostgreSQL、Redis、两个真实 HTTP Runtime 和真实 checkpointer；模型使用可编排的假供应商。假供应商可以挂起请求、返回格式错误、限流、超时、在取消后迟到返回，并记录物理调用次数。检索测试另有固定题库和嵌入/排序夹具。

注入点位于“事务提交前后、发请求前后、checkpoint 写前后、事件投递前后、租约接管前后”。测试进程故障采用终止 worker 并重启；不能仅用 mock 异常证明跨进程恢复。

每项测试同时断言：用户视图、数据库业务行数与内容、receipt/job 状态、模型调用次数、Redis 状态以及 trace 内容边界。模型调用允许按预算重复，业务效果不允许重复；二者必须分别计数。

### 7.2 准备与实时面试故障矩阵

| ID | 故障窗口/输入 | 注入方法 | 必须成立的断言 |
| --- | --- | --- | --- |
| F01 | 创建 session 已提交、HTTP 响应丢失 | 提交后断开连接，同一键重发 | 同一 session_id，只创建一场 |
| F02 | 导入/Observer 含测试密钥 | 在文件、Markdown、模型输出分别放夹具 | 只有替换文本进入业务库/checkpoint/模型/导出；原文件字节不变 |
| F03 | 初始 snapshot 提交后 worker 崩溃 | accept 提交后退出进程 | 不重新覆盖 snapshot，不重复调用 Observer |
| F04 | 目录清点后符号链接被替换到根外 | 文件打开前切换链接 | 工具拒绝读取，模型与日志没有越界内容 |
| F05 | handle 失效或 Local Runtime 重启 | 重启本地进程 | Observer 要求重新授权；应用不能直接读目录 |
| F06 | Planner 两次输出都非法 | 首次错 Topic，修复仍含非法范围 | 不保存 plan，不启动面试；允许显式重试 |
| F07 | 用户快速双击 start | 两请求并发并重放事件 | 同一首题、turn_no=1，仅一个业务效果 |
| F08 | answer 已提交，worker 未开始 | 接收事务后终止 worker | 回答可见；重启只继续该轮，无重复接收或丢失 |
| F09 | 同一 answer 并发重传/改写 | 相同与不同正文同时提交 | 相同返回同一操作；不同 409；最多一个决策生效 |
| F10 | RAG 超时/索引不可用 | 召回服务失败 | 候选为空仍可提问；不读取理想答案补救 |
| F11 | 模型请求已发出，响应未知 | 发出后断链、worker 崩溃 | 尝试预算已消耗；最多一个有效结果，无无界重试 |
| F12 | Supervisor JSON 错误后修复成功 | 第一次破损，第二次合法 | 两次物理调用、一次决策；第 3 次不自动发生 |
| F13 | Supervisor 尝试耗尽 | 两次可重试故障 | answer 保留，Stage/turn 不推进，显示重试/强制退出 |
| F14 | 接受决策后、checkpoint 更新前崩溃 | decision 事务提交后退出 | 回读 receipt，不重新问模型，不重复问题/Stage 结果 |
| F15 | 关闭 Stage 已提交、下一 Stage 首题未生成 | 在两个调用之间停止 | 原 Stage 只关闭一次；新调用使用下一 Stage goal，不创建空 turn |
| F16 | 下一题已提交但 SSE 丢失 | 丢弃通知再重连 | GET 恢复同一 turn；重放旧通知不增加 turn |
| F17 | 纠错卡保存后恢复 interrupt | 在等待确认时重启 worker | 仍显示同一候选；正常恢复不增加 Supervisor 调用 |
| F18 | 用户编辑后重新命中敏感规则 | 编辑加入测试密钥，再用旧 token 确认 | 旧 token 不能提交；显示最终安全文本等待重新确认 |
| F19 | 快照追加事务回滚 | receipt 插入后、追加前抛错 | receipt 与追加都不存在；确认未提交后可重试一次 |
| F20 | 快照追加已提交但响应/checkpoint 丢失 | commit 后丢 ACK | 查询 receipt 得到成功；只追加一次，State 刷新后才展示下一题 |
| F21 | 快照追加结果未知且 DB 不可查 | commit ACK 丢失后隔断数据库 | 显示 write_unknown，不能继续/盲写/生成下一题 |
| F22 | skip 更正后重放 | 跳过后重启并 resume | snapshot 不变，同一决策只应用一次，确认路径不调用模型 |
| F23 | 第 20/40/60 条处理边界崩溃 | compact 写前、写后分别停止 | 一个累计摘要；原文完整，近期对话无重叠/遗漏；失败不无界塞全文 |
| F24 | Redis 整库丢失 | 已关闭 Stage、已写更正、已回答未决策三种夹具 | 从业务事实重建；已提交追加与 Stage 不重复；未确认候选允许重新审阅 |
| F25 | 人工重试时旧调用迟到 | 挂起旧请求，启动新 generation 后返回 | 旧 fence/generation 结果丢弃；业务效果最多一次 |
| F26 | 反馈写入与结束竞争 | 两事务在 session 锁处设置屏障 | 结束前提交的反馈纳入冻结值；结束后返回 409，不能漏结算或事后修改 |
| F27 | 取消强制退出确认 | 打开弹窗后取消 | 没有终止请求/业务写入，反馈仍可改、问题仍可答 |
| F28 | 确认退出与回答/提前完成/模型结果竞争 | 固定各提交顺序，至少三组屏障 | 退出提交后无新问题/赛后产物；finalizing 竞态被抢占；历史保留 |
| F29 | 第 100 题后的 continue 或 close | 第 100 题回答后返回不同动作 | 无第 101 行；close 可以正常关闭；需继续时按 complete Stage 门槛安全停止 |
| F30 | 提前完成时存在未回答尾题 | 一个 complete Stage + 尾题 answer=null | 报告可生成；尾题不作为错误答案，历史/参考答案对齐 turn_no |

### 7.3 赛后、统计与权限故障矩阵

| ID | 故障窗口/输入 | 注入方法 | 必须成立的断言 |
| --- | --- | --- | --- |
| F31 | 本地项目任务失联后旧结果迟到 | 失效 handle，启动 snapshot-only，再返回旧任务 | 仅一个整场项目结果可被采用；不逐题回查、不采用旧任务结果 |
| F32 | 项目版顶层 JSON 截断 | 返回不完整 JSON | 不猜测抢救；有界失败后项目答案缺失，其他流程按规则降级 |
| F33 | 项目版部分 turn 无效/重复 | 顶层合法但缺项、错号、重复 | 仅合法唯一项采用；缺项保持 null，不错位到其他题 |
| F34 | 项目答案已生成、事后核验尚未提交 | 暂停追加事务 | 依赖本批核验的答案不先落库使用；评估不越过最终快照屏障 |
| F35 | 双答案完成次序不同 | 项目版先/后、某题理想答案失败 | 汇合行为一致；每题输入只有自己的双答案，缺失不会直接扣分 |
| F36 | 单题评估失败而其他题成功 | 固定一题耗尽尝试 | 成功结果不重算；无伪造 comment；报告不启动，显示处理未完成 |
| F37 | 报告提交成功但任务 ACK 丢失 | report 事务后崩溃 | 唯一 report，重试只读已有结果，不再生成一份 |
| F38 | 检索服务不可用导致匹配未完成 | 匹配超时 | 不把故障当成无匹配永久冻结；理想答案可现场生成，统计延后 |
| F39 | 匹配后题库理想答案被编辑 | 锁定匹配/复制边界后修改题库 | 已采用答案保持本场副本，不被后续编辑覆盖 |
| F40 | 结算半途失败或提交后 ACK 丢失 | 更新部分计数前回滚；另测 commit 后断链 | 计数与 settlement 一起回滚或全部成功；再次结算不重复加数 |
| F41 | 统计 worker 被两个进程领取 | 租约到期、旧 worker 恢复 | 唯一 settlement，旧 fence 无权提交 |
| F42 | 管理员读取未授权会话 | 列表、直接 URL、任务入口逐个请求 | 无正文泄露，不因管理员身份绕过 owner grant |
| F43 | 策展发布与撤销授权竞争 | 在 session 锁处屏障交换顺序 | 撤销先提交则发布失败；发布先提交则仅保留已泛化公共内容，私有引用被清理 |
| F44 | 题库编辑与索引回写竞争 | 旧索引计算完成前再编辑 | 旧索引不覆盖新题；未就绪题不进入 RAG |
| F45 | 删除时有在途模型与 trace 导出 | 删除成功后释放延迟任务 | 不重建业务行、checkpoint 或 trace；源文件和用户导出不受影响 |
| F46 | Redis/trace 清理暂时失败 | 删除流程中断后重启 worker | session 保持不可见；重试仅清理未完成项，不恢复内容接口 |
| F47 | 旧 worker 在终态清理后写 checkpoint | 延迟 Redis 写，在撤销 guard 后执行 | 原子 guard 拒绝旧 epoch/fence，不留下可恢复的旧图 |
| F48 | token 预算超限 | 超长导入、回答、纠错、100 题输出边界 | 在接受输入/调用前报明确错误，无静默裁剪、无隐式分题项目调查 |
| F49 | Markdown 导出与 UI 数据不同步 | 报告有 score=0 和多种标签 | 同一 JSON 渲染；Markdown 无数字评分/标签/雷达图/UI 说明 |
| F50 | 安全与内容日志泄露 | 验证错误、SDK 错误、注入 README、模型回显 | 只记录白名单元数据；无法通过异常栈/body/checkpointer 绕过过滤 |

### 7.4 状态不变量与质量回归

在随机命令序列中持续检查以下不变量：

- 同场 turn_no 连续且不超过 100，最多一个未回答问题；关闭 Stage 不创建 turn。
- Stage 结果是 plan 的连续前缀；complete 与 unresolved 不被重试改写。
- 同一有效回答只导致一个有效决策；不同物理调用次数不能冒充多个业务 turn。
- snapshot 初始接受后只增追加，确认卡跳过时字节不变；追加 receipt 与正文同时提交。
- termination_reason 非空后 answer/feedback 冻结；aborted 没有可见赛后产物。
- 每个成功 result 只属于其 session/turn；并发 UPDATE 不清空另一结果列。
- Supervisor 请求没有参考答案、评价、反馈、源文件或完整 Topic 树；报告请求没有双答案。
- 题库 RAG 只读 search_ready 的审核题目，未发布草稿不能出现在任何在线候选中。
- 所有权限检查在当前读取/采用时执行，不能复用旧授权结论。

质量回归单独使用 2～3 个冻结项目、五种方向、人工审阅快照、预期 Stage、多档回答脚本和匹配正反例。事实引用有效率 ≥95%、问题相关率 ≥85%、同一会话语义重复率 <10%、模型单次失败后的会话恢复率 ≥90%，均按产品要求验证，并在评估说明中固定分母、样本集和人工判断规则。用户主动要求重述的题目另外分组报告，不能为通过门槛而事后改变验收分母。结构与并发通过不代表这些语义指标已经达标。

## 8. 实施顺序

| 增量 | 正式实现内容 | 完成条件 |
| --- | --- | --- |
| A：合同与存储骨架 | 三个进程入口、配置包、身份、数据库迁移、领域事务、任务领取、SSE 与 checkpointer 适配 | F01/F08/F09/F14/F16/F26/F41/F45/F47 用假模型通过 |
| B：快照与计划 | 本地授权、过滤、Repository Map、只读工具、导入审阅、范围解析、五类模板与 Planner | 两入口都能生成合法计划；F02～F06、F48/F50 通过 |
| C：正式面试链路 | RAG、Supervisor、三动作、确认卡、compact、结束与恢复 | F07～F30 全部通过；模型输入隔离可自动检查 |
| D：赛后与导出 | 整场项目版、理想版、逐题评估、报告、部分失败视图与 Markdown | F31～F40、F49 通过；双答案与报告无上下文串扰 |
| E：策展与质量验收 | 授权策展、审核发布、索引更新、配置回归入口、完整删除 | F42～F50 通过；固定项目达到产品质量门槛 |

各增量都在同一套正式目录、表、接口与状态机上推进。假供应商只用于测试，生产服务从第一步就使用 PostgreSQL 和可恢复任务；不以一套随后废弃的内存流程替代正式工程。

本文完成的是可实施的设计合同。工程尚未建立，迁移、接口、故障矩阵和质量指标均须在实现后实测，不能把这里列出的断言当成已通过的测试结果。
