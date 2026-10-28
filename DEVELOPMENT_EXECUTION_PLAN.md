# Project Interview Lab 今夜开发施工项目书

> 目标：从空代码仓库施工出明天可以提交和现场演示的产品版本。  
> 上游产品合同：[`PRODUCT_DEVELOPMENT.md`](PRODUCT_DEVELOPMENT.md)  
> 工程合同：[`IMPLEMENTATION_DESIGN.md`](IMPLEMENTATION_DESIGN.md)  
> 故障场景库：[`tests/fault_windows/README.md`](tests/fault_windows/README.md)  
> 本文只决定施工顺序、每道验收门、实现校验和本轮边界；如有冲突，以上游文档为准。

> **核心施工原则：功能不减，机制不增。** 已确定的产品行为必须完整实现；实现它们时，只采用能够证明必要的最小机制，不把一次性交付扩建成通用平台。

## 1. 今夜交付结果

明天打开产品后，必须能用一场真实 session 连续演示：

1. 创建 session。
2. 授权一个本地项目目录并生成 snapshot；Local Runtime 不可用时也能导入已有 Markdown 完成同一路径。
3. 审阅 snapshot，解析 Module/Thread，选择方向和范围。
4. 生成不少于 5 个 Stage 的线性计划。
5. 开始面试，发布首题；回答后由 Supervisor 继续追问或关闭 Stage。
6. 刷新浏览器或重启 Application Runtime 后，当前问题和已有问答仍可恢复。
7. 提前完成或正常结束后进入赛后处理，显示完整问答、逐题反馈和报告；部分参考答案失败时明确展示缺失，不伪造成功。
8. 导出当前 snapshot、完整问答 Markdown 和报告 Markdown。
9. 能展示至少一个真实工程保证：重复提交同一回答不会生成第二题，或 turn 已提交但 SSE 丢失时刷新仍能读到该题。
10. 对题目提交好评/差评；进入终态后反馈冻结并正确结算题库统计。
11. Supervisor 提出项目事实更正时显示可编辑确认卡，确认或拒绝后继续同一个决策，不发生第二次 Supervisor 调用。
12. User 授权一场终态 session 进入策展池，Administrator 编辑并人工确认加入唯一题库；撤销授权后私人材料不再可读。

这条链路必须使用正式 PostgreSQL 业务表、Redis checkpoint、两个 FastAPI Runtime 和正式 Web 页面。允许模型和检索外部依赖在测试中换成受控 adapter，不允许把业务事实临时放在进程内字典里冒充完成。

正常完成、提前完成、确认强退、安全上限、删除 session 和断线/重启恢复是同一交付范围内的不同验收路径，不要求塞进同一次现场演示，但都必须实现和验证。

## 2. 施工范围总则

`PRODUCT_DEVELOPMENT.md` 和 `IMPLEMENTATION_DESIGN.md` 已经明确写入的产品行为、数据合同、恢复语义、安全要求和测试要求，默认全部属于本次施工范围。文档中的“首版”“Phase 0/1”“MVP”标签不在本文中被解释为可以删功能；只有上游明确标为后续、扩展或非目标的内容才不实现。

完整范围不等于最大化机制数量。本文要求实现全部既定能力，但不要求为每项能力各建一套抽象、状态机、持久化副本或扩展框架。一个业务不变量只保留一套权威实现；能由数据库约束、短事务、条件写入或现有 module 内部逻辑解决的问题，不升级为新的平台能力。

### 2.1 必须完成

- 正式 monorepo 骨架、依赖锁定、环境变量示例和可重复启动说明。
- PostgreSQL/Alembic 核心 schema、Redis checkpointer、开发身份数据。
- 两个 Runtime 的健康检查、desktop-instance token 和 `source_handle` 隔离。
- snapshot 导入、目录观察、内容过滤、范围解析、选择和计划生成。
- 11 个白名单题库文件的幂等导入，以及在线检索的正式 interface。
- Interview Graph 的首题、回答、Stage 推进、当前视图、显式失败和恢复。
- `user_acts`、可选 `interviewer_message`、快照事实更正确认、decision retry 和每 20 个已回答 turn 的累计 compact。
- turn 发布时的精确 `question_id` 关联；不匹配时写 `NULL`，且不能阻塞提问。
- 正常完成、提前完成、确认强退、安全上限、反馈冻结和全部竞争规则。
- 题库结算、项目版答案、理想版答案、逐题评估、事后核验和报告的完整依赖链。
- curation grant、管理员筛选、编辑审核、人工入库与撤销授权竞争。
- session 删除、checkpoint/trace/local handle 清理和数据保留规则。
- 用户与管理员 Web、SSE 重读策略、结果页、雷达图和三个导出入口。
- 无内容 trace、固定回归、检索评估以及测试设计要求的自动化覆盖。

### 2.2 主链路通过后施工的必做内容

- 快照事实更正确认卡的完整编辑体验。
- 20-turn compact 的真实长对话回放、checkpoint 丢失重建和边界测试。
- Administrator 策展界面的筛选、编辑、隐私处理、查重和人工入库。
- 强制退出的全部竞争窗口、删除清理、30 天 trace 清理任务。
- 八维雷达图、三级标签、固定评分说明、空状态、错误状态和必要的响应式布局。
- 全部故障窗口自动化、RAGAS 离线评估和 P95/P99 参数调优。

这里的“主链路通过后”只表示依赖顺序，不表示可选、锦上添花或有时间才做。任何未完成项都必须如实保留为施工未完成，不能通过改名为扩展功能来收缩范围。

### 2.3 上游明确排除或后续扩展的内容

- 通用 `operation_receipts`、全局 `runtime_jobs` 调度器、execution epoch/fence。
- Celery、Kafka 或新的消息队列。
- 持久化 SSE 事件日志、页面已展示状态或第二份业务缓存。
- 配置发布平台、Prompt 在线编辑器、自动配置提案状态机。
- 赛后相似度匹配或语义补绑 `question_id`。
- snapshot 版本链、跨 session 长期记忆、内容型 trace。
- 为尚不存在的第二个生产实现预建抽象层。
- 语音、GitHub/GitLab/Issue/PR 接入、跨轮训练闭环、教师工作台和用户手动赛后重跑。

## 3. 施工纪律

### 3.1 纵向切片优先

