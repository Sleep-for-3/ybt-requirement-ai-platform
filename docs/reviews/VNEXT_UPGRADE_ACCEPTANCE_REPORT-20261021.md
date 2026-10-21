# 银行监管数据智能平台 VNext 升级实施与验收报告（2026-10-21）

- 仓库：`C:\Users\李儒伟\Desktop\ai-platform-dsh-20260930-150943 (2)\ai-platform`
- 分支：`dsh/banking-semantic-agent-v2`（基线 HEAD `7495676`）→ 工作分支 `dsh/vnext-business-accuracy-20261021`
- 执行环境：Windows 本机；Python 3.12.4（backend/.venv 修复后）；SQLite/TestClient/Mock 为主；无内网 Qwen、Milvus、Redis/Celery 真实组件（均标 BLOCKED/UNVERIFIED）
- 状态标签：IMPLEMENTED=代码存在；TESTED_MOCK=Mock/SQLite 下测试通过；TESTED_REAL=真实组件/真实模型下通过；BUSINESS_VERIFIED=独立业务人员确认；UNVERIFIED=未验证；BLOCKED=依赖缺失

---

## A. 当前成熟度（每项给依据，不给无依据百分比）

| 维度 | 判断 | 依据 |
| --- | --- | --- |
| 后端工程完成度 | 高（成熟） | 全量 1888+ 测试通过，仅 2 例与环境 DNS 相关失败；1886→1888 基线来自 2026-10-19 夜间；本轮基线 3 failed/1883 passed（其中 1 例 jieba 缺失、2 例环境 DNS） |
| AI 真实业务准确性 | 低 / 未知 | 新黄金集 60 例仅完成构建与指标函数（label_status=UNVERIFIED、independent_labeled=0）；仓库无 Qwen 配置（`backend/app/**` 搜 qwen/27b 0 命中）；真实 Top1/Top3、Citation Precision/Recall 均无独立标注数据 → UNVERIFIED，禁止声称达标 |
| Agent 自主处理 | 未验证 | `agent/planner.py`(656 行)、`state_machine.py`(133 行) 存在且有 `test_agent_planner_validation.py`；本轮未新增五场景独立用例（信息足/缺输入/技能未绑定/待人工确认/驳回） |
| 监管口径可追溯 | 中（有实现，真实数据未验） | 引用/主张两级判定、证据版本、置信度降级链路齐全（`rag/citation_validator.py`、`grounded_answer_service.py`）；本轮修 2 处 claim-level 误记；真实制度库未接入 |
| 需求文档可开发（可交付） | 中（SQLite 下端到端可跑） | `test_requirement_formal_delivery.py` + `_e2e.py` 覆盖 三级审核→finalize→xlsx/docx 内容断言→重复 finalize 幂等；真实 Word/Excel 审批未走 |
| 内网部署 | 未验证/部分 BLOCKED | 无 Qwen 端点、无 Milvus/Redis/Celery 真实实例可测；`.env:21` 是 DeepSeek（仅开发期）。见 `docs/audit/VNEXT_PHASE3_INTRANET_MODEL-20261021.md` |
| 人工审核与正式交付 | 中（规则齐全，状态语义有坑） | 待确认问题阻断/结案链路本轮补齐回归；`accept`（已接收待处理）仍阻断易被误解为已解锁 |

## B. 本轮实际完成（按工作包）

### B0 环境与基线（TESTED）

- backend/.venv 原指向另一台机器 `C:\Users\admin\.dsh\...\python.exe`，已备份并改指 `C:\Program Files\Python312`（3.12.4），pytest 9.0.3 / fastapi 0.142.1 / sqlalchemy 2.1.1 可用。
- 全量基线（2026-10-21 上午）：`3 failed, 1883 passed, 1 skipped in 2536.46s`，失败=2×`test_llm_runtime.py`（DNS fake-IP）+1×`test_retrieval_bm25.py`（jieba 缺失）。
- 安装 jieba 后 bm25 通过；`test_llm_runtime` 两例为环境策略（例：`*.example.net` 解到 198.18.0.x 被判非公网）。曾尝试按 RFC2606 主机名放行（含 PRIVATE 解析）→ 会使 `test_model_profiles.py:107/162` 的 SSRF 防滥用用例失效，**已回退**，保留生产安全策略，标记 BLOCKED（环境）。
- 审计文档：`docs/audit/VNEXT_PHASE0_CAPABILITY_MATRIX-20261021.md`（11 项能力矩阵）、`VNEXT_PHASE3_INTRANET_MODEL-20261021.md`、`VNEXT_PHASE5_WORKSPACE-20261021.md`。
- `.planning/STATE.md` 漂移修正（0.3）：原写 `current_phase=11 / semantic-catalog-ui / 2026-08-25`；已改为 `vnext-2026-10 / banking-semantic-agent-vnext / auditing`，保留 Phase 11 段落为历史快照，不删历史。

