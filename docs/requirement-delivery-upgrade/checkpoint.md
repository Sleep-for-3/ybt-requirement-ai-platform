# 恢复点（checkpoint）

> 本文件记录**精确**的当前状态，供上下文丢失或下一轮接手时恢复。最后更新：2026-10-23T21:5x+08:00（round 9 客户模板注册表）。
>
> **阅读顺序**：本文件按轮次追加，§1–§8 记录的是 round 1 当时状态；**判断"现在还有什么没做"请看 §19 与 `plan.md` 状态表**。早期各节里后来已实现的条目，已就地标注"已被后续轮次取代"。

## 1. 代码位置与分支

| 项 | 值 |
| --- | --- |
| 工作目录 | `C:\Users\李儒伟\Desktop\ai-platform-dsh-20260930-150943 (2)\ai-platform` |
| 分支 | `dsh/vnext-business-accuracy-20261021` |
| 基线 HEAD | `b739740aa270abfd26d7d39991495b35d1350c6d` |
| 本轮提交 | **无**（全部改动留在工作区，未 `git add` / 未 push） |
| 远端 | `https://github.com/Sleep-for-3/ybt-requirement-ai-platform`（经 `127.0.0.1:7897` 代理访问） |

## 2. 改动清单（`git status --porcelain`）

修改（19）：

```
backend/app/api/requirements.py
backend/app/models/entities.py
backend/app/schemas/api.py
backend/app/services/agent/tools/ai_skill_tools.py
backend/app/services/knowledge_ingestion/ingestion_service.py
backend/app/services/knowledge_ingestion/parsers.py
backend/app/services/mapping/requirement_input.py
backend/app/services/requirement_candidate_contract.py
backend/app/services/requirement_candidates.py
backend/app/services/requirement_generation_worker.py
backend/app/services/requirement_word.py
backend/app/services/template_parser/excel_parser.py
backend/app/services/template_parser/traceability_excel_parser.py
backend/app/services/template_service.py
backend/app/services/traceability_template_service.py
frontend/app/knowledge/documents/[documentId]/page.tsx
frontend/app/templates/[templateId]/page.tsx
frontend/app/traceability-templates/page.tsx
frontend/lib/types.ts
```

新增：

```
backend/alembic/versions/202611010002_template_parse_report.py   ~25 行
backend/app/services/parse_diagnostics.py                        ~237 行
backend/app/services/requirement_claim_support.py                ~738 行
backend/app/services/requirement_doc_template.py                ~1180-1380 行
backend/app/services/requirement_xlsx_template.py               ~1440-1630 行
backend/app/services/requirement_template_render.py              ~185 行
backend/tests/docx_template_fixtures.py                          ~300-340 行
backend/tests/test_requirement_claim_support.py                  ~330-400 行
backend/tests/test_requirement_doc_template.py                   ~370-480 行
backend/tests/test_requirement_xlsx_template.py                  ~530 行
backend/tests/test_requirement_template_render.py                ~121 行
backend/tests/test_requirement_template_export_api.py            ~127 行
backend/tests/test_xlsx_parse_diagnostics.py                     ~248 行
scripts/requirement_delivery_repro.py                            ~303 行
docs/requirement-delivery-upgrade/（plan / capability-matrix / checkpoint / evidence-index / final-report + evidence/）
```

> 行数区间是因为不同统计口径（末行换行 / 谁写的报告）；以 `git status` 的文件为准，不必纠结具体数字。

`git diff --stat`（仅已跟踪文件）：18 files changed, 802 insertions(+), 54 deletions(-)（该统计早于 `ai_skill_tools.py` 的 1 处 gap 改动）。

## 3. 数据库迁移

新迁移 `202611010002_template_parse_report.py`：`template_versions` 增加 `parse_report_json`（JSON, nullable）。`down_revision = "202611010001"`。升级/回滚对称，且有 `_column_exists` 守卫（可重复执行）。

回滚：`alembic downgrade 202611010001`（只丢弃新增报告列，不影响解析状态与冻结快照）。

## 4. 运行环境（隔离测试）

```powershell
cd "C:\Users\李儒伟\Desktop\ai-platform-dsh-20260930-150943 (2)\ai-platform\backend"
$env:PYTHONPATH='.'
$env:AUTH_MODE='optional'          # 必须；否则 TestClient 请求 /api/projects 返回 401
$env:TASK_QUEUE_PROVIDER='inline'
$env:DATABASE_URL='sqlite:///:memory:'
.\.venv\Scripts\python.exe -m pytest <targets> -q
```

- Python 3.12.4（`backend\.venv`）。
- 前端：`npm --prefix frontend exec tsc -- --noEmit -p frontend/tsconfig.json`；`node --test tests/*.test.mjs`。
- 真实栈（未在本轮运行）：见 `docs/vnext2/checkpoint.md`（WSL PG 5432 / Redis 6379 / Milvus 19530 / 后端 8011 / 前端 3010）。

## 5. 精确恢复步骤

1. 进入 `ai-platform/backend`，按 §4 设环境变量。
2. 跑四个核心测试模块确认工作区可用：
   `pytest tests/test_xlsx_parse_diagnostics.py tests/test_requirement_claim_support.py tests/test_requirement_template_render.py tests/test_requirement_template_export_api.py -q`（期望 16 + 若干 + 7 + 5 通过）。
3. 需要复现三个反例时：`python ..\scripts\requirement_delivery_repro.py --json ..\docs\requirement-delivery-upgrade\evidence\r1-r3-before-after.json`（`cases` 为修复后重跑、`after` 为修复路径；修复前的原始证据在 `evidence/r1-r3-baseline.json`）。
4. 继续 P0-A：先拿到真实案例（含作者）、独立标注人、标注依据与证据位置、争议仲裁规则；缺任何一项只能标 UNVERIFIED。数据集格式见 `scripts/requirement_golden_report.py` 顶部说明。

### 5.1 P1-A / P0-A 落地后追加（2026-10-23T19:4x+08:00）

**新增文件**

```
backend/app/models/requirement_render.py                              ~70 行
backend/app/services/requirement_render_artifact.py                   ~200 行
backend/alembic/versions/202611010003_requirement_render_artifacts.py  ~85 行
backend/app/services/requirement_golden_metrics.py                    ~250 行
backend/tests/test_requirement_render_artifact.py                     ~170 行
backend/tests/test_requirement_golden_metrics.py                      ~140 行
scripts/requirement_golden_report.py                                  ~110 行
docs/requirement-delivery-upgrade/evidence/golden-dataset-synthetic.json
docs/requirement-delivery-upgrade/evidence/golden-report-synthetic.json
```

**新增修改**：`backend/app/models/__init__.py`（导出 `RequirementRenderArtifact`）、`backend/app/api/requirements.py`（产物接线 + 两个新端点）、`backend/app/services/requirement_word.py`（`export_word` 确定性字节）。

**新迁移** `202611010003`：建 `requirement_render_artifacts`（26 列，`uq_requirement_render_identity` 保证同身份唯一）。升级/回滚已实测（sqlite scratch 库 up→down→up）。回滚：`alembic downgrade 202611010002`（丢产物表；已导出的文件仍在存储目录，但记录消失，需先备份 `requirement_render_artifacts`）。

**新端点**：

```
GET  /projects/{pid}/requirements/{rid}/render-artifacts[?source_kind=&source_id=]
GET  /projects/{pid}/requirements/{rid}/render-artifacts/{artifact_id}/download
```

**行为变化（需知悉）**：`/formal-deliveries/{id}/export`、`/snapshots/{id}/export`、`/template-exports` 现在都先查产物记录、命中则读已存文件；响应新增 `X-Requirement-Render-Artifact-Id` 与 `X-Requirement-Rendered-File-Sha256`。存储文件被篡改时返回 409，不再重新渲染。

## 6. 未覆盖 / 待用户提供

- 真实客户 DOCX / XLSX 需求模板：**一份都没有**，全部验证基于 `backend/tests/docx_template_fixtures.py` 与 `test_requirement_xlsx_template.py::build_template` 的合成模板。
- 真实模型环境（`LLM_BASE_URL` 公司网关）本轮未用于新功能的验收（隔离测试全部 mock）。
- 独立银行专家标注：**无** → 业务准确率保持 UNVERIFIED。
- 无头浏览器：本机 `startBrowser` 失败，前端仅有类型检查 + Node 单测（308 pass / 1 环境性失败）。
- LibreOffice：不存在 → XLSX 公式重算 UNVERIFIED。

## 7. 已知遗留

- `frontend` 未为新导出接口做交互（后端接口就绪，页面未接）。
- ~~旧 `/export?format=docx|xlsx` 仍走硬编码版式；客户模板导出是独立端点，未做分流开关。~~ （**已被后续轮次取代**：round 8 增加 `POST .../exports` 统一入口，见 §18 与 `evidence-index.md` §22）
- `parse_report_json` 只写不读诊断之外的用途；暂无按解析损失统计的运维看板。

## 8. P1-C / P1-D / P2-A~C 落地后追加（2026-10-23T20:0x+08:00）

**新增文件**

| 路径 | 行数量级 | 用途 |
| --- | --- | --- |
| `backend/app/services/requirement_generation_cost.py` | ~360 | 用量规整、费用计算、预算判定、账本汇总 |
| `backend/alembic/versions/202611010004_requirement_generation_usage.py` | ~40 | `requirement_generation_items.usage_json` |
| `backend/tests/test_requirement_generation_cost.py` | ~200 | 账本 14 用例（含 1/10/30 目标与 API） |
| `backend/app/services/semantic_index/chunking.py` | 505 | P1-D 分片规划（teammate `chunking` 交付） |
| `backend/tests/test_knowledge_chunking.py` | 417 | 分片 22 用例 |
| `backend/app/services/requirement_runtime_fact.py` | ~300 | P2-A 事实包校验与强度降级 |
| `backend/tests/test_requirement_runtime_fact.py` | ~140 | 13 用例 |
| `backend/app/services/requirement_source_sync.py` | ~190 | P2-B 同步裁决契约 |
| `backend/tests/test_requirement_source_sync.py` | ~120 | 8 用例 |
| `scripts/requirement_chunking_report.py` | ~170 | P1-D 信号保留证据 |
| `scripts/requirement_capacity_probe.py` | ~190 | P2-C 档位/SLO 与组件探针 |

**修改文件（增量）**：`app/models/requirement.py`（`RequirementGenerationItem.usage_json`）、`app/services/llm/prompt_runtime.py`（metadata 补 `token_usage/latency_ms/retry_count/http_status`）、`app/services/requirement_generation_worker.py`（`_record_item_usage` + 每次尝试落账）、`app/api/requirements.py`（`_generation_pricing` + `GET …/generation-inputs/{input_id}/usage`）。

**新迁移**：`202611010004`（`usage_json` 列，可空，`_column_exists` 守卫）；回滚 `alembic downgrade 202611010003`。

**新证据**：`evidence/p1d-chunking-report.json`（`FRAGMENT_PLANNING_PRESERVES_SIGNALS`，3771 字符 → 8 片、头中尾信号在第 0/3/7 片）、`evidence/p2c-capacity-probe.json`（`NOT_RUN`，三组件均不可达）。

**明确未做的接线**（round 2 时点）：~~P1-D 未接 `reindex.py`；P2-A 未接导入 API；P2-B 未接真实接口与游标表；P1-C 未实现"权限撤销即中断批任务"~~ （**已被后续轮次取代**：P1-D 见 §9、P2-A 见 §11/§13、P2-B 见 §12/§13、撤销中断见 §15）；**仍然成立**：P2-C 未跑任何真实恢复场景。

## 9. P1-D 接线（`reindex.py` / 模型 / 迁移 / 提交接口）

**新增文件**：`backend/alembic/versions/202611010005_embedding_record_vector_ids.py`（~40 行）、`backend/tests/test_reindex_fragments.py`（~280 行，5 用例）。

**修改文件（增量）**：`app/models/entities.py`（`EmbeddingRecord.vector_record_ids_json`）、`app/services/semantic_index/reindex.py`（`SUPPORTED_CHUNK_STRATEGIES` / `resolve_chunk_strategy` / `resolve_fragment_budget` / 分片批次循环 / `expected_record_count` / 结果增加 `record_count`、`chunk_strategy_version`）、`app/api/knowledge_rag.py`（`FormalReindexRequest.chunk_strategy` / `fragment_max_tokens`，422 校验，去重与幂等键纳入策略）。

**新迁移**：`202611010005`（`embedding_records.vector_record_ids_json`，可空、`_column_exists` 守卫）；回滚 `alembic downgrade 202611010004`；已实测 up → down → up 三连。

**新证据**：`evidence-index.md` §14（5 passed 的分片账目、坐标复原、默认策略不变、非法策略不回落；迁移三连；77 passed / 52 passed 两组回归）。

**行为变化**：默认策略 `existing-knowledge-unit-v1` 完全不变；只有调用方在 reindex 请求里显式传 `chunk_strategy=knowledge-fragment-v1` 才走分片。旧 `EmbeddingRecord.vector_record_id` 仍可用。

**仍未验证**：真实 embedding/Milvus 上的 TopK/MRR 与召回提升、集合级切换与回滚编排、旧父单元向量残留清理（取决于目标库 upsert/delete 语义）。

## 10. 投影账与超限真实计数（P1-C 补充，2026-10-23T20:3x+08:00）

| 项 | 文件 | 说明 |
| --- | --- | --- |
| 新增模块 | `backend/app/services/mapping/requirement_projection.py` | `PROJECTION_VERSION="requirement-input-projection-v1"`；`projection_summary` / `version_pin_omissions` / `limit_exceeded_summary` / `limit_exceeded_message` |
| 修改 | `backend/app/services/mapping/requirement_input.py` | 物理字段超限改为 `count()` 取真实总数；证据/字节超限带数字与"不做截断"；冻结输入新增 `projection` 键 |
| 新增测试 | `backend/tests/test_requirement_input_projection.py` | 6 passed / 11.08s |

- 行为变化：`input_json` 多一个 `projection` 键（`input_bytes` 不含自身）；超限仍是 **422 拒绝**，不引入自动截断/降采样。
- 恢复：删除该键不影响旧输入读取（消费方按 `content.get("projection")` 可选读取）；无需迁移。
- 回归：`-k "generation or candidate or mapping or projection"` → 330 passed / 503.38s。
- 未验证：投影账尚未在真实 500+ 行资料上跑（只在测试夹具上验证真实计数与策略不变）。

## 11. P2-A 事实包入库（追加，2026-10-23T20:5x+08:00）

| 项 | 内容 |
| --- | --- |
| 新增 | `backend/app/models/requirement_runtime.py`、`backend/app/services/requirement_runtime_fact_store.py`、`backend/alembic/versions/202611010006_requirement_runtime_fact_packs.py`、`backend/tests/test_requirement_runtime_fact_api.py` |
| 修改 | `backend/app/models/__init__.py`（导出 `RequirementRuntimeFactPack`）、`backend/app/api/requirements.py`（两个端点） |
| 迁移 | `202611010006`；回滚 `alembic downgrade 202611010005`，表与索引整体删除 |
| 行为变化 | 新增两个端点；不改变任何既有端点；事实包按 `(requirement_id, pack_sha256)` 去重 |
| 恢复 | 删除表不需要数据迁移（事实包是可选证据，旧需求不含该引用照常工作） |
| 未验证 | ~~事实包尚未注入生成输入；未做前端展示~~ （**已被后续轮次取代**：注入见 §13、面板见 §14）；无真实客户事实包仍成立 |


## 12. P2-B 游标与事件落库（追加，2026-10-23T21:0x+08:00）

**新增文件**

- `backend/app/models/external_sync.py`（~95 行）：`ExternalSyncCursor`、`ExternalSyncEvent`。
- `backend/app/services/external_sync_store.py`（231 行）：`MAX_EVENTS_PER_BATCH=200`、`ingest_events`、`load_known_state`、`list_pending`、`list_cursors`。
- `backend/app/api/external_sync.py`（~110 行）：提交 / 待复核 / 游标三个端点。
- `backend/alembic/versions/202611010007_external_sync.py`（~120 行）。
- `backend/tests/test_external_sync_api.py`（8 用例）。

**修改文件**

- `backend/app/main.py`：api 聚合列表加入 `external_sync`。
- `backend/app/services/requirement_source_sync.py`：`plan_sync` 的版本登记改为复合键 `source:object_kind:object_key` + `max()`（原裸 `object_key` 会让同批内旧版本漏判为乱序）。

**迁移与回滚**

- `202611010007`（`down_revision="202611010006"`）建 `external_sync_cursors` / `external_sync_events`，`_table_exists` 守卫；downgrade 逐表 `drop_table`。
- 实测：upgrade（两表 8 / 16 列）→ downgrade `202611010004`（两表消失）→ upgrade（恢复）。

**验证**

- `tests/test_external_sync_api.py` 8 passed；与 `test_requirement_source_sync.py` 合并 16 passed / 13.21s。
- 组合回归 33 passed / 25.94s。

**未做**

- 无真实外部接口联调；无"复核后应用"动作与界面；事件不进入需求缺口/漂移流程。


## 13. P2-A 注入生成输入（追加，2026-10-23T21:2x+08:00）

**修改文件**

- `backend/app/services/mapping/requirement_input.py`：新增 `_runtime_fact_context(db, project_id, requirement_id)`；`build_requirement_input` 在 `script_basis` 之后注入 `result["runtime_facts"]` 并追加两条 limitations。

**新增测试**

- `backend/tests/test_requirement_input_runtime_facts.py`（4 用例）：无事实包时不注入；完整包 → `full_run_validation`、`verified=true`、`gaps=[]`、limitations 含"导入时冻结"；不合法数字包 → 降级 `static_inference`、`allowed_level` 全为静态、缺口可见；事实包按需求隔离，不串到其他需求。

**行为变化**

- 生成输入 JSON 顶层新增 `runtime_facts`（仅当该需求有事实包时）；字节预算检查在其后执行，超预算仍报 422 且不截断。

**验证**

- `tests/test_requirement_input_runtime_facts.py` 4 passed / 12.02s。
- 区域回归 `pytest tests/ -q -k "generation or mapping or candidate or review or delivery or snapshot or runtime_fact"` → **455 passed, 3 skipped, 0 failed / 607.46s**（后台 job `pwsh-cde01ae4a0ba4ca4`，exit 0）。

**未做**

- 未绑定 `content_version`；未把事实类断言纳入候选 claims 校验；前端未展示 `runtime_facts`。

## 14. round 5：工作台前端接入（P2-A 展示 + P1-B 入口）

- 新增文件：
  - `frontend/components/requirement-workspace/RequirementRuntimeFactsPanel.tsx`（事实包只读列表 + 导入）
  - `frontend/components/requirement-workspace/RequirementTemplateExportPanel.tsx`（按客户模板导出 + 产物列表）
- 修改文件：
  - `frontend/lib/api.ts`：新增 `uploadFormDownload`
  - `frontend/components/requirement-workspace/RequirementWorkspace.tsx`：挂载两个面板（key `runtime-facts:` / `template-export:`）
  - `frontend/app/knowledge/documents/[documentId]/page.tsx`：修回标签“查看解析警告”
