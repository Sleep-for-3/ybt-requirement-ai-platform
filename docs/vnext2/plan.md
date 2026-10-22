# VNext 2 开发台账（docs/vnext2/plan.md）

- 仓库：`Sleep-for-3/ybt-requirement-ai-platform`
- 工作分支：`dsh/vnext-business-accuracy-20261021`
- 本轮起始 HEAD：`6b75384e4bacd94dfae70c58900f09282c7fcde5`（与 `origin/dsh/vnext-business-accuracy-20261021` 一致，工作树干净）
- 环境：Windows + `ai-platform/backend/.venv`（Python 3.12）；真实组件栈运行在 WSL 的 docker compose（ybt-postgres 127.0.0.1:5432 / ybt-redis 127.0.0.1:6379 / Milvus 19530）；开发验收模型为公司 DeepSeek 网关，`LLM_PROVIDER=openai_compatible`，密钥只存于被忽略的 `backend/.env`。**2026-10-22 实测网关已下线 `deepseek-v4-flash`**（422 model not found），开发验收改用 `deepseek-v4.1-flash`；历史证据文件记录的 `deepseek-v4-flash` 结果仍是当时真实调用，不做改写。
- 状态口径：`TODO / IN_PROGRESS / TESTED / BLOCKED / DONE / REJECTED`；证据级别：`MOCK / REAL_COMPONENT / REAL_MODEL / BUSINESS_VERIFIED / UNVERIFIED`。只有实际执行且证据成立才允许 `DONE`。

## 环境前置（已核实）

| 事项 | 结论 | 证据 |
| --- | --- | --- |
| WSL 空闲会自动停机，导致 PG/Redis 端口消失 | 必须先用后台 `wsl -e sh -lc "sleep ..."` 保活，再等端口就绪 | 两次 Test-NetConnection 变 False、容器显示 `Up 5 seconds`（被重新拉起） |
| 测试默认继承 `backend/.env`（AUTH_MODE=required、TASK_QUEUE_PROVIDER=celery） | 定向/全量回归需显式 `AUTH_MODE=optional`；不需要真实队列时加 `TASK_QUEUE_PROVIDER=inline` | 17 例 401「Authentication required」；改后 21 passed |
| 已知全量基线 `1910 passed / 1 skipped` 未能复用 | 历史日志 `pytest-final-20261021-round3.log` 记录 2 failed（`tests/test_llm_runtime.py` 两个回退 provider 用例），需在最终回归重新判定 | 日志尾部原文 |

## 工作包

### P0-A 需求审核与冻结快照时效性治理　`DONE`

- 真实痛点：`review_readiness()` 只看冻结的 `RequirementRevision.content_json` 与脚本依据变化（`script_basis_changes`），冻结之后业务人员新增的 `PendingQuestion` 完全不参与判断；`finalize_formal_delivery()` 同样只查脚本依据变化。于是「快照时无阻断问题 → 快照后新增关键问题 → 旧快照仍可送审/正式交付」。
- 代码位置：`backend/app/services/requirement_review.py:76`（review_readiness）、`:314`（finalize_formal_delivery）、`backend/app/services/requirement_scope.py:78`（live 投影，仅用于 GET document）、`backend/app/api/deliverables.py:294`（create_question）、`:1022`（_ensure_generation_questions）。
- 复现：`backend/tests/test_vnext2_review_freshness.py`（9 例）。改前 **7 failed / 2 passed**（失败断言 `assert True is False`：`review_readiness` 返回 `eligible=True`）；两个“通过”的用例当时是空转（无任何检查时自然通过）。
- 最小修复：新增 `backend/app/services/requirement_delivery_safety.py` 作为“当前交付安全检查层”，按需求 scope（target_table_id / field_ids / scenario_id）读取当前未结案问题，reason code 复用 `manual:<id>`；`review_readiness` 与 `finalize_formal_delivery` 都调用它。冻结事实层 `content_json` 不做任何动态改写。`create_question` / `_ensure_generation_questions` 先对项目内 `requirements` 行加 `FOR UPDATE`（`lock_project_requirements`），与定稿事务的 requirement 行锁串行化，避免 TOCTOU。
- 语义：`answered`/`accepted`/`rejected` 一律仍阻断；`closed` 或 `resolved` 必须带 `resolution_text` 才解除（“已接收 ≠ 已解决”“被驳回 ≠ 口径已确认”）。
- 影响范围：需求送审、审核决策、正式交付、问题创建；不改数据库结构、不改迁移。
- 测试：
  - `pytest tests/test_vnext2_review_freshness.py -q` → **9 passed**（MOCK）
  - `VNEXT_PG_URL=... pytest tests/test_vnext2_review_freshness_pg.py -q` → **3 passed**（REAL_COMPONENT：真实 PostgreSQL 行锁阻塞与可见性）
  - 相邻回归 `tests/test_deliverables.py tests/test_reviewed_content_immutability.py` → **21 passed**（AUTH_MODE=optional + inline 队列）
