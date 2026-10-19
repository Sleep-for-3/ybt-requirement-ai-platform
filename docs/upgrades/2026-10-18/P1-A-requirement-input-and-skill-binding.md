# P1-A 交付说明：需求生成链路的输入补齐与技能绑定

- 日期：2026-10-18
- 范围：`.planning/_prompts.md:231-320`「三　P1-A　需求生成链路：输入补齐与技能绑定」
- 仓库：`ai-platform`（branch `dsh/banking-semantic-agent-v2`，HEAD `e8ce8af`）
- 状态：代码 + 回归 + 前端展示 + 全量回归全部完成；**未提交 git**（工作区保持可 review 状态）

---

## 0　结论摘要

两条独立路径都做了，且都是「不再静默降级，改成显式待办」：

| 路径 | 改动前 | 改动后 |
| --- | --- | --- |
| 输入侧：没有 Requirement 承载 | 生成确定性草稿冒充结果，另发 `requirement_input_missing` gap，共 4 次 | 步骤 `status="blocked"`，`output.next_action.code="create_requirement_input"`，**不生成草稿**；`requirement_input_missing` = 0 |
| 绑定侧：技能未绑定 | 到 agent 运行期才报 `skill_binding_missing` | 配置中心 `GET /ai-skills/binding-todos` 列出未固定技能与当前最新发布版；运行期同样改 blocked + 「固定采用已发布的技能版本」待办 |
| `deterministic_draft` 降级 | 需求链路 4 次 | 需求链路 **0 次**（残留的降级路径改名为 `model_output_unavailable`，语义是「模型没产出」，不再冒充「确定性草稿」） |
| 是否自动绑定最新发布版 | —（本次需人拍板） | **不自动**：发布仍只绑定到版本自身 scope，项目维度必须人工点一次 |

关键数字（验收跑，`tests/test_agent_acceptance.py` 的 fixture，mock 模型）：

```
requirement_input_missing : 4  →  0
requirement 链路 deterministic_draft : 4  →  0
skill_binding_missing     : 4  →  1（仅 rerank_candidates，既有契约，见 §5）
```

---

## 1　人拍板的那一个岔路口

`_prompts.md` 要求先确认「是否允许项目创建时自动绑定技能最新发布版」，不得自行决定。本轮采用并已落地的答案：

- **输入侧自动**：Requirement 可由方案推导（可编辑、有来源标注）——但本轮实现的是「前置条件不满足时阻塞并给出待办」，没有做自动推导 Requirement。理由见 §5「残余」第一条。
- **绑定侧不自动**：`ai-platform/backend/app/services/ai_skills/runtime.py` 的 `resolve_skill` 按绑定记录固定版本；自动绑最新版等于让版本随发布漂移，破坏合规语义。因此绑定侧的产物是**待办提示**，绑定动作仍需人工在配置中心点一次。

后果对照（供复核）：
- 自动绑定 → 项目永远不会缺技能，但每次发布都会静默改变在跑的判定口径，历史结论不可复现。
- 不自动绑定（当前） → 项目可能保持「未固定」状态，但由配置中心的待办显式暴露，运行期以 blocked 拦截而不是降级出草稿。

---

## 2　变更文件清单
后端（`git diff --numstat`，正数为新增行 / 负数为删除行）：

> 说明：工作区还带着**本会话更早阶段**（P0 系列、检索/治理/任务队列等）的改动，`git diff --numstat` 共 38 个 M 文件。下表只列 P1-A 自己触及的文件；其余文件不属于本次交付，复核时请勿归到 P1-A 名下。

| 文件 | +/- | 作用 |
| --- | --- | --- |
| `backend/app/services/agent/tools/ai_skill_tools.py` | +115/-3 | 输入侧与绑定侧的 blocked 归因 |
| `backend/app/services/agent/runtime.py` | +136/-7 | 人工门批准的派发原子性（outbox）与派发身份 |
| `backend/app/services/agent/planner.py` | +24/-1 | 计划校验按「实际执行时」的入参校验 |
| `backend/app/api/ai_skills.py` | +12/-0 | 新增 `GET /ai-skills/binding-todos` |
| `backend/app/services/agent/observation.py` | +1/-1 | `skill_binding_missing` 的待办文案（原写「只得到确定性降级结果」已不成立） |
| `backend/tests/agent_acceptance_fixture.py` | +124/-0 | 验收 fixture 补齐 Requirement / 生成输入 / 技能发布与绑定 |
| `backend/tests/test_agent_ai_skill_tools.py` | +26/-12 | 两个用例改断言 blocked，一个改名 |

