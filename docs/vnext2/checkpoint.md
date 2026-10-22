# VNext 2 检查点（docs/vnext2/checkpoint.md）

> 会话中断、上下文压缩或环境重启后，先读本文件 + `git status` / `git log`，不要依赖聊天记忆。

## 当前状态（2026-10-23 Round 6 收尾）

- 分支：`dsh/vnext-business-accuracy-20261021`
- 起始 HEAD：`6b75384e4bacd94dfae70c58900f09282c7fcde5`
- 当前 HEAD：`13f300a`（Round 6 第一批：需求版本钉扎接入问答链路 + `normalize_version` 缺陷修复）
- 已提交：`08f8e9b`(P0-A) `b5e5ae8`(P0-B) `525190d`(P0-C 后端) `7d37cc7`(P0-C 浏览器 + P1-B 首批)
  `182d479`(P1-B 次批) `2475d46`(P1-A) `a5249f3`(P1-C) `81ab717`(P2-A/P2-B + 报告) `ff45f9f`(P2 文档收尾)
  `13f300a`(Round 6 钉扎)
- 当前工作包：**Round 6 第二批 = 钉扎明细回显 + 问答失败关闭的可执行提示 + 真实浏览器冒烟**

## 本批未提交改动（提交前核对 `git status`）

- `backend/app/api/knowledge_rag.py`：`version_pin` 增加 `pinned_versions` 明细（制度标题 → 版本），
  使“按哪个版本判定”可在页面追溯；标题本来就来自该需求快照证据，不新增外发面。
- `backend/tests/test_vnext2_pinned_versions.py`：断言回显明细。
- `frontend/lib/knowledge-contract.mjs`：`askErrorMessage` 对 400/422 优先展示服务端可读 `detail`
  （业务规则拒绝），`detail` 为数组（请求体结构校验）时仍回落通用文案。
- `frontend/app/knowledge/ask/page.tsx`：钉扎说明只在真的拿到回答后渲染，避免请求失败却提示
  “本次回答未回显固定版本”。
- `frontend/tests/knowledge-contract.test.mjs`：新增 3 个断言（中文 detail 透传 / 数组 detail 回落 / 400 透传）。
- `frontend/components/requirement-workspace/RequirementGenerationPanel.tsx`：候选项增加阶段说明
  （单次模型生成，未做候选间分批比较；采用≠确认）。
- 新增 `scripts/vnext2_r6_pin_browser.mjs`、`scripts/vnext2_r6_pin_seed.py`（造数，幂等）、
  证据 `docs/audit/VNEXT2_R6_PIN_BROWSER-20261023.json`、截图 `docs/audit/vnext2-r6-pin/`。
- 文档：`docs/vnext2/p0b-citation-trust.md` 第 5 节缺口 2、`docs/vnext2/final-report.md` 第十部分 10.3–10.6。

## 测试结果（Round 6）

| 命令 | 结果 |
| --- | --- |
| `pytest tests/test_vnext2_pinned_versions.py -q` | 10 passed |
| 同上 + `tests/test_vnext2_citation_trust.py` | 28 passed / 147s |
| `pytest tests/test_vnext2_pinned_versions.py tests/test_knowledge_rag.py tests/test_rag_citation_support.py -q` | 45 passed / 188.15s |
| `pytest tests -k "citation or rag or knowledge or grounded or ask or pin"` | 334 passed / 900.65s |
| `npm test`（frontend） | 309 passed / 95.0s |
| `npx tsc --noEmit -p tsconfig.json` | 通过 |
| `node scripts/vnext2_r6_pin_browser.mjs` | **6/6 PASS**（真实 Chromium + 真实 API + 真实模型一次问答） |

## 环境事实（重要）

- 全量回归需显式 `AUTH_MODE=optional`；不需真实队列时 `TASK_QUEUE_PROVIDER=inline`。
- 真实模型：`deepseek-v4.1-flash`（`deepseek-v4-flash` 已下线）；`backend/.env` 有 `LLM_MAX_OUTPUT_TOKENS=8192`。
- WSL 空闲会停机 → 容器停止；真实组件测试前先起保活
  `wsl -e sh -lc "sleep 5400"`（工具级后台 job），再 `Test-NetConnection 127.0.0.1 -Port 5432`。
- 真实浏览器栈：后端 `uvicorn app.main:app --port 8011`（需 `CORS_ORIGINS=http://127.0.0.1:3010`）、
  前端 `npx next dev -p 3010`、`frontend/.env.local` 的 `NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8011/api`。