- 新增端点消费（无后端改动）：`GET/POST …/runtime-fact-packs`、`POST …/template-exports/check`、`POST …/template-exports`、`GET …/render-artifacts`、`GET …/render-artifacts/{id}/download`
- 无新增迁移。
- 验证命令：
  - `cd ai-platform/frontend && .\node_modules\.bin\tsc.cmd --noEmit -p tsconfig.json`
  - `node --test tests/workspace-performance-contract.test.mjs tests/type-declaration-coverage.test.mjs`（7 passed）
  - `node --test tests/*.test.mjs`（309 passed, 0 failed, 100.5s）
- 回滚：删除两个面板文件并撤掉 `RequirementWorkspace.tsx` 的两行挂载与两条 import；标签文案改动单独回滚即可。
- 仍未验证：真实浏览器点击路径（无可用无头浏览器）；模板适配配置需要客户真实模板才能验证。

## 15. round 6：标注导入链路 + 撤销中断验证

- 新增文件：
  - `backend/app/services/requirement_golden_import.py`（导入即拒绝不可验收的业务标注）
  - `backend/tests/test_requirement_golden_import.py`（8 passed）
  - `backend/tests/test_requirement_generation_revocation.py`（2 passed）
  - `scripts/requirement_golden_import.py`（CLI，`--strict` 退出码 2）
  - `docs/requirement-delivery-upgrade/evidence/annotation-template.csv`、`evidence/golden-pipeline-business-demo.json`
- 修改文件：无（未改任何既有服务/接口/模型）
- 无新增迁移、无接口变更。
- 验证命令：
  - `pytest tests/test_requirement_golden_import.py tests/test_requirement_generation_revocation.py -q -p no:randomly`
  - `pytest tests/ -q -k "generation or golden" -p no:randomly`
  - `python scripts/requirement_golden_import.py --input docs/requirement-delivery-upgrade/evidence/annotation-template.csv --output <tmp>.json --strict`
- 回滚：删除上述新增文件即可；无数据与迁移残留。
- 仍未验证：真实银行标注（无）、真实业务正确率（N/A）、多 worker 并发撤销（未测）。

## 16. round 7 增量（能力矩阵与分片回滚）

- 新增测试：`backend/tests/test_reindex_fragment_rollback.py`（3 用例，复用 `test_reindex_fragments` 的 `FakeEmbedding` / `_job` / `_seed_corpus` 与 `MockVectorStore`）。
- 重写文档：`docs/requirement-delivery-upgrade/capability-matrix.md`（五节 + 10 条确定性缺口，全部带证据文件与证据级别）。
- 验证命令：
  - `.venv\Scripts\python.exe -m pytest tests/test_reindex_fragment_rollback.py -q -p no:randomly` → 3 passed / 4.97s；
  - `... tests/test_reindex_fragments.py tests/test_knowledge_reindex.py tests/test_knowledge_chunking.py` → 34 passed / 11.71s。
- 环境变量与其余轮次相同：`PYTHONPATH='.'`、`AUTH_MODE='optional'`、`TASK_QUEUE_PROVIDER='inline'`、`DATABASE_URL='sqlite:///:memory:'`。
- 本轮未改动生产代码（只有新增测试与文档），因此回滚方式为删除该测试文件即可。

## 17. round 7 追加（运行事实主张校验）

- 修改文件：`backend/app/services/requirement_claim_support.py`（新增 `_RUNTIME_FACT_ALIASES`、`_LEVEL_RANK`、`_check_runtime_fact`、`_SourceIndex.runtime_fact`、支持项 `runtime_fact` 分支）、`backend/app/services/requirement_candidate_contract.py`（`ClaimAssertionKind`/`ClaimSupportSource` 增加 `runtime_fact`）、`backend/app/services/requirement_generation_worker.py`（claims 提示词）。
- 新增测试：`backend/tests/test_requirement_claim_runtime_fact.py`（9 用例）。
- 验证命令：
  - `.venv\Scripts\python.exe -m pytest tests/test_requirement_claim_runtime_fact.py -q -p no:randomly` → 9 passed / 0.79s；
  - 六文件组合 → 76 passed / 21.54s。
- 未新增迁移，不涉及数据回填：旧候选没有 `runtime_fact` 主张，行为不变（`not_evaluated`）。

## 18. round 8 增量（统一导出入口）

- 修改：`backend/app/api/requirements.py` 新增 `_builtin_export_bytes` 与 `POST .../exports`；`frontend/components/requirement-workspace/RequirementTemplateExportPanel.tsx` 增加内置版式导出按钮。
- 新增测试：`backend/tests/test_requirement_export_unified.py`（5 用例）。
- 验证命令：
  - `.venv\Scripts\python.exe -m pytest tests/test_requirement_export_unified.py -q -p no:randomly` → 5 passed / 13.33s；
  - 与 `test_requirement_template_export_api.py`、`test_requirement_render_artifact.py` 合并 → 15 passed / 21.98s；
  - `node --test tests/workspace-performance-contract.test.mjs tests/type-declaration-coverage.test.mjs tests/resources-governance-contract.test.mjs` → 10 passed。
- 无新迁移、无数据回填：新端点是既有产物表的另一种写入入口，旧端点行为不变。


## 19. round 9：客户模板注册表（追加，2026-10-23T21:5x+08:00）

新增文件：
- `backend/app/models/customer_template.py`（约 40 行）
- `backend/app/services/customer_template_store.py`（约 190 行）
- `backend/app/api/customer_templates.py`（约 110 行）
- `backend/alembic/versions/202611010008_customer_templates.py`（约 60 行）
- `backend/tests/test_customer_template_registry.py`（9 用例，约 260 行）

修改文件：
- `backend/app/models/__init__.py`（导出 `CustomerTemplate`）
- `backend/app/main.py`（注册 `customer_templates` router）
- `backend/app/api/requirements.py`（`_template_source` + `_render_customer_template(template_id=...)` + 三个端点加 `template_id`）
- `frontend/components/requirement-workspace/RequirementTemplateExportPanel.tsx`（模板下拉/注册/`template_id`）

迁移与回滚：
- head `202611010008`；`alembic downgrade 202611010007` 删除 `customer_templates` 表；再 `upgrade head` 恢复。已实测三次往返。

未做的接线：
- 没有"模板停用/下线"状态与历史交付重渲入口。
- 没有跨项目模板库与权限继承。

恢复命令（backend 目录）：
```
$env:PYTHONPATH='.'; $env:AUTH_MODE='optional'; $env:TASK_QUEUE_PROVIDER='inline'; $env:DATABASE_URL='sqlite:///:memory:'
.venv\Scripts\python.exe -m pytest tests/test_customer_template_registry.py -q
```


## 20. round 10：文档一致性审计 + 旧端点弃用（追加，2026-10-23T22:0x+08:00）

修改文件：
- `backend/app/api/requirements.py`（新增 `_EXPORT_REPLACEMENT`、`_deprecated_export_headers`；三个旧导出端点改用后者，`GET …/export` 内联两个头）
- `backend/tests/test_requirement_export_unified.py`（+1 用例，现 6 passed）
- 文档：`evidence-index.md` §24、`checkpoint.md` §20、`final-report.md` §23、`capability-matrix.md` 缺口 #10

无迁移、无模型变化。

## 21. round 10 补：迁移空值约束与 head 断言（精确恢复点）

> 补充（2026-10-23T23:00+08:00）：修复后全量回归 **2236 passed, 5 skipped / 2859.93s, exit 0**，本轮迁移相关失败已清零。


### 21.1 改了什么文件

| 文件 | 变更 |
| --- | --- |
| `backend/alembic/versions/202611010002_template_parse_report.py` | `parse_report_json` → `nullable=False, server_default=text("'{}'")` |
| `backend/alembic/versions/202611010003_requirement_render_artifacts.py` | `diagnostics_json` → `'{}'`；`warnings_json` → `'[]'`（均非空） |
| `backend/alembic/versions/202611010004_requirement_generation_usage.py` | `usage_json` → 非空 + `'{}'` |
| `backend/alembic/versions/202611010005_embedding_record_vector_ids.py` | `vector_record_ids_json` → 非空 + `'[]'` |
| `backend/alembic/versions/202611010006_requirement_runtime_fact_packs.py` | `payload_json`/`validation_json` → `'{}'`；`issues_json` → `'[]'` |
| `backend/alembic/versions/202611010007_external_sync.py` | `payload_json` → 非空 + `'{}'` |
| `backend/alembic/versions/202611010008_customer_templates.py` | `config_json`/`supported_scope_json` → 非空 + `'{}'` |
| `backend/tests/test_audit_chain.py` | 新增 `_current_head()`/`_revision_chain()`；两处 head 断言改为"唯一 head + 审计链 revision 在链上" |

无 ORM 修改（ORM 本来就是契约）。

### 21.2 恢复与回滚

- 若本地库已用旧版迁移建过表：`alembic downgrade 202611010001` 会删掉 `requirement_render_artifacts`/`requirement_runtime_fact_packs`/`external_sync_*`/`customer_templates` 等新表，再 `alembic upgrade head` 即得到修正后的 schema。
- 只想验证不回滚：`TEST_DATABASE=sqlite:///./_check.db alembic upgrade head` 后跑 `tests/test_migration_schema_freeze.py`。
- 代码层无回滚点：本次只改列约束与测试断言，不改 API/服务逻辑。

### 21.3 验证命令

```powershell
$env:PYTHONPATH='.'; $env:AUTH_MODE='optional'; $env:DATABASE_URL='sqlite:///:memory:'
.venv\Scripts\python.exe -m pytest tests/test_migration_schema_freeze.py tests/test_audit_chain.py -q -p no:randomly
# 21 passed / 134.17s
```

### 21.4 判断现状的入口

阅读顺序：本文件 §19（round 9）→ 本节（round 10 补）→ `plan.md` 状态表 → `evidence-index.md` §25 与 `final-report.md` §25。§1–§8 是 round 1 的历史快照，不能当作现状。

## 22. round 11：交付文档结构自动校验（精确恢复点）

### 22.1 新增/修改文件

| 文件 | 变更 |
| --- | --- |
| `scripts/requirement_docs_check.py` | 新增（约 210 行）：四类结构规则 + `--json` + 失败返回 1 |
| `backend/tests/test_requirement_docs_check.py` | 新增（约 130 行，5 passed / 1.16s）：真实文档必须 0 问题 + 四条坏样本反证 |
| `.github/workflows/ci.yml` | 新增 `delivery-docs` job（5 分钟超时，只跑检查器，不装 backend 依赖） |
| `docs/requirement-delivery-upgrade/checkpoint.md` | 编号与层级修复：第二处 `## 20.` → `## 21.`（含 21.1–21.4）；`### 16./17./18.` → `## 16./17./18.`；`## 5.1` → `### 5.1` |
| `docs/requirement-delivery-upgrade/capability-matrix.md` | 裸文件名引用补成带 `.md` 的写法（指向 evidence-index 第 21 节） |
| `docs/requirement-delivery-upgrade/evidence-index.md` | 重排一句，避免未绑定 § 的 `plan.md` 抢占后续 § 引用目标 |
| `docs/requirement-delivery-upgrade/plan.md` 等 | 追加本轮记录 |

### 22.2 恢复与回滚

- 校验：`python scripts/requirement_docs_check.py`（仓库根目录，失败返回 1）。
- 测试：`pytest tests/test_requirement_docs_check.py -q`。
- 回滚：删除上述两个新文件即可；文档改动仅为编号/措辞整理，无代码依赖。

### 22.3 验证命令与结果

```powershell
cd ai-platform
.\backend\.venv\Scripts\python.exe scripts\requirement_docs_check.py
# 未发现结构问题。
cd backend
.venv\Scripts\python.exe -m pytest tests/test_requirement_docs_check.py -q
# 5 passed / 1.16s
```

### 22.4 边界

- 只查结构不查语义；`DOC_NAMES` 硬编码五份文档，新增文档要同步维护。
- 该检查器不读取数据库、不调用模型，可在无环境时运行。

## 23. round 11 补：存量数据上的非空 JSON 列迁移（精确恢复点）

### 23.1 恢复方式

本轮给三张**已可能存有数据**的表新增了 JSON 列，并按 ORM 契约声明为 `nullable=False`：

- `template_versions.parse_report_json`（迁移 202611010002）
- `requirement_generation_items.usage_json`（迁移 202611010004）
- `embedding_records.vector_record_ids_json`（迁移 202611010005）

`test_migration_schema_freeze.py` 只覆盖“空库 upgrade → downgrade → upgrade”，测不到真正危险的情形：**表里已经有行**时执行 `ALTER TABLE ... ADD COLUMN ... NOT NULL DEFAULT`。如果默认值写错，生产库会在升级时失败，或者存量行拿到 NULL 而 ORM 认为非空。

### 23.2 验证命令

`backend/tests/test_requirement_usage_migration_backfill.py`（4 个用例，**4 passed / 107.91s**）：

| 用例 | 停在哪一版 | 插入的存量行 | 断言 |
| --- | --- | --- | --- |
| `test_template_versions_existing_row_gets_empty_report` | `202611010001` | 一行 `template_versions` | 升级后 `parse_report_json == '{}'` 且列 `notnull=1` |
| `test_generation_items_existing_row_gets_empty_usage` | `202611010003` | 一行 `requirement_generation_items` | 升级后 `usage_json == '{}'` 且列 `notnull=1` |
| `test_embedding_records_existing_row_gets_empty_vector_ids` | `202611010004` | 一行 `embedding_records` | 升级后 `vector_record_ids_json == '[]'` 且列 `notnull=1` |
| `test_downgrade_from_head_removes_the_new_columns` | head | 无 | 降到 `202611010001` 后三列都不存在 |

实现方式：`_alembic(database, *arguments)` 用 `subprocess` 在 sqlite 文件库上跑真实 `alembic`（`PYTHONPATH="."`、`DATABASE_URL=sqlite:///...`），`_fetch`/`_column` 直接用标准库 `sqlite3` 读 `PRAGMA table_info` 与行值——不经过 ORM，避免“ORM 默认值掩盖数据库默认值”。

### 23.3 结论

- 三条 `ADD COLUMN NOT NULL DEFAULT` 在**有存量行**时都能成功，存量行拿到 `{}` / `[]`，没有 NULL、没有升级失败。
- 反向降级能把三列都去掉，`alembic downgrade 202611010001` → `upgrade head` 是可用回滚路径（写进 `checkpoint.md` 的回滚说明）。
- 证据级别：**ISOLATED**（sqlite 上真实跑迁移；未在 PostgreSQL 上验证，未在含百万级存量行的库上测耗时与锁表时间）。

### 23.4 边界

- 只在 sqlite 上跑。PostgreSQL 的 `ADD COLUMN ... NOT NULL DEFAULT '{}'` 在 11+ 是元数据操作、不重写表，但锁级别与耗时仍需在真实库上观测，本轮**未做**。
- 未测“部分迁移失败后重试”（例如在 202611010004 失败、库停在中间状态），只测了整段成功与整段回滚。
- 存量行只插 1 行，未验证大表上的升级耗时。

## 24. 真实跑批链路验收（2026-10-24）

- 数据：项目 `project_id=9`，需求 `requirement_id=10`（T_8_1，8 字段），生成输入 `input_id=28`，冻结快照 `1`。
- 产物：`ai-platform/backend/scripts/out/T_8_1-requirement-docx.docx`（51 807 B）、`…-xlsx-standard.xlsx`（43 385 B）、`…-xlsx-survey.xlsx`（10 220 B）。
- 浏览器证据：`ai-platform/frontend/scripts/out/browser/*.png` 与 `requirement-verify.json`。
- 新增脚本：`backend/scripts/e2e_survey_doc.py`（create/generate/adopt/freeze/export/runs）、`backend/scripts/input_profile.py`（逐键量输入字节）、`backend/scripts/export_all_formats.py`（三类导出 + 跨秒重渲染比对）、`backend/scripts/e2e_sql_import.py`、`frontend/scripts/browser_verify_20261024.mjs`、`frontend/scripts/browser_verify_requirement.mjs`。
- 新增测试：`backend/tests/test_requirement_export_determinism.py`（4 用例：归一化幂等 + 三类导出跨秒一致）、`backend/tests/test_gbase_script_parsing.py`、`backend/tests/test_survey_template_parser.py`、`backend/tests/test_requirement_script_basis_projection.py`、`backend/tests/test_requirement_generation_retry.py`、`backend/tests/test_llm_output_budget.py`。
- 恢复：见 `real-run-20261024.md` §6 的启动与复现命令；WSL 必须常驻一个进程，否则容器与 PG 会随发行版休眠而消失。


## 25. 多表批量验收（2026-10-24 第二轮）

- 结论：`T_1_2` / `T_3_8` / `T_10_1` 三表走完同一条真实链路（脚本预览 → 建需 → 真实模型生成 → 采纳 → 冻结 → survey 导出），生成计数分别为 8/8、16/16、14+2；证据文件 `evidence/batch-tables-20261024-233437.json`。
- 新增/更新脚本（均在 `backend/scripts/`）：
  - `e2e_batch_tables.py`：逐表执行并落证据 JSON；`call()` 遇 401 自动重登一次。
  - `redispatch_input.py`：按 scoped 幂等键退役死 job（`retired-{id}-{ts}`、`status=failed`、清租约）→ 重置在途 item → 用 `institution_id=project.institution_id` 重新入队；用于 worker 中断后的恢复。
  - `regen_items.py`：按 `<field_id>:<section>` 补跑个别条目，只采纳 `changes[].changed` 命中的章节，再冻结并导出。
- 行为变化：
  - `SURVEY_DOC_VERSION` → `survey-requirement-doc-v4`：正文为空写"待业务补充"，无映射组仍留空。
  - 生成提示词要求正文给出可交付口径本身，禁止"见候选说明/待业务确认"式元描述。
- 精确恢复：`POST /api/projects/9/requirements/{rid}/generation-runs` 的幂等键为 `requirement-input-{input_id}`；重派必须走 `redispatch_input.py`（或按 `scoped_idempotency_key` 手工退役），否则拿回死 job。
- 仍未验证：真实客户模板、独立银行专家标注（业务准确率 N/A）、真实 provider 用量与价格、真实容量/恢复演练、LibreOffice 公式重算。

## 26. 第二轮多表批量验收（2026-10-25）

- 运行环境：WSL PG/Redis/Milvus 常驻、`uvicorn :8011`（`STORAGE_DIR=dev_storage_local`）、单个 celery worker（`--pool=solo`）、`deepseek-v4.1-flash`、`LLM_MAX_OUTPUT_TOKENS=16384`。
- 五张表：`T_1_2`(req 13)、`T_3_8`(14)、`T_10_1`(15)、`T_9_4`(16)、`T_3_6`(17)；85 个 (字段×章节) 任务，80 completed / 5 blocked / 0 failed。
- 快照：6 / 3 / 5 / 7 / 8；survey 导出 artifact 29–33，全部 `survey-requirement-doc-v6`，字节见 `real-run-20261024.md` §7；同快照第二次导出返回同一 artifact id 与同一 sha256。
- 新增/重写脚本：`backend/scripts/redispatch_input.py`（退役死 job + 重置在途 item + 用项目 `institution_id` 重派）、`backend/scripts/regen_items.py`（按字段章节补跑并重冻结导出）、`backend/scripts/e2e_batch_tables.py`（逐表全链路 + 证据 JSON）。
- 恢复要点：`POST …/generation-runs` 的幂等键存库前被 `scoped_idempotency_key` 哈希，按明文查不到旧 job；重派必须按 scoped 键退役旧 job，且 `institution_id` 取项目值。
- 证据：`evidence/batch-tables-20261024-233437.json`、`evidence/batch-tables-20261025-002243.json`。