每个 Gate 必须形成从公开 HTTP interface 到可观察结果的完整切片。不要先写完所有 repository、再写所有 Graph、最后才第一次联调 Web。

每个 Gate 的顺序固定为：

1. 固定 interface 和错误合同。
2. 写最小失败测试或验收脚本。
3. 实现正式业务路径。
4. 通过该 Gate 的自动化校验。
5. 从 Web 或公开 HTTP 手动走一遍。
6. 才进入下一个 Gate。

### 3.2 Module 必须有深度

- Router 只做身份解析、请求 Schema 和调用业务 module，不拼 SQL、不运行 Graph 节点。
- 业务 module 持有权限、状态前置条件、事务顺序和错误转换。
- Repository 只持久化领域值，不调用模型、Redis 或另一个 Runtime。
- Graph 只编排业务 module，不复制事务规则。
- Web 只消费生成的 OpenAPI client 和当前资源，不在浏览器重建后端状态机。
- 测试从同一个公开 seam 驱动行为；只有约束、原子性、清理和泄漏检查允许直接查看存储。

### 3.3 不跨外部调用持有数据库事务

模型、embedding、reranker 和 Local Runtime 调用统一采用：

```text
短事务读取并验证触发事实
  → 关闭事务
  → 外部调用
  → Schema / 安全校验
  → 新短事务重新检查条件并发布
```

迟到结果只能被条件发布拒绝，不能靠 Redis 锁保证正确性。Redis 执行锁只减少重复工作。

### 3.4 PostgreSQL 是唯一业务事实

- PostgreSQL：session、snapshot、plan、turn、Stage result、反馈、赛后产物、题库和结算。
- Redis：Graph 执行现场、interrupt、compact 和尚未发布的临时候选。
- SSE：可丢失通知。
- Web 状态：当前资源投影。
- Trace：无正文调用元数据。

当这些来源不一致时，恢复逻辑以 PostgreSQL 为准刷新其余投影。

### 3.5 防过度实现审查门

任何新增的表、持久化字段、工作流状态、后台循环、公共 interface、adapter、配置项或基础设施，在编码前必须用一句话回答：

> 哪一条当前产品/工程合同无法由既有机制满足，因此必须新增这个机制？

答不出具体合同和失败窗口，就不新增。即使能回答，也继续检查：

1. **它是业务事实还是投影？** 投影应从现有事实重建，不保存第二份权威数据。
2. **数据库能否直接表达？** 唯一性、对应关系、状态组合和最多一次业务效果优先使用 PK、FK、CHECK、唯一索引、事务和条件写入。
3. **现有 module 能否内部消化？** 只有复杂度会扩散到多个调用方时才新增 module；原样转发参数的薄层不创建。
4. **seam 是否真实存在？** 只有生产/测试或两个真实实现确实需要替换时才定义 adapter；不要为“以后可能更换”预建 port。
5. **失败语义是否已经有落点？** 优先复用 session 行锁、自然业务键、现有 snapshot 回执、post task 和 settlement，不抽象成通用工作流框架。
6. **配置是否需要运行时变化？** 只有需要实测调参的模型、截止时间、重试、并发和检索参数进入配置；固定业务规则不做成万能开关。
7. **性能问题是否已经测量？** 没有 P95/P99、容量或成本证据，不增加缓存层、批处理平台、预计算账本或专用队列。
8. **删除它会损害当前行为吗？** 如果删除后当前验收仍全部通过，这个实现就是非必要实现，应当删除或不写。

施工中的默认选择：

- 一个资源只有一个业务事实来源，其余全部是可恢复 projection。
- 一个重试预算、一个事务发布点、一个状态推进者；不在多层叠加同义机制。
- 测试故障注入使用内部 seam，不把测试 hook 暴露成生产 interface 或业务状态。
- 当前只有一个调用方的简单逻辑先留在深 module 内部，不拆成目录层级和 pass-through 类群。
- 不为兼容尚不存在的旧版本增加 version、migration bridge 或双写。
- 不因已经使用 Redis 就顺便加入队列、缓存、通知存储或分布式锁语义。
- 不因已经有管理员界面就顺便建设通用配置中心、审批引擎或工作流设计器。
- 不用“可扩展”作为复杂度的单独理由；扩展点必须对应上游已经确定的变化方向或当前确有的第二个实现。

每个 Gate 完成时做一次反向检查：除了满足该 Gate 合同的代码，是否还出现了没有当前调用方、没有当前数据来源、没有当前验收或没有当前失败窗口的实现？如果有，先收掉赘余复杂度，再进入下一 Gate。

## 4. Gate 0：工程可启动

### 4.1 施工内容

- [ ] 建立 `apps/web`、`services/application`、`services/local_project`、`packages/*`、`scripts` 和正式测试目录。
- [ ] 固定 Python 与 Node 包管理方式并提交 lockfile；不在同一语言混用两套工具。
- [ ] 建立 PostgreSQL + pgvector、Redis 的本地依赖启动方式。
- [ ] 两个 Runtime 都提供 `/health`，Web 有最小 shell。
- [ ] 提供 `.env.example`，只列变量名和安全示例，不提交真实密钥。
- [ ] 配置项只包含连接、模型、超时、尝试预算、并发、CORS、desktop token 和检索参数。
- [ ] 建立结构化日志；默认不记录请求正文、Prompt、模型输出或 snapshot。
- [ ] 建立开发身份：至少一个 User 和一个 Administrator。身份解析可以是明确标记为 development-only 的本地实现，owner/role 检查不能省略。

### 4.2 验收门

- 全新 checkout 按 README 可以启动数据库、Redis、两个 Runtime 和 Web。
- 两个 `/health` 能区分“进程可用”和“依赖不可用”。
- 未配置模型密钥时启动成功，但模型相关命令返回明确的 `dependency_unavailable`，不能在 import 阶段崩溃。
- 配置或日志中搜索不到真实密钥、Prompt 和测试项目正文。

### 4.3 禁止继续的条件

迁移命令、测试命令或启动步骤只能在某位开发者机器上凭隐含环境工作时，不进入 Gate 1。

## 5. Gate 1：合同、迁移与存储不变量

### 5.1 先固定的合同

按 `IMPLEMENTATION_DESIGN.md` 建立：

