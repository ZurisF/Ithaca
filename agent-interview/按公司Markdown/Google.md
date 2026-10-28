# Google 面试记录

- 已整理题目/主题：**5 条题目**，另有 **1 条主题或流程线索**。
- 来源记录：**2 条**。
- 每条问题均为简洁转述；链接可回到来源核对。证据等级说明见本目录的 [README.md](README.md)。

## Google L5 SWE (AI/ML) Phone Screen August 2026

- 来源：[https://www.reddit.com/r/OfferEngineering/comments/1vz36qi/google_l5_swe_aiml_phone_screen_august_2026/](https://www.reddit.com/r/OfferEngineering/comments/1vz36qi/google_l5_swe_aiml_phone_screen_august_2026/)
- 岗位 / 轮次 / 日期：Software Engineer, AI/ML, L5；Phone screen / system design；2026-08
- 资料类别：可追溯候选人记录 / 收到的面试任务；证据等级：1
- 可追溯情况：公司、岗位、级别、月份和轮次均明确；候选人自述
- 限制：匿名社区自述，无法独立核验；问法在本数据集中做了简洁转述。

### 问题

1. **候选人记录的问题**（`GGL01-Q01`；system design；2026-08）设计一个面向公司内部文档检索的 AI Agent，支持员工用自然语言查找并回答内部资料问题。
   - 标签：`agent-system-design、RAG、enterprise-search`
   - 原文/英文转述：Design an AI agent that lets employees search and ask questions over internal company documents.
2. **候选人记录的追问**（`GGL01-Q02`；system design follow-up；2026-08）在内部文档 Agent 方案中，怎样权衡并优化推理成本与端到端延迟？
   - 标签：`cost、latency、production`
   - 原文/英文转述：How would you reduce cost and end-to-end latency in the internal-document agent?
3. **候选人记录的追问**（`GGL01-Q03`；system design follow-up；2026-08）如果这套文档 Agent 要服务约十万用户，架构和容量设计需要怎样变化？
   - 标签：`scalability、capacity-planning`
   - 原文/英文转述：How would the design change to support roughly 100,000 users?
4. **候选人记录的追问**（`GGL01-Q04`；system design follow-up；2026-08）你熟悉哪些 Agent 框架？结合系统方案说明会怎样选型。
   - 标签：`frameworks、tradeoffs`
   - 原文/英文转述：Which agent frameworks have you used, and how would that affect your design choice?
5. **候选人记录的问题**（`GGL01-Q05`；system design follow-up；2026-08）设计音乐推荐系统后，若把体验改为由 LLM Agent 驱动，系统架构会有哪些变化？
   - 标签：`agent-system-design、recommendation、architecture-tradeoffs`
   - 原文/英文转述：How would the architecture change if the music recommendation experience used an LLM-based agent?

## Learning agentic AI for an interview in a week

- 来源：[https://www.amanjain.codes/blog/google-team-match-agentic-round/](https://www.amanjain.codes/blog/google-team-match-agentic-round/)
- 岗位 / 轮次 / 日期：Software Engineer III, AI/ML (candidate-described team-match context)；Agentic AI team-specific round; no exact question disclosed；2026-08
- 资料类别：主题或流程线索，不计为面试题；证据等级：2
- 限制：作者明确说明只分享准备主题，没有披露实际面试题；只能作为检索主题线索。

### 主题或流程线索（非真实题目记录）

- **仅准备主题，非实际题目**（`GGLTOPIC01-T01`）：multi-agent orchestration; LLM optimization; evaluation; human-in-the-loop safety; dynamic context compression; ReAct and DAG execution patterns; LoRA/SFT
  - 使用限制：原文仅列准备主题，未披露实际问题。可用于 RAG 元数据过滤或生成自有练习题时作主题，不得标成 Google 真实题。
