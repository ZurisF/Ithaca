# Project Interview Lab 实现设计

> 状态：Draft v0.3  
> 上游产品合同：`PRODUCT_DEVELOPMENT.md`  
> 目标：把已经确定的产品语义落实为可以直接编码、迁移和测试的工程合同。

## 1. 文档边界

本文只设计首个完整可用版本。产品语义以 `PRODUCT_DEVELOPMENT.md` 为准；本文负责确定：

- 两个 Runtime 的模块边界与调用方向。
- PostgreSQL 表、约束、事务和删除关系。
- Redis 中的 LangGraph State / checkpoint。
- Graph 节点、interrupt、并行与恢复方式。
- HTTP API、错误合同和并发控制。
- 题库导入、混合检索和赛后统计结算。
- 模型调用适配、结构化输出校验和有界重试。
- 安全、可观测性、测试和实现顺序。

本文不重新讨论以下已经确定的产品边界：

- PostgreSQL 是业务事实唯一来源，Redis 只保存执行现场。
- 一场 session 只有一份当前 snapshot，不建立版本链。
- 不建立跨 session LTM。
- 首版不采集额外点击流或运行时内容诊断样本。
- 不把 compact、RAG、格式修复等辅助调用抽象成独立 Agent 角色。
- 不提供面试结束后的手动赛后流程重跑。

软件与对话配置仍遵守“运行数据只能形成修改建议、不能自动改写 Prompt、Schema、Topic、模板或代码”的产品原则。首个实现不为这类建议建立运行时发布状态机或 `config_proposals` 业务表；管理员基于已授权材料形成建议后，仍通过受版本控制的配置文件、固定回归和人工审核完成发布。题库策展是本版本唯一在产品内完成写入发布的管理员流程。

具体模型、超时秒数、RAG 阈值和并发度是配置与实测参数，不写死为架构合同。

## 2. 总体实现路线

```text
Next.js Web
  │
  ├── HTTP / SSE ──> Application Runtime / FastAPI
  │                    ├── Application Services
  │                    ├── Interview Graph
  │                    ├── Finalization Subgraph
  │                    ├── Retrieval Service
  │                    ├── Model Adapter
  │                    ├── PostgreSQL
  │                    └── Redis Checkpointer
  │
  └── localhost ────> Local Project Runtime / FastAPI
                       ├── Source Authorization Registry
                       ├── Inventory / Parser / Repository Map
                       ├── Shared Content Safety
                       └── Read-only Project Agent Tools

Application Runtime ── session_id + opaque source_handle + operation_id ──> Local Project Runtime
Local Project Runtime ── filtered structured result ─────────> Application Runtime
```

实现遵循四条依赖规则：

1. API 层只做鉴权、请求校验和 application service 调用，不直接操作 Graph State 或拼 SQL。
2. Graph 节点调用 application service；业务事务不散落在节点中。
3. Repository 只处理数据库读写，不调用模型、Redis 或另一个 Runtime。
4. Local Project Runtime 是唯一可以把 `source_handle` 解析成真实路径的进程。

### 2.1 为什么不把所有流程都塞进 LangGraph

创建 session、导入 Markdown、保存选择、生成计划等步骤都是明确的命令式操作，使用普通 application service 更易验证和恢复。LangGraph 只承担两类确实需要编排能力的流程：

- 实时面试：连续上下文、Supervisor 决策、条件确认卡、interrupt/resume。
- 赛后处理：整场项目版答案、逐题理想答案、逐题评估和整场报告的 fan-out / join。

产品文档中的准备流程仍然是业务状态机，但不要求每一个准备步骤都成为持久化 Graph 节点。

## 3. 目标工程结构

当前仓库尚无实现代码，目标结构如下：

```text
apps/
  web/                         # Next.js 用户界面与管理员界面

services/
  application/
    src/app/
      api/                     # FastAPI routers、依赖注入、鉴权
      contracts/               # Pydantic HTTP / Agent contracts
      domain/                  # 枚举、值对象、纯业务规则
      services/                # application services / transaction scripts
      graphs/                  # interview graph、finalization subgraph
      retrieval/               # dense、lexical、RRF、reranker
      models/                  # 各角色调用器，基于共享 Model Adapter
      repositories/            # SQLAlchemy repositories
      observability/           # trace 与结构化事件
      settings.py
    migrations/                # Alembic

  local_project/
    src/local_project/
      api/
      source_registry/
      inventory/
      repository_map/
      observer/
      project_answerer/
      tools/                   # 限定根目录的只读工具
      settings.py

packages/
  content_safety/              # 两个 Runtime 共用的纯文本过滤库与规则配置
  model_adapter/               # 无文件权限的模型传输、重试与无内容 trace 合同
  prompt_assets/               # Prompt、JSON Schema、版本清单
  planning_assets/             # Topic、方向模板和 planning policy

scripts/
  import_question_bank.py
  rebuild_question_indexes.py
  run_regression_suite.py

tests/
  unit/
  integration/
  contract/
  e2e/
  regression/
```

Python 合同由 Pydantic 定义，FastAPI 生成 OpenAPI；Web 的 TypeScript client 从 OpenAPI 生成，避免手工维护两份请求类型。两个 Runtime 只共享无文件访问能力的合同、`content_safety` 和 `model_adapter` 包；Application Runtime 不得 import Local Project Runtime 的路径解析或文件工具。

## 4. 领域枚举与稳定值对象

数据库使用 `text + check constraint`，Python 使用 `StrEnum` / `Literal`。这样添加非破坏性状态时不依赖 PostgreSQL enum 迁移。

### 4.1 Session 状态

```text
preparing        创建后，快照、范围或计划尚未准备完成
interviewing     已开始面试，正在等待回答或处理本轮决策
post_processing  面试已冻结，正在生成赛后产物
completed        所有自动尝试已经到达终点；允许部分赛后产物缺失
aborted          用户二次确认强制退出
```

`completed` 不保证一定存在报告。是否有报告由报告产物和赛后任务状态判断；这样自动重试耗尽后仍能进入终态、删除 checkpoint，并展示“处理未完成”。

### 4.2 结束原因

```text
normal
early_finish
forced_exit
safety_cap
```

`preparing/interviewing` 的 `termination_reason` 为 `NULL`。进入 `post_processing` 时已经确定本场为何结束，因此写入 `normal | early_finish | safety_cap`；进入 `completed` 后保留该值。`aborted` 只允许 `forced_exit`。

### 4.3 其他枚举

```text
interview_direction project_overview | core_flow_deep_dive | cross_cutting | stress_interview | contribution_retrospective
stage_result      complete | unresolved
plan_action       continue | complete | unresolved
feedback_value    upvote | downvote
user_role         user | administrator
post_task_kind    project_answers | ideal_answer | evaluation | report
post_task_status  pending | running | succeeded | failed
curation_status   pending | reviewed | added | rejected
```

`project_answers` 输出顶层 JSON 合法但缺少部分题时，任务仍可视为 `succeeded`；具体缺失通过对应 turn 没有 `project_answer` 表达，不增加新的产品字段。

### 4.4 计划与范围值对象

```python
class SectionRef(BaseModel):
    kind: Literal["module", "thread"]
    title: str

class InterviewStage(BaseModel):
    id: str
    title: str
    goal: str
    complete_when: str
    topic_path: str
    section_refs: list[SectionRef]

class InterviewPlan(BaseModel):
    stages: list[InterviewStage]
    template_id: str
    template_version: str
    topic_registry_version: str
    planning_policy_version: str
```

`Stage.id` 只在本次 plan 内唯一，不扩散成跨 session 业务 ID。

确定性校验至少保证：正常计划包含不少于 5 个且不超过配置上限的 Stage；`Stage.id` 在计划内唯一；每个 `topic_path` 存在于本次 Topic registry；`section_refs` 只能来自本次 `selected_sections`，没有可解析/选择范围时两者都为空；Stage 不得夹带固定问题、分支边或其他运行时状态字段。

## 5. PostgreSQL 物理模型

首版使用一个 PostgreSQL 实例，按逻辑 schema 分隔：

```text
app          session 与业务产物
bank         唯一题库、检索索引和统计
telemetry    无内容调用 trace
```

所有时间使用 `timestamptz`；主键默认 UUID。所有 session 子表使用外键 `ON DELETE CASCADE`。大文本不进入普通列表查询。

### 5.1 身份

#### `app.users`

| 列 | 类型 | 约束 |
| --- | --- | --- |
| `id` | uuid | PK |
| `role` | text | `user | administrator` |
| `display_name` | text | 可空 |
| `created_at` | timestamptz | 非空 |

认证凭据实现由部署环境决定，不在业务表中混入第三方 token。授权器必须同时检查身份角色、session owner 和 `curation_review`，不能只检查 `role=administrator`。

### 5.2 Session 核心

#### `app.interview_sessions`

| 列 | 类型 | 约束 / 用途 |
| --- | --- | --- |
| `id` | uuid | PK |
| `user_id` | uuid | FK `users.id`，必须为 User |
| `status` | text | 五种 session 状态 |
| `interview_direction` | text | 五种方向；准备初期可空 |
| `selected_sections` | jsonb | `SectionRef[]`，默认 `[]` |
| `source_handle` | text | 可空；只是不透明引用 |
| `termination_reason` | text | 可空 |
| `curation_review` | boolean | 默认 false |
| `feedback_frozen_at` | timestamptz | 可空；非空后拒绝反馈更新 |
| `created_at` | timestamptz | 非空 |
| `updated_at` | timestamptz | 非空 |
| `completed_at` | timestamptz | 可空 |

约束：

