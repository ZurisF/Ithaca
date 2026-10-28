# 施工状态

本文件按 `DEVELOPMENT_EXECUTION_PLAN.md` 的完整范围记账。计划中“今夜”和“明天演示”描述交付场景，不是降低质量或缩减功能的理由。未通过的 Gate 保持未通过。

## 已验证

| 验收门 | 当前状态 | 证据 |
| --- | --- | --- |
| Gate 0 工程可启动 | 已通过本机验收 | Python、Node 锁文件；PostgreSQL/pgvector 与 Redis Compose；两个 Runtime `/health`；Web 页面；无模型密钥启动与明确 503；开发 User/Administrator 身份；结构化应用日志。 |
| Gate 1 合同、迁移与存储 | 部分完成 | 核心 schema 从空库 upgrade、downgrade、re-upgrade 已走通；数据库拒绝非法状态组合、第二个未回答 turn、turn 101 和答题时间错配；Pydantic/OpenAPI/TypeScript 类型已生成。面试、赛后、结算的 repository 与事务 seam 仍待对应纵向切片落实。 |
| Gate 2 准备流程 | 部分完成 | 公开 HTTP 与 Web 可创建会话、导入 Markdown、解析 Module/Thread、选择方向和范围；同内容/同选择重放不清空 plan；追加用户意见有幂等回执；Planner 结构化输出经确定性校验后条件发布。本地 handle 绑定 session；inventory、Repository Map、只读工具、迭代 Observer、证据引用和安全过滤已接入公开 `snapshot:observe`，与 Markdown 导入共用持久化规则。真实 Planner、真实 Observer 和双 Runtime 观察链路已用合成材料通过。 |
| Gate 3～7 | 未完成 | 题库导入/检索、面试 Graph、断线恢复、赛后、策展、删除、完整 Web 和故障窗口回归尚未验收。 |

## 最近验证

- `ruff check .` 与针对源码的 `ruff format --check services packages tests scripts` 通过；全仓格式检查会命中未改动的设计文档代码片段。
- `pytest -q`：30 passed，4 skipped；可选的真实 Observer 单测单独 1 passed，双 Runtime HTTP 合同与真实 Observer 单独 2 passed。
- OpenAPI 与 Web TypeScript 客户端已重新生成；`npm run build --prefix apps/web` 通过。
- 真实模型从本机代理调用，Planner 和 Observer 都已用合成材料验证；跨 Runtime 观察时模型 trace 以无内容元数据写入 Application。
- 浏览器手动走通会话选择、Markdown 导入、范围勾选与保存。Web 目录授权与观察操作尚未接入页面。

## 接下来的施工依赖

1. 补齐 Gate 2：完善文档、纯代码、大型/部分分析 fixture；模型 token 预算、目录观察幂等回执、Web 目录授权/观察、敏感命中元数据展示与故障窗口验证。
2. 依 Gate 3 导入 11 个白名单题库文件，落地检索与首题发布；继续补齐当前需要的事务 seam。
3. 依 Gate 4～7 实现面试、恢复、终止、赛后、策展、删除和正式 Web，并逐项映射 `tests/fault_windows`。

以上剩余项仍属于同一交付范围。当前版本是可审查的施工进度，尚不是完整产品。