- 未覆盖/下一步：冻结后新增问题是否应自动生成 `RequirementRecheck`（当前只在 SQL 变化时生成），属 P0-A 延伸，见下方“剩余缺口”。

### P0-B RAG 引用裁判与证据可信性（C08/C09/C10）　`DONE`

- 证据基线：`docs/audit/VNEXT_REAL_MODEL_GOLDEN-20261021.json` 记录真实 DeepSeek 对 10 个合成引用案例 7/10（非银行专家真值，全部 `claim_judgement="citation_level"`、`claims_judged=0`、`claim_coverage=0.0`）。
- 真实原因（已定位）：
  - C08 属产品契约缺陷：旧裁判规则 3 把“只覆盖部分条件”的引用直接判 unsupported，而黄金集要求“引用级 supported + 主张覆盖率不足 → 整体不得 verified”。系统缺少把复合监管结论拆成原子主张的能力（`split_claims_all` 只按句号切）。
  - C09 属产品缺陷：裁判没有“冲突识别”契约，两份互相矛盾的有效来源中排序靠前者被当作 supported，矛盾被静默合并。
  - C10 前半属评测转写缺陷（`scripts/vnext_real_model_golden_eval.py` 未传“需求快照固定 v1”的上下文，模型无从判断版本不一致），后半属产品缺陷（版本一致性这种可确定性判定的问题不该交给 LLM）。
- 最小修复：
  - 新增 `backend/app/services/rag/citation_trust.py`：版本归一/来源标题归一/版本违规（`version_violations`）/冲突类型归一（version|scope|contradiction）/冲突 → 引用判定降级（`downgrade_conflicting_verdicts`），全部为纯确定性函数，不调用模型。
  - `backend/app/services/rag/citation_support.py`：裁判 prompt 升级为 `[AI_SKILL_CITATION_SUPPORT_V2]`（同时输出 verdicts + claims + conflicts，verdict 带 `supported_claim_ids`）；`parse_judge_verdicts` 支持双列表并按 `dimension` 区分引用级/主张级判定（避免 claim-only 判定被按位置错配）；复合结论按“条件/包括/分别为 + 顿号逗号枚举”拆原子主张。
  - `backend/app/services/rag/citation_validator.py`：`check_citation_support(..., pinned_versions=...)` 新增可选参数（默认 None，向后兼容）；版本违规→强制 unsupported（`deterministic=True`）；冲突中**版本冲突且快照已固定版本**时只淘汰落后版本（`resolved_conflicts`，resolution=pinned_version），其余冲突（无固定版本/适用范围/真实矛盾）降级 unknown 并阻断；`trust_blockers` 禁止整体 verified。
- 影响范围：RAG 引用判定、grounded answer 状态机（未改取值）、评测脚本；不改数据库结构。
- 测试：
  - `pytest tests/test_vnext2_citation_trust.py -q` → **18 passed**（MOCK：C08 部分覆盖、C09 冲突暴露、C10 确定性版本、C04 版本冲突裁决、无固定版本的版本冲突仍为 unknown 等）
  - 相邻回归 `tests/test_rag_citation_support.py tests/test_overnight_citation_status.py` → **27 passed**
  - 真实模型 `scripts/vnext_real_model_golden_eval.py` → **10/10 判定与黄金集期望一致，0 degraded，9/10 走主张级判定，冲突暴露 2 例，失败但未 verified 2 例**，avg 4338.6ms，证据 `docs/audit/VNEXT_CITATION_TRUST-20261022.json`（REAL_MODEL，标签仍 UNVERIFIED）。