- `status IN (...)`。
- `status IN ('preparing','interviewing')` 时 `termination_reason IS NULL`。
- `status IN ('post_processing','completed')` 时 `termination_reason IN ('normal','early_finish','safety_cap')`。
- `status='aborted'` 时 `termination_reason='forced_exit'`。
- `curation_review` 只能由 owner 修改。

索引：`(user_id, updated_at DESC)` 支持用户 session 列表，`(status, updated_at)` 支持恢复 worker 扫描；列表索引不包含 snapshot 或对话正文。

#### `app.session_snapshots`

| 列 | 类型 | 约束 / 用途 |
| --- | --- | --- |
| `session_id` | uuid | PK、FK session |
| `content` | text | 当前唯一 snapshot 全文 |
| `updated_at` | timestamptz | 非空 |

该表永远只保留当前全文，不保存 revision、草稿或历史链。列表接口不得默认读取 `content`。

#### `app.interview_plans`

| 列 | 类型 | 约束 / 用途 |
| --- | --- | --- |
| `session_id` | uuid | PK、FK session |
| `plan` | jsonb | 完整 `InterviewPlan` |
| `created_at` | timestamptz | 非空 |

计划进入面试后不再更新。保存前使用 Pydantic 和确定性规划校验器双重验证。

准备期 observe/import 得到的过滤后全文确实变化，或首次应用一条新的用户意见时，才在同一事务中清空 `selected_sections` 并删除已有 plan；与当前 snapshot 全文相同的 observe/import 重放不重复失效范围或 plan。单独更换仍属同一 session 的有效 `source_handle` 只影响赛后目录授权，不改变 plan。方向或范围的规范化值确实发生变化时才删除已有 plan，相同 selection 的 PUT 重放只返回当前资源，不能删除此后生成的 plan。`start` 只接受当前 snapshot、当前选择和当前方向重新生成且通过校验的 plan。进入 `interviewing` 后，准备期 snapshot/selection/plan 写接口全部拒绝；面试中的已确认事实更正只追加当前 snapshot，按产品合同不重跑 Planner。

#### `app.stage_results`

| 列 | 类型 | 约束 / 用途 |
| --- | --- | --- |
| `session_id` | uuid | FK session |
| `stage_index` | integer | 从 0 开始 |
| `stage_id` | text | 对应当前 plan |
| `result` | text | `complete | unresolved` |
| `closed_at` | timestamptz | 非空 |

主键：`(session_id, stage_index)`；另加唯一约束 `(session_id, stage_id)`。关闭同一 Stage 的重复操作返回已有结果。

### 5.3 Turn 与反馈

#### `app.turns`

| 列 | 类型 | 约束 / 用途 |
| --- | --- | --- |
| `session_id` | uuid | FK session |
| `turn_no` | integer | 从 1 开始 |
| `stage_index` | integer | 非空 |
| `question` | text | 非空；实际展示文本 |
| `question_id` | uuid | 可空；FK `bank.questions`，只在问题正文与本轮某条 RAG 候选完全相同时写入 |
| `answer` | text | 问题刚展示时可空 |
| `interviewer_message` | text | 可空；记录在被回应的 turn 上 |
| `question_shown_at` | timestamptz | 非空 |
| `answered_at` | timestamptz | 可空 |

主键：`(session_id, turn_no)`。约束 `turn_no BETWEEN 1 AND 100`。`question_id` 使用 `ON DELETE RESTRICT` 保留已经结算过的题库关联；它不进入 Supervisor 合同或用户界面。

提交回答时：

1. 先做长度、编码和内容安全检查并构造只供模型链路使用的过滤工作文本；硬拒绝时不写数据库。
2. 取得 session 执行锁，检查 `status='interviewing'` 并读取 checkpoint 的 `awaiting`。
3. 当前 turn 必须存在且尚未出现下一 turn；首次提交只允许 `awaiting='answer'`。
4. `awaiting='snapshot_confirmation' | 'decision_retry'` 时拒绝新的回答并返回 `409 operation_in_progress`。
5. `answer IS NULL` 时写入用户提交的原回答。
6. 已有回答与本次完全相同时不重写回答、不重置尝试预算，也不因这个重复请求再次调用模型；无论 Graph 已推进到哪一个后续 interrupt，都只返回当前处理状态或已发布结果。
7. 已有回答不同则返回 `409 answer_conflict`，首版不提供修改回答流程。

Supervisor 自动尝试耗尽后的“重试当前步骤”是独立命令，不伪装成重复回答提交；见 6.4 和 10.3。

#### `app.question_feedback`

| 列 | 类型 | 约束 / 用途 |
| --- | --- | --- |
| `session_id` | uuid | FK session |
| `turn_no` | integer | 与 session_id 组成 FK turn |
| `value` | text | `upvote | downvote` |
| `reason` | text | 可空 |
| `updated_at` | timestamptz | 非空 |

主键：`(session_id, turn_no)`。API 使用 PUT 覆盖当前值；事务先锁定同一 session 行，再检查 `feedback_frozen_at IS NULL`，与结束流程使用同一行锁串行化，避免“冻结已提交、反馈随后落库”的竞态。原因只保存在 session，不进入题库统计字段。

`(session_id, turn_no)` 使用组合外键引用 `app.turns(session_id, turn_no)`；不能把 `turn_no` 当作跨 session 唯一值单独引用。下文所有逐 turn 结果表采用相同规则。

### 5.4 赛后产物

#### `app.turn_post_results`

| 列 | 类型 | 约束 / 用途 |
| --- | --- | --- |
| `session_id` | uuid | FK session |
| `turn_no` | integer | 与 session_id 组成 FK turn |
| `project_answer` | text | 可空 |
| `ideal_answer` | text | 可空 |
| `comment` | text | 可空 |
| `updated_at` | timestamptz | 非空 |

主键：`(session_id, turn_no)`。三类结果分别 UPSERT 自己的列，不能用空值覆盖另一分支已经成功的结果。

#### `app.session_reports`

| 列 | 类型 | 约束 / 用途 |
| --- | --- | --- |
| `session_id` | uuid | PK、FK session |
| `report` | jsonb | 固定报告 JSON |
| `created_at` | timestamptz | 非空 |

Markdown 由确定性 renderer 从 JSON 生成，不保存第二份 Markdown 业务事实。

#### `app.post_tasks`

这是内部执行记录，不进入 Agent 合同或结果页字段。

| 列 | 类型 | 约束 / 用途 |
| --- | --- | --- |
| `task_key` | text | PK；稳定自然键 |
| `session_id` | uuid | FK session |
| `kind` | text | 四种 task kind |
| `turn_no` | integer | 逐题任务使用；整场任务为空 |
| `status` | text | pending/running/succeeded/failed |
| `attempt_count` | integer | 非空，默认 0 |
| `last_error_code` | text | 可空；不得包含正文 |
| `lease_owner` | text | 可空；worker 标识 |
| `lease_expires_at` | timestamptz | 可空；崩溃恢复使用 |
| `started_at` | timestamptz | 可空 |
| `finished_at` | timestamptz | 可空 |
| `updated_at` | timestamptz | 非空 |

自然键示例：

```text
{session_id}:project_answers
{session_id}:ideal_answer:{turn_no}
{session_id}:evaluation:{turn_no}
{session_id}:report
```

自动尝试耗尽后任务变为 `failed`。本版本不提供用户手动重建 task 的 API。

约束：`project_answers/report` 的 `turn_no` 必须为空，`ideal_answer/evaluation` 的 `turn_no` 必须非空并与 `session_id` 组成指向 `app.turns` 的组合外键。数据库不能只依赖调用方正确拼接 `task_key` 来维持这种对应关系。

### 5.5 Snapshot 追加回执

#### `app.snapshot_append_operations`

| 列 | 类型 | 约束 / 用途 |
| --- | --- | --- |
| `operation_key` | text | PK |
| `session_id` | uuid | FK session |
| `section` | text | `用户意见 | 事后核验` |
| `payload_hash` | text | 非空；检测同 key 不同内容 |
| `created_at` | timestamptz | 非空 |

该表只解决 snapshot 只增追加在“事务已提交、调用方未收到结果”窗口中的恰好一次业务效果，不扩展为通用工作流回执表，也不保存 Prompt、回答或模型全文。典型 key：

```text
session:{id}:snapshot:user_opinion:{request_id}
session:{id}:turn:{turn_no}:snapshot_correction
session:{id}:post_verification
```

用户每次确认追加意见时由客户端生成一个随机 `request_id`，并在网络重试时复用；它通过 `Idempotency-Key` 请求头传递，不进入 snapshot、Agent 合同或 session 业务字段。turn 更正和单次赛后核验已经有自然定位，不另造请求 ID。回执与对应 snapshot 写入必须在同一个 PostgreSQL 事务中提交。相同 key 与相同 hash 的重试返回当前全文；相同 key 携带不同 hash 时返回冲突，不能静默采用第一次或第二次内容。

### 5.6 题库统计结算

#### `bank.session_settlements`

| 列 | 类型 | 约束 / 用途 |
| --- | --- | --- |
| `session_id` | uuid | PK、FK `app.interview_sessions`，级联删除 |
| `settled_at` | timestamptz | 非空 |

所有计数更新与这条记录在一个事务中完成。重复执行命中主键后直接返回已结算。

### 5.7 唯一题库

#### `bank.questions`

| 列 | 类型 | 约束 / 用途 |
| --- | --- | --- |
| `id` | uuid | 内部 PK，不进入 Agent 合同 |
| `question` | text | 非空，精确文本唯一 |
| `topic_path` | text | 非空 |
| `ideal_answer` | text | 可空 |
| `usage_count` | bigint | 默认 0 |
| `upvote_count` | bigint | 默认 0 |
| `downvote_count` | bigint | 默认 0 |
| `embedding` | vector | 维度由 embedding adapter 配置 |
| `lexical_document` | tsvector | 预分词后的 FTS 文档 |
| `created_at` | timestamptz | 非空 |
| `updated_at` | timestamptz | 非空 |