### B1 阶段1.3 字段重排：分批不可比的真实缺陷（FIX + TESTED_MOCK）

- 缺陷：`app/services/ai_skills/field_rerank.py` 旧 `_select_finalists` 按批次顺序 round-robin 截断到决赛容量。容量 3、7 批时只有批 0/1/2 的第一名能进决赛，召回序 10~20 位的正确候选**结构上不可能**成为 Top1/Top3。
- 修复：有界淘汰赛（leaders 池 > capacity 时按容量分组、组内一次调用取组首、递归缩小；capacity=1 保持旧行为；最坏 7 批+6 组=13 次调用 ≤ `RERANK_MAX_MODEL_CALLS=16`）。
- 回归（`tests/test_overnight_rerank_batching.py` 追加）：
  - `test_a_tail_candidate_still_gets_a_real_model_comparison`（第 75 行）证明尾部候选拿到真实模型比较；
  - `OracleMock`（"只要目标出现就排第一"）证明淘汰赛使其一路晋级到决赛；断言 `metadata["rerank_tournament_calls"]>0`、`comparisons>0`、`truncated is False`。
- 真实收益（Qwen 下 Top1/Top3 提升幅度）→ UNVERIFIED（无模型）。

### B2 阶段1.4 引用可信度：citation-level 误记 claim-level（FIX + TESTED_MOCK）

- 缺陷①：`app/services/rag/citation_validator.py` citation-level 分支曾把全部 claim 写入 `supported_claims`、`claims_supported=len(claims)`，下游 `grounded_answer_service.py` 把它当 claim 级支持 → 等于把引用级判定冒充主张级 verified（任务书 1.4 明确禁止）。
- 修复：`supported_claims=[]`、claim 级 supported/unsupported/unknown 全 0、`unknown_claims=全部`、`claims_unjudged=len(claims)`；维度自报 `claim_judgement="citation_level"`。
- 缺陷②（既有）：`claim_coverage` 曾出现 1.25/2.5（分子分母不同源），已在显式分母下修正。
- 回归：`tests/test_overnight_citation_status.py:585` `test_citation_level_verdicts_never_count_as_judged_claims`、`:624` `test_citation_level_verdicts_never_claim_claim_level_support`。
- `CITATION_SUPPORT_CHECK=off` 行为不变（不调用模型、不加字段）。

### B3 阶段1.1/1.2 银行监管黄金集（IMPLEMENTED + TESTED_MOCK）

- 新增 `backend/app/services/evaluation/regulatory_golden.py`（411 行）+ `backend/app/services/evaluation/data/vnext_golden_set_v1.json`（25.6KB，60 例）。
- 覆盖 A 字段语义 10、B 多表关联 10、C 引用证据 10、D SQL 语义 10、E Agent 决策 10、F 完整交付 10；每例带 `expectation`（positive/negative/ambiguous）、`expected.correct_candidates/distractors`、`reviewer_id`。
- `version=vnext-regulatory-golden-2026-10-21.v1`、`label_status=UNVERIFIED`、`independent_labeled=0`（无独立领域人员标注，真实指标不得声称达标）。
- 指标函数：`field_retrieval_metrics`（Recall@K/Top1/Top3/MRR，分子分母+样本量）、`citation_metrics`（Citation Support Precision/Recall/False Supported Rate/Unsupported Detection Rate/Claim Coverage/Citation Coverage/Judge Timeout Rate，引用级与主张级分开）、`document_metrics`、`agent_decision_metrics`；比例一律 `_ratio` 校验分母、无样本返回 `None` 而不是伪造 0。
- 回归：`tests/test_vnext_regulatory_golden.py`（覆盖率≥60 且每族≥8、重复 id/缺族拒绝、无样本不伪造比例、字段指标数学正确）。

### B4 阶段2 人工待确认问题闭环（TESTED_MOCK，行为未改）