- 关键环境事实：公司网关已下线 `deepseek-v4-flash`（`POST /chat/completions` 返回 422 `model not found`，`GET /models` 只剩 `deepseek-v4.1-flash / deepseek-flash / deepseek-v4-pro / cc/* / qwen3.8-flash / glm-5.3-flash`），本轮开发验收改用 `deepseek-v4.1-flash`（`backend/.env` 已改，文件本身被 gitignore，不进提交）。
- 未覆盖/下一步：`pinned_versions` 目前只有评测脚本传入，产品生成路径（`backend/app/services/rag/grounded_answer_service.py:166`）还没有从需求快照推导固定版本——需在 P0-C 打通“需求冻结时的知识版本 → 引用裁判固定版本”，否则 C10 确定性规则在产品内不会自动生效。

### P0-C 真实监管需求生成与正式交付 E2E　`DONE`（后端 REAL_COMPONENT+REAL_MODEL，浏览器 REAL_COMPONENT 全链路）

- 痛点：`backend/tests/test_vnext_phase2_closed_loop.py` 的 `_adopt_complete_content` 直接写已确认内容，未证明「真实请求 → 模型生成 → 候选 → 采用 → 修订 → 审批 → 正式交付 → 导出」。
- 已完成（REAL_COMPONENT + REAL_MODEL）：新增 `backend/tests/test_vnext2_p0c_real_delivery.py`，合成“借据→合同→产品→产品期限方案→客户→来源库→数据集市→一表通”场景，主链路全部走 HTTP API（生成走 inline 队列真实执行 worker，真实网关 `deepseek-v4.1-flash` 生成候选），覆盖：冻结 v1 → generation-inputs/runs → 读候选 hash 与 changes → 批量 adopt → 人工补业务/技术口径 → refresh-lineage → gaps resolve → readiness → 三级审核 → finalize → xlsx/docx 导出（校验正文与 `X-Requirement-Snapshot-Hash`）→ 交付后新增问题阻断新交付且旧文件不变 → 建立新修订历史交付仍不变。失败反例：非法结构 → item failed/blocked 且不产生假正文；派生缺口不可用说明关闭；空白说明 422。
- 顺带修复的真实缺陷：①`refresh-lineage` 接口 `record_audit` 调用签名错误导致 100% 500；②AI 候选 gaps 无关闭通道造成需求永久不可送审（新增 `resolve_gap` + `POST .../gaps/{gap_id}/resolve`）；③真实推理模型空正文被“格式修复”伪造成英文占位候选（`openai_compatible.py` 空正文明确失败且不进入修复、新增 `LLM_MAX_OUTPUT_TOKENS`、候选正文必须非空且中文、worker 提示词按 section 要求中文与证据引用）。
- 测试：`pytest tests/test_vnext2_p0c_real_delivery.py -q`（真实模型）→ **4 passed / 159.94s**；相邻回归 10 个文件 → **102 passed**。
- 真实浏览器闭环（REAL_COMPONENT，2026-10-23 完成）：`scripts/vnext2_p0c_browser_e2e.mjs` 全流程 **66 步 PASS / 1019 次真实 API 调用 / exit 0**，全部动作由真实页面触发：登录→工作台→业务生成+采用（v1→v2）→技术生成+采用（v3）→页面逐条关闭分析缺口（v4–v8）→血缘快照刷新（v9）→人工补齐来源表/字段技术确认（v10）→再刷新血缘（v11）→readiness「可送审」→项目管理员送审→业务/技术/终审三级页面审批→新增问题后页面显示「1 项阻断」且「固定正式交付」按钮消失（阻断反例）→回答+结案→正式交付→下载 Excel/Word 并与 `formal-deliveries.file_hash` 对账→交付后建立新修订 v12→历史交付哈希不变→重复下载哈希一致。证据 `docs/audit/VNEXT2_P0C_BROWSER-20261022.json` 与截图目录 `docs/audit/vnext2-p0c-browser/`。
- 浏览器闭环顺带修复的真实缺陷：①前后端契约不一致导致 `adopt` 422（business 候选勾选 evidence/physical_references 越界，`requirement_candidates.py` `SPECIAL_FIELDS` 与前端复选框范围对齐）；②已关闭缺口仍渲染“关闭缺口”按钮且后端静默 201 不产生新版本（前端区分 open/closed + 后端 409「该缺口已关闭」）；③字段派生缺口被误提供“填写说明关闭”入口（前端按 `/^\d+:/` 识别并给出补齐指引）；④阻断项“重试失败项”在单轮内耗尽重试预算后 409（后端在无 failed/blocked 项时 409 明确提示，前端引导“重新点击生成候选创建新一轮”）；⑤`/admin/institutions` 对所有角色无差别请求产生必然 403（projects 页改为按 `can_view_admin` 能力再取）。
- 仍未接入：前端独立“缺口关闭 + 修订原因”编辑器之外的批量能力、`pinned_versions` 产品化（详见第 1 节剩余缺口）。