## 27. 第三轮批量验收（2026-10-25，claims 提示词收敛）

### 27.1 本轮修改

- `app/services/lineage/preprocessing.py`：新增 `truncate_unterminated_block_comment()`，未闭合 `/*` 处截断并给出"脚本可能被人工屏蔽"的 warning；`preprocess_sql` 接上。
- `app/services/metadata/batch_parser.py`：`parse_file` 先截断未闭合块注释，warning 前置合并。
- `app/services/lineage/sql_parser.py`：`_has_sql_content()`/`_strip_sql_comments()`，语句切分不再把"只有注释的分片"当语句报错。
- `app/services/requirement_generation_worker.py`：claims 提示词要求 filter 类主张列全过滤列与取值、join_key 写明关联键、`claim.section` 与章节一致；单字段正文只写该字段、脚本常量须标注为常量并引用脚本行。
- `scripts/e2e_batch_tables.py`（沿用）：本轮跑 `T_3_5 T_10_2 T_1_4 T_3_3`，证据 `evidence/batch-tables-20261025-012056.json`。

### 27.2 结果

| 表 | 需求 | 生成 | 快照 | 导出 |
| --- | --- | --- | --- | --- |
| T_10_2 | req 18 | 20/20，0 blocked（1 142.8 s） | 9 | artifact 35，10 818 B |
| T_1_4 | req 19 | 20/20，0 blocked（841.9 s） | 10 | artifact 36，10 355 B |
| T_3_3 | req 20 | 22/22，0 blocked（1 042.5 s） | 11 | artifact 37，11 319 B |
| T_3_5 | — | 不生成（脚本整段注释屏蔽） | — | — |

### 27.3 恢复要点

- 后端/celery 重启后必须 `PYTHONPATH=.` 与 `STORAGE_DIR=<backend>\dev_storage_local`；`scripts/redispatch_input.py <input_id>` 可退役死 job 并按输入重派（本轮用于 input 40）。
- `scripts/e2e_20261024.py` 的 `Client` 没有 `post_fields`，导出需自行 `requests.post` 带 `Authorization: Bearer <token>`。
- `python.exe` 的 celery 进程是"venv 启动器 + 基础解释器子进程"一对（父 PID 相同），不是两个 worker；只杀子进程会中断在跑的模型调用。
- 仍未验证：>30 字段的大表、真实浏览器点击新导出文件、业务口径独立标注。

## 28. 第四轮批量验收与解析器漂移（2026-10-25）

- 第四轮：`T_8_3` 30/30、`T_3_4` 24/24、`T_5_5` 23+1 blocked；快照 12/13/14，产物 38/39/40，v6 渲染器。
- 新增 `backend/scripts/reparse_drift_report.py`（只读），实测 89 个 SQL 版本中 4 个解析事实落后（`YBT_DKYWCJ_TMP`、`YBT_KHC_TMP`、`YBT_T_3_5`、`YBT_T_4_3`），证据 `evidence/reparse-drift-20261025.json`。
- 未做：原地重解析（会破坏 `lineage_revisions` 固化的节点/边），故只给落后清单与处置建议。
- 恢复命令：`$env:PYTHONPATH='.'; $env:STORAGE_DIR=<backend>\dev_storage_local; .\.venv\Scripts\python.exe scripts\reparse_drift_report.py --project-id 9`。

### 28.3 缺陷 32：`mapping_sources`（2026-10-25）

- 修改 `backend/app/services/mapping/requirement_input.py`：新增 `mapping_sources`（按选中字段的 `mart_field_id` 查 `MartTable`/`MartField`，`kind="mart"`、`source="field_mapping"`），`physical_sources` 语义不变；有内容时追加一条 limitation。
- 修改 `backend/app/services/requirement_candidate_contract.py`：`allowed_physical` 并入 `context["mapping_sources"]`。
- 修改 `backend/app/services/requirement_generation_worker.py`：系统提示词改为"物理引用必须来自 physical_sources 或 mapping_sources"。
- 新增测试 `tests/test_requirement_candidate_contract.py::test_mapping_sources_are_citable_without_widening_selected_scope`。
- 恢复入口：`scripts/regen_items.py <requirement_id> <table_code> <field_id>:<section>`；补跑后 `T_5_5` → 快照 15、`scripts/out/T_5_5-survey.xlsx` 13 788 B。

## 29. 真实浏览器导出闭环与缺陷 33（2026-10-25）

- 新增 `frontend/scripts/browser_verify_export_ui.mjs`：登录取 token → `addInitScript` 注入 `sessionStorage['ybt:access-token']` 与 `localStorage['ybt:selected-project-id']` → 进 `/workspace?projectId=9` → 切表 `T_10_2` → 选需求 → 导出面板选 `xlsx` + `survey` + `draft_snapshot` + `9` → 点「内置版式导出（不套模板）」→ 捕获 `download` 落盘并比对接口导出 sha。
- 修改 `backend/app/main.py`（CORSMiddleware `expose_headers`）、`frontend/lib/api.ts`（`defaultDownloadName` 按 Content-Type 推断）。
- 新增 `tests/test_requirement_export_unified.py::test_cross_origin_export_response_exposes_artifact_headers`。
- 产物：`frontend/scripts/out/browser/ui-T_10_2-survey.xlsx`（10 818 B）、`ui-verify.json`、两张截图。
- 恢复命令：`node scripts\browser_verify_export_ui.mjs`（需前端 3010、后端 8011 在跑，且 `serve` 的 token 账号为 `ybt-lead`）。

### 29.2 客户模板浏览器路径

`frontend/scripts/browser_verify_customer_template.mjs`（作用域 `section[aria-label="客户模板导出"]`）验证「客户模板 → 已冻结快照 9」在真实浏览器里可下载：面板显示文件 sha256/模板 sha256/渲染器/配置版本，下载 `requirement-draft-snapshot-9.docx` 50 324 B、`93c7b7d2…`，与接口导出（artifact 43）字节相同，`consoleErrors: []`。恢复要点：面板内文件输入与配置文本域必须限定在导出面板作用域，否则会命中页面其他上传控件导致"点了没反应"。

### 29.3 界面生成/采纳闭环与缺陷 34

`frontend/scripts/browser_verify_generation_ui.mjs`（生成）+ `browser_verify_adopt_ui.mjs`（采纳/冻结/导出）：需求 13 轮次 #45 10/10 → 采用清单 10 条 → v6 → 快照 16 → survey xlsx 8892 B 与接口一致；`consoleErrors: []`。缺陷 34：v6 把分组名写进来源系统，v7 (`survey-requirement-doc-v7`) 改为只用脚本事实或留空。恢复要点：采纳弹层「加入采用清单」点击后弹层会自动关闭，脚本里必须先判 `isVisible()` 再点关闭，否则 30s 超时。

### 29.4 无写入目标的界面提示

- 改动：`frontend/app/resources/reverse-requirements/page.tsx`（无目标时 `role="alert"` 说明 + 待核验事项默认展开）；新增 `frontend/tests/reverse-requirements-contract.test.mjs`；`frontend/scripts/browser_verify_disabled_script.mjs` 增加 `noTargetAlertVisible/noTargetAlertText` 断言。
- 验证：`tsc --noEmit` 0；`node --test tests/reverse-requirements-contract.test.mjs` 3 passed；浏览器 `YBT_T_3_5.sql` 预览 → 告警可见、建需按钮禁用、`consoleErrors: []`。

## 30. 真实语义索引与检索（2026-10-25）

### 30.1 修改文件
| 文件 | 改动 |
| --- | --- |
| `backend/app/services/semantic_index/reindex.py` | 分片策略双键读取（`chunk_strategy` / `chunk_strategy_version`），修静默降级 |
| `backend/app/api/knowledge_rag.py` | `pending_ingestion_job_ids()`、`ingestion_in_progress_message()`，重新索引前 409 拦截 |
| `backend/app/services/retrieval/hybrid_retriever.py` | `_fragment_metadata()`；结果新增 `fragment`（最佳命中片坐标），正文仍取完整单元 |
| `frontend/lib/types.ts` | `KnowledgeFragmentLocator` + `HybridKnowledgeItem.fragment` |
| `frontend/app/knowledge/search/page.tsx` | 结果卡显示"命中片段 N（原文第 x–y 字）…引用仍取整条资料单元" |
| 新增测试 | `backend/tests/test_semantic_reindex_pending_ingestion.py`（4 用例）；`test_reindex_fragments.py` 增 API 形状 payload 用例；`test_knowledge_rag.py` 增片段坐标用例 |
| 新增/更新脚本 | `backend/scripts/e2e_semantic_index_real.py`（真实索引）、`frontend/scripts/browser_verify_knowledge_search.mjs`、`backend/scripts/reparse_drift_report.py` |

### 30.2 结果
索引版本 10、集合 `ybt_semantic_p9_v10_ec2e880fd3f8_d512`、5 条记录（长单元 3 片）、`validation.valid=true`；检索返回片段坐标、正文完整；浏览器页显示片段位置且无控制台错误。

### 30.3 恢复命令
```
# 组件
wsl -e bash -lc "sleep 86400"                     # 保活，避免容器随发行版休眠消失
docker start ybt-dev-etcd-1 ybt-dev-milvus-minio-1; sleep 5; docker start ybt-dev-milvus-1
.venv\Scripts\python.exe scripts\local_embedding_server.py --port 11434
# 后端/前端
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8011   # STORAGE_DIR=<backend>\dev_storage_local
.venv\Scripts\python.exe -m celery -A app.workers.celery_app worker --pool=solo -l info
cmd /c npx next dev -p 3010                       # 改过 TSX 后先删 frontend/.next
```

### 30.4 边界
召回质量未测；Milvus 容量/并发/真实集合级切换回滚未演练；tokenizer 为估算口径。

### 30.5 缺陷 37：投影身份 hash（2026-10-25）
| 文件 | 改动 |
| --- | --- |
| `backend/app/services/mapping/requirement_input.py` | 投影后写入 `projection.source_basis_hash = basis_hash(未投影 frozen basis)` |
| `backend/app/services/requirement_policy_comparison.py` | `ai_suggestions` 优先用 `source_basis_hash` 比对，旧输入回退旧逻辑 |
| `backend/tests/test_requirement_policy_comparison.py` | 新增不变式断言（18 passed；五文件组合 55 passed） |

定位手法：`git worktree add C:\temp\ybt-baseline HEAD` 拿基线代码复跑同一用例（基线 18 passed、当前 2 failed），确定是本轮回归后再逐条件排查。

## 31. 产物页面预览（2026-10-25）

### 31.1 新增/修改

- 新增 `backend/app/services/requirement_artifact_preview.py`（约 160 行）、`backend/tests/test_requirement_artifact_preview.py`（6 用例）、`frontend/tests/artifact-preview-contract.test.mjs`（3 用例）、`frontend/scripts/browser_verify_artifact_preview.mjs`。
- 修改 `backend/app/api/requirements.py`（新增 `render-artifacts/{artifact_id}/preview`）、`frontend/components/requirement-workspace/RequirementTemplateExportPanel.tsx`（预览入口 + 对话框 + 产物倒序）。

### 31.2 恢复与验证

```
cd ai-platform/backend
$env:PYTHONPATH="."; $env:AUTH_MODE="optional"; $env:TASK_QUEUE_PROVIDER="inline"; $env:DATABASE_URL="sqlite:///:memory:"
.\.venv\Scripts\python.exe -m pytest tests\test_requirement_artifact_preview.py -q
cd ..\frontend
node --test tests/artifact-preview-contract.test.mjs
node scripts/browser_verify_artifact_preview.mjs
```

后端改代码后需重启 uvicorn（`STORAGE_DIR=<backend>\dev_storage_local`）。

### 31.3 边界

仅 xlsx；预览上限 300 行/60 列/单元格 500 字并显式标注；不校验业务口径。

## 32. 阻断原因可见化（2026-10-25，缺陷 38）

### 32.1 新增/修改

- 新增 `backend/tests/test_requirement_generation_run_visibility.py`（2 用例）、`frontend/tests/generation-blocked-reason-contract.test.mjs`（2 用例）、`frontend/scripts/browser_verify_blocked_reason.mjs`。
- 修改 `backend/app/api/requirements.py`（`GET …/generation-runs` 条目加 `failure_detail`）、`frontend/lib/generation-rounds.d.mts`（类型）、`frontend/components/requirement-workspace/RequirementGenerationPanel.tsx`（归并清单 + 行内原因）。

### 32.2 恢复与验证

```
cd ai-platform/backend
$env:PYTHONPATH="."; $env:AUTH_MODE="optional"; $env:TASK_QUEUE_PROVIDER="inline"; $env:DATABASE_URL="sqlite:///:memory:"
.\.venv\Scripts\python.exe -m pytest tests\test_requirement_generation_run_visibility.py -q
cd ..\frontend
node --test tests/generation-blocked-reason-contract.test.mjs
node scripts/browser_verify_blocked_reason.mjs
```

后端改代码要重启 uvicorn；前端改 TSX 后若出现 `/_next/static/...css` 404 或 `clientReferenceManifest` 报错，删 `frontend/.next` 重启 `npx next dev -p 3010`。

### 32.3 边界

旧条目不追改（可能显示"未记录原因"）；归并只按文本完全相同；不自动关闭缺口或重试。


## 33. 监管模板多组集市映射与解析提示（2026-10-25）

### 33.1 新增/修改文件
- 修改 `backend/app/services/template_parser/survey_excel_parser.py`（`MART_GROUP_KEYS`、`_column_map` 三返回值、`mart_group_payloads`、`_mart_mappings`、`report.columns_unrecognized.extend`）
- 修改 `backend/app/services/template_service.py`（`_apply_mart_mapping` 逐组、`_apply_single_mart_mapping`）
- 修改 `backend/app/services/requirement_claim_support.py`（`physical_tokens` 同时索引 `mapping_sources`）
- 修改 `frontend/lib/product-language.ts`（`success: "解析成功"`）、`frontend/app/templates/[templateId]/page.tsx`（共享 `parseStatusLabel`、`sheetFindings`、统计行、数组计数）
- 新增 `backend/scripts/reparse_template_version.py`、`frontend/scripts/browser_verify_template_parse.mjs`
- 新增测试 `frontend/tests/template-parse-findings-contract.test.mjs`、`backend/tests/test_survey_template_parser.py::test_repeated_mart_columns_keep_every_mapping`、`backend/tests/test_requirement_claim_support.py::test_mapping_sources_are_citable_as_physical_support`

### 33.2 恢复与复核
- 后端改动需重启 `uvicorn`（8011）与 `celery worker` 才生效；
- 模板版本重算：`scripts/reparse_template_version.py --template-version-id 2 --commit`，随后 `POST /api/templates/2/apply`；
- **清理无效字段的规则**：`target_fields.field_code` 不符合 `^[A-Za-z][A-Za-z0-9_]{1,63}$` 的"辅助字段/数据项编码/增加字段/补充字段"先删 `mart_to_ybt_mappings` 再删字段（先确认无 `requirements.scope_json.field_ids` 引用），本轮已清 20 条 → `target_fields 2422`。

### 33.3 边界
- 多组列只覆盖五键；已冻结需求不追溯；单次 Apply 会重写 `required_flag`（`_as_required` 修复后的正常结果）。


### 33.4 端到端复核顺序（多集市映射）
1. `scripts/reparse_template_version.py --template-version-id 2 --commit`（新解析器写回版本快照 + `parse_report_json`）
2. `POST /api/templates/2/apply`（把多组集市映射写入 `MartTable`/`MartField`/`MartToYbtMapping`）
3. 重新建需（`from-scripts` 会按当前映射生成 `fields[*].mart_mappings`）→ 生成 → 采纳 → 冻结 → 导出
4. 复核：`openpyxl` 读导出 xlsx 的「溯源-监管集市」组，来源表/字段单元格应出现换行并列的多条映射

## 34. 字段级溯源面板（round 11）

### 34.1 文件

- 新增 `frontend/components/requirement-workspace/FieldTraceSummary.tsx`。
- 修改 `frontend/components/requirement-workspace/SelectedFieldEditor.tsx`（替换本地实现为共享组件）、`RequirementContentEditor.tsx`（需求专属内容模式接入）。
- 新增 `frontend/tests/field-trace-contract.test.mjs`（5 用例）、`frontend/scripts/browser_verify_field_trace.mjs`。
- 证据：`frontend/scripts/out/browser/ui-field-trace-multi-mart.png`、`ui-field-trace-no-mapping.png`、`ui-field-trace.json`。

### 34.2 复核

```powershell
cd ai-platform\frontend
.\.\node_modules\.bin\tsc.cmd --noEmit -p tsconfig.json
node --test tests/field-trace-contract.test.mjs
node scripts/browser_verify_field_trace.mjs
```

若真实页面查不到 `[aria-label="字段溯源与解析事实"]`：先确认当前需求是否绑定 `requirementId`（绑定后渲染 `RequirementContentEditor`），再确认 `next dev` 的 `.next` 缓存是否为改代码前的（删 `.next` 重启）。

### 34.3 边界

- 只显示已固定事实，不做推断；无映射必须写后果。
- 多映射需业务确认口径，不默认取第一条。
- 冻结快照不追溯。

## 35. 交付完整度（round 12）

### 35.1 文件

- 修改 `backend/app/services/requirement_survey_export.py`（`_completeness_rows` + 页脚区块，版本 `survey-requirement-doc-v8`）。
- 修改 `backend/tests/test_requirement_survey_export.py`（版本断言 + `test_completeness_footer_counts_what_is_missing`）。
- 修改 `frontend/scripts/browser_verify_artifact_preview.mjs`（新增三个断言）。
- 产物：`req 25` artifact 49（12 236 B）、`req 13` artifact 50（9 509 B）。

### 35.2 复核

```powershell
cd ai-platform\backend
.\.venv\Scripts\python.exe -m pytest tests/test_requirement_survey_export.py -q -p no:randomly
cd ..\frontend
node scripts/browser_verify_artifact_preview.mjs
```

渲染器版本变化后旧产物不会被复用（渲染身份含 `renderer_version`），如需查看新页脚必须重新导出。

### 35.3 边界

只有"有内容/没有内容"的统计；不判断口径正确性。

## 36. 覆盖度筛选（round 13）

### 36.1 文件

- 新增 `frontend/lib/field-trace.ts`、`frontend/tests/field-trace-filter-contract.test.mjs`、`frontend/scripts/browser_verify_trace_filter.mjs`。
- 修改 `frontend/components/requirement-workspace/DocumentPreview.tsx`（覆盖度筛选条、`visibleRecords`、0 行提示）。
- 证据：`frontend/scripts/out/browser/ui-trace-filter-T_1_2.png`、`ui-trace-filter-T_8_1.png`、`ui-trace-filter.json`。

### 36.2 复核

```powershell
cd ai-platform\frontend
node --test tests/field-trace-filter-contract.test.mjs
node scripts/browser_verify_trace_filter.mjs
```

### 36.3 边界

筛选与导出统计同口径（正文是否为空 + 映射条数）；不判断业务正确性，不改变审批状态。

## 37. 缺口定位筛选（round 14）

### 37.1 文件