内部 ID 用于索引、运行时候选映射和结算。Retrieval Service 把 ID 与正文保留在 State 中，但给 Supervisor 组装上下文时只投影正文；Supervisor 输入、模型输出和用户界面都不接触题库 ID。程序在发布问题时把解析出的可空 ID 写入 turn。

索引：

- `embedding` 的 pgvector ANN 索引。
- `lexical_document` 的 GIN 索引。
- `topic_path` btree 索引。

### 5.8 策展

#### `app.curation_items`

管理员主动选择一条已授权会话材料后才创建：

| 列 | 类型 | 约束 / 用途 |
| --- | --- | --- |
| `id` | uuid | PK |
| `source_session_id` | uuid | 必须已授权；与 source_turn_no 组成源 FK |
| `source_turn_no` | integer | 原始问题；与 source_session_id 组成源 FK |
| `status` | text | pending/reviewed/added/rejected |
| `edited_question` | text | 可空 |
| `proposed_topic_path` | text | 可空 |
| `review_notes` | text | 可空 |
| `reviewed_by` | uuid | 可空，Administrator |
| `question_bank_id` | uuid | 加入题库后可空转非空 |
| `created_at` | timestamptz | 非空 |
| `updated_at` | timestamptz | 非空 |

创建和读取时都重新检查源 session 的 `curation_review=true` 且已经进入 `completed/aborted` 终态；进行中的会话即使提前授权，也不能出现在管理员材料列表中。撤销授权后，未加入题库的 item 不再向管理员展示；已完成的题库变更按审计规则保留，但不能反向读取私人会话。

`(source_session_id, source_turn_no)` 使用组合外键引用源 turn，避免把一个 session 的 turn 号误关联到另一场会话。

### 5.9 无内容 Trace

#### `telemetry.model_calls`

| 列 | 类型 |
| --- | --- |
| `trace_id` | uuid PK |
| `span_id` / `parent_span_id` | text / text nullable |
| `session_id` | uuid nullable，FK `app.interview_sessions`，`ON DELETE CASCADE` |
| `operation_name` | text |
| `provider` / `model` | text |
| `prompt_version` | text nullable；embedding/reranker 无 Prompt 时为空 |
| `status` | text |
| `attempt_no` | integer |
| `started_at` / `finished_at` | timestamptz |
| `latency_ms` | integer |
| `input_tokens` / `output_tokens` | integer nullable |
| `cost_micros` | bigint nullable |
| `error_code` | text nullable |

严禁保存完整 Prompt、输入输出正文、snapshot、answer、`user_acts` 或安全过滤前内容。定时任务删除 30 天前记录；删除 session 时由外键级联同步删除关联 trace。

## 6. 事务与并发合同

### 6.1 不跨外部调用持有数据库事务

模型调用、embedding、reranker 和 Local Project Runtime 请求全部在数据库事务外执行：

1. 短事务读取并验证触发条件。
2. 调用外部能力。
3. 校验结构化结果。
4. 新短事务通过条件写入发布结果。

发布事务必须重新检查 session 状态和触发上下文。迟到结果如果发现 session 已进入其他终态、Stage 已变化或对应自然业务结果已经存在，直接丢弃。

### 6.2 单 session 执行互斥

Application Runtime 使用 Redis 短期执行锁避免同一 session 同时运行两个 Graph resume：

```text
lock key: interview:{session_id}:execution
```

锁具有 TTL 和续租；它只减少重复工作，不承担业务正确性。即使锁失效，PostgreSQL 唯一约束、snapshot 追加回执和条件写入仍保证业务结果最多生效一次。

### 6.3 Snapshot 追加

统一服务接口：

```python
append_snapshot(
    session_id,
    operation_key,
    section: Literal["用户意见", "事后核验"],
    sanitized_text,
) -> current_snapshot
```

事务步骤：

1. 锁定 snapshot 行。
2. 尝试插入 `snapshot_append_operations`。
3. key 已存在且 hash 相同时返回当前全文；hash 不同时返回冲突。
4. 验证追加内容已经带有安全过滤证明，只向指定区块追加。
5. 更新当前全文并提交。

安全过滤证明是进程内值对象，不作为用户字段；未经 `content_safety` 构造的普通字符串不能调用 repository 写入方法。

初次用户意见需要清空旧范围与 plan 时，该失效操作只与“首次成功插入回执 + 追加 snapshot”处于同一事务。命中既有回执的迟到重试只返回当前资源，绝不能再次清空此后新生成的范围或 plan。

### 6.4 Supervisor 决策发布

发布事务：

1. 锁定 session。
2. 检查仍为 `interviewing`，当前 Stage 与调用前一致。
3. 按触发类型重新检查前置事实：`AnsweredTurnTrigger` 要求触发 turn 的回答仍存在且没有更新的 turn；`StageEntryTrigger` 要求目标 Stage 是第一个未关闭 Stage，且当前没有等待回答的问题。
4. `continue`：用 Supervisor 最终 `question` 在 State 的本轮 RAG 候选中做精确字符串查找；完全相同时取出内部 `question_id`，否则为 `NULL`。在 100 turn 上限内把问题正文和这个可空关联一起写入下一 turn。
5. `complete/unresolved`：写 `stage_results`，不创建 turn。
6. 只有回答后决策才把面试官回应保存到被回答 turn 的 `interviewer_message`；Stage 首题没有可回写的上一 turn。
7. 提交。

`StageEntryTrigger` 的有效输出只能是 `continue`，并要求 `user_acts=[]`、`interviewer_message=null`。Stage 尚未开始时没有可回应的用户消息，不能伪造一条面试官回应，也不能直接发布 `complete/unresolved`；首题创建成功才使该 Stage 进入问答流程。

所有触发类型都先执行确定性动作校验：`continue` 必须携带且只携带一个非空主要问题，`complete/unresolved` 的 `question` 必须为 `null`。不满足时只能进入同一调用预算内的格式修复或失败 interrupt，不能靠应用层猜测动作。

Supervisor 不读取或输出题库 ID；候选映射与上述关联解析完全由程序处理。Supervisor 决策不写通用 operation receipt。下一题由 `(session_id, turn_no)` 主键、Stage 关闭由 `(session_id, stage_index)` 主键保证最多写入一次；事务中的 session 状态、当前 Stage 和“是否已有更新 turn”条件拒绝迟到或冲突结果。重复发布命中已有自然业务事实时返回当前状态。

若 Supervisor 输出包含待确认事实更正，步骤 4～6 暂不执行；结构化决策和已过滤候选保留在 checkpoint。用户确认或拒绝后，同一决策继续发布，不进行第二次 Supervisor 调用。checkpoint 丢失时允许丢失该未确认候选，并重新发起本逻辑决策。

Supervisor 自动尝试耗尽时，Graph 进入 `decision_retry` interrupt 并在 checkpoint 保存无正文的 `last_error_code`。若触发源是回答，回答已经在 PostgreSQL 中，因此不回滚；若触发源是 Stage 首次进入，此时尚不存在该 Stage 的 turn。显式“重试当前决策”命令取得 session 执行锁后，按当前 PostgreSQL 事实重新验证该决策仍未发布，再清除本次执行错误并给共享 Model Adapter 一份新的有界尝试预算。普通的重复 answer 请求绝不执行这一步，两种触发都不得因失败或重试增加 turn。

### 6.5 强制退出竞争

用户点击按钮只在前端展示确认框，不发送终态命令；确认框打开期间前端禁用回答提交和提前完成。确认后才调用 API。`finish-early`、安全停止和确认强退统一经过同一个 session 终止服务与同一把 session 执行锁，避免各 endpoint 各自实现状态竞争。

确认强退事务：

1. 锁定 session。
2. 如果已经 `aborted`，返回当前终态；如果在确认请求到达服务端之前已经完成 `completed` 提交，或 `post_processing` 已经发布赛后业务产物/`post_verification`，则返回当前状态，强退优先级不追溯回滚已经发布的业务事实。
3. 若只是并发的提前完成刚进入 `post_processing`、尚未发布赛后业务产物，则取消并删除尚未生效的 task 执行记录。
4. 设置 `status='aborted'`、`termination_reason='forced_exit'`。
5. 冻结反馈并记录 `completed_at`。
6. 提交后取消可取消的在途调用并删除 checkpoint。

一旦确认强退事务获得 session 锁，尚未提交的回答、提前完成和模型结果均在重新检查 status 后失败，因此强退在同一并发窗口中获胜；无法取消的迟到结果也不会落库。这里的“优先”以尚未发布不可逆业务产物的并发窗口为边界，不意味着用户确认请求到达前已经完成的终态或赛后产物会被事后回滚。

### 6.6 题库统计结算

问题与题库的关联已经在实时发布 turn 时确定。统计结算只读取所有已经展示的 turn（包括提前结束时尚未回答的当前 turn）上的非空 `question_id` 和已经冻结的反馈，不读取问题正文、不执行检索，也不重新判断题目归属。

正常赛后路径在任何答案 Agent 之前执行结算：

1. 开启事务并尝试插入 `bank.session_settlements`；已存在则直接结束。
2. 按 `app.turns.question_id` 聚合本场 usage；左连接 `app.question_feedback` 聚合 upvote/downvote。`question_id IS NULL` 的 turn 不参与题库累计。
3. 使用原子增量更新批量写入 `bank.questions`。
4. 提交。