### P1-A Agent 五类业务决策　`DONE`（证据：`docs/vnext2/p1a-agent-decisions.md`；级别 `MOCK`/机制级，业务准确率 UNVERIFIED）

- 复用 `backend/app/services/agent/{planner,runtime,state_machine,dependencies,gate_policy,tools/}`，未引入第二套调度框架；五类决策各有运行时测试（`backend/tests/test_vnext2_agent_decisions.py`，5 例）：
  1. **信息充分**：确定性模板 `field_mapping` 计划可被 `materialize` 成真实步骤并执行，工具调用落在计划内、证据进入交付物，`confirm` 门禁把取舍停在 `waiting_human`（不自作主张确认）。
  2. **缺少输入**：没有 `Requirement`/生成输入时生成类任务被明确阻断（`GenerationBlockedError` → `task.blocked` + `blocked_reason_code`），不产出看似完成的空草稿。
  3. **Skill 未绑定**：仅“已发布但未固定”的 Skill 存在时视为缺失绑定，给出明确待办而不是静默绑定最新版本。
  4. **需要人工确认**：工具返回多个候选、无法唯一判定时进入 `waiting_human`，已取得的证据保留在 `step.output_summary_json`，收到人工决定后恢复执行。
  5. **人工否决**：`decision=reject` → 步骤 `blocked` + `error_code=human_rejected` + artifact `rejected`；`retry_task` 拒绝把被否决的步骤直接重跑（见下），只允许有边界的 `replan_task`（计划版本递增、原步骤 `skipped/replanned`）。
- 本轮修复真实缺陷：`backend/app/services/agent/runtime.py` 的 `retry_task` 原实现会把 `human_rejected` 的步骤重置为 `pending` 并用同一计划重跑，等于把人工否决的结论悄悄重新产出；现在先检查 `status=blocked and error_code=human_rejected` 的步骤并返回 409 `human_rejected_requires_replan`（附 `rejected_step_keys`），引导走 `replan`。
- 恢复与安全复用既有 `AgentTask/AgentPlan/AgentStep/ToolCall/BackgroundJob` 与租约，未新增状态机；`replan_task` 保留 `rejected` artifact 供审计。
- 未完成：五类决策的“业务收益”指标（正确阻断次数、错误继续率、人工返工、单任务模型调用数）尚无独立标注真值，仅能给出机制级断言；`agent_metrics` 已提供 `model_execution_rate`/`deterministic_fallback_rate`/`human_reanalysis_rate` 三个可计算比率。

### P1-B 复杂 SQL 与监管口径变化　`DONE`（证据：`docs/vnext2/p1b-sql-semantics.md`、`docs/audit/VNEXT2_SQL_DIALECT_MATRIX-20261023.json`；级别 `REAL_COMPONENT` / 合成期望）

- 已完成的语义补强（不改既有 group_by/distinct/union_mode/having/join_type 逻辑）：
  - `top_limit`：新增行数上限维度，`ORDER BY ... LIMIT/TOP` 与 `ROW_NUMBER() ... WHERE rn <= n` 都会归因为“影响样本范围”；只改格式/常量不影响。
  - `cte`：CTE 定义签名（投影+WHERE+聚合多重集，**不含名称**）参与比较，CTE 内部过滤/投影变化可归因；CTE 名称与表别名按位置规范化，等价重命名静默。
  - `order_by`：**明确 limitation**，保持 `unsupported`，理由记录在比较器与文档：仅影响展示顺序的排序不应自动认定影响监管值，产品不伪造归因。
  - 覆盖度由 36/39 提升到 38/39（`SQL_SEMANTIC_CLASSES` 统计），不为凑 39/39 输出假归因。