新增文件（未跟踪 → 待 add）：

| 文件 | 行数 | 作用 |
| --- | --- | --- |
| `backend/app/services/ai_skills/binding_readiness.py` | 72 | 绑定待办的唯一计算入口 |
| `backend/tests/test_ai_skill_binding_todos.py` | 58 | 4 条路由级回归 |
| `frontend/lib/skill-binding-todos.mjs` | 35 | 待办 → 展示视图的纯函数 |
| `frontend/lib/skill-binding-todos.d.mts` | — | 手写类型声明（仿 `lib/semantic-detail-contract.d.mts`） |
| `frontend/tests/skill-binding-todos.test.mjs` | 44 | 4 条 node:test 用例 |

前端改动：`frontend/app/ai-control/skills/page.tsx` +7/-0（第 11 行 import、第 77 行 state、第 86-87 行独立请求、第 100 行面板）。
---

## 3　实现要点

### 3.1　输入侧：`blocked` 替代确定性草稿

`backend/app/services/agent/tools/ai_skill_tools.py`：
- `REQUIREMENT_INPUT_GAP_CODES`（:956）= `{"requirement_input_missing", "requirement_input_invalid"}`，两类都算「前置条件未满足」，不是模型失败。
- `_requirement_block_todo(ctx, skill_key, gaps, document=False)`（:959）：把 gap 映射成可执行待办。
  - 生成候选：`code="create_requirement_input"`、`label="先建需求输入"`、`api=/projects/{id}/requirements`、`follow_up_api=/projects/{id}/requirements/{requirement_id}/generation-inputs`、带 `target_field_id`。
  - 生成文档（`document=True`）：文档跑需要**固定修订**，所以报 `code="prepare_document_revision"` 而不是「建需求」，`api=/projects/{id}/requirements`。
  - `skill_binding_missing` → `code="bind_skill_version"`、`api=/ai-skills/{key}/binding-options`、`bind_api=/ai-skills/{key}/bindings`，文案明确「系统不会自动跟随最新发布版」。
  - 返回 `None` 表示是真执行失败，调用方保留自己带标签的降级路径——这条分支保证「阻塞」不会把模型故障也说成配置问题。
- `_blocked_requirement_result(...)`（:1020）返回 `status="blocked"`、`output.next_action`、`requires_human_confirmation=True`、`gap_codes`，并把 subject 作为 `facts` 与唯一 `evidence_ref`。
- 三个调用点：候选路径 :1070（信封构建后）、:1098（候选为 None 时）、文档路径 :1242。原 `degraded_path="deterministic_draft"` 改为 `model_output_unavailable`（:1107、:1280）。

### 3.2　绑定侧：待办由服务端统一计算

`backend/app/services/ai_skills/binding_readiness.py`（新增，86 行）：
- `_published_for(db, definition_id, scope)`（:26）：按 `version_no desc` 取 published 且 `published_at` 非空、并且 `evaluation.compatible_owner(version, scope)` 为真的版本。
- `_availability(db, version)`（:35）：`version.release_dependency_hash == evaluation.dependencies(db, version)`；评估侧抛 `HTTPException` 时判为不可用（不炸路由）。
- `_todo(definition, latest, scope)`（:44）：产出 `code/label/skill_key/task_key/display_name/scope/latest_published{id,version_no,scope_type,content_hash}/api/bind_api/available/reason`，`reason` 只有 `no_binding` 与 `no_published_version` 两种。
- `binding_todos(db, scope)`（:64）：只对 `project` / `task` scope 生效（其余返回 `[]`），用 `scope_key(scope)` 查已绑定 `definition_id` 集合，遍历全部 `AISkillDefinition` 逐条产出。

`backend/app/api/ai_skills.py:85`：`@router.get("/binding-todos")`，**声明在 `/{skill_key}` 之前**以保证字面路径优先；进入即 `control.authorize_scope(db, principal, scope)`（platform 要平台管理员、project 要 `knowledge.manage` 且项目属于该机构、institution 要机构管理员），再调 `binding_todos`。