- 修改 `frontend/lib/field-trace.ts`（`gapFieldIds`、`withGaps`、`with_gaps`）。
- 修改 `frontend/components/requirement-workspace/DocumentPreview.tsx`（「有缺口 N」筛选与归零说明）。
- 修改 `frontend/tests/field-trace-filter-contract.test.mjs`（6 用例）与 `frontend/scripts/browser_verify_trace_filter.mjs`（新增加缺口场景断言）。

### 37.2 复核

```powershell
cd ai-platform\frontend
node --test tests/field-trace-filter-contract.test.mjs
node scripts/browser_verify_trace_filter.mjs
```

库内对照 SQL：取最新 `requirement_revisions.content_json->gaps`，过滤 `field_id` 非空且 `status` 不在 `resolved/rejected/closed`。

### 37.3 边界

范围级缺口不计数；筛选不改变任何状态。

## 38. 缺口归并与定位（round 15）

### 38.1 文件

- 修改 `frontend/components/requirement-workspace/DocumentPreview.tsx`（`RequirementGapList` 按字段归并、定位按钮进 summary、`focusField` 切页签/切筛选/滚动/高亮）。
- 新增 `frontend/tests/gap-locate-contract.test.mjs`（5 用例）、`frontend/scripts/browser_verify_gap_locate.mjs`。

### 38.2 复核

```powershell
cd ai-platform\frontend
node --test tests/gap-locate-contract.test.mjs tests/field-trace-filter-contract.test.mjs
node scripts/browser_verify_gap_locate.mjs
```

若出现 `/_next/static/css/app/workspace/page.css 404`，删 `frontend/.next` 后重启 `npx next dev -p 3010`（已复现两次，属 Next dev 缓存问题）。

### 38.3 边界

定位只负责"找到"；不改缺口状态、不改需求内容。

## 39. 导出前预检（round 16）

### 39.1 文件

- 修改 `frontend/components/requirement-workspace/DocumentPreview.tsx`（`showPreflight` 状态、预检对话框、导出按钮改为先开预检）。
- 新增 `frontend/tests/export-preflight-contract.test.mjs`（4 用例）、`frontend/scripts/browser_verify_export_preflight.mjs`。

### 39.2 复核

```powershell
cd ai-platform\frontend
node --test tests/export-preflight-contract.test.mjs
node scripts/browser_verify_export_preflight.mjs
```

导出在浏览器里由 `GET /api/projects/{pid}/requirements/{rid}/export` 触发（旧端点，带 Deprecation 头）；预检不改变该行为。

### 39.3 边界

预检只是统计；不会因为存在占位而阻止导出。

## 40. 环 17 增量（来源说明注脚 + 渲染器指纹）
### 41.1 改动文件
- `backend/app/services/requirement_survey_export.py`：`_source_notes`、`_renderer_fingerprint`、`RENDERER_FINGERPRINT`、`renderer_version()`、`SURVEY_DOC_VERSION` v9。
- `backend/app/api/requirements.py`：survey 产物身份与响应头改用 `renderer_version()`。
- `backend/tests/test_requirement_survey_export.py`：注脚断言 + 指纹断言（8 passed）。
### 41.2 复核命令
```powershell
cd ai-platform\backend
$env:STORAGE_DIR=(Get-Location).Path+'\dev_storage_local'
.\venv\Scripts\python.exe -m pytest tests/test_requirement_survey_export.py tests/test_requirement_export_unified.py -q
```
### 41.3 注意
- 改渲染逻辑必须同时升 `SURVEY_DOC_VERSION`（语义）；指纹只兜底，不能替代升版。
- 旧快照不追溯：新增注脚只作用于重新导出的产物，旧 artifact 内容不变。

## 41. 冻结并导出（round 18）复核要点

### 40.1 改动的文件

- 后端：`ai-platform/backend/app/api/requirements.py`（新增 `freeze-and-export`、抽出 `_builtin_export_artifact`）、`ai-platform/backend/app/main.py`（`expose_headers` 加两个快照头）、`ai-platform/backend/tests/test_requirement_export_unified.py`（+2 用例、跨源断言扩到 7 头）。
- 前端：`ai-platform/frontend/lib/api.ts`（`downloadIdentityHeaders` / `DOWNLOAD_IDENTITY_HEADERS` / `uploadFormDownload` 返回 headers）、`components/requirement-workspace/DocumentPreview.tsx`（`ExportOutcome`、`onFreezeAndExport`、导出身份区块）、`RequirementWorkspace.tsx`（`freezeAndExport()`）、`tests/freeze-export-contract.test.mjs`（新增）。
- 浏览器脚本：`ai-platform/frontend/scripts/browser_verify_freeze_export.mjs`（新增；第一轮取身份后点「返回修改」关闭弹层，关闭浏览器前 `waitForTimeout(1500)` 避免在途请求被记成 `ERR_ABORTED`）。

### 40.2 复核命令

```powershell
cd ai-platform\backend
$env:PYTHONPATH='.'; $env:AUTH_MODE='optional'; $env:TASK_QUEUE_PROVIDER='inline'; $env:DATABASE_URL='sqlite:///:memory:'
.venv\Scripts\python.exe -m pytest tests/test_requirement_export_unified.py -q
# 复核完务必清掉环境变量，否则会污染后续 uvicorn 启动（见 §40.3）
Remove-Item Env:DATABASE_URL,Env:AUTH_MODE,Env:TASK_QUEUE_PROVIDER,Env:PYTHONPATH -ErrorAction SilentlyContinue

cd ai-platform\frontend
.\node_modules\.bin\tsc.cmd --noEmit -p tsconfig.json
node --test tests/freeze-export-contract.test.mjs
node scripts/browser_verify_freeze_export.mjs
```

### 40.3 环境陷阱（本轮踩到）

在同一个 PowerShell 会话里跑过 pytest（设了 `DATABASE_URL=sqlite:///:memory:`）后启动 uvicorn，后端会连内存 sqlite：`/health/live` 仍返回 200，但登录 500（`no such table: login_attempts`）。

- 启动后端前清掉 `DATABASE_URL`/`AUTH_MODE`/`TASK_QUEUE_PROVIDER`/`PYTHONPATH`；
- 判断服务是否真的可用用 **`/health/ready`**（含 database / alembic_revision / storage / redis / task_queue）。

### 41.4 边界

见 `real-run-20261024.md` §22.5：未测并发冻结、角色权限组合、docx+standard 的浏览器点击、审批链复测。

## 42. 导出前字段级差异（round 19）

### 42.1 变更文件

| 类型 | 文件 |
| --- | --- |
| 后端接口 | `backend/app/api/requirements.py`（`read_draft_snapshot_content`） |
| 后端测试 | `backend/tests/test_requirement_export_unified.py`（新增用例） |
| 前端纯函数 | `frontend/lib/snapshot-diff.ts` |
| 前端组件 | `frontend/components/requirement-workspace/DocumentPreview.tsx`、`RequirementWorkspace.tsx` |
| 前端契约测试 | `frontend/tests/snapshot-diff-contract.test.mjs` |
| 浏览器脚本 | `frontend/scripts/browser_verify_snapshot_diff.mjs` |

### 42.2 复核步骤

```powershell
# 1) 服务健康（看 /health/ready，不是 /health/live）
Invoke-RestMethod http://127.0.0.1:8011/health/ready
# 2) 契约与后端用例
cd ai-platform/frontend; node --test tests/snapshot-diff-contract.test.mjs
cd ai-platform/backend;  .\.venv\Scripts\python.exe -m pytest tests/test_requirement_export_unified.py -q
# 3) 真实浏览器两态
cd ai-platform/frontend; node scripts/browser_verify_snapshot_diff.mjs
```

### 42.3 做"有变化态"要动的数据（会留修订历史）

```powershell
# 在旧需求 10 上编辑 H010010 业务定义（expected_content_version 必须带，否则 409）
PUT /api/projects/9/requirements/10/fields/2316
{"expected_content_version":4,"section":"business","changes":{"business_definition":"…（评审补充：需与合同编号交叉校验，避免同借据号跨合同。)"}}
# 复现完把内容改回原文；注意 content_version 会继续 +1（本次到 6），content_hash 不再等于快照 1
```

### 42.4 边界

- 只与最近一次快照比；不比较资料范围/缺口/脚本依据逐项内容。
- 大字段数（100+）渲染耗时未测。
- 快照 JSON 损坏时接口报错，界面显示"差异暂不可用"而不是空。

## 43. 冻结状态常驻可见（round 20）

### 43.1 变更文件

| 类型 | 文件 |
| --- | --- |
| 后端接口 | `backend/app/api/requirements.py`（`list_draft_snapshots` 增加 `is_latest`） |
| 后端测试 | `backend/tests/test_requirement_export_unified.py`（新增 `test_snapshot_list_marks_only_the_latest_snapshot`） |
| 前端组件 | `frontend/components/requirement-workspace/RequirementSnapshotsPanel.tsx` |
| 前端契约测试 | `frontend/tests/snapshot-status-contract.test.mjs` |
| 浏览器脚本 | `frontend/scripts/browser_verify_snapshot_status.mjs` |

### 43.2 复核步骤

```powershell
# 1) 服务健康（/health/ready，不是 /health/live）
Invoke-RestMethod http://127.0.0.1:8011/health/ready
# 2) 接口返回 is_latest
#    GET /api/projects/9/requirements/10/snapshots → 首项 is_latest=true
# 3) 两种状态的浏览器证据
cd ai-platform/frontend; $env:STATUS_SUFFIX="frozen"; node scripts/browser_verify_snapshot_status.mjs
cd ai-platform/frontend; $env:STATUS_SUFFIX="stale";  node scripts/browser_verify_snapshot_status.mjs
```

### 43.3 做"有未冻结改动"态要动的数据

```powershell
# 需求 10 当前已冻结在快照 19；改一个字段即可复现 stale 态
PUT /api/projects/9/requirements/10/fields/2316
{"expected_content_version":<当前 revision.content_version>,"section":"business",
 "changes":{"business_definition":"<原文>（冻结状态演示：这一句尚未冻结）"}}
# 复现完改回原文，再 POST /snapshots 冻结一份新快照，回到"已冻结"态
```

### 43.4 边界

- 只回答"内容是否冻结在最近快照"，不判断可交付性。
- 快照列表上限 200；大量快照渲染耗时未测。

## 44. 任选两份快照对比（round 21）

### 44.1 变更文件

| 类型 | 文件 |
| --- | --- |
| 前端纯函数 | `frontend/lib/snapshot-diff.ts`（新增 `diffSnapshotPair` / `snapshotPairSummary` / `SnapshotSide`） |
| 前端组件 | `frontend/components/requirement-workspace/RequirementSnapshotsPanel.tsx`（对比基准 + 与基准对比 + 对比弹层） |
| 前端契约测试 | `frontend/tests/snapshot-compare-contract.test.mjs` |
| 浏览器脚本 | `frontend/scripts/browser_verify_snapshot_compare.mjs` |

本轮**没有**后端改动：两份快照内容都走 round 19 已有的 `GET …/snapshots/{id}/content`。

### 44.2 复核步骤

```powershell
Invoke-RestMethod http://127.0.0.1:8011/health/ready
cd ai-platform/frontend; node --test tests/snapshot-compare-contract.test.mjs
cd ai-platform/frontend; $env:COMPARE_SUFFIX="identical-fields"; node scripts/browser_verify_snapshot_compare.mjs
cd ai-platform/frontend; $env:COMPARE_SUFFIX="changed"; node scripts/browser_verify_snapshot_compare.mjs
```

### 44.3 造"口径有变化"的两份快照

```powershell
# 1) PUT /api/projects/9/requirements/10/fields/2316
#    {"expected_content_version":<当前>,"section":"business",
#     "changes":{"business_definition":"<原文>（对比演示：本条需与合同编号交叉校验）"}}
# 2) GET …/document 取 content_hash → POST …/snapshots {expected_version, expected_hash}
# 3) 复原：把 H010010 业务定义改回原文（可从 GET …/snapshots/19/content 取），再冻结一份
```

### 44.4 边界

- 只比四个口径段落；缺口/资料范围/脚本依据的差异只体现为"hash 不同"。
- 明细上限 20 条。
- 对比只读，不落库、不写审计。

## 45. round 22：项目级交付状态

### 45.1 变更文件

| 文件 | 变更 |
| --- | --- |
| `backend/app/services/requirement_delivery_status.py` | 新增：项目级聚合（冻结态 / 快照 / 产物 / 打开缺口） |
| `backend/app/api/requirements.py` | 新增 `GET /projects/{project_id}/requirements-status` |
| `backend/tests/test_requirement_delivery_status.py` | 新增 4 个用例 |
| `frontend/lib/delivery-status.ts` | 新增：三态判定与文案、体积格式化 |
| `frontend/app/projects/[projectId]/readiness/page.tsx` | 新增"需求交付状态"区块 |
| `frontend/tests/delivery-status-contract.test.mjs` | 新增 4 个契约用例 |
| `frontend/scripts/browser_verify_delivery_status.mjs` | 新增真实浏览器验证脚本 |

### 45.2 复核步骤

1. 重启后端（清 `DATABASE_URL/AUTH_MODE/TASK_QUEUE_PROVIDER/PYTHONPATH`，设 `STORAGE_DIR`），等 `/health/ready` 200。
2. `GET /api/projects/9/requirements-status` 应返回 17 条，`summary.frozen=13`、`no_snapshot=4`。
3. `node scripts/browser_verify_delivery_status.mjs` → 头条"17 条需求：已冻结 13 条 · 有未冻结改动 0 条 · 无快照 4 条"。
4. 造有改动：`PUT /api/projects/9/requirements/13/fields/487`（`expected_content_version` 取当前），再 `STATUS_SUFFIX=stale` 重跑 →
   头条变 12/1/4，`T_1_2` 行显示"最近快照 #16 之后仍有改动"。
5. 复原：把正文改回原文后 `POST …/snapshots` 冻结（会生成新快照，因为 hash 含修订痕迹），状态回到 13/0/4。

### 45.3 边界

- 只读；不冻结、不渲染、不改内容；判据只有 `content_hash`。
- 仅草稿快照；不含正式交付；200 条上限。

## 46. round 23：正式交付与就绪度

### 46.1 变更文件

- `backend/app/services/requirement_delivery_status.py`：`_readiness` 增 `formal_current`/`formal_present` 两个入参，产出 `delivered`/`delivered_stale`；`READINESS_LABELS` 增两项；summary 增 `delivered`/`delivered_stale`。
- `backend/tests/test_requirement_delivery_status.py`：`test_readiness_mapping_covers_every_state` 扩到六态（含"正式交付后又改内容不算已交付"）。
- `frontend/lib/delivery-status.ts`：六态类型、标签、徽标、排序权重、`readinessHeadline` 与 `deliveryReadiness` 回退规则、`formalDeliveryText`。
- `frontend/app/projects/[projectId]/readiness/page.tsx`：交付就绪列、正式交付列、排序开关（`aria-pressed`）、说明文案。
- `frontend/tests/delivery-readiness-contract.test.mjs`：新增 7 个断言组（六态、回退、排序权重、正式交付文案、头条四条互斥、页面渲染、禁止自行推断）。
- `frontend/scripts/browser_verify_delivery_readiness.mjs`：真实浏览器验证脚本（项目 9 两种排序 + 项目 7 已交付内容已改），输出 `ui-readiness*.png` 与 `ui-readiness.json`。

### 46.2 复核步骤

```powershell
# 1) 后端
cd ai-platform/backend
Get-CimInstance Win32_Process -Filter "Name='python.exe'" | ? { $_.CommandLine -like "*uvicorn*8011*" } | % { Stop-Process -Id $_.ProcessId -Force }
Remove-Item Env:DATABASE_URL,Env:AUTH_MODE,Env:TASK_QUEUE_PROVIDER,Env:PYTHONPATH -ErrorAction SilentlyContinue
$env:STORAGE_DIR="<repo>i-platformackend\dev_storage_local"
Start-Process .\.venv\Scripts\python.exe -ArgumentList "-m","uvicorn","app.main:app","--host","127.0.0.1","--port","8011"
# 2) 接口：GET /api/projects/9/requirements-status 看 summary.delivered / delivered_stale
# 3) 页面：/projects/9/readiness 看「交付就绪」列与排序开关；/projects/7/readiness 看「已交付，内容已改」
# 4) 浏览器脚本：node scripts/browser_verify_delivery_readiness.mjs
```

### 46.3 边界

- `delivered` 无真实数据（需完整审批链才产生内容一致的正式交付），只有单测；`delivered_stale` 有真实数据与浏览器证据。
- 排序是纯展示逻辑，切回默认不影响任何服务端状态；看板依旧只读。

## 47. round 24 增量：批量冻结并导出

### 47.1 变更文件

- 新增 `backend/app/services/requirement_batch_archive.py`（zip 归档 + 清单，固定时间戳）。
- 新增端点 `POST /projects/{project_id}/requirements/exports-batch`（`backend/app/api/requirements.py`）。
- `backend/app/main.py`：`expose_headers` 增 `X-Requirement-Batch-Items`/`-Snapshots-Created`/`-File-Sha256`。
- `frontend/lib/api.ts`：`DOWNLOAD_IDENTITY_HEADERS` 增同三个头（缺陷 46）。
- `frontend/app/projects/[projectId]/readiness/page.tsx`：多选 + 批量导出按钮 + 结果区。
- 新增测试：`backend/tests/test_requirement_batch_export.py`、`frontend/tests/batch-export-contract.test.mjs`。
- 新增脚本：`frontend/scripts/browser_verify_batch_export.mjs`。

### 47.2 复核步骤

1. 后端：`cd ai-platform/backend && .\.venv\Scripts\python.exe -m pytest tests/test_requirement_batch_export.py tests/test_requirement_export_unified.py -q -p no:randomly`。
2. 前端类型与契约：`tsc --noEmit -p tsconfig.json`、`node --test tests/batch-export-contract.test.mjs`。
3. 真实浏览器：先起 8011/3010，再 `node scripts/browser_verify_batch_export.mjs`，核对
   `frontend/scripts/out/browser/ui-batch-export.json` 的 `identical=true` 与 `noticeText`。
4. 解压 `batch-export-first.zip` 核对 `manifest.json` 与两份 xlsx 的 sha256。

### 47.3 边界

- 只支持 `xlsx` + `survey`；单批 ≤20 条；预检不一致时一份都不冻结。
- 若渲染器升版，重新导出会得到新字节（渲染身份含渲染器版本）。

## 48. round 25 增量：监管表覆盖度

### 48.1 变更文件

- 新增 `backend/app/services/requirement_table_coverage.py`
- 新增 `backend/tests/test_requirement_table_coverage.py`
- 修改 `backend/app/api/requirements.py`（`GET /projects/{project_id}/table-coverage`）
- 新增 `frontend/lib/table-coverage.ts`
- 修改 `frontend/app/projects/[projectId]/readiness/page.tsx`（`aria-label="监管表覆盖度"` 区块）
- 新增 `frontend/tests/table-coverage-contract.test.mjs`
- 新增 `frontend/scripts/browser_verify_table_coverage.mjs`

无数据库迁移（纯读接口）。

### 48.2 复核步骤

1. 重启后端（清 `DATABASE_URL`/`AUTH_MODE`/`TASK_QUEUE_PROVIDER`/`PYTHONPATH`，设 `STORAGE_DIR`），
   `http://127.0.0.1:8011/health/ready` 200 后：
   `GET /api/projects/9/table-coverage` 应为 `90/12/0/71/1/6`，`field_count=2422`、`mapped_field_count=1297`。