`session_settlements` 是这次原子发布的完成标记：记录存在表示本场计数已经发布，即使本场所有 turn 的 `question_id` 都为空也不需要额外空结果行。事务失败时结算记录和计数一起回滚；事务已经提交但 checkpoint 尚未更新时，恢复流程命中 settlement 后直接继续，不重复累计。

## 7. LangGraph State

### 7.1 Interview State

```python
class InterviewGraphState(TypedDict):
    session_id: UUID
    current_stage_index: int

    snapshot: str
    plan: InterviewPlan
    stage_results: list[StageResult]

    compact: str | None
    compacted_through_turn_no: int
    recent_turns: list[TurnContext]

    trigger: StageEntryTrigger | AnsweredTurnTrigger
    rag_candidates: list[QuestionCandidate]

    pending_supervisor: SupervisorDecision | None
    pending_snapshot_append: SanitizedAppend | None
    awaiting: Literal["answer", "snapshot_confirmation", "decision_retry"] | None

    last_error_code: str | None
```

不进入 State：

- 题目反馈。
- 题库计数和检索分数。
- 完整历史 turns 的第二份副本。
- 原始文件路径或未脱敏项目内容。
- 已应用的 `user_acts`。
- 模型 trace 正文。

每次从 start/resume 运行到下一个 interrupt 前，`load_session_context` 用 PostgreSQL 当前 snapshot、plan、Stage 结果和必要 turns 覆盖工作副本。`retrieve_candidates` 随后把本轮内部候选映射写入 `rag_candidates`，Prompt 组装器只把其中的 `question` 列表提供给 Supervisor。`compacted_through_turn_no` 只存在于 checkpoint，用来确定累计 compact 已经覆盖到哪个已回答 turn；它不是业务字段。

`TurnContext` 只包含组装连续对话所需的 Stage、问题、回答和可选面试官消息，不含历史 turn 的 `question_id`。题库关联不参与 Supervisor 推理。

### 7.2 Finalization State

赛后使用子图和独立 State，避免实时 State 无限膨胀：

```python
class FinalizationState(TypedDict):
    session_id: UUID
    snapshot: str
    turns: list[CompletedTurn]

    settlement_committed: bool

    project_answers_terminal: bool
    ideal_answers_terminal: bool

    pending_post_verification: SanitizedAppend | None
    failed_task_keys: list[str]
```

实际大文本产物一旦通过校验就写 PostgreSQL，State 只保存协调所需标识和当前 snapshot，不长期堆积所有模型原始响应，也不另设 `final_snapshot` 副本；事后核验成功后直接用 PostgreSQL 返回的当前全文覆盖 `snapshot`。题库关联已经持久化在 `app.turns.question_id`，Finalization State 不保存第二份关联结果。每次 resume 时，`settlement_committed` 从 `session_settlements` 重建，所有 `*_terminal` 和 `failed_task_keys` 从 PostgreSQL `post_tasks` 重载；这些 State 字段都不是第二份业务事实。需要评估的 turn 直接从 `turns` 与任务终态计算，不保存额外 ready 列表。

`CompletedTurn` 是从 `app.turns` 装载的内部记录，包含可空 `question_id`；给项目版答案、理想版答案和评估 Agent 组装 Prompt 时仍只投影各自合同允许的正文，题库 ID 不进入模型上下文。

### 7.3 Compact

compact 是辅助模型调用，不是 Agent：

```text
input  = previous_compact + exactly next 20 answered turns
output = one cumulative compact string
```

调用成功后把新 compact 与新的 `compacted_through_turn_no` 一起写入 checkpoint；失败时保留旧 compact、旧游标和尚未压缩的原文，下次有界重试。`recent_turns` 始终从游标后的第一个 turn 开始装载，完整 turns 永不删除。checkpoint 丢失时从 0 开始按相同 20-turn 边界依次重新生成。

## 8. Graph 设计

### 8.1 Interview Graph 节点

| 节点 | 职责 | 外部副作用 |
| --- | --- | --- |
| `load_session_context` | 从 PG 重建本次 State | 无 |
| `maybe_compact` | 在下一次 Supervisor 上下文前折叠满 20 个 turn 的批次 | checkpoint |
| `build_trigger` | 判断 Stage 首题或回答后决策 | 无 |
| `retrieve_candidates` | 调用 RAG，把候选 ID 与正文写入 State；失败返回空 | checkpoint |
| `call_supervisor` | 只把候选正文提供给模型并校验/修复 | trace |
| `prepare_snapshot_confirmation` | 过滤事实更正候选 | checkpoint interrupt |
| `persist_snapshot_append` | 幂等追加并刷新 State | PG |
| `apply_supervisor_decision` | 精确解析候选关联并条件发布 Stage/turn 结果 | PG |
| `interrupt_for_decision_retry` | 自动尝试耗尽后等待显式重试或强退 | checkpoint interrupt |
| `interrupt_for_answer` | 等用户回答 | checkpoint |
| `freeze_and_route_terminal` | 冻结反馈并选择赛后分支 | PG |

### 8.2 Interview Graph 路径

```text
START / RESUME
  → load_session_context
  → maybe_compact
  → build_trigger
  → retrieve_candidates
  → call_supervisor
      ├─ attempts exhausted
      │    → interrupt(decision_retry)
      ├─ correction candidate
      │    → prepare_snapshot_confirmation
      │    → interrupt(snapshot_confirmation)
      │    → persist_snapshot_append or skip
      └─ no correction
  → apply_supervisor_decision
      ├─ continue
      │    → interrupt(answer)
      ├─ close stage + remaining stage
      │    → load_session_context
      └─ close final stage
           → freeze_and_route_terminal
```

关闭 Stage 的决策和下一 Stage 首题是两个不同的逻辑 Supervisor 操作。前者不创建 turn；后者重新经过 `retrieve_candidates → call_supervisor`。

### 8.3 外部终止命令

`finish-early` 和确认后的 `force-exit` 是 application command，不作为 Supervisor 输出：

- 全部 Stage 正常耗尽时冻结反馈并进入 `post_processing`。
- `finish-early` 锁定 session 并冻结反馈：至少一个 Stage 为 `complete` 时进入 `post_processing`，否则直接进入 `completed`、只保留已有对话并由终态 worker 结算题库统计。
- `force-exit` 进入 `aborted`，不运行赛后 LLM，但仍由终态 worker 按 turns 已保存的 `question_id` 执行题库统计结算。
- 创建第 101 个问题前触发安全停止：至少一个 Stage 为 `complete` 时进入 `post_processing`，否则进入 `completed`；不得先创建第 101 个 turn 再回滚。

### 8.4 Finalization Subgraph

```text
load_finalization_context
  → settle_question_statistics
  → fork_reference_answers
      ├─ project_answers_whole_session ──> optional_post_verification_append
      └─ ideal_answers_fan_out(turn_no)
                    │
                    ▼
             wait_reference_terminal
                    │
        (参考答案成功、部分成功或失败都继续)
                    │
                    ▼
             evaluations_fan_out(turn_no)
                    │
           ┌────────┴────────┐
           │ all succeeded   │ any failed after budget
           ▼                 ▼
      report_generation   finish_incomplete
           │                 │
           └────────┬────────┘
                    ▼
             mark_session_completed
             delete_checkpoint
```

规则：

- 题库统计结算是赛后首个处理节点；它只读取 turns 已保存的 `question_id` 与冻结反馈，通过幂等事务更新题库统计，然后才启动答案 Agent。
- 题库统计覆盖所有已经展示的 turn；项目版答案、理想版答案、逐题评估和报告只处理 `answer IS NOT NULL` 的 turn。提前结束时尚未回答的问题保留在完整历史中；若带 `question_id` 仍计一次使用，但不生成评价，也不作为报告中的能力证据。
- `session_settlements` 已存在时，Graph 跳过重复计数；不存在时才执行结算。所有 turn 的 `question_id` 都为空时仍插入 settlement，不增加空关联行或额外完成字段。
- 结算完成后，项目版答案任务与逐题理想答案并行；理想答案路由只读取 `app.turns.question_id`，关联题目已有预生成答案时复用，否则现场生成。
- 统计结算只依赖 PostgreSQL，不存在独立的赛后匹配基础设施故障分支。事务故障按同一 settlement 幂等逻辑重试；答案 Agent 仍严格在结算提交后启动。
- 项目版答案允许缺项；顶层 JSON 必须完整可解析，每项按 `turn_no` 独立校验。
- 被截断的顶层 JSON 整体不采用。
- 项目版答案始终以当前 snapshot 为最高优先级事实；目录只补充 snapshot 缺失证据。目录不可用时退回 snapshot，目录与 snapshot 冲突时采用 snapshot 并在答案中自然说明证据缺口。
- 项目版 Agent 使用目录获得的新事实，必须先通过过滤和 `post_verification` 幂等追加；评估随后读取数据库返回的最终 snapshot。
- 某题缺少项目版答案或理想版答案时仍要评估；评估使用最终 snapshot、本题 Q/A 与已有的可空参考答案，不能因为系统自己的参考答案任务失败而直接降低用户评价。
- 理想版答案每题只读取该实际问题以及按 `question_id` 可复用的题库理想答案或必要的一般背景，不读取项目目录、项目版答案和用户反馈；其语义是通用行业实践，不是当前项目的唯一正确答案。
- 逐题评估必须区分项目事实与通用实践：最终 snapshot 和项目版答案用于当前项目判断，理想版答案只作一般性参照；不得仅因用户基于项目约束偏离理想版答案就作负面评价，必要时在 `comment` 中解释两者差异。
- 逐题评估只读取最终 snapshot、本题 Q/A 和本题两版可空参考答案；报告只读取最终 snapshot 与按 Stage 排序的 `Q/A/comment`，不读取两版参考答案、反馈、项目目录或其他题的模型原始输出。
- 参考答案任务在自动尝试耗尽后失败只令对应参考字段保持为空，不阻止评估。只有某题评估在自动尝试耗尽后仍失败，才不生成伪完整报告；系统保存其他成功产物并把 session 标为 `completed`。
- 报告失败时保留完整问答中已经成功的内容，结果页显示处理未完成。
- 当前版本没有创建新赛后批次的用户 API。

