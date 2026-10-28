> 谁能拉开项目作者的弓，并让解释穿过十二层架构边界，谁才真的做过这个项目。

# 项目模拟面试 Bot：产品开发文档

> 文档状态：Draft v0.3  
> 产品代号：Project Interview Lab（暂定）  
> 首版定位：面向 AI 软件开发岗位项目作者的中文、文本式、证据驱动模拟面试

## 1. 产品摘要

Project Interview Lab 面向 AI 软件开发岗位，读取用户授权的本地项目目录，或导入用户自己的 Markdown 项目文档，形成本场使用的 `snapshot.md`。这份 Markdown 同时供用户审阅、保存、导入、选择面试范围和直接交给 LLM 使用。Planner 根据完整快照与用户选择生成线性 Stage 计划；Supervisor 每轮从三种允许动作中选择下一步，并结合 1～3 条题库 RAG 候选和历史回答组织一个问题。满足报告生成条件后，项目版答案 Agent 与理想版答案处理并行运行，各题再并发评估，最后由报告 Agent 聚合能力观察、项目建议和下一轮训练建议。

它解决的不是“多刷几道八股题”，而是三个更具体的问题：

1. 项目作者知道自己做过什么，却未必能清楚说明为什么这样做。
2. 通用面经无法根据具体项目持续追问，训练容易停留在背诵。
3. 面试结束后缺少基于原回答证据的复盘，用户不知道下一次该改哪一句。

## 2. 产品目标与非目标

### 2.1 目标

- 将代码、文档和用户补充信息整理为用户可读、可选保存、可直接导入的 Markdown 项目快照。
- 生成与项目特征和 AI 软件开发岗位能力匹配的问题。
- 根据面试方向与范围生成有序 Stage 列表，用阶段目标和完成条件控制节奏，同时保留问题表达和追问的适应性。
- 将实时面试与赛后答案、评估隔离，在保持面试连贯性的同时降低每轮延迟和成本。
- 输出细粒度、可验证、可执行的复盘报告，并将散落在面试过程中的工程缺口汇总为项目改进建议。
- 由管理员在控制台从会话材料中选择高价值问题，完成编辑、隐私处理、查重和质量确认后发布到正式题库。

### 2.2 非目标

- 不在 MVP 中替企业作招聘、淘汰或录用决定。
- 不把用户归类为固定人格或生成带歧视风险的“人才标签”。
- 不承诺从代码中准确还原所有业务背景、规模数据和个人贡献。
- 不自动替用户润色或伪造不存在的项目经历。
- 不在 MVP 中覆盖语音、视频、表情和肢体表现分析。
- 不覆盖与 AI 软件开发无关的通用前端、后端、算法或工程效率岗位面试。
- 不把产品做成通用代码审查、IDE 或在线判题平台。
- 不让系统生成的新问题未经审核直接进入正式题库。
- 不承诺长期自动缓存项目快照，也不承诺快照与后来修改的项目目录始终一致。

## 3. 用户与使用场景

### 3.1 核心用户

- 准备实习、校招或社招 AI 软件开发岗位面试的项目作者。
- 希望重新梳理 AI 项目、补齐表达和技术理解的开发者。
- 带教者或课程教师，用同一项目反复组织结构化模拟面试。

### 3.2 核心场景

1. **首次梳理**：用户导入项目，发现自己没有准备过的架构、边界和评估问题。
2. **定向训练**：用户从 `snapshot.md` 解析出的 Module、Thread 中选择范围，完成对应的线性 Stage 计划。
3. **项目改进**：将面试中暴露的问题与行业理想实践汇总，形成符合现有项目边界的改进清单。
4. **复盘重练**：系统依据上轮薄弱项组织下一轮面试，并对比前后回答。

### 3.3 系统角色

- **User**：授权并分析自己的项目，完成模拟面试，查看、导出和删除本人的会话产物。
- **Administrator**：从会话材料中选择需要审核的内容，管理正式题库、对话配置版本、质量回归与受控迭代。管理员控制台的数据来源、编辑状态和实现依赖尚待确认的运行时持久化方案。

## 4. 核心设计原则

### 4.1 证据优先

Observer 应在 Markdown 正文中清楚区分以下三类内容，但不要求使用 JSON 字段或固定的字段元数据。证据表达属于 Observer Prompt 中的质量要求，不作为程序强制解析的结构化合同：

- **事实**：可由代码、文档、配置或用户陈述直接支持。
- **推断**：由事实推导而来，必须记录证据、推断理由和置信度。
- **未知**：当前材料无法回答、但面试中值得询问的内容。

系统不得把推断悄悄改写成事实。用户补充内容通过 `## 用户意见` 追加，赛后核验通过 `## 事后核验` 追加；两者都不覆盖原文。

证据引用主要服务于用户审阅、离线质量评估，以及项目版答案 Agent 对授权目录的定向取证。无法访问项目目录的其他 Agent 只把引用作为快照正文的一部分，不尝试自行解引用或据此声称已核验源文件。

### 4.2 实时面试与赛后分析隔离

Supervisor 只能访问系统 Prompt、完整 `snapshot.md`、当前 Stage、本轮动作菜单、1～3 条题库候选和连续对话上下文。它不读取项目版或理想版答案，不在面试热路径中检查代码，也不负责对用户进行详细评分。

项目版答案 Agent 与理想版答案处理使用独立上下文。两类答案完成后，每道题由独立评估 Agent 并发生成 `comment`；报告 Agent 只接收最终快照和按顺序排列的 `Q/A/comment`，不读取两版参考答案。

### 4.3 追问胜过题量

问题编排由线性的 Stage 列表控制，而不是只依靠 Supervisor 临场决定或不断切换主题。每个 Stage 描述目标、完成条件和主题，不写死具体问题。一个常见列表可以是：

`事实确认 → 设计动机 → 备选方案 → 约束变化 → 故障或边界 → 个人贡献 → 复盘改进`

面试计划决定“当前阶段要问清楚什么”，Supervisor 决定“结合此刻回答具体怎么问”，并在 `continue | complete | unresolved` 中选择一个动作。

### 4.4 反馈必须可执行

不输出“架构能力较强”一类空泛结论。评估仍只输出自然语言结果；Prompt 可以建议结果尽量覆盖：

`回答依据 → 能力信号 → 主要缺失或风险 → 下一步练习`

这些是写作指导，不是要求程序维护证据数组、置信度字段或更多评估元数据。

### 4.5 项目建议必须经过汇总

面试中的两版答案只解决单题参照问题。逐题评估 Agent 负责将用户回答与两版答案交叉比较；报告 Agent 再根据最终快照和 `Q/A/comment` 去重、归类形成项目级改进建议。只整理根据现有项目可以判断的改进点，不把脱离项目实际的行业最佳实践机械地列为待办。

### 4.6 题库迭代必须受控

实际提问、回答、Supervisor 临时创建的 Topic 和用户反馈首先只属于会话记录。系统可以在管理员控制台中汇总使用情况和生成待审建议，但不得自动把任何内容复制进正式题库。只有管理员主动选择某条会话材料，完成隐私处理、语义查重、Topic 和理想答案补充并明确发布后，它才成为正式题目并进入面试 RAG。

Stage 规划 Prompt、Supervisor Prompt、行为 Schema、Topic 列表、Planner 模板和监督规则采用同样的发布原则：运行数据只能形成控制台中的修改建议，不能直接改变线上配置；经过回归测试、人工审核和发布后才生效。所有正式变更保留版本、审核记录和撤回能力。

## 5. 完整用户流程

### 5.1 准备项目快照

用户从两个入口中选择一个：

1. 选择本地项目目录并确认系统可读取的文件范围与排除规则，由 Observer 分析项目并生成 `snapshot.md`。
2. 导入用户自己的 Markdown 项目文档，包括此前保存的 `snapshot.md`，并可同时授权对应项目目录。只导入 Markdown 时，后续系统没有原项目可读。

从目录开始时，系统先建立文件清单，过滤二进制、依赖目录、敏感文件和超大文件，并在解析前替换疑似密钥。Observer 读取脱敏后的材料，输出以 Module 和 Thread 为主要结构的 Markdown。用户导入的 Markdown 同样先经过脱敏和基础内容安全审查，原文件保持不变，处理后的工作副本作为本场 `snapshot.md`。

用户随后直接审阅 Markdown，并可以在输入框中补充意见。输入非空时，程序只在文末追加 `## 用户意见`；用户确认后可以选择将最终 `snapshot.md` 保存到本地。系统不自动长期缓存快照，不计算文件哈希，也不做增量更新或目录一致性校验。

### 5.2 发起模拟面试

用户选择：

- 面试方向：项目导览、核心链路深挖、横切专项、压力面试、贡献与复盘。
- 面试范围：程序从 `## Modules` 和 `## Threads` 下的 `###` 标题即时解析出的一个或多个 Module、Thread；如果没有任何可解析范围，则按下述降级流程处理。

Planner 接收完整 `snapshot.md`、用户选择、面试方向与完整 Topic 列表，生成有顺序的 `interview_plan`。系统不展示或承诺预计问题数量。

如果导入的 Markdown 没有产生任何 Module 或 Thread 选项，程序提示这是非常规项目文档，由用户选择返回修改或继续。用户继续时跳过范围多选，直接把完整 Markdown 交给 Planner 生成计划。Modules 和 Threads 只用于范围选择；Stage 生成后，后续流程不再依赖这两个标题。

### 5.3 面试进行中

每一轮：

1. 编排器按全局 `interview_plan` 的顺序加载当前 Stage，并提供 `continue | complete | unresolved` 三种动作。
2. 题库 RAG Hook 根据完整快照、当前 Stage、最近回答和已问内容召回 1～3 条候选问题。
3. Supervisor 把同一条用户消息拆成一个或多个 `user_acts`，可选输出对用户问题的 `reply`，并在当前 Stage 内选择动作、输出 Topic 和至多一个主要问题。
4. 如果检测到明确的项目事实更正，程序先显示可编辑的“写入快照”确认卡。用户确认后，只把最终确认文字追加到 `## 用户意见`；选择暂不写入则保持快照不变。确认卡不触发第二次模型调用。
5. 如果动作为 `continue`，同一次输出中的 `question` 是当前 Stage 的下一个问题；程序依次展示可选 `reply` 和该问题并等待用户回答。
6. 如果动作为 `complete` 或 `unresolved`，`question` 必须为 `null`，且不进入对话上下文。程序先记录 Stage 结果并推进当前索引；如果仍有下一 Stage，则重新渲染它并再次调用 Supervisor，由新调用生成该 Stage 的第一个问题；如果 Stage 已耗尽，则直接结束面试。

首次进入任一 Stage 时，该 Stage 还没有上一条用户回答。程序仍按同一方式渲染当前 Stage 并调用 Supervisor；Supervisor 结合既有历史输出 `continue` 和该 Stage 的第一个问题。