2. `frontend` 下 `node --test tests/table-coverage-contract.test.mjs` → 4 passed。
3. `node scripts/browser_verify_table_coverage.mjs` → 头条五类计数、点"缺少脚本"6 行、点"脚本未解析出写入"1 行、
   `consoleErrors: []`；截图写入 `scripts/out/browser/ui-table-coverage*.png`。
4. `python scripts/requirement_docs_check.py` → 0 问题。

### 48.3 边界

- `script_absent`（`T_5_4/T_6_16/T_6_17/T_8_10/T_8_16/T_9_5`）依赖输入目录文件是否导入，
  换项目/换资料后数字会变，不能把当前 6 当常量。
- `script_disabled` 只有 `T_3_5` 一个真实样本，且原因（整段块注释）由缺陷 28 修复后的 warning 单独给出，
  覆盖度本身不判断原因。

## 49. round 26 增量：覆盖度原因解释

### 49.1 变更文件

- 修改 `backend/app/services/requirement_table_coverage.py`（`disabled_reason`、`_version_by_code`、
  `_version_text`、`_statement_statuses`、item 增 `script_reason_kind`/`script_reason`）
- 修改 `backend/tests/test_requirement_table_coverage.py`（+3 用例）
- 修改 `frontend/lib/table-coverage.ts`（item 类型两个可选字段）
- 修改 `frontend/app/projects/[projectId]/readiness/page.tsx`（状态列下渲染原因）
- 修改 `frontend/tests/table-coverage-contract.test.mjs`（+1 断言组）
- 修改 `frontend/scripts/browser_verify_table_coverage.mjs`（抓 `reason` 字段）

无数据库迁移（只读）。

### 49.2 复核步骤

1. 重启后端后 `GET /api/projects/9/table-coverage`：带 `script_reason` 的应为 7 条，
   `T_3_5` 的 `script_reason_kind=="block_comment"`。
2. `pytest tests/test_requirement_table_coverage.py -q` → 8 passed。
3. `node --test tests/table-coverage-contract.test.mjs` → 5 passed；
   `node scripts/browser_verify_table_coverage.mjs` → `disabled.reason` 含"未闭合的块注释"。
4. `python scripts/requirement_docs_check.py` → 0 问题。

### 49.3 边界

- 原因依赖存档脚本原文（`script_file_versions.raw_content_storage_file_id`）可读；文件被清理后只会退回
  解析记录口径，不会报 500。
- `disabled_reason` 是纯函数，新增原因类别时先加单元测试再改文案。

## 50. round 26 增量：标准模板列填充率

### 50.1 变更文件

- 新增 `ai-platform/backend/app/services/template_column_coverage.py`（`COLUMN_SPECS` 七列、`_non_empty`、`_script_count`、`_business_count`、`build_template_coverage`）。
- `ai-platform/backend/app/api/requirements.py`：新增 `GET /projects/{project_id}/template-coverage`。
- 新增 `ai-platform/backend/tests/test_template_column_coverage.py`（4 用例）。
- 新增 `ai-platform/frontend/lib/template-column-coverage.ts`、`ai-platform/frontend/tests/template-column-coverage-contract.test.mjs`、`ai-platform/frontend/scripts/browser_verify_template_coverage.mjs`。
- `ai-platform/frontend/app/projects/[projectId]/readiness/page.tsx`：新增 `aria-label="标准模板列填充"` 区块。
- 证据：`frontend/scripts/out/browser/ui-template-columns.png|json`。

### 50.2 复核步骤

1. 重启后端（杀 8011 → 清 `DATABASE_URL/AUTH_MODE/TASK_QUEUE_PROVIDER/PYTHONPATH` → `STORAGE_DIR=<root>\ai-platform\backend\dev_storage_local` → 起 uvicorn），`/health/ready` 200。
2. `GET /api/projects/9/template-coverage` 应返回 2 422 字段、七列、`data_format.fill_rate == 0`。
3. 前端 `node --test tests/template-column-coverage-contract.test.mjs`；浏览器跑 `node scripts/browser_verify_template_coverage.mjs`，应四项断言全真且 `consoleErrors` 为空。

### 50.3 边界

- 夹具里造血缘必须给 `lineage_edges.script_file_version_id`（NOT NULL），可复用 `test_requirement_table_coverage._script_version`。
- 合成夹具的需求 `content_version` 为 0，`PUT /fields` 前必须先 `POST /requests/{rid}/revisions`。
- 页面区块失败只影响本区块，文案固定说明"该区块不影响上方内容"。

## 51. round 28 增量：模板列缺口清单

### 51.1 变更文件

- `ai-platform/backend/app/services/template_column_coverage.py`：新增 `TEMPLATE_COVERAGE_GAP_VERSION`、`MAX_GAP_ROWS=5000`、`COLUMN_BY_KEY`、`_business_filled_ids`、`_missing_condition`、`gaps_for_column`、`_current_value`。
- `ai-platform/backend/app/api/requirements.py`：新增 `GET /projects/{project_id}/template-coverage/gaps/{column_key}`（`limit` 1..5000）。
- `ai-platform/backend/tests/test_template_column_coverage.py`：+4 用例。
- `ai-platform/frontend/lib/template-column-coverage.ts`：新增 `TemplateGapItem/TemplateGapResponse`、`templateGapCsv`、`gapSummaryText`。
- `ai-platform/frontend/app/projects/[projectId]/readiness/page.tsx`：列名按钮 + `aria-label="模板列缺口清单"` 弹层 + CSV 下载。
- `ai-platform/frontend/tests/template-column-coverage-contract.test.mjs`：+2 用例。
- `ai-platform/frontend/scripts/browser_verify_template_gaps.mjs`：新增。
- 证据：`frontend/scripts/out/browser/ui-template-gaps.png|json`、`template-gaps-data_format.csv`。

### 51.2 复核步骤

1. 重启后端（杀 8011 → 清 `DATABASE_URL/AUTH_MODE/TASK_QUEUE_PROVIDER/PYTHONPATH` → `STORAGE_DIR=<root>\ai-platform\backend\dev_storage_local`）。**新接口必须重启才生效**。
2. `GET /api/projects/9/template-coverage/gaps/data_format?limit=3` 应返回 `total=2422`、`truncated=true`。
3. 前端 `node --test tests/template-column-coverage-contract.test.mjs`；浏览器 `node scripts/browser_verify_template_gaps.mjs`，CSV 行数应等于 `total`。

### 51.3 边界

- 缺口清单与填充率共用同一 `_non_empty` / 映射 / 血缘条件，改一处必须同步另一处。
- 夹具里 `snapshot_api` 的字段自带一条集市映射：测"映射缺口"要另建字段，不能拿夹具字段当空。
- 浏览器脚本先点「下载全部」再下载，否则只能拿到 500 行（`limit` 默认 500）。

## 52. 表级口径（round 29）

### 52.1 变更文件

- 新增 `backend/alembic/versions/202611010009_target_table_meta.py`（`down_revision="202611010008"`）。
- 修改 `backend/app/models/entities.py`（`TargetTable` 4 列、`TemplateVersion.table_meta_json`）、
  `backend/app/services/template_parser/survey_excel_parser.py`（`_parse_table_level`）、
  `backend/app/services/template_service.py`（写入/Apply 只补空值）、
  `backend/app/services/requirement_scope.py`（`_with_table_meta`）、
  `backend/app/services/requirement_survey_export.py`（`_TABLE_HEADERS` 主备路径）、
  `backend/scripts/reparse_template_version.py`（重算时写 `table_meta_json`）、
  三个测试文件、新增 `frontend/scripts/browser_verify_table_meta_export.mjs`。

### 52.2 复核步骤

1. `alembic upgrade head`（真实 PG 到 `202611010009`）。
2. `python scripts/reparse_template_version.py --template-version-id 2 --commit` → 表级口径 90 张表。
3. 重启 uvicorn（清 `DATABASE_URL/AUTH_MODE/TASK_QUEUE_PROVIDER/PYTHONPATH`、设 `STORAGE_DIR=backend/dev_storage_local`）→ `POST /api/templates/2/apply`。
4. 冻结需求（`POST /api/projects/9/requirements/25/snapshots`）→ `POST …/exports`（`layout=survey`）→ 第 4 行应为 `状态类数据`。
5. `node scripts/browser_verify_table_meta_export.mjs`（前端 3010 + 后端 8011 都要在）。

### 52.3 边界

- `数据分类` 无模板来源，仍写“待业务补充”。
- 历史快照不会追溯补表级口径；要看新值必须重新冻结。

## 53. 看板下载最近导出产物（round 30）

### 53.1 变更文件

- 改：`frontend/app/projects/[projectId]/readiness/page.tsx`（`apiDownload` 导入、`downloadingId/artifactNotice/artifactError`
  状态、`downloadArtifact(item)`、行内「下载产物 #N」按钮、`aria-label="产物下载结果"` 提示、失败文案）。
- 新增：`frontend/tests/delivery-artifact-download-contract.test.mjs`、
  `frontend/scripts/browser_verify_delivery_download.mjs`。
- 后端无改动（复用 `GET …/render-artifacts/{artifact_id}/download`）。

### 53.2 复核步骤

1. 起后端（`/health/ready` 200）与前端（`/login` 200）。
2. `node scripts/browser_verify_delivery_download.mjs` → 两个项目各下载一次，退出码 0。
3. `node --test tests/delivery-artifact-download-contract.test.mjs tests/delivery-status-contract.test.mjs tests/delivery-readiness-contract.test.mjs` → 15 passed。

### 53.3 边界

- 只覆盖"最近一次产物"；历史产物走工作台产物列表。
- 表级口径并入内容后，看板会显示"有未冻结改动"（hash 含引用元数据），需要按 §33 的边界理解。

## 54. 口径身份（round 31）

### 54.1 变更文件

- 改：`backend/app/services/requirement_scope.py`（新增 `caliber_digest`，顶部 `import copy`）、
  `backend/app/services/requirement_delivery_status.py`（`STATUS_VERSION` → v2，新增三个 item 字段、
  `latest_snapshot.caliber_hash`、两个 summary 计数）、
  `frontend/lib/delivery-status.ts`（类型 + `deliveryDetail` 三态文案 + `readinessHeadline` 追加说明）。
- 新增/改测试：`backend/tests/test_requirement_delivery_status.py`（新增 1 个用例，共 8 passed）、
  `frontend/tests/delivery-status-contract.test.mjs`（新增 1 组断言）。
- 新增脚本：`frontend/scripts/browser_verify_meta_change.mjs`。

### 54.2 复核步骤

1. 重启 uvicorn（清 `DATABASE_URL/AUTH_MODE/TASK_QUEUE_PROVIDER/PYTHONPATH`、`STORAGE_DIR=backend/dev_storage_local`），`/health/ready` 200。
2. `GET /api/projects/9/requirements-status` → `summary.reference_meta_only == 12`、`caliber_changed == 0`。
3. `node scripts/browser_verify_meta_change.mjs` → 退出码 0，头条含“仅引用元数据变化”。
4. `pytest tests/test_requirement_delivery_status.py -q`（`AUTH_MODE=optional`）→ 8 passed。

### 54.3 边界

- `caliber_hash` 只在聚合里重算，不落库，不参与冻结判定。
- 若后续要让“引用元数据变化”成为独立看板状态，需要把它从 stale 里拆出去并同步 `_readiness` 的排序语义。


## 55. 就绪状态 `metadata_stale`（round 32）

### 55.1 变更文件

- `backend/app/services/requirement_delivery_status.py`（`STATUS_VERSION` v3、`_readiness(..., meta_only)`、summary 互斥计数）
- `frontend/lib/delivery-status.ts`（七态、rank、头条五段）
- `backend/tests/test_requirement_delivery_status.py`、`frontend/tests/delivery-readiness-contract.test.mjs`
- `frontend/scripts/browser_verify_meta_change.mjs`（增加就绪列断言与列序注释）

### 55.2 复核步骤

1. 重启后端（杀 8011 → 清 `DATABASE_URL/AUTH_MODE/TASK_QUEUE_PROVIDER/PYTHONPATH` → `STORAGE_DIR=<root>\ai-platform\backend\dev_storage_local`），等 `/health/ready` 200。
2. `GET /api/projects/9/requirements-status` 应为 `status_version=requirement-delivery-status-v3`、`metadata_stale=12`、`stale=0`。
3. `cd frontend; node scripts\browser_verify_meta_change.mjs` 退出码应为 0，`readinessMetaOnly=12`。
4. 若 `readinessMetaOnly=0`，先核对表格列序（第 24 轮起 `0=选 1=监管表 2=需求 3=字段 4=冻结状态 5=交付就绪`）。

### 55.3 边界

- 没有真实“表级口径更新 + 已冻结需求”组合时，看板不会出现 `metadata_stale`；不要用改 `snapshot_count` 之类手段造态。
- 历史快照不追溯：`metadata_stale` 行重新冻结后才变成 `exportable`。


## 56. round 33：交付状态按就绪状态筛选（筛选条 + 勾选当前筛选）

### 56.1 变更文件

| 文件 | 变更 |
| --- | --- |
| `frontend/lib/delivery-status.ts` | 新增 `DeliveryStatusFilter`、`DELIVERY_STATUS_FILTERS`、`deliveryFilterCount`、`filterDeliveryItems`、`deliveryFilterHint` |
| `frontend/app/projects/[projectId]/readiness/page.tsx` | 新增 `aria-label="交付状态筛选"` 按钮组、`当前显示 X / Y 条`、按档位提示、`勾选这 N 条`；表体改渲染 `visibleDeliveryItems`；筛空说明 |
| `frontend/tests/delivery-filter-contract.test.mjs` | 新增（5 用例） |
| `frontend/tests/delivery-status-contract.test.mjs`、`frontend/tests/delivery-readiness-contract.test.mjs` | 表体断言从 `delivery.items` 改为 `visibleDeliveryItems` |
| `frontend/scripts/browser_verify_delivery_filter.mjs` | 新增（真实浏览器取证，不触发导出） |

无后端改动、无迁移。

### 56.2 复核步骤

1. 后端 `/health/ready` 200、前端 `/login` 200。
2. `cd ai-platform/frontend && node --test tests/delivery-filter-contract.test.mjs`（5 passed）。
3. `node scripts/browser_verify_delivery_filter.mjs`，退出码 0，检查 `ui-delivery-filter.json` 里 `rowCountAfterFilter === summary.metadata_stale`、`counter == "当前显示 12 / 17 条"`、`batchButton` 含 `（12）`、`consoleErrors` 为空。
4. 若 `rowCountAfterFilter` 为 0：先确认后端仍在 `requirement-delivery-status-v3`（`summary.metadata_stale` 是否存在），再看页面是否渲染了旧 bundle（删 `frontend/.next` 重启 `next dev`）。

### 56.3 边界

- 筛选与勾选纯前端，不写库；`批量冻结并导出` 仍是人工动作。
- 项目 9 当前 12 条 `metadata_stale` 是第 29 轮表级口径接入后的真实状态，不是造出来的。


## 57. round 34：只对齐快照（批量重新冻结）

### 57.1 变更文件

| 文件 | 变更 |
| --- | --- |
| `backend/app/api/requirements.py` | 新增 `POST /projects/{project_id}/requirements/refreeze-batch`（只冻结、不渲染）；`Body` 加入 fastapi 导入 |
| `backend/tests/test_requirement_refreeze_batch.py` | 新增（4 用例） |
| `frontend/app/projects/[projectId]/readiness/page.tsx` | 新增"只对齐快照"按钮与结果提示；交付状态改为独立 `useEffect`（`deliveryReload` 就地刷新）；`apiPost` 导入 |
| `frontend/tests/refreeze-batch-contract.test.mjs` | 新增（3 用例） |
| `frontend/scripts/browser_verify_refreeze_batch.mjs` | 新增（幂等段 + 界面演示段） |

无迁移、无模型改动。

### 57.2 复核步骤

1. 后端 `/health/ready` 200（改后端代码后必须重启 uvicorn）。
2. `pytest tests/test_requirement_refreeze_batch.py -q` → 4 passed。
3. `node --test tests/refreeze-batch-contract.test.mjs` → 3 passed。
4. `node scripts/browser_verify_refreeze_batch.mjs`：有 `metadata_stale` 时跑界面段（数行数、按钮文案、提示、归零、产物数不变）；没有时只跑幂等段（`snapshots_created=0`），退出码 0。
5. 若按钮点了没提示：先确认 `POST …/refreeze-batch` 返回 200（401 多半是脚本把登录响应整个当 token 用了）。

### 57.3 边界

- 这是单向动作：跑过之后 `metadata_stale` 归零，界面演示无法重复；要重复需重新制造模板表级口径变化。
- 不产生产物、不推进审批；20 条上限；并发未测。


## 58. round 35：看板「最近动作」（操作人 + 时间）

### 58.1 变更文件

| 文件 | 变更 |
| --- | --- |
| `backend/app/services/requirement_delivery_status.py` | `STATUS_VERSION` → v4；`latest_snapshot.actor` / `last_artifact.actor`；批量查 `User`（非 N+1） |
| `backend/tests/test_requirement_delivery_status.py` | 新增 `test_delivery_status_names_who_froze_and_exported` |
| `frontend/lib/delivery-status.ts` | 新增 `DeliveryActor`、`formatActionTime`、`deliveryActionText` |
| `frontend/app/projects/[projectId]/readiness/page.tsx` | 新增「最近动作」列；空表 `colSpan` 10 → 11 |
| `frontend/tests/delivery-action-contract.test.mjs` | 新增（6 用例） |
| `frontend/scripts/browser_verify_delivery_action.mjs` | 新增（项目 9 / 项目 7 两项目取证） |

无迁移、无模型改动。

### 58.2 复核步骤

1. 改后端后重启 uvicorn（`/health/ready` 200）。
2. `GET /api/projects/9/requirements-status` 应有 `status_version=requirement-delivery-status-v4`，条目里 `latest_snapshot.actor.name` 有值。
3. 前端 `tsc --noEmit` → 0；`node --test tests/delivery-action-contract.test.mjs` → 6 passed。
4. `node scripts/browser_verify_delivery_action.mjs` → 退出码 0，输出 actionCount/noActionCount 与接口一致。
5. 若脚本报"看板没有最近动作列"：先确认表头已渲染（section 在数据回来之前就存在），并检查 frontend dev server 是否需要清 `.next`。

### 58.3 边界

- 只显示最近一次动作；操作人取自 `created_by` 对用户表的当前显示名。
- 并发与多人交替未做真实浏览器样本。

## 59. 缺口清单按监管表筛选（round 36）

### 59.1 变更文件

| 文件 | 变更 |
| --- | --- |
| `backend/app/services/template_column_coverage.py` | `_escape_like`、`_table_condition`（默认完全匹配、`*` 结尾才前缀）、`gaps_for_column(..., table_code=None)`、`filtered_total`/`table_filter` |
| `backend/app/api/requirements.py` | 缺口清单端点新增 `table_code` Query 参数 |
| `frontend/lib/template-column-coverage.ts` | 类型补 `filtered_total`/`table_filter`；`gapSummaryText` 分筛选/未筛选两种口径 |
| `frontend/app/projects/[projectId]/readiness/page.tsx` | `gapFilter` 状态、筛选/清除按钮、`openGapPanel(columnKey, limit, tableCode)`、关闭时重置筛选 |
| `backend/tests/test_template_column_coverage.py` | 新增 2 条用例（整列口径、通配符转义） |
| `frontend/tests/template-column-coverage-contract.test.mjs` | 新增 1 条契约 |
| `frontend/scripts/browser_verify_gap_filter.mjs` | 新增真实浏览器取证脚本 |