### 8.5 Worker 与恢复

首版使用 Application Runtime 内的受控后台 worker；不引入 Celery/Kafka。Finalization Graph 是赛后依赖关系和 fan-out/join 的唯一编排者，`post_tasks` 只是各节点的持久化执行账本，不自行决定后继任务。

worker 周期性查询：

- `status='interviewing'` 且数据库事实显示系统尚欠一个 Supervisor 决策的 session。
- `status='post_processing'` 的 session。
- 已进入终态但尚未完成题库结算的 session。

对于 `interviewing` session，worker 只恢复没有在等待用户输入的图：最新问题已有回答但尚未发布回答后决策、当前 Stage 已关闭但下一 Stage 首题尚未发布，或开始面试后首个 Stage 尚无首题。checkpoint 明确处于 `answer`、`snapshot_confirmation` 或 `decision_retry` interrupt 时绝不自动越过；checkpoint 丢失时则从 PostgreSQL 的 turn 与 Stage 结果重建触发类型。这样进程崩溃后的恢复不依赖用户重复提交 answer，也不会把一次明确失败变成无限自动重试。

对于 `post_processing` session，worker 只领取整场 session 并 start/resume 它的 Finalization Graph，不直接领取某条 `post_task` 或根据任务表另行拼装 DAG。答案、评估和报告节点执行外部调用前把对应 task 置为 `running` 并写短租约；节点崩溃后，下一次 Graph resume 可以回收租约已失效的 task。对于不启动赛后 LLM、但仍未结算题库统计的终态 session，worker 只调用同一套统计结算 service，不创建第二条赛后 DAG。多个 worker 使用 session 执行锁与 `FOR UPDATE SKIP LOCKED` 避免重复处理同一 session。Graph checkpoint 用于恢复节点位置，PostgreSQL task/产物用于确认业务效果和节点终态。

节点发布已校验产物与把对应 task 标记为 `succeeded` 必须在同一个 PostgreSQL 事务中完成；不能先把账本标为成功、再单独写产物。项目版答案若依赖新增目录事实，则相关答案、`post_verification` snapshot 追加回执和 task 成功状态一起发布；追加失败时这些依赖新事实的答案不能提前进入评估。

## 9. Application Service 合同

核心 service 只暴露业务操作，不暴露 ORM model：

```python
class SessionService:
    create_session(user_id) -> SessionView
    list_sessions(user_id, filters) -> Page[SessionSummary]
    set_direction_and_sections(session_id, direction, sections) -> SessionView
    start_interview(session_id) -> InterviewView
    finish_early(session_id) -> SessionView
    force_exit(session_id) -> SessionView
    delete_session(session_id) -> None

class SnapshotService:
    import_markdown(session_id, markdown, source_handle=None) -> SnapshotView
    apply_observation(session_id, observed_markdown, source_handle) -> SnapshotView
    append_user_opinion(session_id, text) -> SnapshotView
    parse_ranges(session_id) -> RangeOptions
    export_markdown(session_id) -> str

class PlanningService:
    generate_plan(session_id) -> InterviewPlan

class InterviewService:
    get_current_view(session_id) -> InterviewView
    submit_answer(session_id, turn_no, answer) -> InterviewView
    retry_current_decision(session_id) -> InterviewView
    resolve_snapshot_confirmation(session_id, confirm, edited_text) -> InterviewView

class FeedbackService:
    put_feedback(session_id, turn_no, value, reason) -> FeedbackView

class ResultService:
    get_report(session_id) -> ReportView
    get_full_qa(session_id) -> FullQaView
    render_report_markdown(session_id) -> str
    render_full_qa_markdown(session_id) -> str

class CurationService:
    grant(session_id, user_id) -> None
    revoke(session_id, user_id) -> None
    list_authorized_items(admin_id, filters) -> Page[CurationCandidate]
    list_question_bank(admin_id, filters) -> Page[QuestionBankView]
    add_to_question_bank(admin_id, item_id, reviewed_input) -> QuestionBankView
```

Repository 接口接受领域值对象；安全过滤、权限判断、模型调用和事务编排位于 service，不进入 router。

## 10. HTTP API

### 10.1 通用响应与错误

成功响应包含当前资源，不返回 ORM 字段。错误统一为：

```json
{
  "error": {
    "code": "state_conflict",
    "message": "当前会话已经结束，不能继续提交回答。",
    "retryable": false
  }
}
```

常用状态码：

```text
400 invalid_request / schema_invalid
401 unauthenticated
403 forbidden / curation_not_granted
404 session_not_found / turn_not_found
409 state_conflict / answer_conflict / feedback_frozen / operation_in_progress / retry_not_available
422 safety_filter_rejected / plan_invalid
503 dependency_unavailable
```

错误详情不得包含 Prompt、模型原始输出、文件正文或敏感值。

### 10.2 Session 与准备

```text
POST   /v1/interviews
GET    /v1/interviews
GET    /v1/interviews/{session_id}
DELETE /v1/interviews/{session_id}

POST   /v1/interviews/{session_id}/snapshot:observe
POST   /v1/interviews/{session_id}/snapshot:import
POST   /v1/interviews/{session_id}/snapshot:append-user-opinion
POST   /v1/interviews/{session_id}/snapshot:parse-ranges

PUT    /v1/interviews/{session_id}/selection
POST   /v1/interviews/{session_id}/plan:generate
GET    /v1/interviews/{session_id}/plan
POST   /v1/interviews/{session_id}/start
```

`snapshot:append-user-opinion` 要求 `Idempotency-Key` 请求头；同一次用户确认在超时或断线重试时复用该值，新的意见使用新值。其余准备接口通过当前资源与确定性覆盖语义恢复，不共用这个 header。

observe/import/append-user-opinion 与 selection/plan 写接口只在 `preparing` 接受。前一组改变 snapshot 后清空范围与 plan，selection 改变后删除 plan；这些失效操作与对应写入处于同一 PostgreSQL 事务，不能留下“新输入 + 旧 plan”的组合。

`snapshot:import` 可以同时携带用户刚为本 session 授权的可空 `source_handle`。Application Runtime 先向 Local Runtime 验证 handle 与 `session_id` 的绑定，再保存不透明引用；导入 Markdown 本身仍是 snapshot，授权目录只供赛后项目版答案定向取证，不能反向改写导入正文。

`selection` 请求：

```json
{
  "interview_direction": "core_flow_deep_dive",
  "selected_sections": [
    {"kind": "thread", "title": "User Query to Final Answer"}
  ]
}
```

保存选择时重新使用当前 snapshot 解析标题，拒绝不存在的引用。

列表接口按 owner 过滤并分页，只返回 session 状态、方向、结束原因和时间等摘要，不读取 snapshot、turn 正文或赛后产物大字段。

### 10.3 实时面试

```text
POST /v1/interviews/{session_id}/answers
POST /v1/interviews/{session_id}/decision:retry
POST /v1/interviews/{session_id}/snapshot-corrections:resolve
POST /v1/interviews/{session_id}/finish-early
POST /v1/interviews/{session_id}/force-exit:confirm
GET  /v1/interviews/{session_id}/events
```

回答请求：

```json
{
  "turn_no": 7,
  "answer": "用户原始回答"
}
```

首次写入回答要求 session 为 `interviewing`、当前 turn 尚无回答且 checkpoint 明确为 `awaiting='answer'`；随后执行 Graph，直到下一个 interrupt 或终态。`awaiting='snapshot_confirmation' | 'decision_retry'` 时拒绝新的回答并返回 `409 operation_in_progress`。相同 `turn_no + answer` 的重复请求是幂等例外：无论 Graph 已推进到哪个后续 interrupt，都只返回当前状态或既有结果，不重写回答、不重置预算，也不承担“重试当前步骤”；不同回答返回 `409 answer_conflict`。

只有界面已经收到当前决策处理失败状态时才调用 `decision:retry`。该命令要求 session 仍在 `interviewing`、checkpoint 明确为 `awaiting='decision_retry'`、当前没有等待回答的问题，并且当前 Stage 仍存在尚未发布的回答后决策或 Stage 首题决策；满足条件后才为同一逻辑决策开启一轮新的有界自动尝试。回答后重试不改写回答，Stage 首题重试在问题真正发布前不创建 turn。双击时由 session 执行锁合并或返回 `409 operation_in_progress`；若前一次重试已经发布下一题或关闭 Stage，则返回 `409 retry_not_available`。checkpoint 丢失时用上述 PostgreSQL 业务条件重建触发类型并恢复等价 awaiting 状态，不需要新增持久化失败字段。

更正确认请求：

```json
{
  "turn_no": 7,
  "decision": "confirm",
  "edited_text": "可空；确认原文时为空"
}
```

`decision` 为 `confirm | do_not_write`。该命令只在 `awaiting='snapshot_confirmation'` 时接受，否则返回 `409 operation_in_progress`。若编辑文字经过安全过滤发生替换，API 返回需要再次确认的最终文本，不能直接写入。

`force-exit:confirm` 只接收已经通过前端二次确认的明确命令；取消确认不调用 API。

### 10.4 反馈、结果与导出

```text
PUT /v1/interviews/{session_id}/turns/{turn_no}/feedback

GET /v1/interviews/{session_id}/report
GET /v1/interviews/{session_id}/report.md
GET /v1/interviews/{session_id}/full-qa
GET /v1/interviews/{session_id}/full-qa.md
GET /v1/interviews/{session_id}/snapshot.md
```