- Session 状态、结束原因、方向、Stage action、反馈和赛后 task 枚举。
- `SectionRef`、`InterviewStage`、`InterviewPlan`。
- Supervisor、项目版答案、理想版答案、逐题评估和报告 Pydantic 输出。
- 通用错误 envelope 和稳定 error code。
- Web 使用的 `SessionView`、`InterviewView`、`ResultView`；不直接暴露 ORM model。
- 共享 Model Adapter 的 structured/tool-step interface、统一 RetryPolicy 和无内容 TraceSink；Prompt、工具执行、路径解析和 repository 不进入 adapter。
- 版本化 Prompt、JSON Schema、Topic、五类 planning template 与 planning policy 资产及其 manifest。

### 5.2 迁移

- [ ] 创建 `app`、`bank`、`telemetry` schema。
- [ ] 一次建立实现设计定义的核心表、外键、检查约束和索引。
- [ ] `turns` 包含 `(session_id, turn_no)` 主键、1～100 上限、单 session 至多一个未回答 turn、`answer/answered_at` 同空同非空。
- [ ] `stage_results`、`session_settlements`、`snapshot_append_operations` 和 `post_tasks` 使用正式自然键。
- [ ] session 子表删除关系和 trace 级联关系明确，不依赖应用层手工猜测。
- [ ] 大文本列不进入列表查询 projection。

### 5.3 Repository 与事务 seam

只实现业务 module 当前需要的 repository 方法。不要为每张表生成一套通用 CRUD interface。

事务由业务 module 开启，repository 接收同一 transaction/session。首批必须有：

- session 创建、owner 读取、条件状态变更；
- 当前 snapshot 读取/覆盖/幂等追加；
- plan 保存和读取；
- 当前 turn 读取、首次回答和条件发布下一题；
- Stage result 条件插入；
- post task/产物同事务发布；
- question settlement 原子提交。

### 5.4 验收门

- migration upgrade 从空库成功，downgrade/upgrade 至少走通一次。
- 数据库直接拒绝非法 session 状态组合、turn 101、第二个未回答 turn和错配的 `answer/answered_at`。
- 同一自然键重复发布不会形成两条业务记录。
- Pydantic 合同能生成 OpenAPI，Web client 可以生成或编译。

## 6. Gate 2：准备流程纵向链路

### 6.1 最短可用链路

```text
POST session
  → authorize source / import Markdown
  → append zero or more user opinions
  → persist current snapshot
  → parse Module/Thread headings
  → PUT selection
  → generate and validate plan
  → GET current session
```

先跑通 Markdown import，再把 Local Runtime observe 接到同一个 `SnapshotService` interface。两条入口在安全过滤之后必须产生相同的 snapshot 领域值和失效规则。

### 6.2 Local Runtime 边界

- [ ] 真实路径只存在于本地 registry。
- [ ] `source_handle` 使用高熵随机值并绑定 `session_id`。
- [ ] Application Runtime 和 PostgreSQL 只看见 opaque handle。
- [ ] inventory 应用排除规则、文件数和长度预算。
- [ ] read-only 工具不提供写文件、执行命令、包管理器或任意绝对路径读取。
- [ ] inventory 不是读取授权；每次实际打开文件重新 canonicalize 并验证根目录。
- [ ] symlink 在 inventory 后被替换并逃逸根目录时，读取受控失败。
- [ ] Local Runtime 返回的文本先安全过滤，再跨 Runtime 或进入模型。

### 6.3 Observer 与 Repository Map

- [ ] 确定性 inventory 记录相对路径、类型、大小、编码、跳过原因和解析错误；安全硬排除不能被用户规则覆盖。
- [ ] 支持常见代码、Markdown、纯文本、JSON、YAML、TOML 和 `.gitignore`；跳过二进制、`.env`、私钥、凭据目录、嵌套仓库和未选择子模块。
- [ ] 在任何模型调用前完成敏感文件排除和疑似凭据替换；UI 只展示命中文件、行号和类型，不回显原值。
- [ ] 使用 Tree-sitter/语言 AST 或保守文本降级生成受预算约束的 Repository Map：目录、语言/框架、符号签名、位置和可确认关系，不默认保存完整实现。
- [ ] Observer 先读 Repository Map，再通过 `list_tree`、`search_text`、`get_file_symbols`、`find_symbol_references`、`read_file_range` 迭代取证。
- [ ] 工具调用路径、单文件大小、候选文件数、累计文本、token、步数和总耗时都有配置上限；达到上限时明确标记部分分析和未覆盖范围。
- [ ] 每个写入 snapshot 的 Module/Thread 至少有实际读取材料支持；推断和未知在正文中明确区分，引用路径仍需位于授权根目录。
- [ ] Observer 停止条件是主要结构已确认、新一轮没有改变结构的信息或预算到达；不能静默截断后宣称分析完整。
- [ ] 输出前复验 Modules/Threads 结构、重复标题、引用路径和敏感规则；Repository Map 和临时工作清单不成为第二份业务快照。

### 6.4 Snapshot 与范围校验

- 导入、observe、用户意见和以后事实更正都经过同一 `content_safety` module。
- 用户原始 Markdown 只有在过滤和长度检查通过后才写业务库。
- 只有 `## Modules / ### title` 与 `## Threads / ### title` 生成范围项；正文和更深标题不生成。
- 只解析出一类时正常展示该类；两类都为空时先要求用户明确确认，再以空 selection 和完整 Markdown 进入 Planner，不创建虚假的“整份文档”范围项。
- 保存 selection 时必须重新解析当前 snapshot，拒绝陈旧或不存在的标题。
- snapshot 内容确实变化时，在同一事务清空 selection 和 plan；相同内容重放不失效后来生成的 plan。
- 相同 selection 重放不删除已有 plan；规范化后的方向或范围变化才删除。
- 面试开始后拒绝准备期写接口。

### 6.5 Planner 发布条件

Planner 输出必须同时通过 JSON Schema/Pydantic 和确定性校验：

- 程序按五种面试方向选择审核过的 template/policy，把完整 snapshot、方向、选择范围和完整 Topic registry 交给一次结构化 Planner 调用；不再额外调用模型检索模板；
- Stage 数在 5 与配置上限之间；
- Stage ID 在 plan 内唯一；
- `topic_path` 存在于 registry；
- `section_refs` 全部属于当前 selection；
- 每个已选范围至少被一个 Stage 引用，未选择范围不能伪装成用户已选范围；
- 不含固定问题、分支边或运行时状态字段；
- 保存 plan 时记录 template、topic registry 和 policy 版本。