### 59.2 复核步骤

1. 重启后端（清 `DATABASE_URL/AUTH_MODE/TASK_QUEUE_PROVIDER/PYTHONPATH`，设 `STORAGE_DIR=<root>\ai-platform\backend\dev_storage_local`），`/api/health/ready` 200；
2. 看板 → 「标准模板列填充」→ 点「数据格式」列名 → 输入 `T_8_1` → 筛选；
3. 断言摘要含「筛选「T_8_1」：9 个字段（该列共 2436 个）」，表格 9 行且首列**完全等于** `T_8_1`（用 `T_8*` 才做前缀匹配）；
4. 点「清除筛选」应回到「共 2436 个字段…」。

### 59.3 边界

- 只做单表/前缀过滤；不支持多表与数据域维度；
- 筛选不影响看板列统计；
- 2 436 / 164 是 2026-10-25 实测值。
## 60. 缺口摘要（round 37）

### 60.1 变更文件

| 类型 | 文件 |
| --- | --- |
| 新增 | `frontend/lib/gap-breakdown.ts`、`frontend/tests/gap-breakdown-contract.test.mjs`、`frontend/scripts/browser_verify_gap_breakdown.mjs` |
| 修改 | `backend/app/services/requirement_delivery_status.py`（`gap_breakdown` + 类别折叠）、`backend/app/api/requirements.py`（`GET …/gap-breakdown`）、`frontend/app/projects/[projectId]/readiness/page.tsx`（缺口数字变按钮 + 弹层）、`backend/tests/test_requirement_delivery_status.py` |

### 60.2 复核步骤

1. 后端 `pytest tests/test_requirement_delivery_status.py -q` 应 11 passed。
2. 重启 uvicorn（清 `DATABASE_URL/AUTH_MODE/TASK_QUEUE_PROVIDER/PYTHONPATH`，`STORAGE_DIR=<root>\ai-platform\backend\dev_storage_local`），`/api/health/ready` 200。
3. `GET /api/projects/9/requirements/10/gap-breakdown` 应返回 `open_gap_count=406`、`field_count=8`、`category_count=219`、`categories` 长度 9（含 `aggregated=true` 的"其他"）。
4. `node scripts/browser_verify_gap_breakdown.mjs folded` 退出码 0，截图里能看到字段表与「其他 211 类」行。

### 60.3 边界

- `category_limit` 默认 8，可通过参数调整；折叠行的文案是 `其他 N 类（见工作台明细）`，条数为剩余类别之和。
- `gap_breakdown` 不写库，`open_gap_count` 与 `/requirements-status` 共用同一套 `_open_gaps` 口径（有用例固定这一点）。
## 61. 产物结构自检（round 38）

### 61.1 变更文件

| 类型 | 文件 |
| --- | --- |
| 新增 | `backend/app/services/requirement_survey_structure_check.py`、`backend/tests/test_requirement_survey_structure_check.py`、`frontend/tests/structure-check-contract.test.mjs`、`frontend/scripts/browser_verify_structure_check.mjs` |
| 修改 | `backend/app/api/requirements.py`（structure-check 端点 + 导入）、`backend/tests/test_requirement_export_unified.py`（xlsx pass / docx 422 用例）、`frontend/components/requirement-workspace/RequirementTemplateExportPanel.tsx`（入口 + 弹层） |

### 61.2 复核步骤

1. `pytest tests/test_requirement_survey_structure_check.py -q` → 6 passed；`pytest tests/test_requirement_export_unified.py -q` → 14 passed。
2. 重启 uvicorn 后 `GET /api/projects/9/requirements/10/render-artifacts/59/structure-check` → `verdict=pass`；对 Word 产物 → 422。
3. `node scripts/browser_verify_structure_check.mjs` 退出码 0，截图里有 8 行检查项与只读说明。

### 61.3 边界

- `_FOOTER_MARKS` 与 `_TABLE_HEADERS` 都是导出器结构的一部分；导出器改结构时自检会 fail，这是预期（自检就是用来兜住这类改动的）。
- 端点只读，不写库、不改产物；不触发重新渲染（文件被替换时仍走完整性校验）。
## 62. 结构契约按渲染时代次（round 39）

### 62.1 变更文件

| 类型 | 文件 |
| --- | --- |
| 修改 | `backend/app/services/requirement_survey_structure_check.py`（`contract_for_renderer` / `skipped_keys` / `upgrade_hint`）、`backend/app/api/requirements.py`（透传 `renderer_version`、统一 422）、`backend/tests/test_requirement_survey_structure_check.py`（+5 用例）、`frontend/components/requirement-workspace/RequirementTemplateExportPanel.tsx`（契约与提示两行）、`frontend/tests/structure-check-contract.test.mjs`（+1 组断言） |
| 新增 | `frontend/scripts/browser_verify_structure_contract.mjs` |

### 62.2 复核步骤

1. `pytest tests/test_requirement_survey_structure_check.py -q` → 11 passed。
2. 重启 uvicorn 后：`GET …/render-artifacts/59/structure-check` → v9+ 契约、无提示；`GET …/render-artifacts/30/structure-check` → v7 及更早契约、`skipped_keys=['completeness','source_notes']`、有 `upgrade_hint`。
3. `node scripts/browser_verify_structure_contract.mjs` 退出码 0，两张截图分别显示两代契约。

### 62.3 边界

- 改后端后必须重启 uvicorn，否则界面拿不到 `upgrade_hint`（本轮就踩了一次：先改代码后没重启，浏览器里提示为空）。
- 工作台下拉顺序固定为 0=项目、1=需求、2=目标表、3=场景；脚本按索引取值，页面结构变化需同步。

## 63. round 40 变更：Word 结构自检

### 63.1 变更文件

| 文件 | 变更 |
| --- | --- |
| `backend/app/services/requirement_docx_structure_check.py` | 新增：内置版式 Word 结构契约（5 阻断 + 1 信息项），客户模板/非 docx 拒绝打分 |
| `backend/app/api/requirements.py` | `structure-check` 端点按 `record.format` 分派（xlsx/docx），统一 422 文案映射 |
| `frontend/components/requirement-workspace/RequirementTemplateExportPanel.tsx` | 入口放开到 docx；弹层按格式切换统计；失败提示优先 `ApiError.detail` |
| `backend/tests/test_requirement_docx_structure_check.py` | 新增 6 用例（用 `snapshot_api` + 真实导出取内置版式字节，避免另造内容夹具漂移） |
| `backend/tests/test_requirement_export_unified.py` | docx 用例由"422 拒绝"改为"内置版式 200 pass + 契约名断言" |
| `frontend/tests/structure-check-contract.test.mjs` | 入口按 xlsx/docx 收窄；补 docx 契约与拒绝断言 |
| `frontend/scripts/browser_verify_structure_docx.mjs` | 新增：项目 7 内置版式 Word + 项目 9 客户模板 Word 两段取证 |

### 63.2 复核步骤

1. 重启后端（`/health/ready` 200）——**改后端代码必须重启，否则界面拿到的是旧响应**。
2. `GET /api/projects/7/requirements/5/render-artifacts/42/structure-check` 应 200 且 `check_version="docx-structure-check-v1"`、`verdict="pass"`。
3. `GET …/artifacts/43/structure-check`（同上项目 9 需求 18）应 422 且 detail 含「不是平台内置版式」。
4. `cd frontend && node scripts/browser_verify_structure_docx.mjs` 退出码 0。

### 63.3 边界

- 仅内置版式 Word；客户模板 Word 不打分。
- 浏览器日志里的预期 404/422 记成 `resourceErrors`，不计入 `consoleErrors`。

## 64. Word 产物页面预览（round 41）

### 64.1 变更文件

| 文件 | 说明 |
| --- | --- |
| `backend/app/services/requirement_artifact_preview.py` | 新增 `DOCX_PREVIEW_VERSION="artifact-docx-preview-v1"`、`MAX_DOCX_BLOCKS=600`/`MAX_DOCX_CHARS=1200`/`MAX_DOCX_TABLE_ROWS=40`、`preview_docx`/`_docx_paragraph`/`_docx_table`/`preview_xlsx_document`；`SUPPORTED_FORMATS=("xlsx","docx")` |
| `backend/tests/test_requirement_artifact_preview.py` | docx 用例替代原"docx 必须 422"用例；新增 API 200 用例 `test_preview_endpoint_serves_docx_sections` |
| `frontend/components/requirement-workspace/RequirementTemplateExportPanel.tsx` | 预览入口放开到 docx；弹层按 `preview.format` 分章节视图/网格视图 |
| `frontend/tests/artifact-preview-contract.test.mjs` | 新增 docx 章节视图断言与"预览不得回落到渲染器"断言 |
| `frontend/scripts/browser_verify_docx_preview.mjs` | 真实浏览器两场景（项目 7 docx / 项目 9 xlsx） |

### 64.2 复核步骤

1. 重启后端（改代码必须重启）：杀 8011 监听进程 → 清 `DATABASE_URL/AUTH_MODE/TASK_QUEUE_PROVIDER/PYTHONPATH` → `$env:STORAGE_DIR="<root>\ai-platform\backend\dev_storage_local"` → `Start-Process .\.venv\Scripts\python.exe -ArgumentList "-m","uvicorn","app.main:app","--host","127.0.0.1","--port","8011"`；等 `/api/health/ready` 200。
2. 前端若 CSS 404（`/_next/static/css/app/workspace/page.css`）→ 杀 next 进程、删 `frontend/.next`、`Start-Process cmd.exe "/c npx next dev -p 3010 > _next.out.log 2>&1"`，`/login` 200 后再验。
3. `cd frontend && node scripts/browser_verify_docx_preview.mjs`（期望退出码 0、`sectionCount>=5`、`notFound=[]`）。

### 64.3 边界

- 内置版式 Word 的字段是"每字段小标题 + 段落"，预览里 `tables=0` 属正常；不要把它当成"表格丢了"。
- 预览不判业务语义，也不替代 Word/PDF 里的版式验收。

## 65. 看板缺口 → 工作台字段深链（round 42）

### 65.1 变更文件

| 文件 | 说明 |
| --- | --- |
| `backend/app/services/requirement_delivery_status.py` | `gap_breakdown()` 增 `target_table_id`/`target_table_code`/`scenario_id` |
| `backend/tests/test_requirement_delivery_status.py` | 增断言：三个 id 与 `/document` 一致 |
| `frontend/app/projects/[projectId]/readiness/page.tsx` | 缺口摘要字段表加「处理」列 + `/workspace?...` 深链 |
| `frontend/components/requirement-workspace/RequirementWorkspace.tsx` | URL `fieldId` → `initialFocusFieldId` |
| `frontend/components/requirement-workspace/DocumentPreview.tsx` | `initialFocusFieldId` 一次性应用（切页签 + 高亮 + 滚动） |
| `frontend/tests/gap-deeplink-contract.test.mjs` | 契约测试（3 条） |
| `frontend/scripts/browser_verify_gap_deeplink.mjs` | 真实浏览器端到端 |

### 65.2 复核步骤

1. 改后端后重启 uvicorn（杀 8011 → 清 `DATABASE_URL/AUTH_MODE/TASK_QUEUE_PROVIDER/PYTHONPATH` → 设 `STORAGE_DIR` → 启动，`/api/health/ready` 200）。
2. `cd frontend && node scripts/browser_verify_gap_deeplink.mjs`（期望退出码 0、`landedUrl` 含五个参数、`focusedText` 以字段编码开头、`documentTabActive=true`）。

### 65.3 边界

- 深链不强制选中不相干的需求；表/场景/需求/字段任一不匹配即退回原逻辑。
- 「无法定位」只在后端没返回 table/scenario id 时出现（老缺口摘要响应）。

## 66. 产物预览按字段定位（round 43）

### 66.1 变更文件

| 文件 | 说明 |
| --- | --- |
| `frontend/components/requirement-workspace/RequirementTemplateExportPanel.tsx` | 预览弹层加查找输入、命中高亮与滚动、多工作表全表搜索 + 自动切 sheet |
| `frontend/tests/preview-search-contract.test.mjs` | 契约 4 条（入口/命中/无命中解释/多 sheet） |
| `frontend/scripts/browser_verify_preview_search.mjs` | 真实浏览器两场景（Word 命中与未命中、xlsx 跨 sheet 命中） |

### 66.2 复核步骤

1. `cd frontend && node scripts/browser_verify_preview_search.mjs`（期望退出码 0；docx `命中 2 个章节`；xlsx `命中 1 行（工作表「字段口径」）`）。
2. 若页面没出现查找框：先确认 dev server 已重启（改 TSX 后 `.next` 偶发缓存坏 → 删 `.next` 重启）。

### 66.3 边界

- 纯前端过滤，不发额外请求；不重渲染、不改产物。
- 被 `MAX_ROWS=300` / `MAX_DOCX_CHARS=1200` 截断的内容查不到，属预期。

## 67. 交付前检查单（round 44）

### 67.1 变更文件

- 新增 `backend/app/services/requirement_delivery_checklist.py`
- 修改 `backend/app/api/requirements.py`（新增 `GET …/render-artifacts/{artifact_id}/delivery-checklist`）
- 修改 `frontend/components/requirement-workspace/RequirementTemplateExportPanel.tsx`（交付检查单入口与弹层）
- 新增 `backend/tests/test_requirement_delivery_checklist.py`、`frontend/tests/delivery-checklist-contract.test.mjs`、`frontend/scripts/browser_verify_delivery_checklist.mjs`

### 67.2 复核步骤

1. 重启真实后端：杀 8011 监听进程 → 清 `DATABASE_URL/AUTH_MODE/TASK_QUEUE_PROVIDER/PYTHONPATH` → `STORAGE_DIR=<root>\ai-platform\backend\dev_storage_local` 启动，等 `/health/ready` 200。
2. `GET /api/projects/7/requirements/5/render-artifacts/42/delivery-checklist` 应 `verdict=="pass"`；`…/9/requirements/10/render-artifacts/20/…` 在传 `renderer_version` 后也应 pass。
3. 若前端出现 `/_next/static/css/app/workspace/page.css` 404，杀 next、删 `frontend/.next` 重启 `npx next dev -p 3010`。
4. `node frontend/scripts/browser_verify_delivery_checklist.mjs` 退出码 0，两份 json 里 `consoleErrors`/`resourceErrors`/`realFailed` 为空。

### 67.3 边界

identity 为"可回查"口径；fields 在正式交付上为信息项；结构与预览截断的判定沿用 round 38/39 的契约与截断规则。


## 68. 从跑批脚本一键建需（round 45）

### 68.1 变更文件

- 新增 `backend/app/services/requirement_script_authoring.py`（`AUTHORING_VERSION`、`MAX_TABLES = 10`、`author_candidates`、`author_requirements`）。
- 修改 `backend/app/api/requirements.py`：`POST /requirements/author-preview`、`POST /requirements/author-from-scripts`、`_authoring_codes`。
- 新增 `backend/tests/test_requirement_script_authoring.py`（3 passed）。
- 修改 `frontend/app/projects/[projectId]/readiness/page.tsx`：覆盖度表「操作」列、`authorFromScript`、`coverageReload`、两个提示块。
- 新增 `frontend/tests/script-authoring-contract.test.mjs`（4 passed）与 `frontend/scripts/browser_verify_script_authoring.mjs`。

### 68.2 复核步骤

1. 后端：`pytest tests/test_requirement_script_authoring.py -q`。
2. `tsc --noEmit -p tsconfig.json`。
3. 起后端（清 `DATABASE_URL`/`AUTH_MODE`/`TASK_QUEUE_PROVIDER`/`PYTHONPATH`，设 `STORAGE_DIR=<root>\ai-platform\backend\dev_storage_local`），确认 `/api/health/ready` 200。
4. 起前端后用 `AUTHOR_TABLE=T_1_1 node scripts/browser_verify_script_authoring.mjs`（会真的建一条需求，属预期副作用）。
5. 覆盖度表默认只显示 15 张，目标表靠后时脚本需先点「再显示 30 张」。

### 68.3 边界

- 只产出草稿；正文、候选、冻结、导出仍需在工作台完成。
- 未绑字段保留为缺口，不静默丢弃。
- 一次 ≤ 10 张表，同表已有需求即拒绝。


## 69. 批量一键建需（round 46）

### 69.1 变更文件

- 修改 `frontend/app/projects/[projectId]/readiness/page.tsx`：覆盖度勾选列、`authorSelected`/`authorBatchBusy`/`authorResults`、`authorBatch()`、批量条与逐表结果列表。
- 修改 `frontend/tests/script-authoring-contract.test.mjs`（4 → 6 passed）。
- 新增 `frontend/scripts/browser_verify_batch_authoring.mjs`。
- 后端无改动（沿用 round 45 的 `author-preview` / `author-from-scripts`，`MAX_TABLES = 10`）。

### 69.2 复核步骤

1. `tsc --noEmit -p tsconfig.json`。
2. `node --test tests/script-authoring-contract.test.mjs`。
3. 起后端（清 `DATABASE_URL`/`AUTH_MODE`/`TASK_QUEUE_PROVIDER`/`PYTHONPATH`，设 `STORAGE_DIR=<root>\ai-platform\backend\dev_storage_local`）+ 前端。
4. `AUTHOR_TABLES="T_1_3,T_1_5" node scripts/browser_verify_batch_authoring.mjs`（会建两条真实需求）。
5. 覆盖度表首次只显示 15 张，脚本会先点「脚本可建需」筛选再「再显示 30 张」。

### 69.3 边界

- 一次 ≤ 10 张；超出需分批，界面不排队。
- 只建草稿，不触发正文生成。

## 70. 脚本覆盖列与假字段清理（round 47）

### 70.1 变更文件

| 文件 | 变更 |
| --- | --- |
| `backend/app/services/requirement_delivery_status.py` | 新增 `_script_binding(...)`；`build_delivery_status` 批量取 `fields_by_table` 并给每条需求附 `script_binding`（无绑定为 `None`） |
| `backend/app/services/template_service.py` | 新增 `_FIELD_CODE_PATTERN`；`apply_template` 跳过非标识符字段代码并计入 `skipped_rows` |
| `backend/tests/test_template_apply.py` | 新增 `test_apply_template_skips_section_marker_rows_with_chinese_codes` |
| `frontend/lib/delivery-status.ts` | `scriptBindingText` / `scriptBindingUnboundLabel` / `DeliveryScriptBinding` 类型 |
| `frontend/app/projects/[projectId]/readiness/page.tsx` | 「脚本覆盖」列 + `role="dialog" aria-label="脚本未覆盖字段"` 弹层 |
| `frontend/tests/script-binding-contract.test.mjs` | 3 条契约（不适用语义、弹层与"未覆盖不是不需要"、服务端无绑定返回 None） |
| `frontend/scripts/browser_verify_script_binding.mjs` | 真实浏览器取证脚本 |

无迁移。

### 70.2 复核步骤