报告与完整问答导出由当前 PostgreSQL 数据确定性渲染；snapshot 导出直接返回业务库中的当前 Markdown 全文，不生成第二份格式或版本。服务端不把导出文件当作运行时事实；Web 使用浏览器保存到用户选定位置。

### 10.5 策展

```text
PUT    /v1/interviews/{session_id}/curation-grant
DELETE /v1/interviews/{session_id}/curation-grant

GET  /v1/admin/curation-items
POST /v1/admin/curation-items
POST /v1/admin/curation-items/{item_id}:add-to-question-bank
GET  /v1/admin/question-bank
```

管理员会话材料列表查询必须在 SQL 层 join `interview_sessions.curation_review=true AND status IN ('completed','aborted')`，不能先读取所有材料再在应用层过滤。题库列表只展示公共题目字段及 usage/upvote/downvote 累计，不反向读取私人 session 或反馈原因。

本版本的管理员写入流程只覆盖人工确认加入题库。软件与对话配置建议可以引用已授权材料，但不在运行时数据库中形成可直接发布的配置实体；实际变更继续通过版本控制、固定回归和人工审核完成。

### 10.6 事件流

`GET /events` 使用 SSE 传递状态变化，不作为业务事实来源。客户端连接或重连时先 GET session 当前视图，再订阅新事件。事件只包含用户本来可以从当前资源读取的信息：

```text
question_ready
snapshot_confirmation_required
stage_changed
post_processing_started
post_processing_progress
turn_processing_failed
session_completed
session_aborted
```

SSE 不持久化内容事件日志；错过事件时重新读取当前资源即可恢复 UI。

### 10.7 Runtime 内部接口

Local Runtime 上报模型调用 span 使用仅监听 loopback 的内部接口：

```text
POST /internal/v1/model-call-spans
```

请求必须通过 desktop-instance bearer token 鉴权，只接受 5.9 定义的无内容字段。该接口不对 Web 开放；上报失败只进入 Local Runtime 的有界内存缓冲，不能令已经成功的 Observer 或项目版答案任务失败。

## 11. Local Project Runtime 合同

### 11.1 Source Handle

Local Project Runtime 接收用户通过本地文件选择器确认的绝对目录，完成：

- canonical path 解析。
- symlink 逃逸检查。
- 排除规则与文件清单确认。
- 生成高熵随机 `source_handle`。
- 把 handle、所属 `session_id` 与真实路径绑定在本地授权 registry。

Application Runtime 和 PostgreSQL 只保存 handle。后续请求必须同时携带同一 `session_id`，Local Runtime 拒绝跨 session 复用 handle。registry 为 handle 设置本地过期时间，活跃 session 使用时续期；显式删除 session 时立即释放，释放通知丢失时也会由 TTL 自行失效。handle 失效时项目版答案自动退回 snapshot；用户要重新访问目录必须重新授权。

### 11.2 本地 API

```text
POST   /v1/sources:authorize
GET    /v1/sources/{source_handle}/inventory
POST   /v1/sources/{source_handle}:observe
POST   /v1/project-answer-tasks
DELETE /v1/sources/{source_handle}
```

所有携带 `source_handle` 的接口同时要求 `session_id`（GET/DELETE 使用 query 参数，POST 使用请求体或已鉴权内部合同），并由 registry 校验二者绑定关系；只知道 handle 不能跨 session 读取目录。

项目版答案请求：

```json
{
  "session_id": "UUID",
  "operation_id": "stable task key",
  "source_handle": "opaque",
  "snapshot": "已脱敏当前快照",
  "turns": [
    {"turn_no": 1, "question": "...", "answer": "..."}
  ]
}
```

响应必须是完整可解析 JSON：

```json
{
  "post_verification_append": "可空文本",
  "answers": [
    {"turn_no": 1, "project_answer": "..."}
  ]
}
```

Local Runtime 可以返回少于全部 turn 的合法答案项；不能返回不存在或重复的 `turn_no`。Application Runtime 仍负责最终 JSON Schema 校验、安全过滤和业务持久化。

所有触发 Local Runtime 模型调用的请求都显式携带 `session_id` 和稳定的 `operation_id`。前者只用于归属本次业务与无内容 trace，后者只用于本地短期任务合并；任何一方都不得通过解析另一字段恢复身份。

### 11.3 本地任务幂等

Local Runtime 在当前进程内以 `operation_id` 合并同时或重复到达的同一任务，并在短期 TTL 缓存内返回已有状态或结果，以减少重复目录读取和模型费用。首版不为这项成本优化引入本地持久化数据库；Local Runtime 重启后允许再次执行外部调用。

跨进程严格保证的是 Application Runtime 中的业务效果恰好一次：重复或迟到的本地结果仍由 PostgreSQL task 自然键、结果主键、snapshot 追加回执和条件发布决定是否采用。`operation_id` 不是新的业务事实或跨重启 exactly-once 承诺。

### 11.4 本机调用安全

- 两个 Runtime 启动时共享随机 desktop-instance bearer token。
- 只监听 loopback；拒绝非预期 Origin。
- Local Runtime 的文件工具始终接收 source registry 解析后的根目录，不接收模型生成的绝对路径。
- 读取工具执行 canonicalize 后再次验证目标仍在授权根目录内。
- 禁止写文件、执行项目代码、运行包管理器和访问未授权目录。
- 工具结果在进入云端模型前再次经过内容安全过滤和长度预算。

Web 在首次可能把已过滤材料发送给云端模型前明确展示供应商与数据边界说明；这是界面披露，不新增 `cloud_processing_accepted` 之类的 session 业务字段或版本化同意记录。

## 12. Content Safety

`packages/content_safety` 提供纯函数式接口：

```python
scan_and_redact(text, source_metadata) -> SafetyResult
validate_user_append(text) -> SafetyResult
```

`SafetyResult` 包含：

- 处理后的文本。
- 命中类型和位置；不包含敏感原值。
- 是否需要用户再次确认。
- 是否因长度、编码或基础安全策略拒绝。

同一规则集用于：

- 项目文件进入 snapshot 前。
- 导入 Markdown。
- 用户回答进入 RAG、Supervisor、compact 或赛后模型上下文前。
- 用户意见。
- 面试事实更正。
- 赛后事后核验。

日志只记录规则 ID、命中数量和处理结果，不记录原值或上下文。

`app.turns.answer` 保留用户实际提交的业务原文，供本人历史与导出使用；进入任何模型上下文前现场构造 `SanitizedText`，不再持久化一份 `sanitized_answer`。State 中的 `recent_turns`、compact、RAG query 和赛后 Agent 输入只使用这份过滤后的工作文本。这样不增加答案版本字段，也不会让原始回答进入云端模型或 trace。

## 13. 模型调用适配层

`packages/model_adapter` 是两个 Runtime 共用的纯传输层，不包含 Agent Prompt、项目工具、数据库 repository 或路径能力。Application Runtime 的 Supervisor/Planner/赛后调用器与 Local Runtime 的 Observer/项目版答案调用器都必须经由它发出物理模型请求，避免两边各自实现重试规则。

### 13.1 接口

```python
class ModelAdapter(Protocol):
    async def generate_structured(
        self,
        *,
        session_id: UUID | None,
        operation: str,
        messages: list[Message],
        output_schema: type[BaseModel],
        prompt_version: str,
        retry_policy: RetryPolicy,
    ) -> BaseModel: ...

    async def generate_tool_step(
        self,
        *,
        session_id: UUID,
        operation: str,
        messages: list[Message],
        tools: list[ToolSchema],
        final_output_schema: type[BaseModel],
        prompt_version: str,
        retry_policy: RetryPolicy,
    ) -> ToolCallBatch | BaseModel: ...
```

Observer 和项目版答案调用器负责自己的有界工具循环；adapter 只传输工具 Schema、返回工具请求或最终结构化结果，永远不执行文件工具，也不获得 `source_handle → path` 的解析能力。工具循环步数是配置上限，正常工具步骤不是故障重试；传输重试和格式修复仍共同消耗该次逻辑调用的尝试预算。

BGE-M3 embedding 与 Reranker 由 Retrieval Service 内的专用 client 调用；它们不得开启各自的隐藏重试层，RAG 的“最多 2 次”预算包住整次检索尝试。两类调用仍使用相同的无内容 TraceSink 合同。

对于生成式模型，只有共享 adapter 负责传输层重试。Graph 节点、SDK 默认重试和外层 service 不得各自再重试。若 SDK 无法关闭内部重试，必须把其尝试计入同一个总预算。

### 13.2 错误分类

自动重试：

- 连接失败、连接重置、读取超时。
- 408、429。
- 明确可重试的 5xx / provider overload。

不原样重试：

- 认证、权限和模型不存在。
- 非法参数。
- 安全拒绝。
- 已知上下文超限。

结构化输出无法通过 Schema 时，可以携带确定性错误做一次修复；修复消耗总尝试次数。上下文超限允许先执行一次确定性裁剪或 compact 后再尝试，仍失败则终止。

### 13.3 初始尝试预算

```text
RAG / Supervisor / Planner       最多 2 次
项目版答案 / 理想答案 / 评估 / 报告  最多 3 次
```

退避使用有上限的指数退避和随机抖动；服务端 `Retry-After` 优先，但不能超过整次操作截止时间。具体时间在实现后测量 P95/P99 再配置。

### 13.4 Trace

adapter 为每一次物理请求产生一条无内容 span。Application Runtime 的 TraceSink 直接写 `telemetry.model_calls`；Local Runtime 的 TraceSink 通过 desktop-instance token 认证的内部接口把同一无内容事件交给 Application Runtime 写入，不把 Prompt、模型正文或文件内容夹带在 trace 事件中。trace 上下文由调用任务显式提供 `session_id/operation_name`，Local Runtime 不从 `operation_id` 字符串反向解析业务身份。

