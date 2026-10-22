# VNext 2 检查点（docs/vnext2/checkpoint.md）

> 会话中断、上下文压缩或环境重启后，先读本文件 + `git status` / `git log`，不要依赖聊天记忆。

## 当前状态（2026-10-23）

- 分支：`dsh/vnext-business-accuracy-20261021`
- 起始 HEAD：`6b75384e4bacd94dfae70c58900f09282c7fcde5`
- 当前 HEAD：`a5249f3`（P1-C）
- 已提交：
  - `08f8e9b` P0-A 冻结后新增问题阻断送审与交付
  - `b5e5ae8` P0-B 引用裁判主张级 + 冲突暴露 + 确定性版本裁决
  - `525190d` P0-C 真实需求生成-采用-审核-交付后端闭环
  - `7d37cc7` P0-C 浏览器闭环 + P1-B 第一批（行数上限/CTE/复合业务键/需求关联）
  - `182d479` P1-B 第二批（GBase/Hive 方言矩阵、等价重写静默、filter 归因）
  - `2475d46` P1-A Agent 五类决策与人工否决重试守卫
  - `a5249f3` P1-C 黄金集结构化标注与 not_run 覆盖
- 当前工作包：**P2-A（真实组件稳定性与身份边界）+ P2-B（工作台体验）——代码与文档已完成，待提交**

## 本轮尚未提交的改动

- 后端：`app/services/auth/actors.py`（flush 移入 savepoint）、`app/services/auth/permission_service.py`
  （legacy 管理员仅 optional 模式）
- 前端：`app/questions/page.tsx`（状态语义/责任人/阻断提示/关闭前置条件）、
  `components/requirement-workspace/RequirementDeliveryPanel.tsx`（冻结快照哈希 + SQL 复核状态）
- 新增：`backend/tests/test_vnext2_auth_actors.py`、`scripts/vnext2_milvus_restart.py`、
  `scripts/vnext2_p2b_ui_smoke.mjs`、`docs/vnext2/p2a-stability-and-auth.md`、`docs/vnext2/p2b-workspace.md`、
  `docs/audit/VNEXT2_P2B_UI-20261023.json`、`docs/audit/vnext2-p2b-ui/*.png`

## 测试结果（本轮累计）

| 命令 | 结果 |
| --- | --- |
| `pytest tests/test_vnext2_review_freshness.py`（P0-A） | 9 passed（改前 7 failed） |
| `pytest tests/test_vnext2_review_freshness_pg.py`（真实 PG） | 3 passed |
| `pytest tests/test_vnext2_citation_trust.py` + 引用相关（P0-B） | 18 + 27 passed |
| `pytest tests/test_vnext2_p0c_real_delivery.py`（MOCK/REAL_COMPONENT） | 4 passed |
| 同上 + `VNEXT2_P0C_REAL_MODEL=1`（真实 DeepSeek） | 4 passed / 159.94s |
| `pytest tests -k agent`（P1-A） | 224 passed |
| `pytest tests -k "sql or lineage or semantic or impact"`（P1-B） | 365 passed |
| `pytest tests/test_vnext2_golden_annotation.py` 等（P1-C） | 19 passed |
| `pytest tests/test_vnext2_auth_actors.py`（SQLite） | 4 passed, 1 skipped |
| 同上 + `VNEXT_PG_URL`（真实 PG 竞态） | 5 passed |
| `pytest tests -k "auth or permission or project_member or rbac or admin"` | 153 passed, 1 skipped |
| `npm test`（前端） | 307 passed / 1 failed（`semantic-catalog-browser` CDP 8s 超时；单跑 12/12 通过，判定为并行负载下的时序抖动） |
| `npx tsc --noEmit` | 通过 |
| 浏览器：`scripts/vnext2_p0c_browser_e2e.mjs` | 66 步 PASS / 1019 次 API |
| 浏览器：`scripts/vnext2_p2b_ui_smoke.mjs` | 6 项断言 PASS |
| 真实 Milvus 重启：`scripts/vnext2_milvus_restart.py create/verify` | 16 行、top1 一致、21.8ms、`index_survived_restart=true` |

## 环境事实（重要）

- 全量回归需要显式 `AUTH_MODE=optional`，否则 `backend/.env` 的 `required` 会让 17 例 401；
  不需要真实队列时用 `TASK_QUEUE_PROVIDER=inline`（否则依赖真实 Celery/Redis）。
- 真实模型：网关 `openai_compatible` + `deepseek-v4.1-flash`（`deepseek-v4-flash` 已下线）；
  `backend/.env` 已加 `LLM_MAX_OUTPUT_TOKENS=8192`（推理模型 2048 会把正文耗尽）。
- WSL 空闲会自动停机 → 容器随之停止。真实组件测试前先起保活：
  `wsl -e sh -lc "sleep 5400"`（后台 job），再 `Test-NetConnection 127.0.0.1 -Port 5432`。
- 启动命令：后端 `cd backend; .\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8011`、
  Celery `-A app.workers celery_app worker --pool=solo`、前端 `cd frontend; npx next dev -p 3010`
  （`npm run dev -- --port` 会被当成目录参数）。
- 演示数据重置：`scripts/vnext2_p0c_reset.sql`（单事务、外键逆序、`psql -v ON_ERROR_STOP=1`）。

## 当前阻断项

1. 全量后端回归已完成：隔离配置复跑 **`1983 passed, 5 skipped, 0 failed / 2362.45s`**
   （`docs/audit/VNEXT2_FULL_REGRESSION-20261023b.log`）。第一次默认环境全量
   （`docs/audit/VNEXT2_FULL_REGRESSION-20261023a.log`）的 2 例已定因：
   `tests/test_requirement_generation_input.py::test_blocked_item_of_a_completed_job_can_be_retried`
   是测试自身断言写错（job 实为 `failed`，已改为验证“历史 completed 任务上的残留 blocked 项可重试”），
   `tests/test_requirement_formal_delivery_e2e.py::test_formal_delivery_api_integration`
   是内存 SQLite `SingletonThreadPool` 在 TestClient 线程间的连接脱离（单跑/相邻合跑均通过）；
   曾尝试把 `tests/conftest.py` 改 `StaticPool`，定向验证 `test_knowledge_rag.py` 出现 18 failed
   （共享连接破坏跨会话可见性），已回滚。
2. 检索规模性能（小/中/规划容量）`UNVERIFIED`：缺容量基线语料。
3. Worker/Beat 进程自动重启属部署层，仓库无 supervisor，`UNVERIFIED`。
4. AI 候选“分批模型比较 / 进入最终比较”阶段标识：候选数据结构目前只记录 `runtime` 与
   `execution_metadata`，没有可靠的阶段字段，属新增能力缺口（未在本轮实现）。
5. `pinned_versions` 尚未接入产品生成链路（引用裁判已支持确定性裁决，
   生成侧仍依赖 `script_basis.policy_snapshot`）。

## 下一步准确动作

本轮 A–G 验收门槛已闭合，`docs/vnext2/final-report.md` 已给出九部分结论。下一轮按报告第八部分推进：
①真实案例独立标注；②容量分档检索测评；③`pinned_versions` 进生成/导出闭环；
④部署韧性与长任务租约；⑤工作台 AI 候选阶段标识与跨页待办。