1. 重启后端（清 `DATABASE_URL/AUTH_MODE/TASK_QUEUE_PROVIDER/PYTHONPATH`，`STORAGE_DIR=<root>\backend\dev_storage_local`），`/api/health/ready` 200。
2. `GET /api/projects/9/requirements-status` 检查 `script_binding` 字段。
3. 前端 `node scripts/browser_verify_script_binding.mjs`，断言 `T_8_1 → 8/8（全覆盖）`、`T_1_2 → 4/5（脚本未产出 1）`。

### 70.3 边界

- 项目 9 做过一次性数据清理（删 20 条假字段 + 24 条映射），不是迁移的一部分；换环境需重跑同样的清理。
- 「脚本覆盖」是只读展示，不触发重新绑定。


## 71. 脚本依据新鲜度（round 48）

### 71.1 变更文件

| 文件 | 说明 |
| --- | --- |
| `backend/app/services/requirement_delivery_status.py` | 新增 `build_script_basis_freshness`、`FRESHNESS_VERSION`、四态与优先级 |
| `backend/app/api/requirements.py` | 新增 `GET /projects/{project_id}/script-basis-freshness` |
| `frontend/lib/script-basis-freshness.ts` | 类型、标签、版本明细文案、固定说明 |
| `frontend/app/projects/[projectId]/readiness/page.tsx` | 「脚本依据」列 + 明细弹层 + 独立加载失败提示 |
| `backend/tests/test_requirement_delivery_status.py` | 新增脚本更新用例（14 passed） |
| `frontend/tests/script-freshness-contract.test.mjs` | 4 条契约断言 |
| `frontend/scripts/browser_verify_script_freshness.mjs` | 真实浏览器取证脚本 |

### 71.2 复核步骤

1. 后端重启（清 `DATABASE_URL/AUTH_MODE/TASK_QUEUE_PROVIDER/PYTHONPATH`，设 `STORAGE_DIR`，`/health/ready` 200）；
2. `GET /api/projects/9/script-basis-freshness` 应看到需求 #29 `script_updated`、`YBT_T_1_5.sql` v1 → v2；
3. `node scripts/browser_verify_script_freshness.mjs`（前端 3010 + 后端 8011）应退出码 0。

### 71.3 边界

看板只提示差异；重新冻结或重建需求才能跟随新脚本。版本推进与语义等价是两件事。

## 72. 脚本版本字段级差异（round 49）

### 72.1 变更文件

- 新增 `backend/app/services/requirement_script_basis_diff.py`、`backend/tests/test_requirement_script_basis_diff.py`、`frontend/lib/script-basis-diff.ts`、`frontend/tests/script-basis-diff-contract.test.mjs`、`frontend/scripts/browser_verify_script_basis_diff.mjs`。
- 修改 `backend/app/api/requirements.py`（新增 `GET …/script-basis-diff`）、`frontend/app/projects/[projectId]/readiness/page.tsx`（弹层内差异区块）。

### 72.2 复核步骤

1. `curl -s -H "Authorization: Bearer <token>" http://127.0.0.1:8011/api/projects/9/requirements/29/script-basis-diff`
2. `cd ai-platform/frontend && node scripts/browser_verify_script_basis_diff.mjs`（期望退出码 0，摘要含 `最新版本共 24 个目标字段`）
3. `cd ai-platform/backend && .venv\Scripts\python.exe -m pytest tests/test_requirement_script_basis_diff.py -q`

### 72.3 边界

差异只比较血缘签名、只比同一脚本文件、只做提示；不自动改写已冻结依据。

## 73. 依据变更的处置建议（round 50）

### 73.1 变更文件

- 修改 `backend/app/services/requirement_script_basis_diff.py`（新增 `impact` 判定与 `bound_field_codes`）、`backend/app/api/requirements.py`（传 `bound_codes`）、`backend/tests/test_requirement_script_basis_diff.py`（3 个新用例 + 端点断言 `impact`）。
- 修改 `frontend/lib/script-basis-diff.ts`（`ScriptBasisImpact`/`IMPACT_BADGE`/`impactText`/`affectedFieldTexts`）、`frontend/app/projects/[projectId]/readiness/page.tsx`（弹层内处置建议区块）、`frontend/tests/script-basis-diff-contract.test.mjs`（+1 组断言）、`frontend/scripts/browser_verify_script_basis_diff.mjs`（+3 个断言）。

### 73.2 复核步骤

1. `pytest tests/test_requirement_script_basis_diff.py -q` → 6 passed
2. `GET /api/projects/9/requirements/29/script-basis-diff` → `impact.recommendation == "review_and_rebase"`、`bound_field_count == 13`
3. `cd ai-platform/frontend && node scripts/browser_verify_script_basis_diff.mjs` → 退出码 0

### 73.3 边界

`regenerate` 只是"必须重新生成"，不等于自动改正文；`review_and_rebase` 不允许跳过复核直接冻结。

## 74. 脚本依据滞后的复核决定（round 51）

### 74.1 变更文件

- 新增 `backend/app/models/script_basis_decision.py`、`backend/alembic/versions/202611010010_script_basis_decisions.py`、`backend/app/services/requirement_script_basis_decision.py`、`backend/tests/test_requirement_script_basis_decision.py`、`frontend/tests/script-basis-decision-contract.test.mjs`、`frontend/scripts/browser_verify_script_basis_decision.mjs`。
- 修改 `backend/app/models/__init__.py`、`backend/app/services/requirement_delivery_status.py`（新鲜度附 `decision`/`fully_decided`/`decided_requirements`）、`backend/app/api/requirements.py`（新端点 + `Project` 导入）、`frontend/lib/script-basis-freshness.ts`（决定类型与文案）、`frontend/app/projects/[projectId]/readiness/page.tsx`（弹层登记区）。

### 74.2 迁移与坑

- 迁移 `202611010010` 建表；**`created_at`/`updated_at` 必须带 `server_default=sa.func.now()`**——漏了这一轮真实插入直接 500 `NotNullViolation`（表是新的，已 `downgrade 202611010009` 再 `upgrade head` 修好）。
- 审计里的 `institution_id` 取自 `db.get(Project, project_id)`：`Principal` 没有 `institution_id`，本文件原本也没导入 `Project`（两次 `NameError`）。

### 74.3 复核步骤

1. `cd ai-platform/backend && .venv\Scripts\python.exe -m pytest tests/test_requirement_script_basis_decision.py -q` → 4 passed
2. `GET /api/projects/9/script-basis-freshness` → 需求 29 的落后版本带 `decision`、`fully_decided=true`
3. `cd ai-platform/frontend && node scripts/browser_verify_script_basis_decision.mjs` → 退出码 0

### 74.4 边界

登记决定不执行任何动作；决定绑定最新版本号，新版本出现后自动回到未决定。

## 75. 按新脚本一键重新生成候选（round 52）

### 75.1 变更文件

- 新增 `backend/tests/test_requirement_script_basis_regenerate.py`、`frontend/tests/script-basis-regenerate-contract.test.mjs`、`frontend/scripts/browser_verify_script_basis_regenerate.mjs`。
- 修改 `backend/app/api/requirements.py`（新增 `script-basis-regenerate`，复用 `PrepareGenerationInput`/`prepare_input`/`requirement_generation_handler`）、`frontend/app/projects/[projectId]/readiness/page.tsx`（`follow_planned` 时调端点并显示 `aria-label="复核决定结果"`）。

### 75.2 复核步骤

1. `cd ai-platform/backend && .venv\Scripts\python.exe -m pytest tests/test_requirement_script_basis_regenerate.py -q` → 4 passed
2. 重启 uvicorn（清 `DATABASE_URL/AUTH_MODE/TASK_QUEUE_PROVIDER/PYTHONPATH`、设 `STORAGE_DIR`）→ `/health/ready` 200
3. `cd ai-platform/frontend && node scripts/browser_verify_script_basis_regenerate.mjs` → 退出码 0
4. 演示后回收：把新任务退役（`status='failed'`、`idempotency_key='retired-demo-<id>'`），条目置 `blocked / demo_revoked`

### 75.3 边界

端点只建输入与任务；不采纳、不冻结、不改脚本依据。演示会真实产生一条排队任务，务必回收，否则会在 celery 恢复后空跑 26 次模型调用。

## 76. 看板待采纳候选（round 53）

### 76.1 变更文件
- `backend/app/services/requirement_delivery_status.py`：`STATUS_VERSION` → `requirement-delivery-status-v5`；
  新增 `pending_candidates` 聚合、`pending_candidate_count` / `target_table_id` / `scenario_id`、
  summary 的 `with_pending_candidates` / `pending_candidate_total`。
- `frontend/lib/delivery-status.ts`：`pendingCandidateText`、三个可选字段与两个 summary 计数。
- `frontend/app/projects/[projectId]/readiness/page.tsx`：「待采纳」列 + 深链 Link（空表 `colSpan` 11→12）。
- `backend/tests/test_requirement_delivery_status.py`：新增 `test_delivery_status_counts_pending_candidates`（15 passed）。
- `frontend/tests/pending-candidates-contract.test.mjs`：4 条契约。
- `frontend/scripts/browser_verify_pending_candidates.mjs`：真实浏览器取证脚本。

### 76.2 复核步骤
1. 重启后端（杀 8011 → 清 `DATABASE_URL/AUTH_MODE/TASK_QUEUE_PROVIDER/PYTHONPATH` → `STORAGE_DIR` → 起 uvicorn）。
2. `GET /api/projects/9/requirements-status` 应见 `pending_candidate_total = 55`、4 条有待采纳。
3. `cd frontend && node scripts/browser_verify_pending_candidates.mjs`（需 next dev 在 3010 运行）。

### 76.3 边界
- 测试夹具里 `Requirement.created_by` 不存在，需用 `project.project_owner_id or 1`；
  `RequirementRevision` 要按 `content_version` 倒序取最新。
- 行定位必须按需求名：按需求号会误匹配「字段数/缺口数」中出现的同数字（本轮真实踩坑）。

## 77. 待采纳深链直接打开候选（round 54）

### 77.1 变更文件
- `frontend/app/projects/[projectId]/readiness/page.tsx`：待采纳深链追加 `&pendingCandidate=1`。
- `frontend/components/requirement-workspace/RequirementWorkspace.tsx`：读参数 → `autoOpenPendingCandidate` → 传 `autoOpenPending`。
- `frontend/components/requirement-workspace/RequirementGenerationPanel.tsx`：`autoOpenApplied` 一次性守卫 + 切 `pending` + 打开第一条候选。
- `frontend/tests/pending-candidates-contract.test.mjs`：新增第 5 条契约（意图参数、props 透传、一次性守卫）。
- `frontend/scripts/browser_verify_pending_candidates.mjs`：落点后断言抽屉自动打开且筛选为 `pending`。

### 77.2 复核步骤
1. `cd frontend && node --test tests/pending-candidates-contract.test.mjs`（5 条）。
2. 确保 next dev 在 3010、后端在 8011。
3. `node scripts/browser_verify_pending_candidates.mjs`，输出 `ok=true autoOpened=true filter=pending`。

### 77.3 边界与坑
- Next 缓存坏掉会让页面 404 `/_next/static/css/app/workspace/page.css`，看起来像"页面报错"；删 `.next` 重启即好。
- 自动打开依赖 `pendingCandidates` 已加载；若生成轮次接口还在加载，效果等同于没点，需要用户手动展开。

## 78. 交付前检查留痕（round 55）

### 78.1 变更文件
- 新增 `backend/app/models/delivery_check.py`（`RequirementDeliveryCheck`）与导出；迁移 `202611010011_delivery_checks.py`。
- `backend/app/services/requirement_delivery_checklist.py`：`record_check` / `list_checks` / `serialize_check` / `_iso`。
- `backend/app/api/requirements.py`：`POST …/delivery-checks`（审计 `record_delivery_check`）+ `GET …/delivery-checks`。
- `backend/tests/test_requirement_delivery_checklist.py`：3 个新用例（记录、历史顺序、缺产物 404）→ 8 passed。
- `frontend/components/requirement-workspace/RequirementTemplateExportPanel.tsx`：检查记录区块 + `apiPost` 导入。
- `frontend/tests/delivery-check-record-contract.test.mjs`（4 条）、`frontend/scripts/browser_verify_delivery_check_record.mjs`。

### 78.2 复核步骤
1. `alembic upgrade head`（真实 PG 到 `202611010011`）。
2. 重启后端；`POST /api/projects/9/requirements/10/render-artifacts/20/delivery-checks` 应返回 `record`。
3. `GET /api/projects/9/requirements/10/delivery-checks` 应按 id 倒序。
4. `cd frontend && node scripts/browser_verify_delivery_check_record.mjs`（需 next dev 与后端都活着）。

### 78.3 边界与坑
- 防抖：历史列表不能只等"非空"，旧数据会让断言通过——要等新记录号出现（本轮真实踩坑）。
- 按钮可及名称是 `aria-label="记录本次交付检查"`，按可见文字取 `getByRole` 会超时。

## 79. 检查记录按产物筛选与 CSV（round 56）

### 79.1 变更文件
- `backend/app/services/requirement_delivery_checklist.py`：`list_checks(..., artifact_id=None)`。
- `backend/app/api/requirements.py`：`GET …/delivery-checks` 增 `artifact_id` 参数并在响应里回显。
- `backend/tests/test_requirement_delivery_checklist.py`：新增 `test_history_can_be_filtered_by_artifact`（9 passed）。
- `frontend/components/requirement-workspace/RequirementTemplateExportPanel.tsx`：筛选下拉、导出 CSV、`loadCheckHistory(artifactId = checkArtifactFilter)`。
- `frontend/tests/delivery-check-record-contract.test.mjs`（5 条）、
  `frontend/scripts/browser_verify_delivery_check_filter.mjs`。

### 79.2 复核步骤
1. 两个不同产物各 `POST …/delivery-checks`。
2. `GET …/delivery-checks?artifact_id=<id>` 只返回该产物记录；不带参数返回全部（≤100）。
3. `cd frontend && node scripts/browser_verify_delivery_check_filter.mjs`（期望 CSV 行数 = 筛选行数 + 1）。

### 79.3 边界与坑
- **setTimeout 里读 state 会拿到旧值**：筛选最初写成 `setTimeout(() => loadCheckHistory(), 0)`，
  加载用的是上一次的 `checkArtifactFilter`，界面看起来"筛选没生效"；改为把新值显式传参。
- CSV 每格都带引号，断言要匹配 `,"48",` 而不是 `,48,`（本轮踩过）。
- 文件名原本写"当前打开产物号"、内容是筛选结果 → 审计会拿错文件，已改为跟随筛选。

## 80. 项目级交付审计（round 57）

### 80.1 变更文件

| 类型 | 文件 |
| --- | --- |
| 新增服务 | `backend/app/services/requirement_delivery_audit.py` |
| 新增端点 | `GET /projects/{project_id}/delivery-audit`（`app/api/requirements.py`） |
| 新增前端库 | `frontend/lib/delivery-audit.ts` |
| 修改前端页 | `frontend/app/projects/[projectId]/readiness/page.tsx`（`aria-label="交付审计"` 区块） |
| 新增测试 | `backend/tests/test_requirement_delivery_audit.py`、`frontend/tests/delivery-audit-contract.test.mjs`、`frontend/scripts/browser_verify_delivery_audit.mjs` |

### 80.2 复核步骤

1. 重启后端（清 `DATABASE_URL`/`AUTH_MODE`/`TASK_QUEUE_PROVIDER`/`PYTHONPATH`，设 `STORAGE_DIR`），`/health/ready` 200。
2. `GET /api/projects/9/delivery-audit?limit=200` 看 `summary` 与 `items[*].state`。
3. 打开 `/projects/9/readiness`，确认「交付审计」头条与按钮计数与接口一致，点「还没检查」行数 = `min(unchecked, 12)`。

### 80.3 边界与坑

- 审计不写库；`unchecked` 表示**没有检查记录**，不是检查失败。
- 浏览器脚本取 `当前显示 X / Y 个产物` 时要注意该行是 `<span>` 而不是 `<p>`，且 Y 是**当前筛选后的总数**。

## 81. 模板一致性比对（round 58）

### 81.1 变更文件

| 类型 | 文件 |
| --- | --- |
| 新增服务 | `backend/app/services/requirement_survey_fidelity.py` |
| 新增端点 | `GET /projects/{project_id}/requirements/{requirement_id}/render-artifacts/{artifact_id}/template-fidelity` |
| 修改前端组件 | `frontend/components/requirement-workspace/RequirementTemplateExportPanel.tsx`（「模板一致性」按钮 + 弹层） |
| 新增测试/脚本 | `backend/tests/test_requirement_survey_fidelity.py`、`frontend/tests/template-fidelity-contract.test.mjs`、`frontend/scripts/browser_verify_template_fidelity.mjs` |

### 81.2 复核步骤

1. 重启后端（清数据库相关环境变量、设 `STORAGE_DIR`），`/health/ready` 200。
2. `GET /api/projects/9/requirements/25/render-artifacts/59/template-fidelity` 看 `verdict` 与各列计数。
3. 打开工作台 `T_8_1` 需求，产物行点「模板一致性」，确认弹层结论与接口一致。

### 81.3 边界与坑

- 字段代码不是全局唯一（`SFJJGDM` 每张表都有）：比对必须按需求的目标表取值，否则会把正确文档判成不一致（本轮真实踩过）。
- Word 产物没有模板列结构，接口 422 是有意的。
- Next 开发缓存坏掉时页面会报 `Failed to load resource: 404`（`/_next/static/css/app/workspace/page.css`），删 `frontend/.next` 重启即可，别误当产品缺陷。

## 82. 项目级待办派工清单（round 58 追加）

### 82.1 变更文件

| 类型 | 文件 |
| --- | --- |
| 新增服务 | `backend/app/services/requirement_field_worklist.py` |
| 新增端点 | `GET /projects/{project_id}/requirements-worklist` |
| 新增前端库/测试 | `frontend/lib/requirement-worklist.ts`、`frontend/tests/field-worklist-contract.test.mjs` |
| 修改前端页面 | `frontend/app/projects/[projectId]/readiness/page.tsx`（入口按钮 + 弹层 + CSV） |
| 新增脚本/用例 | `backend/tests/test_requirement_field_worklist.py`、`frontend/scripts/browser_verify_field_worklist.mjs` |

### 82.2 复核步骤

1. 重启后端后 `GET /api/projects/9/requirements-worklist?limit=5` 应为 `field_count=233`、`truncated=true`。
2. 看板「交付状态」区点「待办派工清单」，头条中的四个数字应与接口 `reason_totals` 一致。
3. 任选一档筛选 → 行数等于该档计数；`下载 CSV` 的行数等于当前筛选条数、文件带 BOM。

### 82.3 坑

- CSV 断言若直接 `startsWith('"监管表编号"')` 会因 BOM 失败，需先 `replace(/^\ufeff/, "")`。
- 动态 `import` 本地 `.ts` 必须用 `pathToFileURL`，Windows 上直接传绝对路径会报 `ERR_UNSUPPORTED_ESM_URL_SCHEME`。
- `RequirementGenerationItem` 有 `(input_id, field_id, section)` 唯一约束，造夹具时不能同一字段同一章节重复插入。

## 83. round 59：派工清单行级深链（改动与复核）

### 83.1 变更文件