逻辑操作 trace 关联所有尝试，但“一个 Supervisor 决策”与“一个物理模型请求”不混为一谈。trace 上报失败不能改变业务结果；Local Runtime 只做小型有界内存缓冲，不为 telemetry 另建本地持久化数据库。

## 14. 题库导入与混合检索

### 14.1 初始种子来源

首次建立唯一题库时，导入脚本只读取 `agent-interview/按考点/` 下 README 明确列出的 11 个主题文件：

- 不递归读取其他目录。
- 不读取 `README.md`。
- 不读取旧版、原始材料、公司分类或研究文件。
- 每个文件只把一级 `- ` 项识别为题目；缩进子项如英文翻译不生成第二道题。
- `ideal_answer` 初始为空，除非受控配置明确提供。
- 文件名到正式 `topic_path` 的映射由审核过的配置维护。

导入前后都校验题数和重复项，并产生不含题目正文的统计报告。

脚本按精确 `question` 唯一约束幂等插入种子题；遇到已存在文本时记录冲突并保留 PostgreSQL 当前行，不静默覆盖人工编辑。重复运行不得 truncate `bank.questions`，也不得删除管理员后来确认加入的题目。管理员加入的新题与种子题写入同一张表并生成相同检索索引；不为两者建立“正式/临时”两套题库或额外来源状态。

### 14.2 检索接口

```python
retrieve_for_turn(
    session_id: UUID,
    query_text: str,
    topic_path: str,
    limit: int = 3,
) -> list[QuestionCandidate]
```

`QuestionCandidate` 在应用内部只包含 `question_id` 与 `question`。Retrieval Service 把这组映射写入本轮 Interview State；Prompt 组装器只向 Supervisor 投影 `question` 字符串列表，ID 不进入模型输入或输出。

调用方不传“asked question”字段。Retrieval Service 根据 `session_id` 自行读取最近 3 个实际问题并执行短期冷却。

`AnsweredTurnTrigger` 的 `query_text` 只能是刚持久化用户回答的安全过滤工作文本，`StageEntryTrigger` 只能使用当前 Stage 的 `goal`；snapshot、动作菜单、完整历史、会话状态和已问问题正文都不能拼入检索 query。`topic_path` 只作为后续软权重先验。

### 14.3 在线链路

1. BGE-M3 生成 query embedding。
2. pgvector dense 召回。
3. 对 query 做与入库相同的技术词/中文分词，执行 PostgreSQL FTS。
4. 两路使用 RRF 合并。
5. 对 topic 做软权重：当前主题最高，父主题与相邻主题可通过，其他主题不硬过滤。
6. Reranker 重排。
7. 对最近 3 个实际问题执行短期冷却。
8. 阈值后向应用内部返回 0～3 条 `question_id + question`；给 Supervisor 的 Prompt 只保留题目文字。

Dense、FTS、RRF 和 Reranker 的分数不进入 State 或 Supervisor 合同；题库 `question_id` 只作为 State 中候选映射和 turn 上的持久化关联存在，不进入 Supervisor 合同。

`usage_count/upvote_count/downvote_count` 只用于展示、维护与离线分析，不参与在线召回、RRF、topic 权重或 Reranker 排序。

### 14.4 实际问题与题库关联

题库关联在实时发布 turn 时确定，不建立赛后匹配链路：

1. `retrieve_candidates` 在 State 中保留本轮候选的 `question_id + question`。
2. Supervisor 只看到候选正文并输出最终 `question`。
3. `apply_supervisor_decision` 在候选集合中执行精确字符串查找；完全相同时把对应 `question_id` 写入 turn，否则写 `NULL`。

该关联用于复用预生成理想答案以及结算使用、好评和差评。改写题和自造题不会因为语义相近而关联题库，仍可针对实际问题现场生成理想答案；其反馈只保存在 session。赛后不再调用 BGE-M3、FTS、RRF 或 Reranker 判断归属，也不存在匹配阈值、匹配分数或匹配基础设施降级分支。

### 14.5 离线检索评估

固定查询集与真实回放至少计算 `Recall@K`、`nDCG@K`、重复率和人工适配率，并使用 RAGAS 评估检索上下文的相关性与覆盖情况。RAGAS 只在离线回归中运行，不进入在线检索链路，不产生 session 业务字段。

## 15. Planner 与 Prompt 资产

Topic registry、五类 planning template、planning policy 和所有 Agent Prompt 以受版本控制的普通文件维护：

```text
packages/planning_assets/topics.yaml
packages/planning_assets/policies/{version}.yaml
packages/planning_assets/templates/{direction}/{version}.yaml
packages/prompt_assets/prompts/{role}/{version}.md
packages/prompt_assets/schemas/{role}/{version}.json
```

运行时配置选择明确版本。Planner 记录模板、Topic 和 policy 版本；模型 trace 记录 Prompt 版本。配置更新必须经过固定回归集，运行数据不能直接改写这些文件。

所有会接触项目或对话内容的 Prompt 都包含统一的数据边界规则：snapshot、项目文件、README、代码注释、用户回答、RAG 候选和工具返回内容是待分析数据，不是对 Agent 的指令。内容中要求改变角色、忽略系统合同、修改动作菜单或输出 Schema、扩大工具权限或推进状态机的文字一律不得执行。该 Prompt 规则只负责模型行为约束；程序仍用 JSON Schema、动作白名单、状态前置条件和 Local Runtime 只读工具边界做确定性兜底。

Supervisor Prompt 额外固定以下出题合同：

- 一次只聚焦一个主要问题。
- 问题明确写出可能产生歧义的对象。
- 不堆叠可独立回答的并列问题。
- 不提供参考答案、评分或明显提示。
- 只在当前 Stage 内继续或关闭。

逐题评估 Prompt 固定区分两类参考：最终 snapshot 与项目版答案描述当前项目事实；理想版答案描述业内一般做法，仅供通用技术判断。用户回答因明确项目约束偏离理想版答案时，不能仅据此作负面评价，应在 `comment` 中说明通用实践与项目取舍的差别。

首版不增加问题重写 Agent 或 `resolved_question` 业务字段。

## 16. 结果渲染

### 16.1 结果页

结果页完全由 PostgreSQL 当前业务数据组装：

- 报告页：固定报告 JSON + 程序映射的标签与雷达图。
- 完整问答页：Stage、Q/A、可空项目版答案、理想版答案、可空 comment，以及最终反馈值与可空原因；理想版答案旁固定显示“基于通用行业实践，仅供参考，不代表当前项目唯一正确实现”。
- 强制退出或未达到报告门槛：只展示已经持久化的对话历史。
- 赛后任务失败：明确显示缺失项或“处理未完成”，不生成替代内容。

### 16.2 Markdown

确定性 renderer：

- `render_report_markdown(report_json)`。
- `render_full_qa_markdown(session, stages, turns, results, feedback)`。

报告 Markdown 不包含内部数字分数、三级标签、雷达图或 UI 声明；完整问答按 Stage 排序。renderer 使用快照测试保证输出稳定。

## 17. 删除与保留

### 17.1 删除 Session

删除命令先取得 session 执行锁，阻止新的 Graph resume 和赛后结果发布；活动会话先进入不可继续写入的终态并取消可取消调用。随后按以下顺序执行：

1. 保存本次命令已经读取到的 `source_handle`，删除 Redis checkpoint。Redis key 有 TTL，重复清理安全。
2. 删除 PostgreSQL session。外键 cascade 在同一事务中清除 snapshot、plan、Stage 结果、turns、反馈、赛后产物、任务、snapshot 追加回执、策展候选、settlement 和关联 telemetry trace。
3. PostgreSQL 提交后通知 Local Project Runtime 释放已保存的 handle，并再执行一次幂等 Redis 清理，覆盖删除过程中迟到的 checkpoint 写入。本地释放通知为 best effort，由 handle TTL 收尾。

若步骤 1 的 Redis checkpoint 删除明确失败，在 PostgreSQL session 尚存在时返回可重试错误，不先销毁恢复清理所需的业务定位信息。Local handle 释放失败不阻塞业务数据删除：删除后 Application Runtime 已失去 handle，registry 中的孤立授权再由短 TTL 清除；真实路径始终只存在于本地 registry。

已经由用户导出到本地的 Markdown 不受影响。已经经过独立人工审核加入题库的题目不因源 session 删除而删除，但不得保留可反向读取私人会话的引用内容。

已经结算进题库的 usage/upvote/downvote 是题库级累计，不因删除原 session 反向扣减；原 turns、feedback 和 settlement 会随 session 删除，累计值不能用于反向读取某场私人会话。本版本不为删除操作建立计数冲销账本。

### 17.2 保留

- session 业务数据：直到 User 删除。
- active/post-processing checkpoint：直到进入 `completed/aborted`。
- trace：最多 30 天；session 删除时提前删除。
- source_handle：由本地授权 registry 管理，可失效；失效不删除 session。

## 18. 测试设计

### 18.1 单元测试

