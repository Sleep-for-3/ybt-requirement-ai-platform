# VNext 阶段0 能力矩阵（2026-10-21）

- 仓库分支：`dsh/banking-semantic-agent-v2`（工作分支 `dsh/vnext-business-accuracy-20261021`），HEAD `7495676`
- 判定口径：KEEP=有实现且本轮复核到代码/测试证据；IMPROVE=能跑但有真实缺陷或覆盖不足；FIX=本轮已修复可复现缺陷；MISSING=无实现（须代码证据，本轮未发现）；UNVERIFIED=未逐行复核或依赖本机不具备的组件
- 证据说明：凡标 file:line 的为本轮实际读取；仅写文件名的是本轮至少确认存在且被相关测试覆盖；标 UNVERIFIED 的明确写出未验证原因

## 1. 监管知识识别与引用真实性

- 状态：**FIX（本轮两处修复）+ IMPROVE**
- 入口：`backend/app/services/rag/citation_validator.py`（引用/主张两级判定、分母 claims_total/claims_judged/claims_unjudged、claim_coverage、coverage_truncated）、`backend/app/services/rag/citation_support.py`（judge 分批、降级 unknown）、`backend/app/services/rag/grounded_answer_service.py`（grounded/needs_confirmation/degraded 状态与置信度）
- 验证：`backend/tests/test_overnight_citation_status.py`（494 行，脚本化 judge）、`test_rag_citation_support.py`、`test_rag_evaluation_fidelity.py`
- 本轮修复：① `citation_validator.py` 的 citation-level 分支曾把引用级判定结果写进 `supported_claims`（等于把 citation-level 误记 claim-level verified），已改为 `supported_claims=[]`、claim 级计数全 0、`unknown_claims`=全部 claim；② `claim_coverage` 曾出现 1.25/2.5（分子分母不同源），已在显式分母下修正。
- 业务作用：正式结论/交付前核查只认 claim 级已验证；裁判失败不冒充全支持。
- 风险：真实模型下的 Citation Support Precision/Recall 尚无独立人工标注 → UNVERIFIED。

## 2. 字段语义匹配（召回 + 模型重排）

- 状态：**IMPROVE → 已 FIX 结构性缺陷**
- 入口：`backend/app/services/ai_skills/field_rerank.py`（582 行；`measure_batch_capacity`、`split_batches` 最多 `RERANK_MAX_BATCHES=7` 批、单批 top2 晋级、多批决赛）
- 缺陷（已复现）：旧 `_select_finalists` 按批顺序 round-robin 截断到决赛容量，召回序 10~20 位的正确候选即使被分批评估也**结构上进不了决赛**，Top1/Top3 被批次顺序决定。
- 修复：改为有界淘汰赛（leaders 池按容量分组、组内一次调用取组首、递归缩小、最后 ≤ capacity 决赛；capacity=1 保留旧行为；最坏调用数 7+6=13 ≤ `RERANK_MAX_MODEL_CALLS=16`）。新增 oracle-mock 回归（追加在 `backend/tests/test_overnight_rerank_batching.py` 末尾：旧实现失败、新实现通过，TESTED_MOCK）。
- 验证：`test_overnight_rerank_batching.py`（20 候选全评估、容量 3→7 批、超时 1 次调用即降级 deterministic_recall）、`test_ai_skill_field_rerank.py`、`test_ai_skill_rerank_timeout.py`
- 业务作用：尾部正确候选有机会成为 Top1；不同批次结果可比。
- 未验证：真实 Qwen 下的 Top1/Top3 提升幅度、token/延迟预算 → UNVERIFIED（本机无 Qwen）。

## 3. Source → Mart → YBT 取数路径溯源