- 发现：`tests/` 对 `PendingQuestion` 零覆盖；`requirement_scope.document_content`（约 109-117 行）把未解决人工问题投影成 `manual:<id>` gap，`review_readiness` 据此阻断送审。
- 曾误判 `accept` 应解锁并改动白名单，被仓库既有规格 `tests/test_requirement_scope.py:54-58`（accepted 仍是"已接收待处理"→阻断）当场证伪，**已回退**，未改任何既有测试预期。
- 新增 `tests/test_vnext_phase2_manual_question.py`（2 用例）：open→阻断；answer 有依据但未结案仍阻断；accept 仍阻断；close+依据→解除；close 无依据→仍阻断且提示"缺少解决依据"。
- 真实发现（保持待改进，未擅自改语义）：全仓库无写入方把状态置为 `"resolved"`（仅读过滤命中），实际闭环路径是 `answer(text) → close`；`accept` 是易误读的中间态。

### B5 阶段2 既有端到端链路（TESTED_MOCK，复核未重写）

`test_requirement_formal_delivery.py` / `_e2e.py` 已验证：revision 快照 → generation-runs（inline queue + patched candidate）→ adopt → review-readiness → 三级角色审批（business/technical/final）→ `finalize_formal_delivery` → xlsx 内容断言（"正式交付"/content_version/审核人）→ 重复 finalize 幂等 → `append_revision` 不改变已冻结 formal_file；HTTP 层同路径 + 审批前 finalize 返回 409。

## C. 改前 / 改后对比

| 项目 | 改前 | 改后 |
| --- | --- | --- |
| 全量后端测试 | 3 failed / 1883 passed / 1 skipped（1887 收集，2536s，含 jieba 缺失） | 2 failed / 1901 passed / 1 skipped（1904 收集，2014s）；2 例仍为环境 DNS 的 `test_llm_runtime`，`provider_quota_exhaustion…` 与 `fallback_can_target_a_separate_endpoint…` |
| 新增测试数 | — | +17（golden 11、manual-question 2、tournament 2、citation-level 2） |
| 字段重排：尾部候选进决赛 | 结构上不可能（按批截断） | 可晋级；oracle-mock 证明；真实 Top1/Top3 = N/A（无 Qwen） |
| 引用：citation-level 冒充 claim verified | 会发生（supported_claims 全填） | 不可能；claim 级计数全 0 |
| 人工待确认问题 | 零测试 | 2 条回归覆盖阻断/结案语义 |
| 黄金集 | 无独立于原 benchmark 的银行监管集 | 60 例、6 族各 10；真实指标 not_run（无标注/无模型） |
| 111 例合成机制回归 | 改前全过（历史） | 随全量测试一并跑（未单独重跑） |
| SQL 语义 36/39 | 任务书基线 | 本轮未重跑（脚本依赖未验证）→ UNVERIFIED |
| 模型调用量预算 | 旧实现 ≤16 次/需求 | 淘汰赛最坏 13 次，仍 ≤16，新增 metadata 字段可审计 |
| 前端 | — | 本轮未做浏览器验收（UNVERIFIED），仅遗留 `frontend/tests-node-test-20261021.log` |

## D. 未解决问题（原因/风险/最小后续）

1. **无 Qwen 3.8 27B 内网端点**（BLOCKED）：仓库只有 DeepSeek 开发配置；最小后续=部署端点后跑黄金集与 `test_llm_runtime` 真机验证。
2. **真实业务准确率无独立标注**（UNVERIFIED）：黄金集 60 例 by Lead，`independent_labeled=0`；最小后续=组织 1~2 名领域人员按 `reviewer_id` 标注 ≥30 例后重算指标。
3. **2 例 `test_llm_runtime` 环境失败**（BLOCKED 环境）：本机 DNS fake-IP 使 `example.net` 被判非公网；不要放宽 SSRF 白名单（会破坏 `test_model_profiles.py` 防滥用用例）；最小后续=CI 环境用可控 DNS 或改测试域名。
4. **`accept` 语义易误读**（IMPROVE）：业务人员以为"已接收"即解锁；最小后续=UI 文案或 API 文档标注"仍需结案"，或产品决策后统一语义（需人工确认，不擅自改）。
5. **PendingQuestion 状态迁移仍缺系统回归**（IMPROVE）：仅 2 例；reject/close 权限拒绝、导出脱敏未覆盖。
6. **Agent 五场景、SQL 方言、工作台真机验收未做**（UNVERIFIED）：见后续工作包。

## E. 后续工作包（≤5，按优先级）