首次输出不合法时，只把确定性错误列表交给同一 Planner 做一次有界修复；模型调用失败或修复后仍不合法时，不保存半个 plan，不使用未经审核的通用计划兜底，返回明确错误并保留 preparing 状态。

### 6.6 验收门

- 用固定 Markdown 完成“创建 → 导入 → 范围 → 选择 → plan”。
- 相同导入和相同选择各重放一次，plan 不被意外删除。
- 非法标题选择、少于 5 个 Stage、未知 topic、Prompt 注入式 Markdown 都被确定性规则挡住。
- 授权目录 A 的 handle 不能被 session B 使用；Application Runtime 的日志和数据库中没有真实路径。
- 用文档完善、只有代码和大型/部分分析三个 fixture 验证 Repository Map、迭代取证、预算停止和证据引用。

## 7. Gate 3：题库、检索与首题

### 7.1 题库导入

- [ ] importer 只读取 `agent-interview/按考点/README.md` 明确列出的 11 个主题文件。
- [ ] 只把一级 `- ` 项识别为问题，不递归旧版、原始材料或公司分类目录。
- [ ] 按精确 `question` 幂等插入；重复执行不 truncate、不覆盖管理员题目。
- [ ] 生成 embedding 与 lexical document，并输出不含题目正文的数量/冲突统计。

### 7.2 Retrieval Module

对 Graph 只暴露一个小 interface：

```python
retrieve(stage, snapshot, recent_questions, limit=3) -> list[QuestionCandidate]
```

module 内部完成 dense、FTS、RRF、topic 软权重、reranker 和最近三题冷却。分数不离开 module；Supervisor projection 只包含题目正文。

外部 embedding/reranker 使用正式 client adapter 和受控测试 adapter。这是实际存在的生产/测试 seam，不再给 dense、RRF、topic weighting 各包一层无价值 interface。

### 7.3 首题发布

`start` 只接受：

- session 为 `preparing`；
- 当前 snapshot 存在；
- 方向和 selection 与当前 snapshot 相容；
- 当前 plan 存在并重新通过校验。

进入 `interviewing` 后，以 `StageEntryTrigger` 运行：

```text
load current PG facts
  → retrieve 0..3 candidates
  → call Supervisor
  → validate Stage-entry action
  → conditional publish turn 1
  → checkpoint awaiting=answer
  → notify SSE
```

Stage 首题只允许 `continue + one non-empty question`，`user_acts=[]`、`interviewer_message=null`。RAG 失败降级为 0 候选，不能单独令 session 失败。

### 7.4 `question_id` 边界

- State 内保留本次候选的 `{question_id, question}`。
- Supervisor 只看正文。
- 发布前只在本次候选集合做精确字符串查找。
- 完全相同则写对应 ID；改写、自造、大小写或标点不同都写 `NULL`。
- `NULL` 不影响 turn 发布、回答、现场理想答案或报告。
- 禁止赛后重新检索、相似度补绑或让 Supervisor 返回 ID。

### 7.5 验收门

- importer 连续运行两次，题数和唯一性不变。
- 受控检索返回题目 T 时，Supervisor 原样采用 T 会写 ID；改写 T 会写 `NULL`。
- Retrieval 超时仍能由 Supervisor 发布一个问题。
- 连续两次调用 `start` 最多存在一个首题。
- turn 的 PostgreSQL 提交早于 SSE；丢弃 SSE 后，GET 当前视图仍返回首题。

## 8. Gate 4：实时面试闭环

### 8.1 回答链路

```text
POST answer
  → 请求 Schema / owner / 长度检查
  → 安全过滤出仅供模型使用的工作文本
  → session execution lock
  → verify awaiting=answer + current turn
  → persist original answer
  → resume Graph
  → retrieve + Supervisor
  → conditional publish next turn or Stage result
  → return current InterviewView
```

原始回答只保存在 owner 的业务历史；checkpoint、RAG query、compact 和模型上下文只接收过滤后的工作文本。

### 8.2 回答幂等与冲突

- 首次回答只接受当前未回答 turn。
- 相同 `turn_no + answer` 重放只返回当前状态，不重写、不重置尝试预算、不再次调用模型。
- 相同 turn 的不同回答返回 `409 answer_conflict`。
- `snapshot_confirmation` 或 `decision_retry` interrupt 中的新回答返回 `409 operation_in_progress`。
- 新题或 Stage result 的发布事务重新检查 session、Stage 和触发 turn；迟到模型结果不能发布第二份。

### 8.3 Supervisor 输出与上下文隔离

- 上下文只含系统 Prompt、完整 snapshot、当前 Stage、三动作菜单、0～3 条候选和过滤后的历史对话；不含源文件、题库 ID、理想/项目版答案、评分或完整 Topic 树。
- `user_acts` 是多标签数组，至少支持 `answer`、`ask_interviewer`、`correct_project_fact`、`decline_current_line`；不能退化为互斥单意图字段。
- `ask_interviewer.question_kind` 区分题意澄清、流程问题和索取答案/即时反馈；`interviewer_message` 可以回应，但不能包含新的正式面试问题。
- `continue` 必须输出一个非空、单一主要判断点且指代清楚的问题；`complete/unresolved` 的 `question` 必须为 `null`。
- 换种说法仍创建一个真实的新 turn 并保留历史；拒绝当前讨论由 Supervisor 判断 `continue` 或 `unresolved`，不增加隐藏 Skip 事件。
- Supervisor 不查代码、不核验事实、不评分、不决定整场结束，也不输出 `propose_complete`。
- JSON Schema、动作白名单、长度和确定性不变量由程序校验；礼貌、自包含、单问题和信息增益由 Prompt、固定回归和人工评审验证，不增加第二个逐轮监督模型。

### 8.4 Stage 推进

- `continue` 发布且只发布下一 turn。
- `complete/unresolved` 写 Stage result，不创建 turn。
- 若仍有 Stage，关闭事务提交后才为下一 Stage 发起新的首题操作。
- 最后 Stage 关闭后冻结反馈并进入 `post_processing`。
- 创建 turn 101 前执行安全停止，不能先插入再回滚。

### 8.5 SSE 与当前视图

- Web 首次加载和每次重连先 GET 当前视图，再订阅 SSE。
- SSE 只触发“重新读取什么”，不携带唯一业务事实。
- 旧事件到达时，Web 以 GET 返回的 status/turn 覆盖本地状态，不能回退到旧页面。
- 不为 SSE 做持久化、重放游标或 exactly-once。

