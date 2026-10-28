# Meta 面试记录

- 已整理题目/主题：**7 条题目**，另有 **0 条主题或流程线索**。
- 来源记录：**2 条**。
- 每条问题均为简洁转述；链接可回到来源核对。证据等级说明见本目录的 [README.md](README.md)。

## Meta Software Engineer Interview Experience — Five Rounds Including AI Coding and a New Agentic System Design Round

- 来源：[https://prachub.com/interview-experiences/meta-software-engineer-interview-experience-five-rounds-including-ai-coding-and-a-new-agentic-system-design-round](https://prachub.com/interview-experiences/meta-software-engineer-interview-experience-five-rounds-including-ai-coding-and-a-new-agentic-system-design-round)
- 岗位 / 轮次 / 日期：Software Engineer；Onsite, AI-enabled system design；2026-04
- 资料类别：可追溯候选人记录 / 收到的面试任务；证据等级：2
- 可追溯情况：页面标明公司、岗位、月份、轮次和候选人结果；平台注明经编辑整理
- 限制：候选人报告经第三方编辑；题目方向保留，措辞已转述。

### 问题

1. **候选人记录的问题**（`META01-Q01`；onsite AI-enabled system design；2026-04）设计一个能够自动分流和初步处理支持工单的 Agent；候选人称讨论中面试官更倾向 ReAct 式循环方案。
   - 标签：`agent-system-design、ticket-triage、ReAct`
   - 原文/英文转述：Design an agent that automatically triages support tickets; the candidate reported that the interviewer steered toward a ReAct-style loop.

## Meta SWE Interview: Two AI Coding Rounds and AI-Enabled Design

- 来源：[https://prachub.com/interview-experiences/meta-software-engineer-interview-experience-two-ai-coding-rounds-a-leetcode-system-design-and-an-ai-enabled-design-round-with-no-ai](https://prachub.com/interview-experiences/meta-software-engineer-interview-experience-two-ai-coding-rounds-a-leetcode-system-design-and-an-ai-enabled-design-round-with-no-ai)
- 岗位 / 轮次 / 日期：Software Engineer；Onsite：AI-enabled design round（面经页面标注采访时间 2026-03）；2026-03
- 资料类别：可追溯候选人记录 / 收到的面试任务；证据等级：2
- 可追溯情况：面经页面披露公司、岗位、轮次和完整 Code Review Agent 设计题及追问。
- 限制：第三方平台编辑整理，发布于 2026-08；作者报告的实际面试日期为 2026-03。该轮面试环境未提供 AI 辅助。

### 问题

1. **候选人记录的问题**（`META02-Q01`；Onsite；AI-enabled design（Code Review Agent）；2026-03）设计一个 Code Review Agent，说明从代码变更输入到审查意见输出的主流程。
   - 标签：`agent-system-design、code-review`
2. **候选人记录的追问**（`META02-Q02`；Onsite；AI-enabled design（Code Review Agent）；2026-03）审查流程中哪些判断适合用 LLM，哪些应由确定性规则或静态分析完成？
   - 标签：`LLM-boundaries、deterministic-systems`
3. **候选人记录的追问**（`META02-Q03`；Onsite；AI-enabled design（Code Review Agent）；2026-03）如何验证 Agent 生成的审查意见准确、可操作且不会引入错误？
   - 标签：`agent-evaluation、code-review`
4. **候选人记录的追问**（`META02-Q04`；Onsite；AI-enabled design（Code Review Agent）；2026-03）Orchestrator 如何组织步骤和状态？需要哪些记忆或上下文？
   - 标签：`orchestration、memory、architecture`
5. **候选人记录的追问**（`META02-Q05`；Onsite；AI-enabled design（Code Review Agent）；2026-03）Code Review Agent 需要哪些工具或数据访问能力，如何限制权限？
   - 标签：`tool-calling、least-privilege、security`
6. **候选人记录的追问**（`META02-Q06`；Onsite；AI-enabled design（Code Review Agent）；2026-03）如何核算每次 LLM 推理的成本，并把成本与审查质量联系起来？
   - 标签：`cost、evaluation、production`
