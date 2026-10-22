# VNext 2 检查点（docs/vnext2/checkpoint.md）

更新时间：2026-10-22 21:0x（Asia/Shanghai）

## 当前状态

- 当前分支：`dsh/vnext-business-accuracy-20261021`
- 起始 HEAD：`6b75384e4bacd94dfae70c58900f09282c7fcde5`
- 当前工作包：**P0-A 需求审核与冻结快照时效性治理 —— 已完成定向与真实 PostgreSQL 验收**
- 下一个工作包：**P0-B RAG 引用裁判（C08/C09/C10）**

## 已完成改动（未提交）

1. 新增 `backend/app/services/requirement_delivery_safety.py`
   - `unresolved_question_risks(db, requirement)`：按需求 scope（target_table_id / field_ids / scenario_id）筛选当前未结案 `PendingQuestion`，返回 `manual:<id>` 风险；`answered/accepted/rejected` 仍阻断，`closed/resolved` 必须有 `resolution_text`。
   - `lock_project_requirements(db, project_id)`：按 id 排序对项目内 `requirements` 行 `SELECT ... FOR UPDATE`，串行化“问题写入”与“定稿”。
2. `backend/app/services/requirement_review.py`
   - `review_readiness()` 追加当前问题风险；`finalize_formal_delivery()` 追加同样的检查并以 409 阻断。
3. `backend/app/api/deliverables.py`
   - `create_question` 与 `_ensure_generation_questions` 在写入问题前调用 `lock_project_requirements`。
4. 新增测试
   - `backend/tests/test_vnext2_review_freshness.py`（9 例，MOCK）
   - `backend/tests/test_vnext2_review_freshness_pg.py`（3 例，REAL_COMPONENT，需 `VNEXT_PG_URL`）
5. 文档
   - `docs/vnext2/plan.md`、本文件。

## 测试结果

| 命令 | 结果 |
| --- | --- |
| `pytest tests/test_vnext2_review_freshness.py -q`（改前） | 7 failed, 2 passed（证明缺陷存在） |
| `pytest tests/test_vnext2_review_freshness.py -q`（改后） | 9 passed |
| `VNEXT_PG_URL=... pytest tests/test_vnext2_review_freshness_pg.py -q` | 3 passed（真实 PG 行锁阻塞/可见性） |
| `AUTH_MODE=optional TASK_QUEUE_PROVIDER=inline pytest tests/test_deliverables.py tests/test_reviewed_content_immutability.py -q` | 21 passed |

## 恢复命令

```powershell
# 0) 保活 WSL（否则 PG/Redis 端口会消失）
wsl -e sh -lc "sleep 7200"   # 后台运行
# 1) 定向测试
cd ai-platform/backend
$env:AUTH_MODE="optional"; $env:TASK_QUEUE_PROVIDER="inline"
.\.venv\Scripts\python.exe -m pytest tests/test_vnext2_review_freshness.py -q
# 2) 真实 PG 证据（DSN 见被忽略的 backend/.env）
$env:VNEXT_PG_URL="postgresql+psycopg://<user>:<pwd>@127.0.0.1:5432/<db>"
.\.venv\Scripts\python.exe -m pytest tests/test_vnext2_review_freshness_pg.py -q
```

## 当前阻断项

- 无（P0-A 范围内）。注意两点环境约束：WSL 空闲停机导致 PG/Redis 不可达；`backend/.env` 的 `AUTH_MODE=required`/`TASK_QUEUE_PROVIDER=celery` 会影响不覆盖依赖的测试。

## 下一步准确动作

1. 提交 P0-A（代码 + 两个测试文件 + docs/vnext2）。
2. 进入 P0-B：读取 `backend/app/services/rag/{citation_support,citation_validator,grounded_answer_service}.py`、`knowledge_evidence.py`、`knowledge_eligibility.py`、`knowledge/version_applicability.py` 与 `docs/audit/VNEXT_REAL_MODEL_GOLDEN-20261021.json`，先复现 C08/C09/C10，再决定最小修复。