### 8.6 自动失败与显式重试

- 只有共享 Model Adapter 负责自动传输重试和一次结构修复，并共同消耗预算。
- RAG、Supervisor、Planner 初始总尝试预算最多 2 次；项目版答案、理想答案、评估、报告最多 3 次。SDK 隐式重试必须关闭或计入同一预算。
- 连接失败、超时、408、429 和明确可重试 5xx 才自动重试；鉴权、权限、模型不存在、非法参数、安全拒绝和确定性上下文超限不原样重试。
- 退避遵守有上限的指数退避、随机抖动和受总 deadline 限制的 `Retry-After`；具体秒数由 P95/P99 实测配置。
- 预算耗尽后 checkpoint 进入 `decision_retry`，不制造占位问题。
- 只有显式 `decision:retry` 可以开启新预算；重复 answer 不能暗中重试。
- checkpoint 丢失时，从 PostgreSQL 判断究竟欠首题、回答后决策还是下一 Stage 首题。

### 8.7 快照事实更正确认

- Supervisor 输出含 `correct_project_fact` 时，先过滤候选并进入 `snapshot_confirmation` interrupt，不能提前发布问题或 Stage result。
- 界面显示可编辑候选；`confirm` 或 `do_not_write` 只在该 interrupt 中接受。
- 用户编辑后的文字若再次被安全过滤改变，必须展示最终文字并再次确认。
- 确认追加使用 `session_id + turn_no + snapshot_correction` 稳定操作键，与 snapshot 更新同事务。
- 追加成功后以 PostgreSQL 返回的当前全文刷新 State，再发布原本已经生成的同一个决策。
- 确认和拒绝都不再调用 Supervisor；checkpoint 丢失时允许丢失未确认候选，并按文档重新生成逻辑决策。

### 8.8 Compact 与上下文恢复

- 每满 20 个已回答 turn 才生成一层新的累计 compact。
- 输入是 previous compact 加恰好下一批 20 个已回答 turn；Stage close、确认卡和反馈都不是伪 turn。
- `compacted_through_turn_no` 与 compact 同 checkpoint 写入；失败保留旧 compact 和旧游标。
- recent turns 从游标下一题开始，不能与 compact 重复或遗漏。
- Redis checkpoint 全丢时，从 PostgreSQL 原始 turns 按相同 20-turn 边界从零重建。
- compact 只使用过滤后的 Q/A，不含 `question_id`、检索分数、参考答案或用户反馈。

### 8.9 Worker 与进程恢复

- Application Runtime 内的 worker 扫描欠 Supervisor 决策的 interviewing session、post-processing session，以及终态未结算 session。
- worker 不自动越过 `answer`、`snapshot_confirmation` 或 `decision_retry` interrupt。
- 多 worker 使用 session execution lock 与 `FOR UPDATE SKIP LOCKED` 减少重复领取；业务正确性仍由 PostgreSQL 条件发布保证。
- 进程停止点至少覆盖回答提交后、Stage 关闭后、模型返回后和 checkpoint 写入前后。
- 恢复只补欠下的业务效果，不把一次明确失败变成无限自动重试。

### 8.10 验收门

- 完成至少两个 Stage 的真实对话：一个 `continue`，一个 Stage close。
- 同一回答并发或重放不会创建第二题，也不会增加模型调用次数。
- 回答已经提交、决策未发布时重启进程，worker 能补完一个决策。
- Stage close 后重启，恢复只生成下一 Stage 首题，不重新关闭旧 Stage。
- SSE 全丢时刷新页面仍显示正确当前问题。
- 快照更正确认和拒绝各走一次，Supervisor 物理调用次数都不增加。
- 构造超过 40 个回答 turn，验证两次累计 compact 和 Redis 全丢后的等价重建。

## 9. Gate 5：结束、赛后处理与结果

### 9.1 终止入口

- 正常结束：最终 Stage 关闭。
- 提前完成：锁 session、冻结反馈；有至少一个 complete Stage 才进入赛后 LLM。
- 强制退出：二次确认后进入 `aborted`，不运行赛后 LLM，但仍结算题库统计。
- 安全上限：创建第 101 题前结束。

所有入口调用同一个终止业务 module，不在多个 router 复制状态竞争代码。

`finish-early`、安全停止和确认强退都取得同一 session 行锁。确认强退先提交时，尚未发布的回答、决策和赛后结果必须在复验 status 时失败；已经先完成并发布的终态或赛后业务事实不被追溯回滚。若提前完成刚进入 `post_processing` 但尚无赛后产物，确认强退可以取消未生效 task 并进入 `aborted`。

题目反馈使用独立 PUT 覆盖当前值，但更新前同样锁 session 并检查 `feedback_frozen_at IS NULL`。终止事务先冻结反馈，再让 settlement 读取；任何迟到反馈返回冲突。

好评只表达问题有价值；差评原因限定为重复、不相关、表述不清或其他。反馈和原因不进入 Supervisor、报告 Agent 或题库题目字段，也不自动影响检索权重、删除或降权。`decline_current_line` 是对话行为，不得伪装成题目差评。

### 9.2 结算先行

Finalization 的第一个业务效果必须是题库统计结算：

1. 插入以 `session_id` 唯一的 settlement。
2. 只按 turns 已保存的非空 `question_id` 聚合 usage 和冻结反馈。
3. settlement 与全部计数在同一事务提交。
4. 已存在 settlement 时直接继续，不重复计数。

尚未回答但已经展示的问题计 usage；不生成答案、评估或报告证据。

### 9.3 赛后依赖链

```text
settlement committed
  → project answers (whole session) || ideal answers (per answered turn)
  → optional post-verification append committed
  → evaluations (per answered turn)
  → report when every evaluation succeeded
  → completed + checkpoint deletion
```

发布每个产物与把对应 `post_task` 标成 `succeeded` 必须在同一事务。不同分支只更新自己拥有的列，不能用空值覆盖别的分支。

Finalization Graph 是依赖关系的唯一编排者；`post_tasks` 只记录稳定自然键、尝试、租约和终态，不自行拼第二套 DAG。worker 崩溃后回收过期租约并从 PostgreSQL 产物/task 事实恢复；不引入 Celery/Kafka，也不允许同一 task 的迟到结果覆盖已经发布的结果。