- 复合业务键（P1-B 4）：`backend/app/services/lineage/join_plan.py` 新增 `declared_key_columns` / `key_coverage` / `partial_unique_keys`，只有关联覆盖**完整**声明唯一键才允许 1:1 / N:1；仅按 `PRODUCT_ID` 关联 `(PRODUCT_ID, TERM_NO)` 维度时基数保持 unknown 并生成 `missing_join_cardinality` 待确认问题（文案含“复合唯一键”“不得视为一对一”“记录数或金额可能重复累计”），且**不自动拼接**缺失键。
- SQL 变化 → 需求（P1-B 5）：修复真实缺陷 `semantic_impact.py` 把 `target_field_ids` 当 `requirement_ids` 返回（`_impact_scope_dict` 又按 TargetField 反查，导致“关联需求”实际是目标字段）。现在按 `Requirement.project_id + scope_json.field_ids` 求真实需求 id，`_impact_scope_dict` 返回需求摘要（name/content_version/target_table_id/field_ids）；无关需求与其他项目不误关联，格式/注释类变化不产生复核任务，JOIN 类型变化仍生成 impact + ReviewTask。
- 本轮又修复 5 个真实缺陷（均由语法矩阵与本项测试暴露）：
  1. `gbase`/`hive` 方言字符串直接传给 `sqlglot.parse(read=...)` 抛 `ValueError: Unknown dialect` → 上传 GBase 脚本后变化分析整段 500；改为统一 `resolve_dialect`（`backend/app/services/lineage/dialects.py`）。
  2. 普通 SELECT 的 WHERE 谓词变化无结构化维度承接，掉进 AST 兜底桶 → 新增 `StatementSemantics.filters` + `filter_changed`（边层已有归因时不重复计数）。
  3. AST 兜底项按 category 表判定，导致“未归因变化”也宣称可能改变口径 → `ChangeItemSpec.attributed` 标志；未归因项 `affects_caliber=False` 且 label 标注“（未归因 AST 变化）”。
  4. CTE/表别名重命名在 AST 文本层不同 → 报未归因变化；新增 `_canonicalize_cte_names` / `_canonicalize_table_aliases` / 裸列限定符不敏感比较。
  5. CTE 名称参与签名导致纯重命名报口径变化 → 签名不含名称。
- 测试：`tests/test_vnext2_sql_rowlimit_cte.py`（12）、`tests/test_vnext2_composite_business_key.py`（3）、`tests/test_vnext2_sql_impact_requirement_link.py`（4，含 2 正例 2 反例）、语法矩阵 `scripts/vnext2_sql_dialect_matrix.py`（15 解析用例 15/15 一致、8 变更用例 8/8 一致）；`pytest -k "sql or lineage or semantic or impact"` → 365 passed；`tests/test_sql_lineage.py` 的 requirement 断言已按正确契约更新（原断言把字段 id 当需求 id）。
- 限制（已写入文档）：`order_by` 单独变化不归因；未归因变化只提示人工核对；方言白名单外的 GBase 8a 专有语法可能落到 partially_parsed/failed；字段级血缘完整性依赖元数据登记。

### P1-C 黄金集评测体系　`DONE`（框架与标注治理；业务准确率仍 `UNVERIFIED`）

- 60 例保留、`expected` 一字未改（`git diff --numstat` 仅 +12 行元数据）。新增 `GoldenAnnotation`：案例作者 / 预期答案作者 / 独立标注人 / 角色 / 标注时间 / 标注依据 / 状态（`draft/in_review/accepted/disputed/rejected`）/ 争议说明；`accepted` 必须能证明独立性（标注人 ≠ 作者）且有日期与依据，否则加载即报错；`disputed` 必须有争议说明且不计入已验证。
- 修复真实缺陷：原 `dataset_summary()` 以 `reviewer_id` 非空计 `independent_labeled`，等于允许开发 Agent 自行写个字符串宣称业务验证完成。现在历史 `reviewer_id` 只作候选，状态默认 `draft`，`verified` 需满足全部条件；`label_status` 由已验证比例决定（当前 `UNVERIFIED`）。
- `evaluate_golden_set()` 新增 `coverage`（按 kind 的 `cases/scored/not_run/truth_level`）与每个指标的 `truth_level`；未执行族显式 `not_run`、`ratio=None`，不再出现无分母的 100%。
- 证据：`docs/vnext2/p1c-golden-evaluation.md`、`docs/audit/VNEXT2_GOLDEN_REPORT-20261023.json`（脚本 `scripts/vnext2_golden_report.py`）；测试 `tests/test_vnext2_golden_annotation.py`（8 例）+ 既有 `tests/test_vnext_regulatory_golden.py` → 19 passed。
- 真实执行边界：C 引用族有真实模型专项执行（P0-B，未回灌 case 级映射）；SQL 语义真实执行见 P1-B 矩阵；交付真实执行见 P0-C；其余 50 例标 `not_run`，需下一轮逐族准备夹具。任何准确率均不得表述为真实监管准确率。