### 3.3　派发原子性（同批做的 P0 前置）

`backend/app/services/agent/runtime.py`，因为「批准后不派发」会让 blocked 待办永远没人看到：
- `_continuation_job_key`（:975）：用 `decision_id` 做幂等键——同一条决策重复投递去重，后一条不同的决策合法地拿自己的作业。
- `_stage_continuation`（:996）：在**决策同一事务**内 stage + flush，失败即回滚决策（门还开着，可再决策）。
- `_dispatch_staged`（:1035）：提交后才派发；失败只记 alert，不 park 任务（作业行本身是恢复源）。
- `_dispatch_actor`（:1049）：续跑用 `task.created_by` 派发，因为审批者不必持有 `task.manage`；创建者恢复失败则退回调用者。
- `_record_dispatch_failure`（:1067）：写 `error_code="resume_dispatch_failed"` + `dispatch_alert=True` 并 `log.warning`，只 commit 不 park。
- `decide()`：decide → stage（同事务）→ commit → dispatch；`resume_task()` 两处 `submit_task` 改用 dispatcher 而非调用者。

### 3.4　计划校验按「实际执行时」的入参

`backend/app/services/agent/planner.py:214` `_contract_input(step, spec, subject)`：只把 subject 中「工具 `input_schema` 已声明、且 payload 该键为 `None`」的键补齐，再 `validate_input`。原先拿裸 `step.input` 校验，会把 subject 已经提供的字段判成缺参，从而在没有故障的情况下回落到更弱的计划。

### 3.5　前端：配置中心的「待固定」面板

`frontend/lib/skill-binding-todos.mjs:14` `bindingTodoView(todos)`：
- 无待办返回 `null`；否则 `{count, actionable, items[], message}`。
- `actionable` 只认 `item.available === true`——把「stale published」误报成「可绑定」会让操作员点了才发现绑不上。
- `detail` 为 `可固定 v{n}` 或 `尚无已发布版本`；`message` 形如「本范围还有 N 个技能未固定采用版本。X 个已发布待固定：…；Y 个尚无已发布版本：…。」

`frontend/app/ai-control/skills/page.tsx:100`：面板 `<section aria-label="未固定技能">`，标题「待固定的技能」，按钮点击切换到对应技能，尾注「固定采用需要人工确认，不会随发布自动变更。」。待办请求（:86-87）**独立于** `Promise.all` 并对失败静默 `.catch(() => undefined)`——待办是 advisory，读不到不能阻塞编辑器。

---

## 4　验收证据

### 4.1　目标测试集

```
pytest tests/test_agent_acceptance.py tests/test_ai_skill_binding_todos.py \
       tests/test_agent_ai_skill_tools.py tests/test_ai_skill_binding_options.py \
       tests/test_project_readiness.py -q
→ 20 passed
```

拆分：`test_agent_acceptance.py` 3 passed、`test_agent_ai_skill_tools.py` 8 passed、`test_ai_skill_binding_todos.py` 4 passed、其余共用。

`test_ai_skill_binding_todos.py` 的 4 条：
1. `test_unpublished_skill_is_a_todo_that_publishing_clears` —— 未发布时 `reason="no_published_version"`、`available=False`、`latest_published is None`；`ready()` 后仍如此；`publish()` 200 后 project scope 待办清空。
2. `test_todo_points_at_the_newest_available_published_version` —— task scope 比 project 窄，发布后仍为 `no_binding`，且指向 `latest_published.version_no == 1`、`scope_type == "project"`。
3. `test_platform_scope_has_no_todos` —— 平台维度没有「项目固定采用」语义，返回 `[]`。
4. `test_todos_require_scope_access` —— outsider → 404、未认证 → 401、manager 请求 platform scope → 403。

### 4.2　前端

```
node --test tests/*.test.mjs                     → 285 passed, 0 failed (30.4s)
node node_modules/typescript/bin/tsc --noEmit -p tsconfig.json  → 无输出（通过）
```

（本机无全局 node，使用 DSH 自带 `node.exe` v24.21.0；TypeScript 5.9.3。）

### 4.3　全量 backend 回归