项目版答案按整场一次生成：顶层 JSON 必须完整解析，再逐项校验 `turn_no` 存在且不重复；合法顶层允许缺少部分 turn，非法或截断顶层整体不采用。目录新发现的事实若支撑项目版答案，相关答案、过滤后的 `## 事后核验` 追加回执和 task success 必须一起发布，评估只能在最终 snapshot barrier 之后启动。

理想版答案按题隔离：turn 有 `question_id` 且题库已有预生成答案时直接复用，否则只针对实际题目现场生成；不得重新检索补绑题库，也不得读取项目材料、项目版答案或反馈。逐题评估只接收最终 snapshot、本题 Q/A 和两版可空参考答案。报告只接收最终 snapshot 与按序的 `stage/Q/A/comment`，不得接收两版参考答案、反馈、目录或别题的模型输出。

### 9.4 降级规则

- Local Runtime 或 source handle 不可用：项目版答案退回最终 snapshot。
- 单题理想答案失败：保持空值，评估仍继续。
- 项目版答案缺项：对应字段为空，评估仍继续。
- 评估失败：保留其他成功产物，不生成伪完整报告。
- 报告失败：完整问答仍可读取，session 最终进入 `completed` 并显示处理未完成。
- 任何参考答案和评分信息都不能回流 Supervisor。

### 9.5 结果 projection

- 完整问答按 Stage/turn 返回 Q/A、可空两版答案和可空 comment。
- 报告 JSON 是唯一报告业务事实；Markdown 由确定性 renderer 生成。
- snapshot Markdown 直接返回当前数据库全文。
- 导出不创建新业务版本或服务器文件记录。
- 报告 JSON 固定包含总评、八个维度的 `0..5 + analysis`、项目建议和训练建议；`0` 表示证据不足，不是最低能力。
- UI 不展示内部数字或总分；`1～2/3/4～5` 映射为“需改进/普通/优秀”，`0` 显示“证据不足”并在雷达图中使用灰色或空心样式。
- 报告页固定显示“能力评分由 AI 基于本次面试内容生成，仅供复盘参考，不代表对实际能力的完整评价”。
- 完整问答中的理想版答案固定说明其基于通用行业实践、不代表当前项目唯一正确实现。
- 报告 Markdown 固定生成总评、能力画像、八维分析、项目改进建议和下一轮训练建议，不包含数字分数、三级标签、雷达图或 UI 声明。

### 9.6 验收门

- 提前完成一场含已回答和未回答当前题的 session：未答题只计 usage，不进入评估。
- settlement 在事务提交后模拟 ACK 丢失，重跑不重复累计。
- 一个参考答案任务失败时，其他评估仍能发布。
- 评估全部成功后才生成报告；报告输入捕获中没有两版参考答案。
- 三个 Markdown 导出与当前 PostgreSQL 事实一致。
- 反馈 PUT 与终止冻结并发时，只有先取得 session 行锁的一方生效。
- 强退分别与回答、提前完成和迟到模型结果竞争，最终状态和已发布业务事实符合 6.5 合同。
- post task 在领取后、外部调用后、产物发布前分别中断，恢复后每个业务产物仍至多一份。

## 10. Gate 6：Web 演示闭环

### 10.1 页面集合

- Session 列表/创建/删除，以及 owner 的策展授权开关。
- 项目授权或 Markdown 导入、snapshot 审阅。
- 方向、范围和 plan 确认。
- 面试页面：Stage 进度、当前问题、回答、反馈、提前完成、处理状态。
- 快照事实更正确认卡、decision retry 和确认强退交互。
- 结果页面：复盘报告/完整问答两个页签、三个导出入口。
- Administrator 页面：已授权材料筛选、策展 item 编辑审核、隐私/查重结果和人工加入题库。
- 题库管理列表：公共题目字段及 usage/upvote/downvote，不反查私人 session。
- 明确的错误和重试页面；不能只在 console 打印。

### 10.2 Web 状态规则

- Server state 来自生成的 HTTP client；不手写第二份领域类型。
- 页面加载先 GET，SSE 只令相关 query 失效并重取。
- 提交按钮防双击是体验优化，后端幂等仍独立成立。
- 强制退出只有二次确认后的确认按钮调用后端；取消不发请求。
- 删除 session 同样需要明确确认并展示可重试清理失败，不能先从 UI 隐藏仍未删除的资源。
- 模型处理中明确显示状态；不能用前端假问题或假报告填充等待时间。
- `operation_in_progress`、`decision_retry`、部分赛后失败有可理解的界面文案。

### 10.3 固定演示脚本

在一个冻结的小型真实项目上预演并记录：

1. 授权目录，展示 Application Runtime 只收到 handle。
2. 生成 snapshot，查看一次脱敏结果。
3. 选择一个 Thread 和 `core_flow_deep_dive`，生成 Stage plan。
4. 开始面试，回答两到三题；至少触发一次继续追问和一次 Stage 切换。
5. 刷新页面，证明当前状态恢复。
6. 提前完成，观察赛后任务进度。
7. 打开报告和完整问答，导出 Markdown。
8. 展示一次重复回答或 SSE 丢失测试。
9. 另开一场终态 session 授权策展，由 Administrator 编辑并确认加入题库，再验证检索链路可见。

演示数据不得包含真实凭据或不愿上传给模型的私人代码。

### 10.4 验收门

- 从空浏览器状态可以独立完成上述脚本，无需手改数据库或调用隐藏脚本推进状态。
- 刷新、返回列表再进入、Application Runtime 重启后都能回到当前资源。
- 浏览器网络面板中没有真实路径、题库内部 ID、Prompt、参考答案泄漏到 Supervisor 请求或非 owner 资源。
- 雷达图显示八维形状和三级标签，但不显示内部数字或聚合总分，并包含固定“评分仅供参考”说明。
- User 和 Administrator 两种身份只能看到合同允许的资源，管理员角色本身不能绕过 `curation_review`。

## 11. Gate 7：策展、删除、回归与硬化

### 11.1 策展授权与人工入库