1. **P0 真实模型验收包**：Qwen 端点接入 → 黄金集全量观测（字段召回/重排、引用判定、文档必需字段）→ 出真实 Top1/Top3 与 Citation Precision/Recall（BLOCKED 解除条件明确）。
2. **P0 端到端真实交付包**：在 TestClient 之外用真实浏览器完成 需求→生成→人工确认→审核→导出→变更复核 一轮，记录人工修改工作量与阻断准确性。
3. **P1 Agent 决策五场景包**：补齐信息足/缺输入/技能未绑定/待人工确认/驳回的独立用例与阻塞恢复证据。
4. **P1 SQL 变更影响包**：GBase/Hive 方言回归集 + order_by/top_limit/cte 三族正反例，复用 36/39 基线先测后修。
5. **P2 工作台收敛包**：模型已比较/仅召回标注、失败态与空态区分、人工未保存保护，按 `docs/audit/VNEXT_PHASE5_WORKSPACE-20261021.md` 逐项真机验收。

## F. 面向非 Python 开发者的中文使用说明

- **能做什么**：在"需求工作台"里新建监管需求，绑定一表通目标表/字段；系统会召回候选字段、给出 Source→Mart→YBT 取数路径与制度/SQL 依据，并生成需求文档草稿（Word/Excel/Markdown）。文档里每一项来源、加工口径、证据都带出处。
- **必须人工做的事**：①口径确认——AI 只给候选与证据，业务/技术审核人必须在系统里逐级审批，AI 不能自动批准；②待确认问题——信息不足时系统会生成"待确认问题"并阻断文档定稿，需要有人填写依据并**结案**（注意"接受"只表示已接收待处理，不会解锁）；③正式交付——审批全部通过后才生成正式交付文件；之后若源字段或脚本变化，系统会提示复核，不会自动覆盖历史正式版本。
- **怎么操作（最短路径）**：新建需求 → 选目标字段 → 看候选/证据 → 提待确认问题或确认口径 → 提交审核（业务→技术→终审）→ 导出交付文件 → 变更后按提示复核。
- **哪些是当前不可靠的**：真实模型（Qwen）尚未接入，本机只能用开发用 DeepSeek；真实业务准确率没有独立人工标注，不能对外宣称准确率；内网 Milvus/Redis/Celery 未实测。遇到"未验证/阻断"标记，请按提示补数据或找管理员，不要当成正式口径。

---

## 最终全量回归

命令（cwd=backend；AUTH_MODE=optional、TASK_QUEUE_PROVIDER=inline、PYTHONIOENCODING=utf-8、STORAGE_DIR=<repo>\dev_storage_local）：`python -m pytest -q`

结果：**2 failed, 1901 passed, 1 skipped, 12 warnings in 2014.11s (0:33:34)**，日志 `pytest-final-20261021.log`。
失败仅两例，均为环境级（本机 DNS 把 `*.example.net` 解析到代理 fake-IP 198.18.0.x，出站策略判定非公网）：
- `tests/test_llm_runtime.py::test_provider_quota_exhaustion_moves_to_the_fallback_provider`
- `tests/test_llm_runtime.py::test_fallback_can_target_a_separate_endpoint_and_key`

说明：若放宽 reserved 主机名会破坏 SSRF 防滥用用例，故保留生产策略；在正常 DNS 环境（CI）应全绿 → 标 BLOCKED（环境），非产品缺陷。

## 附：本轮改动文件清单

- `backend/app/services/ai_skills/field_rerank.py`（淘汰赛、metadata）
- `backend/app/services/rag/citation_validator.py`（citation-level 不冒充 claim 级）
- `backend/app/services/rag/grounded_answer_service.py`（同步口径，如涉及）
- `backend/tests/test_overnight_rerank_batching.py`（追加 tournament/oracle 用例）
- `backend/tests/test_overnight_citation_status.py`（追加 citation-level 用例）
- `backend/app/services/evaluation/regulatory_golden.py` + `data/vnext_golden_set_v1.json` + `backend/tests/test_vnext_regulatory_golden.py`（新增）
- `backend/tests/test_vnext_phase2_manual_question.py`（新增）
- `.planning/STATE.md`（仅事实同步）
- `docs/audit/VNEXT_PHASE0_CAPABILITY_MATRIX-20261021.md`（新增）
- 回滚：以上均为工作分支未提交改动，`git checkout -- <file>` 即可逐文件回退；或 `git switch dsh/banking-semantic-agent-v2` 保留分支不动。