- Markdown Module/Thread 标题解析。
- snapshot 区块只增追加。
- plan 字段、范围引用、Topic、Stage 数和禁止字段校验。
- 准备期修改 snapshot 会清空范围与 plan，修改方向/范围会删除 plan；进入面试后准备写接口全部冲突。
- 相同 selection 的 PUT 重放不会删除随后已经生成的 plan。
- observe/import 的过滤后全文与当前值完全相同时不重复清空随后生成的范围或 plan；单独更换有效 source_handle 也不使 plan 失效。
- Supervisor JSON Schema 和三动作不变量。
- Stage 首次进入只允许 `continue + question`，且 `user_acts=[]`、`interviewer_message=null`，不能在没有首题时直接关闭 Stage。
- “一个主要问题”和模糊指代回归样本。
- report JSON 校验与 Markdown renderer。
- snapshot 导出与数据库当前全文逐字一致，不创建版本或导出记录。
- 题库一级 bullet 导入规则。
- RRF、topic 软权重和冷却。
- `QuestionCandidate` 在 State 中保留 ID 与正文，Supervisor Prompt 投影只包含正文。
- Supervisor 最终问题与本轮候选正文完全相同时解析出对应 `question_id`；任意改写或自造题解析为 `NULL`。
- 内容安全规则。
- 所有 Agent Prompt 都把 snapshot、项目文件、用户回答和工具结果视为数据而非指令。

### 18.2 PostgreSQL / Redis 集成测试

使用真实 PostgreSQL（含 pgvector）和 Redis，不用内存替代物验证关键语义：

- 同一个 snapshot append key 与相同 payload 重复执行只追加一次；同 key 不同 payload 返回冲突。
- 两次不同 `Idempotency-Key` 的用户意见都能追加；同一次请求重放不会把同一意见追加两遍。
- 数据库提交成功、checkpoint 更新前崩溃，恢复后只刷新 State。
- 首次回答只在 `awaiting='answer'` 时接受；快照确认或决策重试 interrupt 中的新回答返回 `operation_in_progress`。
- 同一个回答重复提交不调用模型也不创建第二题，即使 Graph 已进入后续 interrupt 也只返回当前状态；不同回答冲突。
- 快照更正确认只在 `awaiting='snapshot_confirmation'` 时接受，决策重试只在 `awaiting='decision_retry'` 时接受。
- 只有显式“重试当前决策”才能在失败后重新调用 Supervisor；它同时覆盖回答后决策和 Stage 首题决策，不改写回答、不提前创建 turn，双击不会并发启动两个决策。
- 重复调用 `start` 不创建两个首题；状态已经进入 `interviewing` 但首题尚未发布时由 recovery worker 接管，而不是把第二次 `start` 当重试。
- Stage 关闭不增加 turn，下一 Stage 首题才增加。
- 提前结束时尚未回答的当前 turn 参与题库使用结算并保留在完整历史，但不进入答案、评估或报告任务。
- 第 101 题不会创建。
- 反馈冻结后 PUT 返回 409。
- 反馈 PUT 与结束冻结并发时只有先取得 session 行锁的一方生效；settlement 读取不到冻结后的迟到反馈。
- session 列表只返回当前 User 的摘要，不加载 snapshot/turn/报告正文。
- 同一 session 并发结算题库统计只累计一次。
- 题库统计只累计 turns 上非空 `question_id`；相似但未原样采用的改写题不计数，也不复用预生成答案。
- settlement 已存在时，恢复流程直接进入答案分支，不重复累计；即使本场所有 `question_id` 都为空也适用。
- 结算事务未提交时计数与 settlement 一起回滚并允许重做；事务已提交但 checkpoint 未更新时从 settlement 重建，不重复累计。
- 终态 checkpoint 删除，业务数据仍可读取。
- 删除 session 级联清理会话 PG 数据、Redis 和 trace，但不反向扣减已经结算的题库累计。
- 已授权但仍在进行中的 session 不出现在管理员策展材料中；进入终态后才可读取。

### 18.3 Graph 恢复测试

- `interrupt(answer)` 前后重启。
- 回答已提交或 Stage 已关闭后进程崩溃，recovery worker 恢复尚欠的决策；重复 answer 请求本身仍不调用模型。
- 快照确认卡出现后重启。
- 用户确认追加后 PG 成功、Redis 失败。
- Supervisor 超时后恢复。
- Supervisor 自动尝试耗尽后进入 `decision_retry` interrupt；重复提交相同回答不重试，显式重试命令才恢复回答后决策或 Stage 首题决策。
- 关闭 Stage 后、生成下一 Stage 首题前重启。
- 正常路径中，答案 Agent 在 settlement 提交前不能启动；结算事务失败时 Graph 保持在该节点并按数据库幂等语义恢复。
- post-processing fan-out 中部分任务完成后重启。
- 项目版或理想版参考答案任务失败时仍启动对应逐题评估；只有评估失败才阻止完整报告。
- Redis checkpoint 丢失后按 20-turn 边界重建 compact、`compacted_through_turn_no` 与近期上下文。

### 18.4 跨 Runtime 合同测试

- Application Runtime 永远拿不到真实路径。
- 无效/过期 source_handle 正确降级。
- 一个 session 获得的 source_handle 不能被另一个 session 复用。
- 同一 Local Runtime 进程内，相同 operation_id 合并为一次任务；进程重启后即使再次执行，Application PostgreSQL 也只采用一次业务结果。
- symlink 不能逃出授权根目录。
- 工具结果先过滤再返回。
- Local Runtime 不提供写文件或执行命令能力。
- Observer 与项目版答案的物理模型请求都经过共享 Model Adapter，不在 Local Runtime 复制一套重试规则。
- Local trace 上报只包含无内容字段；上报失败不改变业务结果，也不落入本地持久化数据库。

### 18.5 模型回归

测试使用两层：

1. 确定性 fake adapter：覆盖状态机、重试、非法 JSON 和迟到结果。
2. 固定真实项目回放：评估 snapshot、plan、Supervisor、RAG、逐题评价和报告质量。

真实模型回放不把输入输出写入普通 trace；固定评估数据必须来自测试资产或明确授权材料。

Prompt 注入回归至少包含恶意 README、Markdown、代码注释、用户回答和工具返回内容，尝试要求 Agent 忽略角色、修改动作菜单或 Schema、扩大工具权限以及只问简单问题；这些文字只能作为数据被分析，不能改变 Agent 行为。逐题评估回归同时覆盖“项目约束合理偏离通用理想答案”的样本，确保 `comment` 不把差异直接判为错误。

检索回归同时计算 `Recall@K`、`nDCG@K`、重复率、人工适配率和 RAGAS 相关性/覆盖指标；RAGAS 不出现在在线测试路径中。

### 18.6 故障注入矩阵

至少覆盖：

| 故障点 | 预期 |
| --- | --- |
| RAG 超时 | 0 候选，Supervisor 继续 |
| 题库结算事务失败 | settlement 与全部计数一起回滚；恢复后按 turns 上既有 `question_id` 重做，答案 Agent 尚未启动 |
| Supervisor 429 / 5xx | adapter 有界重试 |
| Supervisor 结果迟到 | 条件发布失败，不推进 |
| snapshot 写入结果未知 | 查询 snapshot append receipt，未确认前阻塞 |
| Local Runtime 不可用 | 项目版答案退回 snapshot |
| 项目版顶层 JSON 截断 | 不采用原始片段 |
| 单题理想答案失败 | 参考字段保持为空；对应评估仍使用最终 snapshot、Q/A 和已有参考继续 |
| 单题评估失败 | 保留其他结果，报告不伪造 |
| 报告失败 | 完整问答成功项仍可查看 |
| 强制退出与回答竞争 | 已确认强制退出获胜，迟到结果丢弃 |
| 强制退出与提前完成竞争 | 确认强退事务取得锁后，尚未提交的提前完成失败；已先完成的终态不被追溯改写 |

## 19. 实现顺序

以下阶段都在同一套正式模块和接口上推进，不建立随后丢弃的内存版：

### 19.1 工程与基础设施

- 建立 monorepo 目录、Python/TypeScript 工具链和配置加载。
- PostgreSQL schemas、Alembic 和 Redis checkpointer。
- Pydantic 领域合同、共享 Model Adapter、统一错误和无内容 trace。
- 真实 PostgreSQL/Redis 集成测试夹具。

### 19.2 Snapshot 与 Local Runtime

- source authorization、inventory 和只读工具边界。
- content safety 共用包。
- Observer、Markdown 导入、用户意见追加和范围解析。
- session 创建、读取、删除和授权。

### 19.3 题库、RAG 与 Planner

- 11 文件白名单导入。
- embedding、FTS、RRF、reranker，以及含 RAGAS 的离线检索评估。
- Topic / template / policy 资产。
- plan 生成、修复、校验和持久化。

### 19.4 实时面试

- Interview Graph、interrupt/resume 和 Supervisor Adapter。
- answer 幂等、Stage 推进、快照确认卡和 compact。
- 提前完成、强制退出、安全上限和反馈冻结。
- 用户 Web 面试界面与 SSE。

### 19.5 赛后处理

- turn 上题库关联、原子统计结算与 settlement 恢复。
- project answer 跨 Runtime 任务。
- ideal answer fan-out、evaluation fan-out 和 report join。
- 结果页、两个 Markdown renderer 和失败展示。

### 19.6 管理与硬化

- curation grant、管理员筛选和人工入库。
- 删除与保留任务。
- 固定项目回归、故障注入、成本与时延测量。
- 根据 P95/P99 调整模型截止时间、并发度和检索阈值。

## 20. 开始编码前的完成标准

实现设计进入编码前只需确认以下工程资产可以建立，不再增加产品概念：

- 数据库迁移能创建本文件定义的核心表和约束。
- Pydantic 合同能表达 plan、Supervisor、项目版答案和报告输出。
- Interview Graph 节点能映射到明确 service 方法。
- 两个 Runtime 的 OpenAPI 合同不传递真实项目路径。
- 关键幂等窗口各有一条真实数据库集成测试设计。
- 题库 importer 只读取明确的 11 个文件。
- 所有实测参数都通过配置提供，不成为业务数据字段。

满足这些条件后，可以直接从 19.1 开始建立正式工程骨架。