- [ ] owner 可以 grant/revoke `curation_review`，其他 User 不能修改。
- [ ] 管理员列表在 SQL 层只读取 `curation_review=true` 且 `completed/aborted` 的 session；进行中会话即使授权也不可见。
- [ ] 管理员主动选择源 turn 后才创建 curation item，组合外键不能跨 session 串 turn。
- [ ] 编辑题目、建议 topic、审核备注、隐私处理和精确文本查重在确认页可见。
- [ ] 只有人工确认 `add-to-question-bank` 才写 `bank.questions` 并生成正式检索索引。
- [ ] revoke 与 publish 锁同一 source session 行并重新检查授权：revoke 先提交则不建题，publish 先提交则公共题保留但私人会话不可反查。
- [ ] 题库整理 Agent 只能给出泛化、隐私处理、查重、topic 和理想答案建议，无权自行发布。
- [ ] 控制台可以基于已授权材料形成软件/对话配置修改建议，并支持人工带入版本控制与回归流程；建议不是运行时可直接发布的业务实体，不建立自动发布表，也不自动改写 Prompt、Schema、Topic、模板或代码。

### 11.2 删除与保留

- [ ] 删除前验证 owner，并停止该 session 的新命令和可取消 worker。
- [ ] Redis checkpoint 明确删除失败且 PG session 仍存在时，返回可重试错误，不先销毁恢复定位。
- [ ] PostgreSQL 删除级联清理 snapshot、plan、turn、反馈、赛后产物、settlement、curation 私有引用和 session trace。
- [ ] 通知 Local Runtime 释放 handle；通知失败不阻塞业务数据删除，由本地 TTL 最终失效。
- [ ] 用户已经导出的本地文件不受影响。
- [ ] 已经人工审核进入题库的公共题目保留，但不能保留反向读取私人会话的内容路径。
- [ ] 已结算的题库累计不因删除 session 反向扣减。
- [ ] 定时清理 30 天前无内容 trace；不建立第二条内容日志。

### 11.3 固定回归与质量评估

- [ ] 冻结至少三个项目：文档完善、只有代码、用户口述/Markdown 补充。
- [ ] 保存预期 snapshot、范围、plan 特征和对话行为，不保存私人凭据。
- [ ] Observer/Planner/Supervisor/答案/评估/报告分别有真实模型回放入口。
- [ ] 检索固定查询集计算 Recall@K、nDCG@K、重复率、人工适配率和 RAGAS；RAGAS 不进入在线链路。
- [ ] Prompt 注入覆盖 README、代码注释、Markdown、回答和工具结果，验证它们只能作为数据。
- [ ] 根据真实运行记录 P95/P99，再调整截止时间、并发、检索阈值和退避；这些仍是配置，不变成业务字段。

### 11.4 验收门

- curation grant/read/create/publish/revoke 全链路与并发负例通过。
- 删除一个 active、一个 completed、一个已策展 session，各存储和保留行为符合合同。
- 三个固定项目的端到端回放可重复运行并产出比较结果。
- 无内容 trace、日志、Redis、导出和 provider capture 通过 canary 泄漏扫描。
- `tests/fault_windows` 七个家族都映射到自动化用例或明确的跨进程测试；不能通过改成扩展项来关闭未完成场景。

## 12. 完整自动化测试计划

测试随 Gate 逐步落地，不在最后一次性补。以下首批用例是主链路进入下一 Gate 的阻塞项；`IMPLEMENTATION_DESIGN.md` 第 18 节及 `tests/fault_windows` 的全部已确认场景继续属于完整施工范围，后续按七个家族补齐。尚未自动化的场景只能标记为未完成，不能被重分类为非目标。

### 12.1 纯规则测试

- [ ] Module/Thread 标题解析只接受指定层级。
- [ ] Plan 校验：Stage 数、唯一 ID、topic 和 section 引用。
- [ ] Supervisor 三动作与 Stage-entry 特殊约束。
- [ ] 精确候选正文映射 `question_id`；任意改写映射为 `NULL`。
- [ ] report JSON 到 Markdown 的确定性渲染。
- [ ] content safety 不把测试凭据送进模型工作文本。

### 12.2 真实 PostgreSQL/Redis 集成测试

- [ ] migration 和核心约束。
- [ ] snapshot append 同 key 同内容只追加一次，同 key 不同内容冲突。
- [ ] 相同回答重放不重复调用模型或创建 turn；不同回答冲突。
- [ ] Supervisor 迟到结果不能发布第二个业务结果。
- [ ] turn 提交后 checkpoint 写入失败，恢复不再为同一触发调用 Supervisor。
- [ ] turn 已提交但 SSE 丢失，GET 返回已发布问题。
- [ ] settlement 失败全回滚；提交后重跑不重复计数。
- [ ] 产物与 post task success 同事务发布。

### 12.3 跨 Runtime 合同测试

- [ ] source handle 不能跨 session 使用。
- [ ] Application Runtime 永远拿不到真实路径。
- [ ] inventory 后替换 symlink 不能读取根目录外 canary。
- [ ] Local Runtime 不暴露写文件或执行命令工具。
- [ ] trace 上报失败不改变业务结果，且 trace 无正文。

### 12.4 端到端路径

用 controlled model/retrieval adapter 通过公开 HTTP 跑：

```text
create → import → select → plan → start
→ answer → close Stage → next Stage first question
→ finish early → settlement → evaluations → report
→ reload current view and exports
```

另外分别覆盖：快照更正确认/拒绝、decision retry、正常完成、无 complete Stage 的提前结束、确认强退、100-turn 安全上限、策展 grant/revoke/publish 和 session 删除。

端到端断言只看公开资源；只有业务效果基数和泄漏检查直接查看数据库/Redis。

### 12.5 故障与恢复覆盖

按现有稳定编号实现并在 CI 报告中保留 case ID：

- `FW-EXT-*`：外部调用、结构修复、超时、迟到结果和物理调用计数。
- `FW-COM-*`：事务、ACK、checkpoint 与 SSE 丢失窗口。
- `FW-INT-*`：确认 interrupt、幂等追加和终止竞争。
- `FW-CTX-*`：20-turn compact 与 Redis 重建。
- `FW-RACE-*`：回答、反馈、终止、重试、结算和策展竞争。
- `FW-POST-*`：参考答案、事后核验、评估与报告 barrier。
- `FW-SEC-*`：symlink TOCTOU、删除、授权、迟到写入和泄漏。

大多数排列通过 controlled adapter 和 test-only transaction hook 运行；只有真正跨进程窗口使用少量进程终止测试。不得为了便于注入故障给生产状态机增加状态。

## 13. 每个写入口的统一校验顺序

