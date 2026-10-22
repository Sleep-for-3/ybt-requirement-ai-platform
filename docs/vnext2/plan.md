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

### P0-C 真实监管需求生成与正式交付 E2E　`TODO`

- 痛点：`backend/tests/test_vnext_phase2_closed_loop.py` 的 `_adopt_complete_content` 直接写已确认内容，未证明「真实请求 → 模型生成 → 候选 → 采用 → 修订 → 审批 → 正式交付 → 导出」。
- 待做：借据/合同/产品/产品期限方案/客户/来源库/数据集市/一表通目标表的合成场景；产品 ID 重复、复合业务键、一对多、日期有效期、空值、历史与当前制度；26 步 API 链路；Word/Excel 内容与快照哈希校验；浏览器真实操作扩展。

### P1-A Agent 五类业务决策　`TODO`

- 复用 `backend/app/services/agent/{planner,runtime,state_machine,dependencies,gate_policy,tools/}`；信息充分 / 缺输入 / Skill 未绑定 / 需人工确认 / 人工否决；恢复与并发安全复用 AgentRun/AgentStep/ToolCall/BackgroundJob/租约。

### P1-B 复杂 SQL 与监管口径变化　`TODO`

- 复用 `backend/app/services/lineage/*`；GBase/Hive 语法矩阵；order_by/top_limit/cte 三类补强或明确 limitation；复合业务键膨胀检测；SQL Change → Requirement → ReviewTask 正反例各 2 个。

### P1-C 黄金集评测体系　`TODO`

- 60 例保留；`reviewer_id` 非空不足以证明独立标注，需结构化标注元数据与 `not_run` 显式；指标带样本量与真实性级别，无人工真值不得宣称准确率。

### P2-A 真实组件稳定性与内网可用性　`TODO`

- Worker/Beat 重启、租约续期、Redis/Milvus 断连恢复、索引同步、Embedding 维度变化、模型不可用时的业务状态；`backend/app/services/auth/actors.py` 的 legacy-system 物化身份权限边界；小/中/规划容量检索性能。

### P2-B 工作台业务体验　`TODO`

- 待确认问题“已接收 / 已结案”区分、AI 候选阶段标识、正式交付状态面板、操作体验与 Dirty Guard；桌面 Chromium 真实点击验收。

### 全量回归与最终报告　`TODO`

- 后端全量（`AUTH_MODE=optional`，Redis 保活）、前端测试/类型检查/构建、真实组件专项，产出 `docs/vnext2/final-report.md`。

## 剩余缺口（本轮发现的真实问题）

1. 冻结之后新增的待确认问题目前只阻断送审/交付，不会自动形成 `RequirementRecheck`（`backend/app/services/requirement_recheck.py:46` 仅由 SQL 变化触发），需在 P0-C/P1-B 一并评估是否补一条“人工问题触发复核”的显式路径。
2. `rejected` 语义仍要求 `resolution_text` 才解除阻断；`POST /questions/{id}/reject` 不写解决依据，因此驳回后仍阻断——这与“驳回不等于口径确认”一致，但产品契约需在前端文案与文档中写清。
3. 后端全量基线（1910 passed）未在本轮复现，历史日志有 2 例 llm_runtime 失败，最终回归要重新给出结论。