- 演示数据：project 7 / requirement 5（无钉扎）/ requirement 6（钉扎 v1）/ 账号 `p0c-biz` 等，
  密码 `Vnext2#P0C2026`；重置用 `scripts/vnext2_p0c_reset.sql`（单事务、外键逆序、`psql -v ON_ERROR_STOP=1`）。
- `User` 模型列是 `status`（无 `is_active`/`institution_id`）；`ProjectMembership` 用 `project_role` + `status`；
  `Requirement` 无 `created_by`，`RequirementRevision` 有。
- 前端页面里存在常驻的空 `role="alert"` 提示容器 → Playwright 断言必须取“所有非空 alert 文本”，
  不能 `first()`，否则会把“没提示”判成失败。

## 当前阻断项

1. 检索规模性能（小/中/规划容量）`UNVERIFIED`：缺容量基线语料。
2. Worker/Beat 进程自动重启属部署层，仓库无 supervisor，`UNVERIFIED`。
3. 黄金集 60 例无银行专家独立标注 → 所有准确率仍 `UNVERIFIED`（`docs/audit/VNEXT2_GOLDEN_REPORT-20261023.json`）。
4. 需求生成链路仍用当前知识库内容，未把钉扎版本传入生成输入；候选审计无“引用版本”字段。
5. 未固定版本时是整题拒绝；若业务要“部分回答+明确标注未固定”，需新契约。

## 下一步准确动作

①提交本批（代码 + 脚本 + 证据 + 文档）；
②真实案例独立标注（需业务方）；③容量分档检索测评（需容量基线）；④部署韧性与长任务租约；
⑤把钉扎版本接进 generation-run 输入并在候选审计里记录引用版本。

## 当前状态（2026-10-23 Round 6 第二批收尾）

- 当前 HEAD：`1916143`（R6 第二批：钉扎明细回显 + 问答失败提示可执行 + 候选阶段说明 + 真实浏览器钉扎冒烟 6/6）
- 已提交全量：`08f8e9b`(P0-A) `b5e5ae8`(P0-B) `525190d`(P0-C 后端) `7d37cc7`(P0-C 浏览器 + P1-B 首批)
  `182d479`(P1-B 次批) `2475d46`(P1-A) `a5249f3`(P1-C) `81ab717`(P2-A/P2-B + 报告) `ff45f9f`(P2 文档收尾)
  `13f300a`(R6 钉扎问答) `1916143`(R6 浏览器/提示)
- 当前工作包：**Round 6 第三批 = generation-run 版本钉扎（原阻断项 4 关闭）**

## 本批未提交改动

- `backend/app/services/mapping/requirement_input.py`：新增 `_apply_version_pins`（冻结快照 `{标题: 版本}` 约束送入模型的证据；
  版本不符一律排除并写 `limitations`；同标题多版本不钉扎只报缺口；`input_json` 记录 `pinned_versions` / `version_pin_limitations`）。
- `backend/app/services/requirement_generation_worker.py`：把 `version_pin_limitations` 追加进候选 `gaps`（采用后阻断送审/交付）。
- 新增 `backend/tests/test_vnext2_generation_pins.py`（7 例）。
- 文档：`docs/vnext2/plan.md`（P0-B 增补生成链路钉扎与证据）、`docs/vnext2/final-report.md` 10.7。

## 测试结果（Round 6 第三批）

| 命令 | 结果 |
| --- | --- |
| `pytest tests/test_vnext2_generation_pins.py -q` | **7 passed / 9.28s** |
| 生成/需求相邻 7 文件回归 | **62 passed / 30.11s** |
| `pytest tests -k "generation or requirement or knowledge or citation or pinned"` | **333 passed** / 662.31s (0:11:02) |

## 阻断项更新

4. ~~需求生成链路仍用当前知识库内容，未把钉扎版本传入生成输入~~ → **已关闭**（见 10.7）；
   残余：证据版本字符串写法差异（`2026 年第 1 版` vs `2026-v1`）按 `normalize_version` 归一，等价写法可能被保守排除，需版本字典/别名表。

## 下一步准确动作

①提交本批；②真实案例独立标注（需业务方）；③容量分档检索测评（需容量基线）；④部署韧性与长任务租约；
⑤待确认问题页内带版本提问入口。