拒答、希望结束当前讨论或要求换种说法都作为普通用户行为处理，不对应独立按钮或持久状态。明确拒绝继续当前方向时，Supervisor 可以选择 `unresolved`；要求澄清或换种说法时，通过 `reply` 简短说明并在 `question` 中重述当前问题。

历史上下文每满 20 个真实 Q/A 轮次执行一次累计 compact：将已有 compact 与新产生的 20 轮原始对话折叠为一个新的 compact，再保留下一批原始对话。快照确认卡不作为对话消息，也不计入真实 Q/A 轮次。

#### 面试完成与退出

- **计划结束**：全部 Stage 依次走完后，程序直接结束面试并生成报告，不需要 `propose_complete` 或结束确认。
- **手动完成**：用户可以提前结束；只有至少一个 Stage 的结果为 `complete` 时才生成报告，否则只结束会话。
- **强制结束**：立即终止面试，永远不生成报告。
- **安全停止**：系统保留 100 个真实 Q/A 轮次的内部安全上限；触发后根据是否至少存在一个 `complete` Stage 决定是否生成报告。

系统不保证或预估面试长度，也不设置固定长度和最少问题数。`completed_stage_count` 是根据 Stage 结果即时计算的临时值，不单独持久化。

### 5.4 面试复盘

满足报告生成条件后，项目版答案 Agent 按整场处理，理想版答案按题目来源独立处理。两类答案准备完毕后，每道题启动一个可独立重试的评估 Agent，并发生成逐题 `comment`。最后，报告 Agent 只接收最终 `snapshot.md` 和按顺序排列、同时保留 Stage 与 Topic 的 `Q/A/comment`，生成总评、能力观察、项目建议和下一轮训练建议。

界面最终提供两个页签：

- **复盘报告**：总评、八个能力维度的观察、项目改进建议和下一轮训练建议；UI 额外展示基于八维内部评分生成的雷达图和三级评价标签。
- **完整问答**：按 Stage 展示问题、用户回答、项目版答案、理想版答案和逐题 `comment`。

两个页签都可以分别导出为 Markdown 文件，例如 `review-report.md` 和 `full-qa.md`。复盘报告的 Markdown 只导出文字内容，不包含内部评分、三级标签、雷达图或 UI 评分说明。

## 6. 功能需求

### 6.1 项目材料接入

#### MVP

- 读取用户指定的本地项目目录。
- 导入用户自己的 Markdown 项目文档，包括已有的 `snapshot.md`；项目目录为可选授权项。
- 支持常见代码、Markdown、纯文本、JSON、YAML 和 TOML。
- 支持 `.gitignore`，并提供额外排除规则。
- 展示读取文件清单、跳过原因和解析错误。
- 默认跳过 `.env`、私钥、凭据文件和凭据目录。
- 使用轻量规则扫描器检测 API Key、Token、密码、私钥和带密码的连接串；可采用 `detect-secrets` 加少量自定义规则。
- 命中的值在切块前替换为带类型的占位符。只有脱敏文本可以进入 Markdown 快照、模型上下文、派生产物和日志；本地原文件保持不变。
- 界面展示命中文件、行号和类型，不回显敏感值。MVP 不对姓名、邮箱等一般个人信息做大范围自动替换，避免误伤正常代码。

#### 后续

- GitHub/GitLab 授权接入。
- Issue、PR、提交记录和设计文档接入。
- 在不改变 Markdown 快照边界的前提下扩展更多材料来源。

#### 6.1.1 Observer 大型项目分析机制

Observer 的目标不是逐个总结仓库中的所有文件，也不是把尽可能多的源码一次性塞进模型上下文，而是在可控预算内建立足够可靠的项目地图，再围绕架构边界、核心模块和端到端链路定向取证。MVP 采用“确定性预处理 + 仓库地图 + 迭代读取 + 汇总校验”的本地分析流程。

##### 第一步：本地清点与安全边界

本地 Agent 先执行不依赖 LLM 的清点：

- 解析并验证用户授权的项目根目录，记录相对路径、文件类型、大小、编码和跳过原因。
- 依次应用产品硬排除规则、`.gitignore` 和用户追加的排除规则；规则冲突时，安全硬排除不可被用户规则覆盖。
- 默认不跟随指向授权根目录之外的符号链接，不主动进入嵌套仓库或未选择的子模块。
- 在任何模型调用之前完成二进制识别、敏感文件排除和文本内疑似凭据替换。
- 识别 README、依赖清单、构建配置、容器与部署配置、入口文件、测试目录、数据模型和常见框架约定，形成初始项目画像。

MVP 不执行项目中的任意脚本、安装命令或构建命令。仓库内容、README、注释和配置一律视为待分析数据，不能借此取得新的工具权限或改变系统 Prompt。

##### 第二步：构建轻量 Repository Map

程序使用 Tree-sitter、语言 AST 或保守的文本降级解析，在本地生成受预算约束的仓库地图：

- 精简目录树、主要语言和框架信号。
- 文件中定义的类、函数、方法、接口和关键常量，只保留名称、签名、位置和必要的文档摘要，不默认保留完整实现。
- import、调用、继承、配置引用和测试到实现的关联；无法可靠解析时只记录确定存在的关系。
- README、入口、manifest、依赖中心度、被引用次数和测试覆盖关系等候选排序信号。

Repository Map 是 Observer 的导航上下文，不直接成为最终 `snapshot.md`。地图过大时，程序按结构中心度、入口相关性、文档显式引用和文件类型进行裁剪，并始终受独立 token 预算约束。

##### 第三步：Observer 迭代取证

Observer 首先读取 Repository Map，再通过受限只读工具逐步申请源码或文档片段，而不是一次读取整个仓库。MVP 至少提供：

```text
list_tree(root_or_subtree)
search_text(query, path_filter)
get_file_symbols(path)
find_symbol_references(symbol, path_filter)
read_file_range(path, start_line, end_line)
```

所有工具只能访问本场授权且经过排除规则处理的文件；返回模型前再次经过敏感信息替换。工具调用记录路径与行号，但日志不保存完整源码。

Observer 按以下观察视角逐步收集材料：

1. 项目入口、主要依赖和运行边界。
2. 候选 Module 的职责、公开接口、上下游关系和关键实现。
3. 候选 Thread 的触发入口、控制流、数据流、外部调用、失败路径和最终输出。
4. 测试、评估、安全、可观测性和部署等横切能力。
5. 代码无法证明、需要用户补充的业务背景、规模、结果和个人贡献。

分析过程中可以维护临时的内部工作清单，用来记录“已查看材料、待确认主张、候选 Module、候选 Thread 和未知项”。它只服务于本次 Observer 运行，不改变 `snapshot.md` 是唯一用户可见项目快照的边界。

##### 第四步：预算、停止和降级

单文件大小、候选文件数、累计读取文本、模型 token、工具调用次数和总耗时都必须有可配置上限。具体数值通过黄金项目包校准，不写死为产品承诺。

满足以下条件时 Observer 可以结束探索并生成快照：

- 已识别项目入口和主要边界，或明确标记当前材料无法识别。
- 每个准备写入的 Module 和 Thread 至少有已实际读取的材料支持，纯推测内容被标为推断或未知。
- 新一轮检索没有产生足以改变主要结构的新信息，或已经达到预算上限。

达到预算上限不等于分析完整。系统必须在读取清单和快照中说明本次是部分分析、哪些目录或文件未覆盖。对于超大型 monorepo，可以先要求用户缩小到一个或多个顶层 workspace/package，再开始 Observer；不得静默截断后声称已分析整个项目。

##### 第五步：快照汇总与校验

Observer 根据实际读取过的材料生成 Markdown，自由正文中区分事实、推断和未知，并在适合时使用 `relative/path.ext:Lx-Ly` 形式记录来源。引用格式属于 Prompt 质量要求，不作为除路径安全外的强制数据 Schema。

输出交给用户前，程序执行确定性检查：`## Modules`、`## Threads` 结构能否解析，各区域的 `###` 标题是否重复，引用路径是否仍位于授权范围，输出中是否再次命中敏感信息规则。语义上的事实准确性、推断合理性和 Module/Thread 覆盖度通过黄金项目与人工评审验证，不用另一个隐藏事实数据库代替 Markdown。

该机制借鉴了 Aider 的 Repository Map 和按 token 预算裁剪、Sourcegraph 的关键词搜索与代码关系检索、Agentless 的“目录到文件再到符号”分层定位，以及 RepoCoder 的迭代检索思路；具体实现以本产品的只读观察和隐私边界为准。

### 6.2 Markdown 项目快照与范围解析

快照就是一份 Markdown 文件，不是数据库对象的展示层，也不要求维护 JSON 字段、繁琐元数据或持久化 ID。Observer 应在正文中尽量清楚地表达项目事实、推断、未知项和证据引用，但除少量标题约定外，正文结构保持自由。导入路径不校验项目事实、完整性或正文格式，允许用户提供自己的 Markdown 项目文档；脱敏和基础内容安全审查不等同于内容真实性校验。

程序只对以下结构作机器解析：

```markdown
## Modules

### Retrieval Service

正文与更深层级标题自由。

## Threads

### User Query to Final Answer

正文与更深层级标题自由。
```

- `## Modules` 下的 `###` 标题生成 Module 范围选项。
- `## Threads` 下的 `###` 标题生成 Thread 范围选项。
- `###` 标题在各自区域内不得重复；两个区域之间允许同名。
- 更深层级标题和正文不参与范围解析。
- 解析结果即开即用，不保存持久化范围 ID。
- 只解析出 Modules 或 Threads 中的一类时，正常展示已有选项。两类都没有可解析选项时不拒绝文件，而是在用户确认后以整份 Markdown 作为范围直接进入 Planner。

同一份 `snapshot.md` 同时承担四个角色：用户可读的项目说明、可选保存和重新导入的项目上下文、LLM 的直接输入、面试范围选项的数据来源。

用户审阅时通过独立输入框补充意见。输入非空时，程序只在文末追加 `## 用户意见` 区块；如果文末已经是该区块，则只追加正文，不重写前面的任何内容。面试中如识别到明确的项目事实更正，Supervisor 在 `user_acts` 中输出 `correct_project_fact` 及候选文字；用户通过可编辑确认卡选择写入后，程序再按同一规则追加。确认卡只决定是否同步到共享快照，不重新判断用户陈述真假，也不触发第二次 Supervisor 调用。

项目版答案 Agent 可以在赛后向文末追加 `## 事后核验` 区块；如果文末已经是该区块，则只追加正文，同样不得编辑既有正文或用户意见。追加完成后的 Markdown 是交给逐题评估 Agent 和报告 Agent 的最终快照。

系统不做长期自动缓存、文件哈希、增量更新或自动失效。用户重新开始时自行导入 `snapshot.md`，并可选择对应项目目录。快照与目录不一致时以快照描述的项目状态为准，系统不承诺检测、同步或修复不一致。