- `backend/app/services/requirement_field_worklist.py`：item 增 `target_table_id`、`scenario_id`。
- `frontend/lib/requirement-worklist.ts`：`WorklistItem` 增两个可选字段；新增 `worklistFieldHref()`（五参数齐全才给链接，`projectId` 兼容 string）。
- `frontend/app/projects/[projectId]/readiness/page.tsx`：弹层「处理」列与「去处理」/「无法定位」。
- `backend/tests/test_requirement_field_worklist.py`：夹具补 `content["scenario"]={"id":7,...}` 并断言两个 id。
- `frontend/tests/field-worklist-contract.test.mjs`：新增深链用例。
- `frontend/scripts/browser_verify_worklist_deeplink.mjs`：新增真实浏览器脚本。

### 83.2 复核步骤

```powershell
cd ai-platform\backend; $env:PYTHONPATH='.'; $env:AUTH_MODE='optional'
$env:TASK_QUEUE_PROVIDER='inline'; $env:DATABASE_URL='sqlite:///:memory:'
.\venv\Scripts\python.exe -m pytest tests/test_requirement_field_worklist.py -q -p no:randomly
cd ..\frontend; node --test tests/field-worklist-contract.test.mjs
.\node_modules\.bin\tsc.cmd --noEmit -p tsconfig.json
```

### 83.3 两个坑

1. 断言"高亮行文本以 `编码 名称` 开头"会失败——工作台表格是「名称 编码」顺序，应断言两者都出现，而不是假定顺序。
2. `projectId` 从路由参数取到的是 **string**，`worklistFieldHref(projectId: number)` 会 `TS2345`；签名放宽为 `number | string` 内部 `Number()` 归一。

## 84. round 60：派工清单按监管表分装（改动与复核）

### 84.1 变更文件

- `backend/app/services/requirement_worklist_archive.py`（新增）：分组、CSV、固定时间 zip、manifest。
- `backend/app/api/requirements.py`：`GET …/requirements-worklist/archive` 端点 + `from urllib.parse import quote`。
- `backend/app/main.py`：`expose_headers` 增三个 `X-Requirement-Worklist-*`。
- `frontend/app/projects/[projectId]/readiness/page.tsx`：`worklistArchiveBusy` 状态、`exportWorklistArchive()`、按钮。
- `backend/tests/test_requirement_worklist_archive.py`（新增，5 passed）。
- `frontend/tests/worklist-archive-contract.test.mjs`（新增，3 passed）。
- `frontend/scripts/browser_verify_worklist_archive.mjs`（新增）。

### 84.2 复核步骤

```powershell
cd ai-platform\backend; $env:PYTHONPATH='.'; $env:AUTH_MODE='optional'
$env:TASK_QUEUE_PROVIDER='inline'; $env:DATABASE_URL='sqlite:///:memory:'
.\venv\Scripts\python.exe -m pytest tests/test_requirement_worklist_archive.py -q -p no:randomly
cd ..\frontend; node --test tests/worklist-archive-contract.test.mjs
.\node_modules\.bin\tsc.cmd --noEmit -p tsconfig.json
```

### 84.3 三个坑

1. 新测试用 `snapshot_api` 夹具时必须 `from test_requirement_snapshot_api import snapshot_api, snapshot_db  # noqa: F401`，否则报 `fixture 'snapshot_db' not found`。
2. 中文文件名必须同时给 ASCII 兜底与 `filename*=UTF-8''`，只给后者旧浏览器会退化成 `.zip`。
3. 清单里一旦写"生成时间"，两次导出字节就不同；可复现要求清单只放内容态字段。

## 85. round 61：字段级派工与处置登记（改动与复核）

### 85.1 变更文件

- `backend/app/models/dispatch.py`（新）、`backend/app/models/__init__.py`（导出）
- `backend/alembic/versions/202611010012_field_dispatch.py`（新）
- `backend/app/services/requirement_field_dispatch.py`（新）
- `backend/app/services/requirement_field_worklist.py`（附 `dispatch`/`dispatch_text`）
- `backend/app/api/requirements.py`（`POST …/requirements-worklist/dispatch` + `_positive_int`）
- `frontend/lib/requirement-worklist.ts`（`WorklistDispatch`、`DISPATCH_STATUS_OPTIONS`、`dispatchText`）
- `frontend/app/projects/[projectId]/readiness/page.tsx`（处置列、行内表单、`reloadWorklist`）
- `backend/tests/test_requirement_field_dispatch.py`（新）、`frontend/tests/field-dispatch-contract.test.mjs`（新）、`frontend/scripts/browser_verify_field_dispatch.mjs`（新）

### 85.2 复核步骤

真实 PG 迁移到 `202611010012` 后重启 uvicorn（清 `DATABASE_URL/AUTH_MODE/TASK_QUEUE_PROVIDER/PYTHONPATH`、设 `STORAGE_DIR`），
再跑 `backend/scripts/_verify_dispatch.py`（读回）与浏览器脚本。

### 85.3 两个坑

1. `Client.request` 需要 `/api` 前缀：`Client("http://127.0.0.1:8011")` + `/api/projects/...`；把 `/api` 写进 base 会 404。
2. 同表同名字段可能挂在多条需求上，浏览器脚本**不能只按行文本判定**是否登记成功（会数到另一行）；
   改为等"责任人"出现后以接口读回为准。

## 86. round 62：处置轨迹（改动与复核）

### 86.1 变更文件

- `backend/app/models/dispatch_event.py`（新）、`backend/app/models/__init__.py`（导出）
- `backend/alembic/versions/202611010013_dispatch_events.py`（新）
- `backend/app/services/requirement_field_dispatch.py`（追加事件 + `dispatch_events_for_project` + 清单挂 `history`）
- `backend/scripts/backfill_dispatch_events.py`（新，一次性回填，可重复执行）
- `frontend/lib/requirement-worklist.ts`（`DispatchHistoryEntry`、`dispatchHistoryText`）
- `frontend/app/projects/[projectId]/readiness/page.tsx`（处置轨迹折叠区）
- `backend/tests/test_requirement_field_dispatch.py`、`frontend/tests/field-dispatch-contract.test.mjs`、`frontend/scripts/browser_verify_dispatch_history.mjs`

### 86.2 复核步骤

真实 PG 迁到 `202611010013` → 跑回填脚本 → 重启 uvicorn（清 `DATABASE_URL/AUTH_MODE/TASK_QUEUE_PROVIDER/PYTHONPATH`、设 `STORAGE_DIR`）→ 跑 `_verify_dispatch_history.py` 与浏览器脚本。

### 86.3 一个坑

回填只处理"没有事件的字段"：已经有一条事件的字段会被跳过，所以"回填后条数"不等于"处置数"——
写验证脚本时要按**变更前后差值**断言，不要写死绝对值。

## 87. round 63：处置 vs 缺口对照（改动与复核）

### 87.1 变更文件

- `backend/app/services/requirement_field_worklist.py`（`GAP_CONSISTENCY_STATES`、`_gap_consistency()`、item 加 `gap_consistency`、返回 `gap_consistency_labels/totals`）
- `frontend/lib/requirement-worklist.ts`（`GapConsistencyState`/`GapConsistency`、`GAP_CONSISTENCY_BADGE`、`gapConsistencyText()`、响应类型补计数）
- `frontend/app/projects/[projectId]/readiness/page.tsx`（「处置 vs 缺口」列 + 头条四态计数）
- `backend/tests/test_requirement_field_worklist.py`、`frontend/tests/field-worklist-contract.test.mjs`、`frontend/scripts/browser_verify_gap_consistency.mjs`

### 87.2 复核步骤

重启 uvicorn（清 `DATABASE_URL/AUTH_MODE/TASK_QUEUE_PROVIDER/PYTHONPATH`、设 `STORAGE_DIR`）→ 打开派工清单 → 头条应有"处置与缺口"一行 → 存在矛盾行时徽标为危险色。

### 87.3 两个坑

- `record_dispatch()` 的参数名是 `created_by`（不是 `actor_id`），写错直接 `TypeError`。
- 前端契约里页面/lib 路径是模块级常量（`lib`/`page`），新增用例要 `readFileSync(lib, "utf8")` 并换变量名，否则 `readFile is not defined`。

## 88. round 64：一键验收（改动与复核）

### 88.1 改动

1. `backend/app/services/requirement_acceptance.py`（新）：`ACCEPTANCE_VERSION`、`STEP_ORDER`、`run_acceptance()`。
2. `backend/app/api/requirements.py`：`POST …/acceptance-run`，审计 `run_delivery_acceptance`。
3. `backend/tests/test_requirement_acceptance.py`（新）：4 个用例。
4. `frontend/lib/acceptance-notice.ts`（新）：结果 store + `useSyncExternalStore` 挂钩。
5. `frontend/app/projects/[projectId]/readiness/page.tsx`：审计行按钮、`runAcceptance()`、结果条与关闭按钮。
6. `frontend/tests/acceptance-run-contract.test.mjs`：契约扩到 5 条（含重挂载回归）。
7. `frontend/scripts/browser_verify_acceptance_run.mjs`：真实浏览器验证（含不等安定就点击）。

### 88.2 复核

- 后端四文件组合回归（acceptance / field_dispatch / field_worklist / worklist_archive / delivery_status）：27 passed。
- 前端全量契约：479 passed；`tsc --noEmit` 0。
- 文档结构检查：0 问题。
- 真实浏览器：见 evidence-index.md §92 表格最后一行。

### 88.3 遗留

- 结果条只保留"最后一条"，多产物连续验收时前一条会被覆盖（有意的取舍：避免堆一屏提示）。
- 验收批量入口（一次验多个产物）未做，属于下一轮候选。

## 89. round 65：批量验收（改动与复核）

### 89.1 改动

- `requirement_acceptance.py`：新增 `run_acceptance_batch()`（只挑未检查、单条出错继续、跑完重算审计）。
- 新增 `requirement_acceptance_scope.py`：把"内置版式 xlsx / 客户模板 docx"识别为**不适用**而不是失败。
- `requirement_delivery_audit.py`：条目增 `acceptance_applicable` / `acceptance_scope_code`，汇总增
  `unchecked_supported` / `unchecked_unsupported`。
- `api/requirements.py`：`POST …/requirements-acceptance/batch`（`project.view`、参数校验、审计）。
- 前端：`lib/delivery-audit.ts` 的 `auditPendingSupported()`、看板批量按钮与"不支持自动验收"提示、
  批量结果条（含跳过清单与"跳过的不写记录、也不算通过"）。

### 89.2 复核

- 后端：`test_requirement_acceptance_batch.py` 5 passed、`test_requirement_acceptance.py` 5 passed、
  `test_requirement_delivery_audit.py` 3 passed（合计 13 passed）。
- 前端契约：`acceptance-run-contract.test.mjs` 7 passed；`tsc --noEmit` 0。
- 真实接口：`checked 18 → 23`、`skipped 2`、记录 `#39`–`#43`。
- 真实浏览器：`checked 37 → 38`、`serverMatchesNotice: true`、`consoleErrors: []`、`failedRequests: []`。
- 文档结构检查：0 问题。

### 89.3 遗留

- 批量结果条只保留最后一次动作的摘要，历史看检查记录表。
- "只能人工核对"的产物没有登记入口（人工核对结果目前只能通过检查单字段登记体现），
  属于下一轮候选：给不适用产物一个"人工核对登记"动作，写明核对人/时间/依据。
## 90. round 66：人工核对登记（改动与复核）

### 90.1 改动

- 新增 `app/models/artifact_attestation.py` + 迁移 `202611010014_artifact_attestations.py`。
- 新增 `app/services/requirement_artifact_attestation.py`（校验 + 追加写 + 批量取用户）。
- `requirement_delivery_audit.py` 升 v2：item 带 `attestation`，summary 带 `attested/unattested/attested_confirmed/attested_rejected`。
- `api/requirements.py`：`POST/GET …/render-artifacts/{aid}/attestations`，审计 `record_artifact_attestation`；补 `User` 导入。
- 前端 `lib/delivery-audit.ts` 与 `readiness/page.tsx`：人工核对列、行内表单、提示条、结果播报；修 `auditReload` 依赖。

### 90.2 复核

- 后端 `test_requirement_artifact_attestation.py` 5 passed；真实 PG 迁移到 `202611010014`。
- 前端契约 `artifact-attestation-contract.test.mjs` 5 passed；`tsc` 0。
- 真实浏览器 `browser_verify_attestation.mjs`：`ok: true`，`checkedUnchanged/attestedPlusOne/unattestedMinusOne/stateStillUnchecked` 全真。

### 90.3 未做

- 未做"人工核对结论回填到需求正文"（会越过人工采纳与审批，属于治理红线）。
- 未做登记撤销/作废（历史只追加，撤销应另立结论而不是删除记录）。

## 91. round 67：人工核对不通过压住就绪度

- 目标：把"人工核对不通过"从只留痕变成会影响判定——看板必须看得见、排得前、筛得出。
- 做法：`requirement-delivery-status-v6` + `_readiness(human_rejected=...)`；批量取每需求最近一条登记；
  只有登记落在最新产物上才压住就绪度；前端枚举/排序/筛选/详情四处同步。
- 真实结果：产物 `#66`（需求 28）登记 rejected → `readiness=human_rejected`、`summary.human_rejected=1`；
  审计 `checked` 保持 38（人工判断不是机器检查）。
- 浏览器：`人工核对不通过 1` 筛选命中 1 行、详情写明"被人工核对判「不通过」"、控制台 0 错误；
  截图 `ui-human-rejected-verified.png`。
- 遗留与边界：新产物没被核对过就显示它自己的真实状态（不继承否决）；登记仍不关缺口、不改正式交付。

## 92. 被否产物进入派工清单（round 68）

- 结论：人工核对「不通过」从"只是看板上红一格"变成"派工清单里 29 个带依据的字段"，有下家了。
- 口径：只认最新产物上的最新登记；`confirmed` 不加待办；被否不阻止再次导出，新产物有自己的状态。
- 数据：项目 9 清单 `field_count=233` 不变，`reason_totals.artifact_rejected=29`（29 个字段本就待办，
  多加一条原因而不是造新待办）。
- 顺手修：登记时间曾按 UTC 当本地显示（19:05 显示成 11:05），新增 `formatServerTime()` 按 UTC 补 `Z` 再转本地。
- 证据：`backend/scripts/out/worklist_rejected.json`、`frontend/scripts/out/browser/ui-worklist-rejected-verified.{png,json}`。

## 93. 换版式重导不能解除否决（round 69）
- 结论：把"同一份冻结内容换版式重导"从"红牌消失"改回"红牌继续压着"，并给出被否之后的三种真实状态。
- 判据：`requirement-delivery-status-v7` 用 `content_hash` 比较；`rejection.on_latest_artifact=false` +
  `same_content_as_latest=true` 即"换了壳、正文没改"。
- 真实数字（需求 28）：被否产物 `#66`（xlsx）→ 同快照导出 `#67`（docx，43 824 B）→
  `readiness` 仍 `human_rejected`、`superseded_by=#67`；跟进 `{rejected:1, reexported_same_content:1}`；
  派工清单 `field_count=233`、`artifact_rejected=29`、`later_artifact_count=1`。
- 浏览器：`人工核对不通过 1` 命中 1 行；行详情点名"之后导出的 #67 内容与它一致……红牌仍然压着"；
  弹层「被否后续核对」写明"1 份重导后内容没变（只换版式）"；0 控制台错误。
- 顺手修：验证脚本里"先开弹层再点筛选"会被遮罩挡住（`Escape` 关不掉），改为先做筛选与行详情、再开弹层。
- 遗留与边界：内容真变也只到"等人工再核对"，不自动通过、不关缺口、不改正式交付。
## 94. round 70 收尾：字段覆盖核对

- 做了什么：新增只读「字段覆盖核对」，把没进需求范围的监管字段按"有集市映射 / 只有脚本血缘 / 都没有"三类列出，界面明确写"不改需求、不补字段"。
- 真实结论：项目 9 的 21 条需求共 237 个表字段，覆盖 231 个，未覆盖 6 个且全为 `unreferenced` —— 脚本建需没有静默丢字段；此前"`T_1_3` 248 个字段只覆盖 29 个"的判断是错的（真实 `TargetField` 2422/90 表，`T_1_3` 30 个）。
- 顺带修：就绪度主表 14 列只给 920px 导致需求名竖排 → `min-w-[1560px]` + nowrap + `colSpan=14`。
- 测试：后端 5 passed（覆盖分类/样例截断/未绑表/跨项目/HTTP）；前端契约 3 passed；`tsc` 0。
- 下一步候选：把 `mapped` 类未覆盖字段接进待办派工（"模板要求填但没进范围"是最该补的一类），或给"补字段"做人工确认的受控入口。
## 95. round 71 收尾：交付稳定性核对

- 做了什么：把"同一冻结内容 + 同一渲染器 → 同一字节"从测试断言变成**按真实产物逐份核对**的只读功能；看板可一键跑，结论四段分开（重放一致 / 不一致 / 旧版渲染器 / 不支持重放）。
- 真实结论：项目 9 的 47 个产物里，当前渲染器产物 11 个全部重放一致、0 个漂移；35 个是 v3–v9 旧版渲染器产物（当前代码重放不了，单独计数）；1 个客户模板产物不支持重放。
- 抓到并修正了自己的误报：首版把 35 个旧版产物报成"渲染器漂移"，原因是判定顺序（先比字节）与缺 `historical` 态；修完噪音归零。
- 测试：后端 6 passed；前端契约 5 passed；`tsc` 0；真实浏览器 `ok: true`。
- 下一步候选：客户模板产物的重放（把模板 sha 与适配配置一起纳入重放身份）；把 `historical` 产物列进交付审计，让"这批文件只能在旧渲染器下复核"变成可见的交付风险。
## 96. round 72 收尾：交付审计接入复核风险

- 做了什么：交付审计每份产物多一个 `replay` 维度（可重放 / 仅旧渲染器 / 不支持重放），卡片上多一行风险提示与行内标；判定只看元数据，不重放。
- 真实结论：47 个产物 → 可重放 11、仅旧渲染器 35、不支持重放 1，与 round 71 的重放核对结果**互相对上**；`checked` 仍是 38，不被复核维度影响。
- 文案守住了边界：复核不了写成"再核一遍需要当时的渲染器或模板"，不写"不能交付"，契约里锁死。
- 测试：后端 4 passed；前端契约 4 passed；`tsc` 0；真实浏览器 `ok: true`。
- 下一步候选：把"仅旧渲染器"的历史产物做成可检索的清单（按需求/表/渲染器版本），并在冻结导出前提示"这份交付将无法用当前代码复核"。
## 97. round 73 收尾：交付复核清单 + 交接

- 做了什么：给"哪些产物还能用当前代码复核"做了一张可检索清单（状态/渲染器/需求/关键字），入口在交付审计卡；只读元数据，不重放。
- 真实结论：47 个产物 → 可复核 11、仅旧渲染器 35、不支持重放 1，与 round 71、round 72 两套口径三方一致。
- 测试：后端 5 passed；前端契约 5 passed；`tsc` 0；真实浏览器 11 项断言全过。
- 本轮之后暂停并交接：改动冻结到 `dsh/handoff-20261025-round73`，问题清单见 `handoff-20261025.md`。
- 已知未完成：端到端主线复跑、冻结导出前的复核风险提示、清单 CSV 导出、P2-C 容量恢复演练（NOT_RUN）。
