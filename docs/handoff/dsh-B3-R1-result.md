# DSH B3-R1 交付报告：受控候选模型重排

## 任务 ID / 输入基线 / 当前状态

- 任务 ID：**B3-R1（受控候选模型重排）**
- 输入基线：M0 通过后的同一工作区（见 `docs/handoff/dsh-M0-result.md`）。包内无 `.git`，改动证据以「交接清单 1410 文件哈希 + 本报告列出的文件哈希」代替 `git diff`。
- 当前状态：**实现完成；Mock/确定性路径、门禁与浏览器行为已验证；真实模型质量未验证**。
- B3 仍为 `in_progress`；第二部分完整验收仍为 **false**。

## 实际使用模型

**未调用任何真实模型。** 本工作包的全部结论来自：

- Mock provider（`execution_kind="mock_model"`，Provider=mock，`model_name="mock-llm"`）；
- 确定性召回/确定性降级（`execution_kind="deterministic"`）；
- 测试内**显式替换的云传输桩**（仅用于让发布门禁在无凭据环境下通过，桩被断言从未在端点上被调用）。

运行时未提供可核实的真实模型 ID，故不填写真实模型身份。

## 完成的行为与文件

| 文件 | 大小 | SHA-256(前16) | 状态 |
| --- | --- | --- | --- |
| `backend/app/services/ai_skills/field_rerank.py` | 9243 | `1bb5467b1f7443f5` | 新增（本工作包唯一服务归属文件） |
| `backend/tests/test_ai_skill_field_rerank.py` | 21833 | `6d8ca5fc6bd2876c` | 新增 |
| `frontend/tests/ai-skill-field-rerank.browser.acceptance.mjs` | 7288 | `cb90de9c9015c349` | 新增 |
| `docs/design/ai-skill-b3-model-rerank.md` | 12610 | `ef3bbbec5407d38a` | 新增（实现前接口方案） |
| `backend/app/schemas/ai_skill_ranking.py` | 3226 | `e493111729357e7d` | 修改 |
| `backend/app/schemas/ai_skill_control.py` | 4013 | `89c936cde13cf6a8` | 修改 |
| `backend/app/services/ai_skills/runtime.py` | 17525 | `d8b5b60c357ae92c` | 修改 |
| `backend/app/services/ai_skills/evaluation.py` | 16334 | `d5990b4fd67e0eba` | 修改 |
| `backend/app/services/llm/mock.py` | 13704 | `3c40b336f2d3b2a6` | 修改 |
| `backend/app/api/ai_skills.py` | 18680 | `c061c93d8f1c1572` | 修改 |
| `backend/tests/ai_skill_acceptance_server.py` | 15489 | `a236be75c64daee9` | 修改（新增 `SKILL_ACCEPTANCE_FIELD_RERANK` fixture） |
| `frontend/components/FieldCandidateRecall.tsx` | 11670 | `d47ac1833398833e` | 修改 |
| `docs/handoff/ai-skill-center-implementation-report.md` | — | — | 修改（新增 B3-R1 检查点并更新 `next_action`） |

行为要点：

1. 新增 **`POST /ai-skills/field-candidates/model-rerank`**：仅在用户显式点击后调用；请求体只有 `input` + `context_hash`，**不含 skill_key**（技能键为服务端常量 `field_semantic_matching`）。
2. 调用前重新鉴权并重建召回快照；`context_hash` 不一致 → 409 `candidate_snapshot_changed`，**零模型调用**；无有效固定绑定 → 409 `skill_binding_required`，**不回落 Legacy 或确定性伪成功**。
3. 模型输出强 schema `field_ranking_v1`：ID 集合必须与白名单**完全相等**（缺失/重复/陌生 ID 全部拒绝）、分数严格 0–1 有限、`evidence_refs ⊆ 白名单`。
4. 调用后再次鉴权与重建快照；快照变化 → 丢弃模型排序、返回确定性列表并标注 `candidate_snapshot_changed_after_call`（保留运行日志）。
5. 模型输出非法或 Provider 失败 → **确定性降级**：`ranking_mode="deterministic_recall"`、`execution_metadata.execution_kind="deterministic"`、`rerank.status="failed"` 且给出 `error_code`；**绝不把确定性排序标成模型成功**。
6. 不外发：envelope 只含目录元数据；密级下限 `max(项目密级, "confidential")`，非 `local_only` 云模型在**调用前**被既有 `ensure_external_allowed` 拒绝。
7. 前端新增“模型重排（显式请求）”按钮、执行类别中文标签（真实模型/Mock/确定性/降级）、固定 Skill 版本/作用域/运行编号/模型名与失败原因；输入/项目/场景变化即废弃旧响应；不自动调用、不自动选择、不写映射。

## 关键接口/契约变化