Supervisor 在面试中只能读取完整快照，不读取项目目录。项目版答案 Agent 只有在本场从目录开始或用户同时授权了目录时，才可以在授权范围内定向取证；只导入 Markdown 时必须基于处理后的本场快照回答，并明确标记证据不足。

### 6.3 面试方向、范围与线性 Stage 计划

首版提供五种面试方向：

| 面试方向 | 计划目标 | Planner 侧重 |
| --- | --- | --- |
| 项目导览 | 覆盖关键 Module 和 Thread，建立完整项目叙事 | 全项目粗扫、入口、主要结构与关键链路 |
| 核心链路深挖 | 集中训练一至两条端到端链路 | 选定 Thread、相关 Module、数据与细节实现 |
| 横切专项 | 检查测试、安全、性能、评估或可观测性 | 在所选范围内聚合对应证据和边界 |
| 压力面试 | 通过约束变化、故障、反例和替代方案检验理解 | 容量假设、失败路径、降级和技术取舍 |
| 贡献与复盘 | 澄清个人职责、技术判断、失败与改进 | 决策点、用户陈述、未知项和项目结果 |

面试范围来自 `snapshot.md` 的即时标题解析，可以选择一个或多个 Module、Thread。方向决定“如何问”，范围决定“问哪里”。Planner 接收完整 Markdown、用户选择、方向和完整 Topic 列表，输出一个线性的 `interview_plan`。

`interview_plan` 是有顺序的 Stage 数组。每个 Stage 至少包含：

```yaml
id: 本次计划内的内部引用
title: 给人看的阶段名称
goal: 本阶段想问清楚什么
complete_when: 什么情况下可以进入下一阶段
topic_path: 用于 RAG、当前位置展示和会话记录
scope_refs: 本阶段关联的 Module 或 Thread 标题引用
```

Stage 不包含固定问题和条件分支图。程序按列表顺序维护当前 Stage，并为 Supervisor 提供固定动作菜单：

```json
[
  {"id": "continue", "meaning": "继续当前阶段，针对未说明的部分追问"},
  {"id": "complete", "meaning": "当前阶段已充分，进入下一阶段"},
  {"id": "unresolved", "meaning": "当前阶段未充分，但继续追问价值不大或用户明确不愿继续，进入下一阶段"}
]
```

`continue` 保持当前 Stage，并要求本次 Supervisor 输出携带该 Stage 的下一个问题。`complete | unresolved` 只负责关闭当前 Stage，`question` 必须为 `null`；程序记录结果并推进索引后，才用新 Stage 重新组装上下文并发起下一次 Supervisor 调用。关闭当前 Stage 和生成下一 Stage 的第一个问题绝不发生在同一次调用中。过度追问主要通过 Supervisor Prompt 中的完成条件、信息增益、用户是否愿意继续和继续追问价值判断来避免。`completed_stage_count` 不单独持久化，而是从 Stage 结果中即时计算。

#### 6.3.1 Planner 生成线性计划的建议机制

Planner 的职责是把用户选择的范围和面试方向转换为可执行的 Stage 顺序，不负责提前生成问题、参考答案、评分点或条件分支。计划生成采用“输入归一化 + 单次结构化生成 + 确定性校验 + 有界修复”的流程。

##### 规划输入

程序先构造明确的 `planning_context`：

- 完整 `snapshot.md`。
- 用户选择的 Module、Thread；若没有可解析范围且用户确认继续，则使用“整份文档”这一特殊范围。
- 每个选择项在 Markdown 中对应的标题、正文区块和类型，不创建跨会话持久化范围 ID。
- 面试方向。
- 当前正式 Topic 树及其版本。
- 版本化的 `planning_policy`，用于描述各方向的规划目标、允许的覆盖视角和通用 Stage 编排原则。
- 版本化的 `planning_template_library` 检索结果。模板库包含大量经过审核的参考提问路径，Planner 不是从空白开始自由创造计划。

`planning_template_library` 中的模板描述“在什么项目特征、面试方向和范围组合下，通常按什么顺序澄清哪些目标”。模板可以包含 Stage 原型、顺序关系、适用条件、可替换节点、正反例和 Topic 提示，但不包含要原样问给用户的固定问题。程序先根据面试方向、所选范围类型、快照中的技术与项目特征以及可用 Topic，从大量模板中召回一组相关模板，再与完整 `planning_context` 一起交给 Planner。Planner 可以选择一个主模板，也可以组合多个模板并根据当前项目改写，但必须保留最终计划与用户范围之间的可解释关系。

模板的具体来源、分类体系、召回策略和不同项目类型的覆盖仍属于待调研内容。`planning_policy` 与 `planning_template_library` 都是可以评测、审核、版本化和替换的普通配置，不写死在状态机中；本节先明确“模板驱动规划”的机制，不宣称模板库已经完成。

##### Planner 输出约束

Planner 一次输出完整的线性 Stage 数组。正常计划不得少于 5 个 Stage，并受内部可配置的最大 Stage 数安全上限约束。每个 Stage：

- 必须有唯一 `id`、可展示的 `title`、单一清楚的 `goal`、可由后续回答判断的 `complete_when`、一个正式 `topic_path` 和至少一个 `scope_ref`。
- `scope_ref` 使用 `{kind: module | thread | whole_document, title: string}` 引用本次即时解析结果；Module 与 Thread 同名时依靠 `kind` 区分。
- `topic_path` 必须存在于传入的正式 Topic 树。Supervisor 可以在面试中创建临时 Topic，但 Planner 不创建新的正式 Topic。
- 不得包含固定问题、理想答案、用户应说出的关键词、评分标准、预计问题数量或条件跳转。
- 不应把同一目标拆成多个同义 Stage，也不应创建无法由用户回答判断是否完成的抽象条件，例如“充分展示高级能力”。

计划顺序遵循认知依赖，而不是机械套用固定问卷：先建立后续追问所需的事实和边界，再进入动机、取舍、故障、贡献或复盘等需要前置上下文的目标。不同面试方向可以强调不同视角，但不得脱离用户选定范围强行覆盖整棵 Topic 树。

##### 确定性校验与修复

程序在接受计划前至少校验：

1. Stage 数组至少包含 5 项，且未超过内部可配置的安全上限。
2. `id` 唯一，字段类型、长度和枚举合法。
3. 每个 `scope_ref` 都能匹配本次范围解析结果，或合法使用 `whole_document`。
4. 每个 `topic_path` 都存在于本次 Topic 树。
5. Stage 不包含问题列表、分支边或其他状态机不支持的字段。
6. 所选范围至少被一个 Stage 引用；未选择的范围不得被伪装成用户已选范围。
7. 输出记录本次参考的模板版本和模板 ID，供离线回放与质量评估使用；这些内部引用不进入面试对话。

首次输出未通过时，程序可以把确定性错误列表交给同一 Planner 做一次有界修复。修复仍失败时，计划生成明确失败并允许用户重试；在模板库尚未具备审核通过的兜底模板前，不使用未经审核的通用计划静默兜底。

语义质量不由字段校验冒充完成。是否覆盖了方向重点、Stage 是否重复、顺序是否合理、`complete_when` 是否可判定，需要通过黄金项目的预期计划、人工成对比较和回放测试评估。

##### 计划生成后的边界

计划一旦进入面试即保持线性，不因单轮回答临时插入、删除或重排 Stage。回答中出现的新细节由 Supervisor 在当前 Stage 内追问；经用户确认追加到快照的项目事实更正会从下一轮进入 Supervisor 上下文，但不自动重新运行 Planner。若未来需要动态重规划，应作为新的显式产品能力设计，而不是隐含在 Supervisor 行为中。

### 6.4 面经题库与检索

本产品不是基于 NLP 意图识别和固定回复的 FAQ 系统。面试由 Supervisor 主导，题库 RAG 只是每轮自动执行的检索 Hook，为下一步决策提供有限参考，不直接决定 Supervisor 必须问什么。

正式题库中的运行时题目只保留完成检索、理想答案路由和受控发布所需的最小内容：

- 稳定的题目 ID、不可变版本引用和发布状态。
- 题目正文。
- 一个主要的层级化 `topic_path`。
- 可选的、已经过审核的理想答案。
- 用于语义检索的题目向量。

ID、版本和发布状态是人工审核、回滚及 `adopted` 理想答案关联所需的内部控制字段，不是给用户展示的题目元数据。关键词检索直接从题目正文建立索引，不额外维护关键词字段。标准化语义、适用项目特征、能力标签、Stage 标签、澄清问题和追问变体都不作为 MVP 正式题目的必填字段。版权或来源信息如有保留需要，放在管理员审计记录中，不进入面试 RAG 对象。

题库不以作者身份或“是否由 AI 提出”作为质量字段。运行时只记录当前问题与已有题库的派生关系，用来支持理想答案路由、使用情况汇总和防止重复入库，而不是追溯英雄出处。

正式题库原题可以保存预先生成并审核的理想答案。该答案不参与 RAG，也不会进入 Supervisor 上下文，只在赛后处理 `adopted` 问题时按题目版本读取。项目版答案始终在赛后根据本场项目上下文生成。

检索采用混合策略：

1. 每轮提问前自动调用检索 Hook，根据完整快照、当前 Stage、动作菜单、最近回答、已问内容和会话状态构造查询。
2. 使用向量检索召回语义相关题。
3. 使用关键词检索补回具体技术名和错误码等精确命中。
4. 按主题和审核状态过滤；最近 3 轮已经使用过的题目进入冷却期。
5. MVP 使用 RRF 合并向量与关键词排名，再用确定性规则考虑当前 Stage、重复度和追问连续性；不增加逐轮重排模型调用。
6. 每轮向 Supervisor 返回 1～3 条候选；没有合格结果时允许返回空列表。
7. Supervisor 可以采用、改写或忽略 RAG 候选问题，不直接把 Top 1 当最终问题，也不照题库返回固定回复。

MVP 默认使用 RRF 合并向量与关键词排名；后续再引入专用重排模型。

### 6.5 Supervisor Agent

Supervisor 是实时面试中唯一的对话模型调用。每轮上下文固定由以下部分组成：

```text
系统 Prompt
+ 完整 snapshot.md
+ 当前 Stage
+ 三种允许动作
+ 1～3 条 RAG 候选
+ 历史对话
```

它完成以下工作：

- 识别一条用户消息中并存的回答、向面试官提问、项目事实更正和不愿继续当前讨论等行为。
- 从固定动作菜单中选择一个合法动作。选择 `continue` 时结合上一轮回答输出当前 Stage 的下一个主要问题；选择关闭 Stage 的动作时不输出问题。
- 在用户向面试官提问时可选输出简短 `reply`，但 `reply` 不得包含新的面试问题；正式面试问题只能出现在 `question`。
- 输出本轮 Topic。采用题库候选时可以沿用候选 Topic；不采用 RAG 结果时可以创建临时 Topic。
- 在用户明确纠正项目事实时输出 `correct_project_fact` 及建议同步到快照的文字，但不能自行修改 Markdown。
- 不查代码、不核验事实、不评分，也不决定整场面试是否结束。