所有 router 和业务 module 按同一顺序思考，避免各路径漏一层：

1. **传输校验**：类型、长度、编码、必填字段、枚举。
2. **身份校验**：已认证身份、owner/Administrator 角色。
3. **授权校验**：source handle 绑定、`curation_review`、资源可见性。
4. **状态校验**：当前 session status、interrupt、feedback freeze、终态。
5. **内容校验**：安全过滤、Prompt 数据边界、Schema。
6. **触发事实校验**：当前 turn/Stage/plan 与命令声称的对象一致。
7. **外部调用**：不得持有业务事务。
8. **发布前复验**：重新读取并锁定必要业务事实。
9. **数据库约束**：自然键、FK、CHECK、条件写入兜底。
10. **安全 projection**：响应和错误不泄漏 ORM 字段、路径、Prompt 或原始模型输出。

任一层失败都必须停止在该层，不允许“尽量修好后继续”。唯一允许的模型修复是合同规定的一次结构化输出修复，并计入同一尝试预算。

## 14. 关键 module 与 seam

| Module | 对调用方的 interface | 内部拥有 | 明确不拥有 |
| --- | --- | --- | --- |
| Session | 创建、选择、开始、结束、删除 | 状态前置条件、owner、终止事务 | 模型 Prompt、文件路径 |
| Snapshot | import、observe 结果、append、parse、export | 当前全文、失效规则、安全值 | 历史版本链 |
| Planning | `generate_plan(session_id)` | 资产选择、模型调用、确定性校验 | 面试推进 |
| Retrieval | `retrieve(...) -> candidates` | dense/FTS/RRF/rerank/cooldown | Supervisor 决策、赛后匹配 |
| Interview | current view、answer、retry、resolve correction | Graph resume、触发重建、条件发布 | 题库计数、Web 状态机 |
| Finalization | resume one session | settlement barrier、fan-out/join、产物发布 | 用户手动重跑批次 |
| Result | report/full QA/export | 安全 projection、确定性 renderer | 第二份报告事实 |
| Local source | authorize/inventory/read/observe | path、symlink 校验、只读工具 | session 业务状态 |
| Model Adapter | structured/tool-step generation | 传输、总尝试预算、无内容 trace | Prompt 角色逻辑、文件工具 |
| Content Safety | raw text → `SafetyResult` | 检测、替换、长度/编码规则 | 持久化和状态推进 |

若新增一个类只是把参数原样转给下一层，删除它后复杂度也没有扩散，就不创建该 module。测试所需的 fault adapter 保持在外部依赖 seam，不暴露成产品 interface。

## 15. 允许的降级与不允许的捷径

### 15.1 允许的降级

- RAG 整体失败 → 0 候选，Supervisor 仍可出题。
- Local Runtime/source handle 失效 → 赛后项目版答案仅使用 snapshot。
- 单题参考答案失败 → 可空字段，评估继续。
- 报告失败 → 完整问答仍可用，明确处理未完成。
- SSE 丢失 → GET 当前视图恢复。
- trace 上报失败 → 有界内存缓冲或丢弃，不回滚业务结果。

### 15.2 不允许的捷径

- Application Runtime 直接读取项目路径。
- 用 Redis、Web state 或进程内字典替代 PostgreSQL 业务事实。
- 为演示预写固定问题、固定报告或成功 task 记录。
- 跳过 Pydantic/JSON Schema 后直接采用模型文本。
- 为了让统计好看，把改写题相似度匹配到题库。
- 在 Graph node、业务 module、SDK 三层同时重试。
- 用 `sleep` 猜测后台任务完成；应读取 task/current view 或等待 SSE 后重读。
- 捕获异常后统一返回 200 或空对象。
- 把测试 fault position 变成生产状态字段。
- 把正式设计中的功能改名为“增强项”以便提前宣布完成。

## 16. 收尾与提交检查

### 16.1 代码与运行

- [ ] README 从空环境给出依赖、配置、迁移、种子导入、启动和测试命令。
- [ ] `.env.example` 完整且无真实 secret。
- [ ] migration 可以在空库运行。
- [ ] 题库 importer 可重复运行。
- [ ] Web、两个 Runtime、worker、PostgreSQL 和 Redis 的启动关系清楚。
- [ ] 固定演示项目和演示步骤不依赖个人机器绝对路径。
- [ ] 对照目标工程结构审计新增表、字段、状态、module、adapter、后台循环和配置项；每一项都能指向当前合同与验收，没有“以后可能需要”的空扩展点。

### 16.2 行为

- [ ] 固定演示脚本完整通过。
- [ ] 重复回答、SSE 丢失和一次进程重启通过。
- [ ] 部分赛后失败的展示不伪造完整成功。
- [ ] `question_id` 关联只来自本轮精确候选。
- [ ] 导出内容与当前数据库事实一致。
- [ ] 更正确认、compact、所有终止分支、策展和删除完成各自验收路径。
- [ ] 固定项目回放、检索评估和七类故障窗口有可重复结果。

### 16.3 安全与隐私

- [ ] Application 数据库、日志和错误中无真实路径。
- [ ] trace 无 Prompt、snapshot、answer 和模型正文。
- [ ] 测试凭据 canary 不进入模型请求、Redis、trace 或导出。
- [ ] owner、Administrator 和 curation grant 检查各有负例。
- [ ] 所有文件工具只读且打开时复验根目录。

### 16.4 停工标准

满足以下条件即可冻结本次完整交付，不继续增加架构：

- 纵向主链路和固定演示脚本通过；
- 上游正式设计中的全部功能通过各自 Gate，只有明确后续/扩展项未实现；
- 完整自动化测试计划通过，跨进程慢测可单独运行但不能缺失；
- 已知失败都能明确降级或显示，不会产生错误业务事实；
- README 足以让另一台机器启动；
- 固定回归、检索指标、trace 与安全检查均有结果记录。
- 防过度实现审查通过：不存在第二份业务事实、重复重试层、从单一场景泛化出的通用机制、无调用方抽象或未经实测的性能基础设施。

若时间不足，停在最后一个真实通过的 Gate，并如实记录后续 Gate 未完成；不削功能、不改变上游范围，也不以“展示版/MVP/Phase”名义宣布完整交付。可以调整施工顺序和界面精细度，但产品要求的页面、状态、权限和行为仍必须补齐后才达到本项目停工标准。