- 状态：**KEEP**
- 入口：`backend/app/services/lineage/`（`sql_parser.py`、`impact_analyzer.py`、`version_diff.py`）、`backend/app/services/requirement_script_basis.py`、`requirement_candidate_contract.py`
- 验证：`tests/test_lineage_paths.py`（ECIF.CUSTOMER.CUST_ID→MART.REG_CUSTOMER→YBT 目标字段，含 join/filter 条件与 evidence）、`tests/test_requirement_paths.py`、`tests/test_requirement_script_basis.py`
- 业务作用：需求文档的「来源系统/表/字段/加工逻辑」可回溯到脚本与映射证据。
- 缺口：路径完整性依赖映射表 `mapping_status=approved`；真实生产脚本未接入 → 真实覆盖率 UNVERIFIED。

## 4. 两层映射候选（Source→Mart、Mart→YBT）

- 状态：**KEEP / IMPROVE**
- 入口：`backend/app/models/` 中 `SourceToMartMapping`、`MartToYbtMapping`、`MappingEvidenceReference`；`backend/app/services/mapping/`
- 证据：`tests/test_requirement_formal_delivery.py` 直接构造 approved 两层映射与 evidence，导出 xlsx/docx 成功。
- 缺口：候选自动生成/排序质量未做独立评测；「映射候选是否被人工采用」只有 adopted 字段，缺质量统计 → UNVERIFIED。

## 5. 制度条款与 SQL/现有实现对照

- 状态：**IMPROVE**
- 入口：`backend/app/services/requirement_policy_comparison.py`（153 行）
- 验证：`tests/test_requirement_policy_comparison.py`
- 业务作用：把制度口径与脚本加工逻辑并列，供人工确认。
- 缺口：旧版制度与新版的适用时点冲突处理只在知识侧（`knowledge/version_applicability.py`），需求文档侧未强制引用版本 → IMPROVE。

## 6. 需求草稿 / 快照 / 正式交付

- 状态：**KEEP + FIX（本轮）**
- 入口：`backend/app/services/requirement_scope.py`（`document_content`：content_version>0 走固定 revision 快照，否则按 live facts 生成 gap）、`requirement_review.py`（`review_readiness`/`submit_for_review`/`finalize_formal_delivery`）、`requirement_word.py`、`api/requirements.py`
- 验证：`test_requirement_draft_snapshots.py`、`test_requirement_snapshot_api.py`、`test_requirement_formal_delivery.py`（三级审核→finalize→xlsx 内容断言→重复 finalize 幂等）、`test_requirement_formal_delivery_e2e.py`
- 本轮验证与结论：`requirement_scope.py:109-117` 的人工问题「已处理」白名单为 `{resolved,closed,rejected}`，且要求 `resolution_text` 非空；仓库既有规格 `tests/test_requirement_scope.py:54-58` 明确规定 **accepted（已接收待处理）仍阻断**、closed/resolved 无依据仍阻断。本轮曾把 `accepted` 加进白名单，被该既有回归测试当场证伪（`test_question_resolution_requires_evidence[accepted-已接收待处理-True]` 失败），**已回退**，未修改任何既有测试预期。
- 真实发现（保持待改进）：全仓库没有任何写入方把 `question_status` 置为 `"resolved"`（grep 仅命中 requirement_scope.py:115 与 workspace projection 的读过滤），因此「有依据地结案」的实际路径是 `answer(resolution_text) → close`；`accept` 是「已接收待处理」的中间态，业务人员容易误以为已解锁。已在文档中标注，未擅自改语义。
- 新增回归：`backend/tests/test_vnext_phase2_manual_question.py`（2 个用例，TESTED_MOCK）：open→阻断、answer 未结案仍阻断、accept 仍阻断、close+有依据→解除；以及 close 无依据→仍阻断且提示「缺少解决依据」。此前 `tests/` 对 PendingQuestion **零覆盖**（grep 0 命中）。
- 业务作用：需求能走到「可审核文档」且证据可回溯；人工问题闭环不再无测试保护。

## 7. Agent 规划 / 执行 / 阻塞 / 恢复

- 状态：**UNVERIFIED（本轮未逐行复核）**
- 入口：`backend/app/services/agent/planner.py`（656 行）、`state_machine.py`（133 行）、`api/agent*.py`
- 已知测试：`tests/test_agent_planner_validation.py`、`test_agent_evaluation_v2.py`
- 未验证原因：本轮优先级放在阶段0/1/2，Agent 决策五场景（信息足继续/缺输入阻塞/技能未绑定阻塞/需人工确认等待/驳回停止）未做新的独立用例。列为后续工作包 P1。