1. `SkillContent.output_schema_key`：`Literal` **新增** `"field_ranking_v1"`（仅放宽关键字面量）。
2. `schemas/ai_skill_ranking.py`：新增 `RankedCandidate`、`FieldRankingCandidate`、`FieldRerankRequest`、`validate_field_ranking`；**未改动** `CandidateRank`/`FieldRankProposal`/`FieldCandidatePrepare`。
3. `runtime.py`：新增 `FIELD_RERANK_TASK`、`FIELD_RERANK_SAFETY_PROMPT`、`FieldRerankOutput`，并在 `output_schema`/`native_safety_prompt`/`compile_input`/`validate_native_output`/`execute_resolved` 增加分支。既有 task_key 取值不变 → **既有已发布绑定的依赖哈希不变**（回归证据见下）。
4. `evaluation.mandatory_assertions`：新增本任务的 native 未知候选 ID 与伪造 `evidence_refs` 两项负例探测（与 document/requirement/mapping 同构）。
5. `mock.py`：新增 `[AI_SKILL_FIELD_RERANK_V1]` 合成排序分支（只覆盖白名单；非质量证据）。
6. `api/ai_skills.py`：新增一个路由；既有路由与返回结构未变。
7. `field_candidates.py` **未改动**（召回算法、词汇版本、`validate_rank_proposal` 语义全部保持原样）。

## 测试命令、退出码、日志路径、覆盖内容

工作目录 `backend`；`DATABASE_URL=sqlite:///:memory:`、`ENVIRONMENT=development`、`TASK_QUEUE_PROVIDER=inline`、`LLM/EMBEDDING/VECTOR_STORE=mock`。

| # | 命令 | 退出码 | 结果 | 证据 |
| --- | --- | --- | --- | --- |
| 1 | `pytest tests/test_ai_skill_field_rerank.py -q` | 0 | **22 passed** (8.25s) | `docs/evaluation/ai-skill-b3-rerank-20260930/b3r1-field-rerank.xml` |
| 2 | `pytest tests/test_ai_skill_control.py tests/test_ai_skill_releases.py tests/test_ai_skill_runtime.py tests/test_ai_skill_field_candidates.py tests/test_ai_skill_candidate_preparation.py tests/test_field_candidate_vocabulary.py -q` | 0 | **86 passed** (13.57s) | `.../b3r1-regression1.log` |
| 3 | 复跑 M0 两组（改动前基线 58 / 12） | 0 | **58 passed / 12 passed**（与基线一致） | 见下「回归对照」 |
| 4 | `pytest tests -q`（全量） | 1 | **1114 passed, 11 failed, 1 skipped**（804s） | `.../b3r1-full-suite.xml`、`.../b3r1-full-suite.log` |
| 5 | `node node_modules/typescript/bin/tsc --noEmit` | 0 | 无错误 | `.../b3r1-tsc.log` |
| 6 | `node --test tests/*.test.mjs` | 0 | **156 passed / 0 fail** | `.../b3r1-frontend-unit.log` |
| 7 | `NEXT_DIST_DIR=.next-ai-skill-b2-acceptance next build` | 0 | 生产构建成功 | `.../b3r1-next-build.log` |
| 8 | `node tests/ai-skill-field-rerank.browser.acceptance.mjs` | 0 | **4 checks passed, errors=[]** | `docs/ux/acceptance/ai-skill-field-rerank-browser-20260930/results.json` |

### 第 1 组 22 项覆盖内容

Mock 正常路径（白名单不变、顺序确实改变、原始召回分与理由保留、`rank_source="model"`、固定版本/作用域/运行编号、`CandidateSourceRecommendation` 零写入、日志 `candidate_references.ranking` 可核）；envelope 只含目录元数据且密级下限受控；云模型 409 `external_model_data_denied` 且桩未被触达；非法模型输出五类（陌生 ID/重复/缺失/越界分数/伪造 evidence_refs）→ 确定性降级；Provider 失败（timeout）→ 明确失败标签；调用后快照变化 → 丢弃模型排序；无绑定 → 409 且 `resolve` 仍为 legacy；停用版本/模型漂移 → 409 `skill_unavailable` / `skill_dependency_changed`；快照六类变化与权限撤销 → 403/409；跨项目/匿名/Legacy/机构管理员 → 404/401/409；预算上限 → 409 `context_budget_exceeded`；schema 负例。

### 回归对照（改动前 vs 改动后，同机同环境）

| 组 | 改动前（M0） | 改动后（B3-R1） |
| --- | --- | --- |
| `test_field_candidate_vocabulary + test_ai_skill_field_candidates + test_ai_skill_candidate_preparation + test_retrieval_term_boundaries` | 58 passed | **58 passed** |
| `test_cross_layer_adoption_guards` | 12 passed | **12 passed** |

两组保持完全相同，且第 2 行的 `test_ai_skill_releases.py`（真实发布门禁）继续通过 → 既有发布绑定的依赖哈希未漂移。