Supervisor 在逻辑上具有连续上下文。历史部分只保存真实对话。每满 20 个真实 Q/A 轮次，系统将已有累计 compact 与最新 20 轮原始对话折叠成一个新的累计 compact；上下文中始终保留一个 compact 和不足 20 轮的近期原文。完整原文仍保留给恢复、复盘和赛后 Agent，不被 compact 覆盖。

Supervisor 使用可扩展的 `user_acts` 数组，而不是不断增加固定布尔字段。结构化输出示例：

```json
{
  "user_acts": [
    {"type": "answer"},
    {"type": "ask_interviewer", "question_kind": "clarification"},
    {"type": "correct_project_fact", "text": "项目后来改用 pgvector，而不是 Milvus"}
  ],
  "reply": "这里主要问召回阶段的切片效果。",
  "plan_action": "continue",
  "topic": "rag.chunking.evaluation",
  "question_mode": "follow_up",
  "question_derivation": {
    "mode": "rewritten",
    "question_ids": ["q_123"]
  },
  "question": "你们如何验证当前切片策略优于其他方案？"
}
```

`user_acts` 是对一条用户消息的多标签语义拆解，不是互斥的单意图分类器。MVP 至少支持 `answer`、`ask_interviewer`、`correct_project_fact` 和 `decline_current_line`；`ask_interviewer.question_kind` 再区分题意澄清、流程问题和索取答案或即时反馈。`decline_current_line` 表示用户不愿或无法继续当前讨论，由 Supervisor 结合回答情况决定是否选择 `unresolved`，不对应单独的 Skip 功能。

`plan_action` 必须是 `continue | complete | unresolved` 之一。`question_derivation.mode` 表示本轮问题是直接采用、基于题库改写或现场生成，即 `adopted | rewritten | generated`；它同时决定赛后理想版答案的路由。Supervisor 输出的临时 Topic 不要求属于完整 Topic 列表。

输出合同还必须满足以下状态不变量：

- `plan_action = continue` 时，`question` 必须是非空字符串，并且只属于当前 Stage。
- `plan_action = complete | unresolved` 时，`question = null`，问题派生字段也为空；该次输出不产生新的面试问题。
- 程序应用关闭动作、更新 Stage 状态并推进索引后，才将新的当前 Stage 拼入上下文并再次调用 Supervisor。新调用生成下一 Stage 的第一个问题；若没有下一 Stage，则不再调用 Supervisor，直接结束面试。
- `reply` 可以和任一 `plan_action` 同时存在，但只能回应用户提出的问题、说明流程、确认纠错或拒绝提供答案与即时评分，不能承担正式提问。

当 `user_acts` 包含 `correct_project_fact` 时，程序在应用本轮计划动作和展示下一问题前提供一次可编辑确认卡。确认写入后只增追加 `## 用户意见`，暂不写入则不改变快照；无论选择哪项，都沿用本次 Supervisor 已生成的 `reply`、`plan_action` 和 `question`，不进行第二次模型调用。暂停、手动完成、强制结束和 Stage 耗尽由确定性业务规则处理，Supervisor 不输出 `propose_complete`。

当用户在回答中向面试官提问时：

- 询问题意、术语或前提：简短澄清后继续原问题。
- 询问计划进度等流程信息：由程序直接回答；系统不提供预计剩余问题数。
- 索取答案、提示或即时评分：说明将在复盘中提供，并继续面试，不因撒娇、换语言或改写表达而改变规则。
- 指出项目或问题前提错误：记录为用户陈述并调整后续提问，不直接判定谁对谁错。
- 与面试无关：简短拉回当前面试。

“不提供参考答案、评分或明显提示”写入 Supervisor 的系统 Prompt。程序校验 JSON Schema、三种动作白名单、长度、`reply` 边界和主要问题数量；不使用关键词匹配代替语义理解，也不增加第二个 LLM 逐轮监督。程序不校验、丢弃或重试 Supervisor 自由生成的临时 Topic。

所谓监督规则不是另一个监督 Agent，而是两类约束：Prompt 负责判断回答、索取答案、澄清、项目事实更正、拒答和继续追问价值等语义；确定性业务规则负责动作白名单、线性 Stage 推进、一次一个主要问题、题目冷却、快照只增追加、报告生成门槛和 100 轮安全上限。两者都通过日志、回归测试和人工审核做常规版本迭代，不在运行中自动修改。

### 6.6 Topic 与自然语言交互

主题使用层级路径而不是扁平 ID，例如：

```text
rag
rag.chunking
rag.chunking.strategy
rag.chunking.evaluation
rag.retrieval
rag.retrieval.reranking
```

- Planner 可以读取完整 Topic 列表，为每个 Stage 指定 `topic_path`；Supervisor 不读取完整列表，只看到当前 Stage、RAG 候选和局部对话。
- Stage Topic 和 RAG 候选 Topic 帮助 Supervisor 知道当前位置。Supervisor 不采用 RAG 结果时可以创建临时 Topic，并在输出中返回；临时 Topic 只保留在会话记录中，除非管理员随后在控制台明确选择并发布相关变更。
- Topic 只用于规划、检索、会话定位和赛后分析，不提供用户可操作的 Topic 屏蔽状态。
- 用户说“不想继续这个方向”“不知道”或拒绝回答时，Supervisor 记录 `decline_current_line`，并根据继续追问价值选择 `unresolved` 或用 `continue` 做最后一次必要澄清。
- 用户要求换种说法时，Supervisor 将其识别为 `ask_interviewer` 的题意澄清，在 `reply` 中简短解释，并用 `question` 重述当前问题；不创建问题刷新事件或隐藏历史。
- 用户纠正项目事实时，原始消息照常进入对话；只有用户在确认卡中批准的文字才追加到快照。之后所有 Agent 使用最新的已确认快照版本。

### 6.7 赛后答案 Agent

满足报告生成条件后，并行准备两类参考答案：

1. **项目版答案 Agent**按整场处理。它读取当前 `snapshot.md` 与完整面试对话，统一汇总证据缺口；有授权项目目录时可以定向回看文件，只导入 Markdown 时则完全基于处理后的本场快照回答并标记证据不足。即使目录内容与快照不一致，也以快照状态为准。Agent 一次输出所有问题的项目版答案，并可通过程序只增追加 `## 事后核验`。
2. **理想版答案处理**按实际问题的 `question_derivation.mode` 路由。`adopted` 直接读取正式题库中预生成的理想答案；`rewritten` 和 `generated` 针对实际问出的版本现场独立生成。各题相互隔离、可以并发，不读取项目材料、项目版答案或用户评价。

两类处理输出答案要点、允许的合理变体和必要引用。实时面试阶段不生成或检索理想答案，以降低延迟、成本和泄漏风险。

### 6.8 复盘报告

两类参考答案就绪后，每道题启动一个独立的逐题评估 Agent。各题可以并发，也可以单独失败和重试。输入为最终 `snapshot.md`、本题 Q/A、项目版答案和理想版答案；输出只包含自然语言评估结果 `comment` 和 `insufficient_evidence` 标记。`comment` 可以在一段自由文本中说明主要判断、与参考答案的关键差距和最有价值的改进方向，不要求拆成更多结构化字段。

所有逐题结果完成后，报告 Agent 整场运行一次。它只接收最终 `snapshot.md`，以及按原顺序排列并保留 `stage`、`topic` 的 `Q/A/comment`；不再读取两版参考答案，也不重新访问项目目录。报告 Agent 负责：

1. 给出允许一定自由表达的整场总评。
2. 从逐题表现聚合需求理解、系统设计、技术深度、工程质量、故障思维、数据意识、沟通结构和复盘能力八个维度的观察。
3. 去重、归类项目层面的改进建议。
4. 给出下一轮训练主题和训练重点。

任何维度如果缺少足够证据，必须明确说明“没有足够信息做出有效评价”，不能为了填满合同强行判断。能力层只呈现与本次会话相关的观察，不声称是对人的永久评价。

报告 Agent 输出固定 JSON，而不是自行生成最终 Markdown。最小合同为：

```json
{
  "overall": "自由文本总评",
  "dimensions": {
    "requirements_understanding": {"score": 0, "analysis": "自由文本"},
    "system_design": {"score": 0, "analysis": "自由文本"},
    "technical_depth": {"score": 0, "analysis": "自由文本"},
    "engineering_quality": {"score": 0, "analysis": "自由文本"},
    "failure_thinking": {"score": 0, "analysis": "自由文本"},
    "data_awareness": {"score": 0, "analysis": "自由文本"},
    "communication_structure": {"score": 0, "analysis": "自由文本"},
    "retrospection": {"score": 0, "analysis": "自由文本"}
  },
  "project_recommendations": "自由文本",
  "training_recommendations": "自由文本"
}
```

程序只校验这些固定字段是否存在、八个维度是否齐全，以及 `score` 是否为 `0～5` 的整数；不校验正文内容、证据引用、篇幅或结论是否正确。`0` 专门表示证据不足，不是最低能力分；Prompt 要求此时在 `analysis` 中明确说明无法有效评价。

评估输出的结构暂定以此为边界。程序不增加回答证据数组、置信度字段、差距列表、建议列表或逐条追溯 ID；回答依据、差距和建议如果需要，直接写在 `comment` 或报告自由文本中。

UI 使用原始 `0～5` 值绘制雷达图，但不向用户展示数字，也不计算总分、平均分或排名。文字标签由程序固定映射：`1～2 → 需改进`、`3 → 普通`、`4～5 → 优秀`；`0` 单独显示为“证据不足”，并在雷达图中使用灰色或空心样式，避免被理解为能力很差。报告页面固定展示：

> 能力评分由 AI 基于本次面试内容生成，仅供复盘参考，不代表对实际能力的完整评价。

程序从同一 JSON 渲染复盘报告 Markdown，固定生成 `总评`、`能力画像`、八个能力维度、`项目改进建议` 和 `下一轮训练建议` 标题，并填入相应文字。Markdown 不包含内部评分、三级标签、雷达图或上述 UI 评分说明。

最终界面包含两个页签：

- **复盘报告**：报告 Agent 的总评、能力画像、项目建议和训练建议。
- **完整问答**：程序按 Stage 组装问题、用户回答、项目版答案、理想版答案和逐题 `comment`，不要求报告 Agent 重复生成这些内容。

两个结果都支持独立导出为 Markdown。完整问答的导出与页面结构和顺序一致，并保留 Stage、Topic 及必要的来源关联；复盘报告导出为上述 JSON 的纯文字视图，明确排除只用于 UI 的评分与雷达图。

### 6.9 题库迭代与对话配置演进

