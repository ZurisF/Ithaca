# Agent 架构、规划与多 Agent

- 你熟悉哪些 Agent 框架？结合系统方案说明会怎样选型。
  - Which agent frameworks have you used, and how would that affect your design choice?

- 介绍一个你做过的 Agentic 方案，概述它要解决的问题和你的贡献。
  - Summarize an agentic solution you have built and your contribution to it.

- 设计一个能够自动分流和初步处理支持工单的 Agent。
  - Design an agent that automatically triages and handles support tickets.

- 你的 Agent loop 采用什么架构？

- 除了设置最大步数，还有哪些办法避免 Agent loop 死循环？

- ReAct、Workflow 和 Replan 分别适合什么任务？

- 你设计的视频 Agent 具体解决什么问题？

- 本地 Agent 调度做过哪些优化？为什么会空转，怎样检测和阻止死循环？

- 从用户上传视频到拿到分析结果，完整处理链路是什么？为什么这个项目需要 Agent？

- 你称为“受控 Agent Workflow”的部分具体由什么机制约束？

- 怎样避免 Planner、Executor 和 Critic 之间反复循环？

- 请介绍一个你参与的 Agent 项目：它当前最大的技术边界是什么，离正式上线还缺哪些工作？

- 介绍一个 LangGraph Agent 项目：它解决什么问题，工作流、节点和状态如何组织？

- Agent 的端到端运行链路是什么？

- 项目采用单 Agent 还是多 Agent？选择依据是什么？

- Agent 的核心组件有哪些？各自在执行循环中承担什么职责？

- LangChain 与 LangGraph 的抽象和适用场景有何不同？

- 多 Agent 协作有哪些常见模式，适用场景和主要工程挑战分别是什么？

- Agent 框架选型要考虑哪些因素？

- 有哪些 Planning 实现方法，分别适合什么任务？

- ReAct 与 Plan-and-Execute 的适用场景和优缺点有什么不同？

- 实习中落地的 Agent 应用整体架构和端到端链路是什么？

- 如何判断代码 Agent 的生成结果有效、准确且可用？

- 创建两个 Agent 对象能否解决共享状态竞争？还需要检查哪些共享字段或外部状态？

- 你会使用 Agent 自动化哪些非编码任务？

- 你的 Agent 平台包括哪些功能？

- 如何判断 Agent 流程设计合理且准确？

- 如果重新划分 Agent 平台的系统边界，你会怎样设计？哪些能力放平台，哪些放业务侧？

- 如何验证 Agent 生成的审查意见准确、可操作且不会引入错误？

- 收到一个需求时，你如何判断应该用确定性 Workflow 还是 Agent？

- 什么情况下会从单 Agent 升级到多 Agent？多 Agent 增加了哪些工程代价？

- 讲一个你做过的失败 Agent 设计；如果重做，会怎样改变方案？

- 你会怎样在 LangChain、LangGraph、CrewAI 和 AutoGen 等框架之间选型？

- LangGraph 相比 AgentExecutor 解决了哪些问题？

- LangGraph 图结构支持循环吗？如何设计节点、边和条件路由，并为循环设置明确的终止条件？

- 出现什么信号时，你会考虑自研 Agent 框架而不是继续使用 LangGraph？

- Agent Runtime 应承担哪些职责，哪些能力应放在 Runtime 之外？

- 多个实例同时处理同一会话时，怎样避免 Agent 状态互相覆盖？

- 什么时候使用 Replan？Plan-and-Execute 与 ReAct 有哪些差别？

- 除最大迭代次数外，还能怎样识别并阻止 Agent 死循环？

- 客服 Agent 出错时，人工如何接管并延续当前任务状态？

- 多 Agent 如何通信、如何选择共享状态或消息传递？两个 Agent 互相等待时怎样避免死锁？

- 什么样的需求你会明确建议不要使用 Agent？

- 为什么项目使用多 Agent Teams？相比 Workflow 编排，优势和代价分别是什么？

- 风控归因系统为什么拆成主 Agent、编排 Agent 和原子子 Agent 三层？各层职责是什么？

- 前端断线后重连，怎样确保 Agent 消息能按顺序继续接收？

- 业务要求 Agent 不能基于虚构信息下结论，如何用工程机制保证输出有依据？

- 多 Agent 如何编排？请说明任务分配、执行顺序和结果汇总流程。

- 设计多 Agent 时，怎样决定各 Agent 的角色、共享状态范围和失败恢复策略？

- 从用户请求进入到任务完成，Agent 的完整执行生命周期如何设计？

- 在系统设计中，哪些功能应由确定性 Workflow 承担，哪些才适合交给 Agent？

- 如果 Agent 要执行真实业务操作，哪些步骤必须经过 Human-in-the-loop 确认？

- 如何把用户反馈和执行结果回流到 Agent 的改进闭环？

- Agent 任务状态和执行记录需要如何持久化，失败后怎样恢复？

- 如何让 Agent 的关键业务结果具有确定性或可验证性？

- 用户缺少必要参数时，Agent 应如何追问？哪些参数不能自行推断？

- 何时使用 Sub-agent？主 Agent 如何分解任务并合并子任务结果？

- 如何系统性提升 Agent 稳定性？请分别讨论业务输出质量和系统运行可靠性。

- 如何观测和分析 Agent 各节点的流转情况？需要记录哪些运行状态、耗时和失败信息？

- 多 Agent 协作时，如何防止一个 Agent 读取并执行不属于自己的任务？如何排查任务串扰？

- Agent 执行复杂任务时，TODO list 能起什么作用？它如何帮助模型保持任务焦点，何时需要更新或重排？

- Agent 与 Function Calling 有什么区别？

- 规划应由 Agent 框架负责还是由大模型负责？

- OpenManus 怎样处理不同 Agent 和任务之间的数据依赖、静态条件与竞争？

- 为什么采用 LangGraph 状态图而不自研，Checkpoint 与业务状态冲突时如何处理？

- LangGraph 如何存储状态并在状态间流转？

- Leader Agent 与人工分配 Agent 有什么差异？

- 多 Agent 同时修改同一文件时怎样避免冲突，是否使用分布式锁？

- 多 Agent 修改同一文件时应采用乐观锁还是悲观锁？修改同一方法不同行时怎样合并？

- 多 Agent 并发修改同一文件时如何防冲突？

- 多 Agent 如何运行并避免并发修改同一文件？

- 多 Agent 如何协作，并避免同时修改文件造成冲突？