### 全量套件中 11 项失败的定位（**均为既有/环境问题，与本工作包无关**）

| 失败测试 | 失败原因 | 与本改动的关联 |
| --- | --- | --- |
| `test_migration_schema_freeze.py::test_fresh_install_then_downgrade_then_upgrade` | `rag_evaluation_cases.assertions_json` 的 ORM 可空性与迁移不一致（断言发生在 ORM/迁移契约比较） | 无：未改模型、未改迁移（alembic head 仍 `202609270044`，迁移文件仍 44 个） |
| `test_productization.py::test_windows_lifecycle_script_without_action_keeps_control_console_open` | `scripts/项目启停.ps1` 在本机 Windows PowerShell 下 `ParserError: MissingCatchOrFinally`（line 149） | 无：未改 `scripts/` |
| `test_productization.py::test_windows_lifecycle_status_reports_semantic_runtime_and_docker_engine` | 同上脚本解析失败 + 本机无 docker 引擎 | 无 |
| `test_resources_data_contract.py`（8 项） | `monkeypatch.setattr(grounded, "execute_runtime_chat", ...)` → `AttributeError: module has no attribute 'execute_runtime_chat'`（在 `app/services/rag/grounded_answer_service.py`，本工作包未触及） | 无：失败发生在补丁阶段，早于任何被测代码 |

诚实说明：M0 未运行全量套件，因此这 11 项的「改动前即失败」是以**失败原因与未触及模块**推断的，不是改动前后的直接对照；第 3 行的两组对照才是直接的改动前后证据。

## 失败和未验证项

- **真实模型重排质量、成本、延迟未验证**：Mock 通过只证明流程、契约与门禁，不代表排序质量。
- **云模型端到端未验证**：云路径只在测试内以**无凭据的传输桩**通过发布门禁，并断言端点上桩未被调用（即外发被拒）；没有对任何真实云 Provider 发起请求。
- **PostgreSQL 未验证**（本机无 PG/Docker）；全部验证为 SQLite。
- **业务专家质量评审未完成**；`rationale` 为自由文本，服务端只能校验其**引用**是否属于白名单，不能验证业务正确性。
- **浏览器通道**：本机无 Playwright Chromium，脚本按其首选 `channel: "msedge"` 运行（与既有 B2 浏览器取证一致，但不是 Playwright Chromium）。
- **已知限制**：模型排序按 `(-score, catalog_column_id)` 稳定归一化排序，因此同分时以目录 ID 决定顺序，不保留模型给出的内部次序。
- **前端构建工具链差异**沿用 M0 记录（本机 Node v24.21.0 / npm 10.9.9，原机 npm 不可得）。

## 运行中服务 / PID 与结束方式

- 结束时**无遗留服务**：我启动的验收服务（DSH 后台作业 `pwsh-187`，`127.0.0.1:18427`）已停止，端口确认 `closed`。
- 用户 GUI 端口 `19387` 保持用户自身进程，未被我启动或重启。
- 所有 pytest / tsc / next build / node 测试进程均已退出；临时构建目录（`.next-m0-build`、`.next-ai-skill-b2-acceptance`、进程遗留的 `.next`）与 `tsconfig.tsbuildinfo` 已删除；`frontend/tsconfig.json` 与构建前副本 **SHA-256 完全一致**（`True`）。

## 代码审查风险与下一步

### 风险与需要监督方裁决的点

1. **密级下限取 `max(项目密级, "confidential")`**：这会在默认情况下**阻止云模型**执行重排（可用路径为 Mock 与 `local_only` 本地模型）。若业务需要云模型，应另行设计「逐来源外发授权投影」并单独评审；这是刻意选择的保守默认，也是本工作包的退出条件之一。
2. **`output_schema_key` 新增 `field_ranking_v1`** 与 runtime 四个分支属公共注册点改动；已用发布门禁回归（`test_ai_skill_releases.py` 通过）证明既有任务依赖哈希未变。
3. **200 + 确定性降级 vs 409 的边界**：模型侧失败（输出非法/Provider 失败/调用后快照变化）返回 200 并显式标注失败；输入/权限/绑定/预算/密级问题在调用前返回 4xx。若监督方认为调用后快照变化应为 409，需要调整契约并同步浏览器断言。
4. **`evaluation.mandatory_assertions` 新增两项断言**会改变新任务的依赖哈希（仅新任务），既有任务不受影响。
5. 单条 `rationale` 无法服务端校验语义；分数已在 API 与页面均标注「非置信度」。

### 下一步

- 失败与未验证项按 §「失败和未验证项」保留，不宣称第二部分完成。
- 继续 B3：受控模型**查询改写**、依赖式多跳、条款比较与效力比较；随后 B4（质量/UAT/项目助手）、B5（主备模型、成本/token/延迟观测、持久化缓存与失效）、B6（总体验收、PG 迁移/并发、真实模型与人工质量评审）。