本节只说明控制台如何使用会话材料以及审核通过后产生哪类变更，不规定会话材料最终落在哪种存储、保存多久或如何恢复。控制台的数据来源、LangGraph checkpoint 与业务状态如何分工、事务边界和未完成编辑是否保存，统一留给运行时持久化方案决定。

Supervisor 实际问出的问题、用户回答、临时 Topic 和用户反馈是管理员判断是否需要维护题库或对话配置的材料，但它们首先只属于原会话。完成面试不会自动创建正式题目，也不会把临时 Topic、用户回答或生成题加入任何运行时检索索引。

这里所谓的“用户行为”主要指每条用户消息经过 Supervisor 识别后得到的 `user_acts`，例如回答、要求澄清、纠正项目事实、不愿继续当前讨论、索取答案或提出流程问题。它的用途是让控制台结合计划动作、快照同步确认结果和用户后续纠正，发现行为类型缺失、语义误判或规则冲突，而不是给用户建立画像。逻辑上它属于每轮 Supervisor 决策；物理上是否单独建表由运行时持久化方案决定。好评和差评属于另一类题目反馈事件，用途是题目质量筛查，不能与 `user_acts` 混为一谈。

每轮只保留面试本身需要的最小关联：正式题库 ID、`adopted | rewritten | generated` 派生关系、实际 Topic 和用户反馈事件。控制台可以由这些会话事件派生展示：

- **选用次数**：某道正式题被 Supervisor 直接采用或据其改写的次数，用于发现过度集中、长期未被采用或可能需要维护的题目，不代表质量分。
- **好评**：用户认为实际问出的题目有价值，作为管理员优先查看的正向信号。
- **差评**：用户认为实际问题重复、不相关、表述不清或存在其他问题，作为管理员优先排查的负向信号。

这些数字是从会话与反馈事件汇总出的控制台视图，不是题目正文的元数据，也不自动改变检索权重、发布状态或删除状态。低使用频率不等于低质量，单次好评或差评也不能直接触发线上变更。

面试界面在每道问题旁提供两个轻量入口：

- **好评**：表示这道题有价值，只产生反馈事件并在控制台提高查看优先级。MVP 不提供个人收藏夹，因此不使用“收藏”命名。
- **差评**：表示这道题在当前语境下存在问题，可选“重复、不相关、表述不清、其他”原因，只产生反馈事件并在控制台提高排查优先级。

“不想继续当前讨论”由 Supervisor 识别为 `decline_current_line`，不能当成题目差评。系统也不根据低使用频率自动清理题目：冷门、小众问题可能只适用于少数项目，低频不等于低质量，过时与否也不能仅由热度判断。

面试结束后，管理员控制台负责从会话材料中主动选择需要继续处理的内容，并按以下流程完成审核与发布：

1. 从原会话中选择实际问题或 Q/A 作为参考材料；原始用户回答不会直接成为公共题库内容。
2. 删除或泛化私有项目名、业务数据、人员和实现细节；无法安全泛化的内容继续留在私有会话中。
3. 将问题整理为脱离原项目仍可复用的题目正文，并与正式题库查重。
4. 补充正式题目所需的 `topic_path` 和可选理想答案，由程序生成题目向量。
5. 管理员查看原会话引用、编辑结果、隐私处理结果和查重结果，点击发布后才原子地创建新的正式题目及版本。

点击发布之前，所选材料仍只是管理员正在处理的会话材料，不属于题库，也不会被面试 RAG、Planner 或 Supervisor 读取。题库整理 Agent 只能提供改写、隐私处理和查重建议，无权自行发布。控制台是否保存未完成的编辑进度，等待运行时持久化方案确定后再设计，不在当前文档中预设新的产品实体。

控制台分析会话数据后，可以提出两类性质不同的候选变更：

1. **软件与对话配置迭代**：包括 Planner Prompt、Supervisor Prompt、`user_acts` Schema、Topic 列表、Planner 参考模板、监督规则，以及需要修改的确定性业务逻辑。管理员从误判、越权输出、重复追问、快照同步误识别和用户纠错案例中选择证据，决定是修改文案或配置，还是修改硬编码规则。变更必须经过固定样本回放、回归测试、人工审核和版本发布，性质与软件更新相同；运行时分析结果不能直接改写线上 Prompt、Schema、模板或代码。
2. **题库与 RAG 知识更新**：管理员从会话问题或 Q/A 中选择值得复用的材料，完成泛化、隐私处理、查重、`topic_path`、可选理想答案和向量补充，点击发布后写入正式题库并更新检索索引。这是知识库内容发布，不要求随软件版本一起发布，也不能反向修改 Prompt、Planner 模板或业务规则。

两条通道可以来源于同一场会话，但审核对象、发布动作和生效位置不同。行为 Schema、Topic、Prompt 和硬编码规则不根据运行数据自动扩张或自动替换；会话 Q/A 也不因被控制台分析而自动进入 RAG。

## 7. 多 Agent 编排

### 7.1 角色

| 角色 | 主要输入 | 主要输出 | 是否面向用户 |
| --- | --- | --- | --- |
| 项目观察 Agent | 脱敏后的授权项目材料 | `snapshot.md` | 间接 |
| Markdown 范围解析器 | `snapshot.md` | Module、Thread 复选项 | 是 |
| 面试规划 Agent | 完整快照、用户范围、方向、完整 Topic 列表 | 有序 Stage 列表 | 间接 |
| 计划动作服务 | 当前 Stage、Stage 结果 | 固定三动作菜单与线性推进 | 否 |
| 题库 RAG Hook | 完整快照、当前 Stage、会话状态 | 1～3 条候选问题及 Topic | 否 |
| Supervisor Agent | 完整快照、当前 Stage、动作菜单、历史对话、题库候选 | `user_acts`、可选 `reply`、计划动作、Topic 和一个主要问题 | 是 |
| 快照更正确认 | `correct_project_fact` 候选文字 | 编辑后写入或暂不写入 | 是 |
| 题库整理 Agent | 管理员从已完成会话中选中的问题、Q/A 和反馈 | 改写、隐私处理和查重建议；无发布权限 | 否 |
| 项目版答案 Agent | 当前快照、完整对话、可选授权目录 | 全部项目版答案、`## 事后核验` | 结束后 |
| 理想版答案处理 | 问题、派生模式、题库答案或一般背景 | 各题理想版答案 | 结束后 |
| 逐题评估 Agent | 最终快照、本题 Q/A、两版答案 | `comment` | 结束后 |
| 报告 Agent | 最终快照、按序的 `stage/topic/Q/A/comment` | 固定 JSON：总评、八维评分与分析、项目建议和训练建议 | 是 |

### 7.2 状态机

MVP 使用 LangGraph 实现下列显式状态机。用户回答以及条件式快照更正确认通过 interrupt 暂停与恢复；每轮先提供固定动作菜单，再由题库 RAG Hook 召回候选并进行一次 Supervisor 调用。快照确认后沿用该次调用已经生成的决策，不二次调用 Supervisor。LangGraph 负责编排，当前会话状态和产物仍以应用状态为准；checkpoint、业务状态和持久化存储之间的具体分工仍待运行时持久化设计确认。

```text
SOURCE_SELECTION
  ├─ project_directory → PROJECT_OBSERVATION → SNAPSHOT_REVIEW
  └─ imported_snapshot + optional_directory → SNAPSHOT_REVIEW
  → OPTIONAL_USER_OPINION_APPEND
  → SNAPSHOT_CONFIRMED
  → RANGE_PARSE_AND_SELECT
  → INTERVIEW_PLANNING(linear_stages)
  → LOAD_AND_RENDER_CURRENT_STAGE

LOAD_AND_RENDER_CURRENT_STAGE
  → PLAN_ACTION_MENU
  → QUESTION_RAG_HOOK
  → SUPERVISOR_DECISION
      ├─ correct_project_fact → REVIEW_SNAPSHOT_APPEND → APPLY_SUPERVISOR_DECISION
      └─ no_snapshot_correction → APPLY_SUPERVISOR_DECISION

REVIEW_SNAPSHOT_APPEND
  ├─ confirm_or_edit → APPEND_USER_OPINION → APPLY_SUPERVISOR_DECISION
  └─ do_not_write → APPLY_SUPERVISOR_DECISION

APPLY_SUPERVISOR_DECISION
  ├─ continue + question → SHOW_OPTIONAL_REPLY → ASKING
  ├─ complete | unresolved + question=null → SHOW_OPTIONAL_REPLY → APPLY_STAGE_RESULT → ADVANCE_STAGE_INDEX
  │      ├─ remaining_stage → LOAD_AND_RENDER_CURRENT_STAGE
  │      └─ no_remaining_stage → FINALIZING
  └─ invalid_output → RETRY_OR_FAIL_CURRENT_TURN

ASKING
  └─ user_message → USER_INPUT_RECEIVED → LOAD_AND_RENDER_CURRENT_STAGE

FINALIZING
  → PARALLEL_REFERENCE_ANSWERS
      ├─ whole_session_project_answers + append_post_verification
      └─ routed_ideal_answers(adopted | rewritten | generated)
  → PARALLEL_PER_QUESTION_EVALUATION
  → REPORT_GENERATION
  → REPORT_READY

ASKING / PAUSED
  ├─ user_complete + completed_stage_count >= 1 → FINALIZING
  ├─ user_complete + completed_stage_count = 0 → COMPLETED_WITHOUT_REPORT
  └─ user_force_exit → ABORTED_WITHOUT_REPORT

ASKING
  └─ user_pause → PAUSED → user_resume → PLAN_ACTION_MENU

ANY_ACTIVE_INTERVIEW
  └─ hard_cap(100 real QA)
      ├─ completed_stage_count >= 1 → FINALIZING(termination_reason=safety_cap)
      └─ completed_stage_count = 0 → COMPLETED_WITHOUT_REPORT
```

全部 Stage 正常走完时始终进入赛后分析。手动完成和安全停止按 `completed_stage_count` 决定是否生成报告；强制结束永远不触发赛后分析。完成会话后可以异步触发题库与临时 Topic 整理，不阻塞报告生成。

### 7.3 上下文管理与隔离

- 系统跨项目无状态，不自动长期缓存快照或把某个项目的分析复用于另一个项目。每场会话使用本次生成或导入的完整 `snapshot.md`；是否以及如何持久化由运行时持久化方案决定。
- Supervisor 上下文固定为系统 Prompt、完整快照、当前 Stage、动作菜单、1～3 条 RAG 候选和历史对话。它不能读取源文件，也看不到赛后答案和评价。
- 历史对话每 20 个真实 Q/A 轮次做一次累计 compact；快照确认卡不作为对话消息，也不计入轮次。
- Planner 看完整 Topic 列表；Supervisor 只看当前 Stage、RAG 候选及局部对话，不读取完整 Topic 树。
- 项目版答案上下文是当前快照、完整对话和可选的授权目录；不能访问理想版答案。它按整场生成答案并形成最终快照。
- 理想版答案上下文按题隔离，只包含实际问题和必要的一般背景，或直接读取 `adopted` 原题的预生成答案；不能访问项目材料、项目版答案和用户评价。
- 逐题评估上下文是最终快照、本题 Q/A 和两版答案；各题之间不共享上下文，可以并发和单独重试。
- 报告上下文是最终快照和按顺序排列的 `stage/topic/Q/A/comment`；不包含两版参考答案，也不能重新读取项目目录。