## 8. SQL 变更影响追踪

- 状态：**IMPROVE / UNVERIFIED 细节**
- 入口：`backend/app/services/lineage/sql_semantic_diff.py`（393 行）、`impact_analyzer.py`（208 行）、`agent/sql_change_events.py`、`api/requirements.py` 的 change-impacts / rechecks
- 验证：`tests/test_requirement_recheck.py`、`test_requirement_recheck_concurrency.py`（change_hash 校验、复核后修订、并发保护）
- 基线：任务书给出 SQL 语义 36/39；本轮未重跑该基准（其脚本依赖环境未验证）→ 数字沿用基线，标 UNVERIFIED。
- 缺口：GBase/Hive 方言覆盖、order_by/top_limit/cte 三族未在本轮新增正反例 → P1 后续包。

## 9. 人工确认 / 审批 / UAT / 审计

- 状态：**KEEP + FIX（本轮）**
- 入口：`api/deliverables.py`（PendingQuestion open/answer/accept/reject/close、导出）、`services/uat/`（builtin_checks/execution/freeze/packs/reporting/seed）、`services/governance/`（audit/chain/double_layer_review/merkle/workflow）、`api/requirements.py`（review-submissions、formal-deliveries）
- 验证：`test_requirement_formal_delivery.py`（三级角色审批）、`test_requirement_uat.py`
- 本轮修复：见第 6 项（accepted 状态白名单）。
- 缺口：`tests/` 里此前**没有任何 PendingQuestion 测试**（grep 0 命中），本轮补了 1 个；更多状态迁移（reject/close、权限拒绝）仍缺回归。

## 10. 真实模型 / 向量库 / 队列

- 状态：**IMPROVE（环境受限）**
- 入口：`backend/app/services/llm/providers.py`、`vector/milvus.py`、`task_queue/`
- 事实：仓库内无 Qwen 3.8 27B 的部署配置（`backend/app/**` 搜 qwen/27b 0 命中）；`backend/.env:21` 是 DeepSeek 配置，仅开发期可用；生产主模型绑定 → BLOCKED（缺内网模型端点）。
- 全量回归：1886 passed / 2 failed，两例都在 `tests/test_llm_runtime.py`，原因是本机 DNS 将 `*.example.net` 解到 198.18.0.x（代理 fake-IP）被出站策略判非公网。生产安全策略正确，测试环境相关 → 标 BLOCKED（环境），不擅自放宽 SSRF 白名单（曾尝试按 RFC2606 主机名放行，会削弱 `test_model_profiles.py:107/162` 的用例，已回退）。
- Milvus/Redis/Celery 真实组件验收 → UNVERIFIED（本机无内网组件），见 `docs/audit/VNEXT_PHASE3_INTRANET_MODEL-20261021.md`。

## 11. 工作台体验（前端）

- 状态：**UNVERIFIED（本轮未做真实浏览器验收）**
- 入口：`frontend/components/requirement-workspace/`
- 已有审计：`docs/audit/VNEXT_PHASE5_WORKSPACE-20261021.md`
- 未验证原因：本轮未启动前端与浏览器走查；「模型已比较/仅召回」标注与失败态区分需真实页面确认。列为 P2 后续包。

## 已知缺陷 Top（本轮）

1. ~~citation-level 误写 supported_claims~~（已修，回归在 test_overnight_citation_status.py 与新增断言）
2. ~~分批重排尾部候选进不了决赛~~（已修，oracle-mock 回归）
3. PendingQuestion 零测试覆盖 + `accept` 语义易误解（已补 2 条回归；未改行为，spec 以 test_requirement_scope.py:54-58 为准）
4. `*.example.net` 测试与出站安全策略冲突（环境 BLOCKED）
5. PendingQuestion 状态迁移缺少系统性回归（已补 1 条，仍不足）