```
环境：ENVIRONMENT=test AUTH_MODE=optional DATABASE_URL=sqlite:///./.ci.db
      STORAGE_PROVIDER=local TASK_QUEUE_PROVIDER=inline VECTOR_STORE_PROVIDER=mock
      LLM_PROVIDER=mock EMBEDDING_PROVIDER=mock LINEAGE_GIT_ENABLED=false
pytest -q  →  1689 passed, 1 skipped, 17 warnings in 1584.53s (0:26:24)   exit 0
```

- junit 校核（`backend/.ci-p1a-final.junit.xml`）：1690 个 `<testcase>`（含 1 个 skip）、**0 failure / 0 error**、`zz_probe` 命中 0、`binding_todos` 命中 4。
- 基线 1685 passed / 1 skipped → 1689 / 1：**新增 4 条即本次新增测试，无新增失败**。
- 1 skipped 是既有项（`test_version_consistency.py:136`，需 `PHASE4_VERIFY_DATABASE_URL` 指向一次性 PostgreSQL）。
- 收口后补记：上面是 P1-A 交付时点的数字。P1-A / P1-B / P2-A / P2-B 全部落地后的同一套件为 **1725 passed / 1 skipped**（`pytest tests -q -p no:randomly`，26m31s，exit 0）。

### 4.4　验收跑的前后对比（观测数据，不靠肉眼）

用 fixture 起一次完整验收跑（`seed_agent_acceptance` + `runtime.run_agent_task`），再对 `AgentStep` / `AgentToolCall` 的 gap 做统计：

| 指标 | 改动前 | 改动后 |
| --- | --- | --- |
| `requirement_input_missing` | 4 | **0** |
| 需求链路 `deterministic_draft` 降级 | 4（task 32/567、32/569、35/623、35/625） | **0** |
| `skill_binding_missing` | 4 | 1（仅 `rerank_candidates`） |
| 降级步骤 | 需求候选 / 需求文档等 | 仅 `generate_mapping_draft` |

残留的那 1 次 `skill_binding_missing` 来自 `rerank_candidates`：它属于 rerank 的既有降级契约（检索在缺技能时退回 `deterministic_recall`），不是本轮要消除的需求生成链路，且本轮没有把 rerank 改成阻塞（会打断检索可用性）。这是**有意保留**，已在 §5 记为残余。

---

## 5　残余、边界与需要后续跟进的事

1. **输入侧没有做「由方案自动推导 Requirement」**。`_prompts.md` 给的是二选一（自动推导 / 返回待办并阻塞），本轮选了后者：它不引入「自动编造需求内容」的风险，也不需要新的产品文案规范。真正的自动化留给后续单项。
2. **真实库 project 12 的结论与计划文档的表述不同（重要更正）**。计划文档写「requirement_candidate_generation（def 2）与 requirement_document_assistance（def 3）已发布但未绑定到 project 12」。只读探针实测：这两个 definition 的已发布版本属于 **project 5:11** 的 scope，`compatible_owner` 从 project 12 的视角看是不可见的，所以 project 12 的待办 `reason` 是 `no_published_version` 而不是 `no_binding`。**正确的运营动作是先发布到机构（institution）范围，再在 project 12 固定采用**，而不是直接点绑定。project 12 实测：`requirements` 0 行、`ai_skill_scope_bindings` 仅 1 条（def 1 / v16 / project:4:12）、`binding_todos` 返回 2 条且都是 `available=false`。
3. **验收跑是在 fixture 上做的，不是对 project 12 的活库跑**。活库链路是 celery + 真实模型，且 project 12 没有 Requirement 数据，无法在不改数据的前提下跑通。fixture 用的是 mock 模型与内存 sqlite，这一点在引用「前后对比数字」时需要一并说明。
4. **`rerank_candidates` 的 `skill_binding_missing` 保留**（见 §4.4）。
5. **未提交 git**。工作区非提交态，变更以上表文件清单为准；`frontend/next.config.mjs` 的差异只是 `core.autocrlf=true` 造成的行尾，`git diff` 内容为空，不算改动。
6. **临时探针与缓存已清理**：删除了 `backend/tests/test_zz_probe_gaps.py`、`backend/.probe_binding_todos.py`、`backend/.probe_versions.py`、`backend/jieba.cache`，以及 23 个 `backend/pip-*`、5 个 `p5q-storage-*` 等临时目录。