所有 Agent 输出使用 JSON Schema 校验。原始自然语言输出不得直接驱动数据库写入或状态跳转。

## 8. 技术架构

### 8.1 逻辑架构

```text
Local Web Client
   │ localhost
Local Agent / FastAPI Service
   ├── Project Ingestion Pipeline
   │      ├── File inventory & sensitive content filter
   │      ├── Parser / symbol extractor / repository map
   │      ├── Restricted read-only Observer tools
   │      └── Iterative Markdown snapshot observer / reviewer / importer
   ├── Scope Parser & Interview Planning
   │      ├── Markdown heading parser
   │      ├── Topic registry for Planner
   │      ├── Planning template library / retriever
   │      └── linear Stage plan / three-action menu
   ├── Interview Orchestrator
   │      ├── Question RAG Hook
   │      ├── Supervisor
   │      └── Stage state / snapshot correction confirmation
   ├── Post-interview Analysis
   │      ├── Project-grounded Answerer
   │      ├── Ideal Answer Router / Generator
   │      ├── Parallel Per-question Evaluators
   │      └── Whole-session Report Generator
   ├── Administrator Curation Console
   │      ├── persisted sessions / derived signals
   │      ├── software & dialogue configuration proposals
   │      └── question curation / explicit RAG publish
   ├── Retrieval Service
   │      ├── Question bank
   │      ├── Pre-generated ideal answers
   │      └── Hybrid question search / rerank
   └── Evaluation & Observability
          ├── traces / prompt versions
          ├── offline eval runner
          └── feedback events

Runtime Persistence (TBD)   Question RAG Storage / Index   Object Storage   Optional Redis/Queue

Local Agent ── filtered, redacted, selected text ──> Cloud LLM APIs
```

本地 Agent 是项目目录读取、文件清单、排除、解析、敏感信息检测与替换的执行边界。Web 层只通过 localhost 上的 FastAPI 调用本地能力；云端模型服务只接收经过本地过滤、脱敏和上下文选择后的文本，不获得本地目录权限，也不能主动读取用户文件。

管理员控制台需要读取运行时持久化方案提供的会话材料和派生信号，但本节不预设其具体存储边界。控制台产生的软件/对话配置候选经回归和版本发布后进入应用配置或代码；题库候选经人工发布后进入正式题库和检索索引。两者不共用一条自动发布链路。

### 8.2 建议技术选型

以下是首版候选技术选型；目前只确定编排层使用 LangGraph，运行时持久化相关项仍需专项确认：

| 层 | 建议 | 原因 |
| --- | --- | --- |
| Web | Next.js + TypeScript，本地运行 | 会话 UI、报告页和本地 Agent 交互可放在一个工程中 |
| API | 本地 Python + FastAPI | 作为 UI 到本地 Agent 的 localhost 接口，承载目录读取、模型调用、检索和评估编排 |
| 编排 | LangGraph + 显式业务状态机 | 支持暂停、恢复、条件式快照确认和赛后并行分析；业务状态的持久化方式另行确定 |
| 敏感信息过滤 | `detect-secrets` + 少量自定义规则 | 用正则、关键词和熵检测覆盖常见凭据，不增加 LLM 调用 |
| 主数据库 | PostgreSQL（当前候选，未定） | 会话、面试计划、题库、逐题评估、版本和审计关系清晰；是否作为运行时事实来源等待持久化方案确认 |
| 向量检索 | pgvector（当前候选，未定） | MVP 可减少基础设施；需与题库发布和运行时持久化方案一起确认 |
| 关键词检索 | PostgreSQL FTS（当前候选，未定） | 可与 pgvector 组成低运维成本的混合检索 |
| 对象存储 | S3 兼容存储；本地开发用文件目录 | 按需保存用户明确导出的快照、报告和其他产物 |
| 异步任务 | MVP 使用进程内任务或数据库任务表；规模化后用队列 | 避免过早引入 Redis/Celery 运维成本 |
| 模型接入 | 供应商无关 Adapter + 首版验证过的高质量云端模型 | 产品 quality-first；Adapter 为未来供应商和部署方式保留接口，但不代表本地模型已经适配 |
| 上下文管理 | 完整 Markdown + 每 20 轮累计 compact | 不做项目级长期缓存，只控制单场会话历史长度 |
| 可观测性 | OpenTelemetry 风格 trace + 结构化事件 | 串联每轮检索、提示词版本、模型输出和延迟 |

### 8.3 关键数据实体

以下是产品逻辑中需要表达的数据关系，不代表已经决定对应的物理表、数据库或 checkpoint 划分；这些实现细节属于运行时持久化方案。

- `users`：User、Administrator 两类角色及其偏好；具体权限矩阵仍需补充。
- `source_authorizations`：本场获准读取的本地目录和范围；不存在目录时为空。
- `interview_sessions`：方向、范围、当前快照文本、状态、开始结束时间和终止原因。
- `interview_plans`：本场有序 Stage、当前索引和各 Stage 结果；完成 Stage 数量即时派生。
- `topics`：供 Planner 和题库使用的完整 Topic 列表；不整体暴露给 Supervisor。
- `planning_templates`：经过审核、版本化的参考提问路径、适用条件、Stage 原型、顺序关系和 Topic 提示。
- `questions`：正式题目的稳定身份与发布状态；只有已发布题目进入面试 RAG。
- `question_versions`：不可变的题目正文、`topic_path`、题目向量和可选预生成理想答案。
- `interview_turns`：问题、回答、可选 `reply`、Stage、Topic、时间和引用。
- `supervisor_decisions`：每轮的 `user_acts`、`plan_action`、Topic、实际问题、题库派生关系和模型版本；它也是控制台分析行为识别正确率的主要逻辑来源，是否拆分物理表等待运行时持久化方案确定。
- `reference_answers`：隔离存储的项目版与理想版答案。
- `question_evaluations`：可独立重试的逐题 `comment`、证据不足标记和模型版本。
- `reports`：报告 Agent 的结构化 JSON、版本、UI 渲染状态与 Markdown 导出位置。
- `feedback_events`：针对实际问题的好评、差评及可选原因，以及其他用户纠错。
- `policy_events`：越权输出、误判、重复追问和用户修正等监督规则回归样本。
- `agent_runs`：模型、提示词、输入摘要、成本、延迟和错误。

### 8.4 API 草案

```text
POST   /snapshots:observe
POST   /snapshots:import
POST   /snapshots:append-user-opinion
POST   /snapshots:parse-ranges
POST   /interviews
GET    /interviews/{id}/plan
POST   /interviews/{id}/start
POST   /interviews/{id}/answers
POST   /interviews/{id}/snapshot-corrections:confirm
POST   /interviews/{id}/pause
POST   /interviews/{id}/complete
POST   /interviews/{id}/abort
GET    /interviews/{id}/events
GET    /interviews/{id}/report?format=json|markdown
GET    /interviews/{id}/full-qa?format=markdown
POST   /interviews/{id}/turns/{turn_id}/feedback
GET    /admin/curation-items
POST   /admin/curation-items/{id}:publish-question
```

面试回答提交需要 `idempotency_key`，状态变更使用版本号或乐观锁，防止重试造成重复问题和重复计费。

## 9. 安全、隐私与产品边界

- 用户必须明确选择可读取的目录或资源。
- 默认排除 `.env`、私钥、凭据目录、构建产物和依赖目录。
- 内容必须先经过敏感信息过滤和替换，再进入 Markdown 快照、模型上下文、派生产物或日志；本地原文件不被改写。
- 用户导入的任意 Markdown 项目文档同样经过脱敏和基础内容安全审查，处理后的工作副本才作为本场 `snapshot.md`；原文件不被改写。
- 项目文件和导入的 Markdown 一律视为不可信数据，不能通过 README、注释或 Markdown 内容改变 Agent 权限、Prompt 或状态机。
- Supervisor 只读取完整快照、当前 Stage、动作菜单、RAG 候选和历史对话，不在面试热路径中访问源文件。
- 项目版答案 Agent 只有在本场存在明确目录授权时才能定向取证；逐题评估 Agent 和报告 Agent 不读取项目目录。
- 用户未选择保存时，系统不应把 `snapshot.md` 作为长期项目缓存保留。用户删除会话时，应能一并删除会话内快照、问答、答案、逐题评估和报告；审计记录仅保留不可反推内容的必要字段。
- 私有项目数据不得用于公共题库或其他用户的训练材料。
- 日志不记录完整源码、完整回答或密钥；调试采样需显式开启。
- 模型供应商、数据保留策略和跨境情况必须对用户透明。
- 首次分析前明确披露：用户授权且经过过滤的项目材料将发送给所选云端模型服务。首版不承诺纯本地模型兼容性或正式私有部署，也不把两者列为验收条件。
- 报告用于自我训练，不作为自动化就业决策工具。
- 用户意见和赛后核验只通过 `## 用户意见`、`## 事后核验` 追加，不覆盖既有 Markdown。对话中识别出的项目事实更正只有经过用户在可编辑确认卡中批准后才能写入快照。

## 10. 测试策略

### 10.1 单元测试