### P2-A 真实组件稳定性与内网可用性　`DONE`（证据：`docs/vnext2/p2a-stability-and-auth.md`；规模性能 `UNVERIFIED`）

- 修复 `backend/app/services/auth/actors.py` 的 savepoint 覆盖范围错误（唯一键冲突会打挂外层事务）；
  `permission_service.is_platform_admin` 的 legacy 分支现在只在 `AUTH_MODE=optional` 成立。
- 证据：`tests/test_vnext2_auth_actors.py` SQLite 4 passed / 真实 PG（含双连接竞态）5 passed；
  `pytest -k "auth or permission or rbac or admin"` → 153 passed。Milvus 重启后集合/索引/数据可查
  （`scripts/vnext2_milvus_restart.py`：16 行、top1 一致、21.8ms、重启后 healthy）。
- 未完成：Worker/Beat 进程自动重启属部署层（仓库无 supervisor，标 `UNVERIFIED`）；
  检索规模性能需用户给定容量基线后再测；共享 Redis 未重启（避免影响其他队列）。

### P2-B 工作台业务体验　`DONE`（证据：`docs/vnext2/p2b-workspace.md`；桌面 Chromium 真实点击）

- 待确认问题页区分“已接收处理 ≠ 已解决”，显示责任人/阻断状态/下一步；未填解决依据时禁点关闭并说明原因；
  正式交付面板显示当前版本 + 冻结快照哈希，并把 SQL 变化复核与三级审核状态分开呈现（含失败重试）。
- 证据：`scripts/vnext2_p2b_ui_smoke.mjs` 6 项断言全部 PASS（`docs/audit/VNEXT2_P2B_UI-20261023.json`）；
  `npx tsc --noEmit` 通过。
- 未完成：AI 候选“检索召回 / 分批模型比较 / 最终比较”阶段标识（`candidate_detail` 已返回
  `execution_metadata`，属纯前端展示缺口）。


### 全量回归与最终报告　`IN_PROGRESS`

- 后端全量（`AUTH_MODE=optional` + `TASK_QUEUE_PROVIDER=inline`）、前端测试/类型检查/构建、真实组件专项。
- 第一次全量（默认 `.env`，真实 Celery/Redis）：`2 failed, 1981 passed, 5 skipped, 1 error / 2534s`，
  原始日志 `docs/audit/VNEXT2_FULL_REGRESSION-20261023a.log`。两例定因：
  `test_requirement_generation_input.py::test_blocked_item_of_a_completed_job_can_be_retried`
  （测试断言写错，已改为验证“历史 completed 任务上的残留阻断项可重试”，单跑 8 passed）、
  `test_requirement_formal_delivery_e2e.py::test_formal_delivery_api_integration`
  （内存 SQLite `SingletonThreadPool` 线程连接脱离，单跑/相邻合跑均通过，非产品逻辑）。
- 前端：`npm test` 307/308（1 例 CDP 8s 超时抖动，单跑 12/12）、`npx tsc --noEmit` 通过、`next build` 成功。
- 产出：`docs/vnext2/final-report.md`（九部分）。隔离配置全量复跑结论回填报告第六部分。

## 剩余缺口（本轮发现的真实问题）

1. 冻结之后新增的待确认问题目前只阻断送审/交付，不会自动形成 `RequirementRecheck`（`backend/app/services/requirement_recheck.py:46` 仅由 SQL 变化触发），需在 P0-C/P1-B 一并评估是否补一条“人工问题触发复核”的显式路径。
2. `rejected` 语义仍要求 `resolution_text` 才解除阻断；`POST /questions/{id}/reject` 不写解决依据，因此驳回后仍阻断——这与“驳回不等于口径确认”一致，但产品契约需在前端文案与文档中写清。
3. 后端全量基线（1910 passed）未在本轮复现，历史日志有 2 例 llm_runtime 失败，最终回归要重新给出结论。
