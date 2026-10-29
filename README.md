# Project Interview Lab

基于项目材料的中文模拟面试与复盘。当前仓库按 `DEVELOPMENT_EXECUTION_PLAN.md` 的依赖和质量验收门施工；**页面存在不代表面试业务已完成**。以 [施工进度](#施工进度) 为准。

## 本机要求

- Python 3.13、[uv](https://docs.astral.sh/uv/)
- Node.js 20.9+、npm
- Docker Desktop / Docker Compose v2+

只使用 uv 管理 Python 依赖、npm 管理 Web 依赖。锁文件为 `uv.lock` 和 `apps/web/package-lock.json`。

## 首次启动

在仓库根目录运行：

```sh
python3 scripts/init_dev_env.py
uv sync --locked
npm ci --prefix apps/web
docker compose up -d --wait
uv run alembic -c services/application/alembic.ini upgrade head
uv run python scripts/seed_dev_users.py
```

在三个终端从仓库根目录分别运行：

```sh
uv run uvicorn app.main:app --app-dir services/application/src --host 127.0.0.1 --port 8100 --no-access-log
uv run uvicorn local_project.main:app --app-dir services/local_project/src --host 127.0.0.1 --port 8101 --no-access-log
npm run dev --prefix apps/web
```

检查 `http://127.0.0.1:8100/health`、`http://127.0.0.1:8101/health` 和 `http://127.0.0.1:3000/`。Application 健康检查返回 PostgreSQL、Redis 的独立状态；依赖不可用时返回 503 和 `degraded`，进程仍保持运行。模型密钥留空时两个 Runtime 仍可启动，`/v1/model-readiness` 返回 `503 dependency_unavailable`。

开发身份只在 `APP_DEV_AUTH_ENABLED=true` 下可用。User ID 为 `00000000-0000-4000-8000-000000000001`，Administrator ID 为 `00000000-0000-4000-8000-000000000002`。当前用 `X-Dev-User` 请求头选择身份，例如：

```sh
curl -H 'X-Dev-User: 00000000-0000-4000-8000-000000000001' http://127.0.0.1:8100/v1/me
```

本地 Runtime 的内部接口要求 `.env` 中共享的高熵 desktop token，并且服务只监听 `127.0.0.1`。真实部署必须关闭开发身份，接入经过验证的身份提供者，并替换开发数据库口令。

## 准备流程

在 Web 创建会话后，可以粘贴 Markdown，也可以点击“选择本机目录”。目录选择器由 macOS 上的 Local Runtime 打开；浏览器、Application Runtime 和 PostgreSQL 只接收随机 `source_handle`，不接收真实路径。文件清单会展示跳过原因及脱敏命中的行号和类型。审阅清单后点击“生成项目快照”，Local Runtime 才会把经过过滤的相对路径和必要文件片段发送给 `.env` 中配置的模型渠道。模型请求使用本机现有网络代理设置，Application 与 Local Runtime 的回环通信不经过代理。

目录授权保存在 Local Runtime 进程内，服务重启或授权到期后需重新选择目录。Local Runtime 或模型渠道不可用时，仍可通过 Markdown 导入继续准备。快照内容变化会清空旧方向、范围和计划；没有解析出 Module/Thread 时，须在页面明确确认使用整份 Markdown。

## 题库种子导入

题库脚本只读取 `agent-interview/按考点/README.md` 列出的 11 个直接主题文件。先核对源数据，再使用 BGE-M3 生成向量并写入单一题库：

```sh
uv run python scripts/import_question_bank.py --dry-run
uv run python scripts/import_question_bank.py
```

已有本机模型快照时，可给第二条命令传 `--model-path /path/to/bge-m3-snapshot`。导入按题目正文精确去重，不覆盖已经存在的题目；完成后核对每条种子题的向量和全文索引。当前 11 个文件有 573 条一级题目、537 条不同正文。

在线检索使用同一个 BGE-M3、PostgreSQL 向量与全文索引，以及本机 BGE reranker。首次运行会加载模型；可在 `.env` 中用 `APP_EMBEDDING_MODEL_PATH` 和 `APP_RERANKER_MODEL_PATH` 指向已下载的本机模型快照。检索异常按合同降级为空候选，首题仍由 Supervisor 生成。

## 校验

```sh
uv run pytest
uv run ruff check services packages scripts tests
uv run ruff format --check services packages scripts tests
npm run typecheck --prefix apps/web
npm run build --prefix apps/web
```

修改 HTTP 合同后，先运行 `uv run python scripts/export_openapi.py`，再运行 `npm run generate:api --prefix apps/web`，将生成的 OpenAPI 合同与 TypeScript 类型一起提交。Web 请求通过 `openapi-fetch` 消费这份生成类型。

迁移回退验证只应在一次性的测试数据库执行：

```sh
uv run alembic -c services/application/alembic.ini downgrade base
uv run alembic -c services/application/alembic.ini upgrade head
```

`downgrade base` 会删除 `app`、`bank` 和 `telemetry` schema 中的业务数据，不要在已写入材料的数据库执行。上述命令会通过环境变量 `APP_DATABASE_URL` 使用目标数据库。

## 施工进度

具体完成项、验证记录和剩余范围见 [CONSTRUCTION_STATUS.md](CONSTRUCTION_STATUS.md)。Gate 1 已通过本机验收。Gate 2 的准备流程代码、真实模型和双 Runtime 链路已通过合成材料验证；原生目录选择器的手工核验依用户要求后补。Gate 3 的题库种子导入、在线检索和首题发布已接入。Gate 4 的实时回答、Stage 推进、确认卡、决策重试、compact 和面试欠决策恢复已接入并通过主要验收；赛后 worker 分支、结算、策展、删除和完整故障回归继续施工。

进度按实际通过的验收门更新，不以启动成功或页面存在代替业务完成。产品行为以 `PRODUCT_DEVELOPMENT.md`、`IMPLEMENTATION_DESIGN.md` 为准。