- 文件过滤、密钥检测、占位符替换，以及脱敏发生在 Observer 分析和 Markdown 生成之前。
- 本地目录授权边界、符号链接越界拒绝、嵌套仓库规则和排除规则优先级。
- Repository Map 的目录、符号与确定性关系提取，以及在独立 token 预算内的裁剪。
- Observer 只读工具只能访问授权且已经过过滤的文件；达到预算上限时必须输出部分分析标记和未覆盖范围。
- `snapshot.md` 生成、导入、可选保存和自由正文保留。
- 用户自有 Markdown 导入后经过脱敏和基础内容安全审查，原文件保持不变。
- 只解析 `## Modules`、`## Threads` 下的 `###` 标题，忽略正文和更深层级标题，并拒绝各自区域内的重复标题。
- 范围解析为空时显示非常规文档警告；用户确认后以完整 Markdown 直接进入 Planner，取消时不创建计划。
- `## 用户意见` 与 `## 事后核验` 只增追加，不重写已有 Markdown。
- 线性 Stage 计划至少 5 项，且通过字段、`scope_refs`、正式 `topic_path`、参考模板版本、顺序加载和当前索引推进校验。
- Planner 首次输出不合法时只进行有界修复；修复仍失败时不得静默使用未经审核的通用计划。
- `continue | complete | unresolved` 三动作白名单及其状态结果。
- `completed_stage_count` 从 Stage 结果即时计算，不作为独立状态写入。
- RRF、过滤、去重和覆盖率计算。
- 每轮 RAG Hook 返回 1～3 条候选，并排除最近 3 轮处于冷却期的题目。
- `user_acts`、可选 `reply`、`plan_action`、Topic、单一主要问题和临时 Topic 的 Schema 校验。
- 同一消息中的 `answer`、`ask_interviewer`、`correct_project_fact` 和 `decline_current_line` 可以同时出现，不按互斥单意图处理。
- `correct_project_fact` 只有在用户确认或编辑后才追加到 `## 用户意见`；暂不写入不改变快照，两个分支都不得触发第二次 Supervisor 调用。
- `question_derivation` 的 adopted、rewritten、generated 三类关系及关联题目 ID 校验。
- 每 20 个真实 Q/A 轮次将“旧 compact + 新 20 轮”折叠为单一累计 compact。
- `reply` 不得包含新的面试问题；要求澄清或换种说法时，当前问题的重述仍只出现在 `question`。
- 快照确认卡不进入对话历史，也不计入真实 Q/A 轮次。
- Stage 耗尽自动结束，不存在 `propose_complete` 或结束确认。
- 手动完成、强制结束和 100 轮安全停止的报告生成门槛。
- 面试状态机的合法与非法跳转。
- 暂停、恢复、重试和幂等行为。
- `adopted` 只在赛后读取预生成理想答案，预生成答案不得进入 RAG 结果。
- 逐题评估可独立重试；报告 Agent 输入不包含两版参考答案。
- 项目改进建议的跨题去重和来源保留。
- 报告 JSON 的固定字段、八个维度和 `0～5` 整数范围校验；正文内容不做程序校验。
- UI 将 `1～2`、`3`、`4～5` 分别映射为“需改进”“普通”“优秀”，将 `0` 显示为“证据不足”，且不计算总分。
- 复盘报告 Markdown 固定生成所需标题和文字内容，但不包含内部评分、三级标签、雷达图或 UI 评分说明。

### 10.2 集成测试

- 小型固定仓库从目录授权到 `snapshot.md`、用户意见追加、范围解析和线性计划的完整链路。
- 大型固定仓库能够先生成 Repository Map，再通过多次定向读取形成快照；未读目录不会被描述成已完整分析。
- 只导入 Markdown 时不允许赛后读取源文件；同时授权目录时允许项目版答案 Agent 定向取证。
- 没有可解析 Module/Thread 的自有 Markdown 经用户确认后能够跳过范围多选，并由 Planner 基于整份文档生成 Stage。
- 快照与目录不一致时不触发自动同步，并以快照状态作为回答基线。
- 五类面试方向和不同范围能够生成不同的 Stage 计划。
- 大量模板中能够根据方向、范围和项目特征召回相关参考路径；最终计划可以组合模板，但不会照抄固定问题。
- Planner 生成的每个 Stage 都能追溯到合法范围，错误的范围引用、Topic 或额外分支字段会触发修复或明确失败。
- 选定关键词与向量存储方案后的混合检索、过滤和故障降级。
- 模型 Adapter 的超时、限流、空输出和格式错误。
- 面试热路径不得调用项目目录读取、参考答案 Agent、逐题评估 Agent 或报告 Agent。
- 项目版整场答案与各题理想版答案并行完成顺序不同的竞态测试。
- 项目版与理想版答案的输入上下文相互隔离；两类答案和评价内容不得进入 Supervisor 上下文。
- 项目版答案 Agent 只增追加 `## 事后核验`，逐题评估统一读取追加后的最终快照。
- 多个逐题评估并发运行，单题失败可单独重试，不重复生成其他题结果。
- 报告 Agent 只读取最终快照和按序的 `stage/topic/Q/A/comment`，不读取两版参考答案，并输出可同时驱动 UI 与 Markdown 的固定 JSON。
- 复盘报告 UI 展示八维雷达图、三级标签和固定参考说明；Markdown 导出只包含文字报告，二者来自同一份 JSON。
- Supervisor 只能选择三种合法动作，非法动作不能推进 Stage。
- 明确项目事实更正经用户确认或编辑后只追加 `## 用户意见`，不覆盖已有快照，从下一轮进入 Supervisor 上下文，并且整个用户轮次仍只调用一次 Supervisor。
- 用户拒答、希望结束当前讨论或要求换种说法时，只通过 `user_acts`、`reply` 和三动作菜单处理，不产生额外控制事件。
- 第 20、40、60 轮后的累计 compact 不丢失当前 Stage 所需信息；完整原文仍可用于恢复和赛后分析。
- 正常走完、手动完成、强制结束和安全停止分别触发正确的报告分支。
- 未经管理员选择的会话 Q/A 不进入题库整理；题库整理只能处理管理员选中的材料，不能自动发布。
- 管理员点击发布前不会创建正式题目或线上检索索引。
- 删除会话后检查会话内快照、问答、两版答案、逐题评估和报告是否完整清除。

### 10.3 端到端测试

建立 5～10 个不同类型的“黄金项目包”，每个包含：

- 固定代码和文档。
- 人工审阅的 `snapshot.md`、Module/Thread 标题、项目事实、合理推断和未知项。
- AI 软件开发面试方向、范围、预期 Stage 和允许动作。
- 多档用户回答脚本。
- 预期追问行为和报告要点。

覆盖正常完成、Stage 未解决推进、用户纠错与快照同步确认、拒答、要求换种说法、长回答、矛盾回答、只有快照无目录、中途暂停、模型失败、混合“回答 + 提问”、多语言索取答案和异常循环安全停止。

### 10.4 Prompt 与模型回归测试

- 每次变更提示词或模型前运行固定样本集。
- 结构化输出成功率必须达到发布门槛。
- 验证用户以不同语言、撒娇、角色指令或间接表达索取答案时，Supervisor 仍不提供答案、提示或即时评分。
- 验证正常回答末尾附带提问时，回答内容和用户提问能够同时被识别。
- 验证每轮只产生一个主要问题，且主题切换请求得到尊重。
- 验证 Supervisor 不选择三动作菜单以外的路径，也不自行提议结束整场面试。
- 验证满足 `complete_when` 时能够推进，回答不充分但继续追问价值不大时能够选择 `unresolved`。
- 验证同一句话中的回答、提问、项目事实更正和拒答能够并行识别；更正确认不触发第二次模型调用。
- 比较问题相关性、重复率、无依据主张率和评分一致性。
- 对关键指标做成对比较；未通过门槛不得仅凭“感觉更自然”上线。

### 10.5 安全测试

- 项目文件中的 Prompt Injection 不得改变系统权限或泄露其他材料。
- 恶意 README 不得指挥 Agent 忽略规则、调用未授权工具或上传代码。
- 使用含测试密钥、个人信息和版权材料的夹具验证过滤与脱敏。
- 验证被识别的敏感值不会出现在 `snapshot.md`、模型请求、问答产物、日志或报告中。
- 验证跨用户、跨项目、跨会话数据隔离。

## 11. 评估方法

评估分为离线质量、在线体验和系统性能三层。

### 11.1 Markdown 项目快照质量

| 指标 | 定义 |
| --- | --- |
| Fact precision | 快照中作为事实表述的内容里，确有证据支持的比例 |
| Fact recall | 黄金事实中被系统识别的比例 |
| Citation validity | 引用位置真实存在且支持对应表述的比例 |
| Inference calibration | 不同置信度区间与人工认可率的一致程度 |
| Unknown usefulness | 未知项中被专家认为值得面试追问的比例 |
| Module coverage | 黄金关键模块中被识别并正确描述职责的比例 |
| Thread coverage | 黄金端到端链路中被识别且步骤、模块关系基本正确的比例 |
| Range parse accuracy | `## Modules`、`## Threads` 下的合法 `###` 标题被正确转成范围选项的比例 |
| Human edit burden | 用户确认快照前需要补充或纠正的内容规模 |

MVP 优先保证 Precision 和 Citation validity，不用虚假的“完整”换取 Recall。

### 11.2 检索质量

- `Recall@K`：黄金相关题是否进入候选集。
- `nDCG@K`：高相关问题是否排在前面。
- 计划适配率：候选问题是否适用于当前 Stage、目标和允许动作。
- 重复率：语义相近问题在同一会话重复出现的比例。
- 信息增益：问题是否引出新的项目事实、取舍或缺口。

### 11.3 Supervisor 面试质量

由人工使用 Rubric 盲评：

- 与项目和岗位的相关性。
- 追问是否基于上一轮回答。
- 是否一次聚焦一个主要问题。
- 是否保持问题深度递进和对话连续。
- 是否始终从三种合法动作中选择，并按照线性计划继续或推进。
- Stage 是否被明确记录为 `complete` 或 `unresolved`，而非静默遗漏。
- 是否尊重纠错、拒答和未知边界。
- 是否根据 Stage、RAG 候选和局部上下文正确使用 Topic。
- 是否正确拆解同一消息中的多个 `user_acts`，并只在用户确认后把项目事实更正追加到快照。
- `reply` 是否只回应用户问题或说明边界，没有偷偷增加第二个面试问题。
- 是否出现暗示答案、虚构事实或循环追问。

### 11.4 回答评估质量

- 与专家评分的等级一致率和加权 Kappa。
- 反馈中的证据可定位率。
- 同一回答多次评估的稳定性。
- 对不同表达风格的公平性测试。
- “不知道”与胡编回答的区分能力。
- 证据不足时正确拒绝给出逐题结论或能力判断的比例。

评分模型只能辅助形成反馈。MVP 使用八个维度的 `0～5` 内部评分丰富 UI，但不展示数字、不计算总分，更重视维度分析和建议质量；`0` 只代表证据不足。

### 11.5 报告价值

用户在复盘后回答：

- 哪些反馈是新的、可信的、可执行的。
- 是否能据此改写答案或补充项目证据。
- 项目改进建议是否符合项目边界，是否减少了用户逐题整理的工作。
- 下一轮是否减少同类遗漏。

关键行为指标包括报告查看率、逐题展开率、建议采纳标记、7 日内复练率和同主题前后表现变化。

### 11.6 系统指标

- 首题等待时间。
- 每轮 P50/P95 响应时间。
- 面试热路径每轮模型调用次数。
- 快照生成、Markdown 范围解析和计划生成耗时。
- 每场 Stage 完成与未解决分布、非法动作率和 100 轮安全上限触发率。
- 历史对话累计 compact 的成功率与信息保留率。
- 赛后局部证据请求次数。
- 逐题评估并发度、单题重试率和整场完成耗时。
- 面试恢复成功率。
- 结构化输出失败率。
- 每场模型调用次数与成本。
- 导入成功率和敏感文件过滤率。

## 12. MVP 范围与验收标准

### 12.1 MVP 范围

- 单个 User 使用者、本地项目目录或已有 `snapshot.md`、中文文本面试，并提供独立的 Administrator 控制台角色。
- 代码与文档导入、敏感信息过滤，生成可审阅、可选保存和可再次导入的 `snapshot.md`；也支持导入用户自己的 Markdown 项目文档，并在范围解析为空时经确认降级为整份文档规划。
- 一套人工整理并审核的 AI 软件开发基础题库；正式原题可保存不参与 RAG 的预生成理想答案。
- 项目导览、核心链路深挖、横切专项、压力面试、贡献与复盘五种方向，以及全项目、Module、Thread 或专项主题范围。
- 从 Markdown 标题即时生成范围复选项，并基于方向与范围生成线性 Stage 计划和三动作菜单。
- 一套经过人工整理和审核的 Planner 参考模板库；每份正常计划至少包含 5 个 Stage。
- 不预估或承诺面试长度；全部 Stage 走完后自动结束，100 个真实 Q/A 是内部异常安全上限。
- 面试规划、题库 RAG Hook、Supervisor、项目版答案、理想版答案、逐题评估和报告等核心角色中，面试热路径只有 Supervisor 调用模型。
- 层级 Topic、Supervisor 临时 Topic，以及用于规划、检索、会话定位和赛后分析的 Topic 记录。
- 连续面试上下文、每 20 轮累计 compact，以及只增追加的 `## 用户意见`、`## 事后核验`。
- 可扩展的 `user_acts`、可选 `reply`，以及项目事实更正的可编辑快照同步确认卡；拒答、换种说法和流程提问都在自然对话中处理。
- 每道实际问题的好评和差评入口；使用次数、好评和差评只作为控制台汇总信号，改写题与生成题不会自动创建正式题目或入库。
- 整场项目版答案、按来源路由的理想版答案、并发逐题评估、整场报告，以及“复盘报告/完整问答”两个页签及各自的 Markdown 导出。
- 管理员从会话材料中选择条目、编辑并查看隐私处理与查重结果，再人工发布；点击发布前不创建题库记录或 RAG 索引。
- 控制台基于运行时持久化方案所提供的会话材料，分别产生软件/对话配置候选和题库/RAG 候选；具体存储技术和数据边界不在本节确定。

### 12.2 MVP 验收标准

在黄金项目包上：

- 事实引用有效率不低于 95%。
- 不允许出现跨项目证据泄露。
- 参考答案、事实核验和评分信息进入 Supervisor 上下文的次数为 0。
- 面试热路径不得触发源文件局部检查或读取预生成理想答案；每轮除题库检索外只调用一次 Supervisor 模型。
- 已识别的敏感值进入 `snapshot.md`、模型上下文、派生产物、日志或报告的次数为 0。
- 合法 `snapshot.md` 的 Module/Thread 标题解析准确率为 100%；正文和更深层级标题不得误生成范围选项。
- 无可解析范围的 Markdown 必须先获得用户继续确认，才可按整份文档进入 Planner。
- Planner 的正常输出必须至少包含 5 个 Stage，并记录参考模板版本和模板 ID；模板内容不得作为固定问题直接进入计划。
- 用户意见和事后核验对既有 Markdown 的覆盖或原地修改次数为 0。
- 至少 90% 的会话能在模型单次失败后恢复，而不重复记账或重复提问。
- 人工评审认为“与项目相关”的问题比例不低于 85%。
- 同一会话语义重复题比例低于 10%。
- Supervisor 选择 `continue | complete | unresolved` 以外动作的次数为 0；输出 `propose_complete` 的次数为 0。
- 未经用户确认的 `correct_project_fact` 写入 `snapshot.md` 的次数为 0；确认卡导致同一用户轮次发生第二次 Supervisor 调用的次数为 0。
- 用户要求澄清、换种说法或拒绝继续当前讨论时，不得创建独立控制事件或隐藏问题历史。
- 全部 Stage 走完后自动进入报告流程；手动完成、强制结束和安全停止严格遵守对应报告门槛。
- 正常测试会话触发 100 轮安全上限的次数为 0。
- 单次差评和低使用频率不得自动删除或降权题目，任何正式题库变更都需要人工批准。
- 未经管理员明确发布的会话问题、回答和临时 Topic 创建正式题库记录的次数为 0。
- 管理员点击发布前，相关内容进入题库 RAG、Planner 或 Supervisor 上下文的次数为 0。
- 报告中的能力判断必须以本场用户回答为依据，可以直接写在自由文本 `analysis` 中，不要求额外输出结构化回答引用。
- 没有足够信息的逐题反馈或能力维度必须明确标记证据不足，不得强行评价。
- 报告 Agent 输入中出现项目版或理想版参考答案的次数为 0；它只接收最终快照和 `stage/topic/Q/A/comment`。
- 报告 UI 必须展示八维雷达图、三级文字标签和“评分仅供参考”的固定说明；不得展示内部数字或聚合总分。
- Markdown 复盘报告必须包含固定文字标题，且内部评分、三级标签、雷达图和 UI 评分说明出现次数为 0。
- 报告中的项目改进建议必须基于最终快照、面试问答或逐题 `comment`，但不要求额外输出逐条追溯字段。
- 用户可以分别导出最终 `snapshot.md`、Markdown 格式的完整问答和 Markdown 格式的复盘报告，并删除会话及其派生数据。

这些数值是首版工程门槛，需在积累真实样本后重新校准。

## 13. 分阶段开发计划

### Phase 0：可行性原型

- 使用 2～3 个固定项目验证 Repository Map、Observer 迭代读取、`snapshot.md` 的生成质量、标题解析和自由正文边界。
- 建立首批经过审核的 Stage 路径模板库和规划样例，以及 100～300 道带 Topic、适用 Stage 和预生成理想答案的种子题。
- 用命令行跑通“目录观察或快照导入—用户意见—范围选择—Stage 计划—面试—双答案—逐题评估—报告”。
- 验证三动作约束、多 `user_acts`、快照更正确认、20 轮累计 compact、上下文隔离和并发逐题评估。

### Phase 1：MVP

- Web 快照生成、导入、审阅、可选保存和范围解析。
- 面试方向、范围和线性 Stage 计划。
- 可暂停恢复的文本面试。
- Stage 进度、三动作菜单、可选 `reply` 和 Supervisor 多 `user_acts` 结构化输出。
- `correct_project_fact` 快照同步确认，以及问题好评与差评。
- 双版本答案、并发逐题评估、“复盘报告/完整问答”两个页签。
- 管理员控制台中的会话材料筛选、审核表单和人工发布。
- 基础安全、追踪、成本和质量看板。

### Phase 2：训练闭环

- 基于历史薄弱项自动安排复练。
- 同一问题的跨轮回答对比。
- 项目类型模板和用户自定义评估重点。
- 扩充和细化 Stage 规划模板，并基于真实项目回放调整目标、完成条件和 Topic 分配。
- 离线题库整理 Agent、管理员审核流程和基于反馈的受控重排实验。

### Phase 3：扩展

- 语音面试与转写。
- GitHub/GitLab、Issue、PR、提交历史接入。
- 教师或带教者工作台。
- 在获得足够质量数据后，探索受控的半自动题库晋级。

## 14. 主要风险与缓解

| 风险 | 后果 | 缓解措施 |
| --- | --- | --- |
| Markdown 快照存在错误 | 提问建立在错误事实之上 | 用户直接审阅、证据引用、只增追加用户意见与事后核验 |
| 快照与项目目录不一致 | 赛后证据与面试上下文冲突 | 明示以快照状态为准，不承诺自动校验、同步或修复 |
| Stage 计划与方向不匹配 | 导览过深或专项覆盖不足 | Planner 读取完整快照与 Topic 列表、黄金项目回归 |
| 线性 Stage 过于僵硬 | 面试退化为固定问卷 | Stage 只定义目标与完成条件，具体问题与临时 Topic 由 Supervisor 自适应生成 |
| Stage 无法收束 | 对话过长、成本失控 | `complete`、`unresolved` 和 100 轮异常安全上限 |
| 多 Agent 串扰 | 问题暗示答案，评估失真 | Supervisor、两类答案、逐题评估和报告上下文隔离及泄漏测试 |
| 评分伪精确 | 用户误信内部维度分或聚合总分 | 不展示内部数字、不计算总分，只展示三级标签、证据分析和固定参考说明 |
| 题库或 Topic 污染 | 迭代后质量持续下降 | 临时 Topic 与生成题只留在会话；管理员完成审核并点击发布后才进入正式版本，支持回滚 |
| 私有代码泄露 | 严重信任与合规问题 | 最小授权、敏感过滤、数据隔离与删除 |
| 成本与延迟过高 | 面试节奏断裂 | 热路径单次 Supervisor 调用、1～3 条 RAG、预生成理想答案复用、赛后并行评估 |
| 过度查证 | Supervisor 频繁读取代码导致延迟 | 面试中不做事实核验，局部证据检查只用于赛后分析 |
| 过度追问单点 | 覆盖不足、体验压迫 | Stage 完成条件、`decline_current_line`、继续追问价值判断和 `unresolved` |
| 项目事实更正误识别 | 快照被错误信息污染 | 只生成可编辑候选，用户明确确认后才只增追加；确认不触发第二次模型调用 |
| 用户诱导泄漏答案 | 面试流程被打乱 | 语义识别、结构化动作、系统 Prompt 和多语言回归测试 |
| 用户背参考答案 | 形成模板化表达 | 延迟展示、约束变体、要求结合证据回答 |

## 15. 待决策问题

已确定的产品边界：首版只服务 AI 软件开发岗位，不提供岗位自由选择。

以下问题不阻塞 Phase 0，但应在 MVP 开发前决定：

1. 种子面经题库如何获得合法可用的内容，版权和审核责任如何处理？
2. 首版各方向的 Stage 模板如何划分，是否需要按项目类型调整目标和完成条件？
3. 哪些匿名化的产品事件可以用于改善检索和监督规则，哪些必须完全退出采集？

## 16. 建议的首个验证实验

选取三个已知项目：一个文档完善、一个只有代码、一个由用户口述补充背景。邀请项目作者各完成两轮范围和计划规模相当的面试。

第一轮验证：

- `snapshot.md` 中的 Module、Thread 和项目事实是否准确，引用是否真的支持结论，用户能否低成本完成审阅和意见追加。
- Markdown 标题能否稳定生成正确的面试范围，Planner 能否据此产出合理的线性 Stage。
- 问题是否像在问这个项目，而不是替换名词后的通用八股。
- 追问是否会因回答发生变化。
- 并发逐题反馈和整场报告是否指出了作者自己未意识到的表达或工程缺口。

第二轮只训练第一轮的两个薄弱主题，验证用户能否给出更具体、更有证据且更完整的回答。若看不到可重复的改善，继续增加 Agent 数量没有意义；那只会让会议纪要变厚。
