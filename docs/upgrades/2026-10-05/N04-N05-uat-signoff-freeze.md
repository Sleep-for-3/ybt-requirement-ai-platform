# N04 / N05：UAT 签署绑定证据 hash 与轮次冻结 manifest

本轮（2026-10-05）安全工作包之五，对应复核项 **N04（高，正式 UAT 签署前阻断）** 与 **N05（高，证据可追溯验收阻断）**。

## 1. 问题与风险（修复前）

### N04：签署后人工结果仍可修改，原 approved 仍然有效

`POST /uat-case-results/{id}/complete-manual` 与 `attach-evidence` 只检查 `run.status == "cancelled"`。
签署接口 `create_uat_signoff` 只校验 `run.status == "passed"` 与关键问题是否闭环，**签署与具体证据无任何绑定**。
复核复现：轮次 passed 且 approved 签署后，修改人工结果返回 **200**、轮次翻成 `failed`，而原 approved 签署**依然存在**
（`docs/reviews/2026-10-04/uat-signed-result-repro.json`，optional-auth 单测模式，不证明生产 RBAC 绕过）。

### N05：证据包每次读“当前环境”

`build_evidence_package` 每次下载都调用 `run_health_checks(db, get_settings())`、读**当前** alembic revision，
并把**全项目**交付包列表写入证据，因此同一 closed 轮次在环境变化后产出的字节不同；且创建轮次允许版本为空。
复核复现：`uat-snapshot-repro.json`（stub 报告与环境，无真实数据库/健康探测）。

## 2. 改动（修复后）

### 2.1 新增 `backend/app/services/uat/freeze.py`

| 函数 | 作用 |
| --- | --- |
| `build_run_manifest(db, run, request_id=…)` | 服务端固化：run/suite/环境/应用版本/git sha、发布身份（component/app_commit/build_time/schema_head/image_digest）、需求绑定（requirement_id/revision_id/content_hash/cases_hash/content_version）、模型档案清单 |
| `freeze_run_manifest(db, run, request_id=…)` | **只固化一次**，后续调用绝不覆盖既有快照 |
| `manifest_digest` / `results_digest` / `signoff_evidence_hash` | 冻结清单 + 结果/证据的稳定摘要（排序规范化 JSON → SHA-256） |
| `approved_signoff(db, run)` / `assert_run_mutable(db, run)` | 存在未撤销的 approved 签署时，结果/证据写入一律 **409**，detail 为 `{"code": "uat-run-signed-off", …}` |
| `FROZEN_SIGNOFF_STATUSES = ("approved",)` | `rejected` 不冻结，保留返工闭环 |

### 2.2 模型与迁移

- `UatRun.manifest_json`（NOT NULL，默认 `{}`）——建轮次时写入冻结快照。
- `UatSignoff.evidence_hash`（String(64)）、`revoked_at`、`revoked_by`（FK users）——签署绑定证据、撤销可审计。
- 迁移 `alembic/versions/202610050002_uat_run_freeze.py`（`down_revision = 202610050001`）；SQLite 下 FK 走
  `op.batch_alter_table`（与 `202609200040/202609200041` 同款），列可空性严格对齐 ORM（schema-freeze 契约测试会比对）。

### 2.3 API 接线（`backend/app/api/uat.py`）

- `create_uat_run`：创建后立即 `freeze_run_manifest(db, run, request_id=current_request_id())`。
- `complete_manual_result` / `attach_result_evidence`：写入前 `assert_run_mutable(db, run)`（签署后 409）。
- `create_uat_signoff`：先 `freeze_run_manifest`，再算 `signoff_evidence_hash` 写入签署并记入 `summary_json` 与审计。
- 新增 `POST /uat-signoffs/{signoff_id}/revoke`：显式撤销（重复撤销 409），撤销后必须**重签**，历史签署保留。

### 2.4 证据包（`backend/app/services/uat/reporting.py`）

新增 `uat-run-manifest.json`、`signoffs.json`；`version.json` 增加 `frozen_manifest_digest`、
`current_signoff_evidence_hash`、`frozen_release_identity`、`frozen_requirement`、`frozen_at`。
原 `alembic_revision` / `alembic_head_revision` 语义保持（下载时的实时观测，向后兼容既有断言）；
权威历史依据是冻结块，不再用下载时的健康/schema 冒充历史证据。

## 3. 验证

### 3.1 新增反例测试 `backend/tests/test_uat_signoff_freeze.py`（4 passed）

驱动**真实 HTTP 端点**（非 helper），夹具用 **manual** 用例（自动用例会在进 N04 守卫之前被“仅 manual/hybrid”前置校验拒绝）：

| 用例 | 断言 |
| --- | --- |
| `test_run_creation_freezes_the_input_manifest` | 建轮次即带 `manifest_json`（manifest_version=1、run.id、frozen_at、release_identity.app_commit） |
| `test_evidence_package_is_stable_after_the_environment_changes` | 证据包含 `uat-run-manifest.json`/`signoffs.json`/`version.json`/`SHA256SUMS`；**两次下载的 version.json 与 manifest 完全一致**（不漂移）；签署带 `evidence_hash` |
| `test_signed_run_rejects_result_changes` | **N04 复现转绿**：签署后 `complete-manual` 与 `attach-evidence` 均 **409** 且 `detail.code == "uat-run-signed-off"`；轮次仍 `passed`、签署仍 approved |
| `test_revoking_a_signoff_allows_a_new_one` | 撤销成功且 `revoked_at` 非空；重复撤销 409；重签得到新的 `evidence_hash` 且新 id；列表保留 2 条（撤销历史 + 新签署） |

### 3.2 回归（无行为回退）

```
cd backend; $env:TASK_QUEUE_PROVIDER='inline'; $env:AUTH_MODE='optional'
.venv\Scripts\python.exe -m pytest tests/test_uat_signoff_freeze.py tests/test_uat.py `
  tests/test_requirement_uat.py tests/test_uat_migrations.py tests/test_migration_schema_freeze.py `
  tests/test_version_consistency.py -q
→ 36 passed
```

迁移确定性/可逆（`test_uat_migrations.py` 三个参数化场景）与 schema-freeze 契约通过，唯一 head 为 `202610050002`。

## 4. 未验证 / 边界（不得当作通过）

1. 未在真实银行 UAT 环境、四类角色账号下执行完整闭环（属 W11，需测试账号与真实样本）。
2. 复核的 N04 复现使用 optional-auth 单测模式；本轮未证明生产 RBAC 层绕过与否，**只证明状态契约被封闭**。
3. `manifest_json` 固化了需求/发布身份/模型档案；**资产与 Skill 版本清单尚未纳入**（需与 W11 输入 manifest 对齐后收敛）。
4. 迁移 `202610050002` 已在 SQLite 全量测试与 schema freeze 契约中验证；**未**在业务库执行（需另行批准）。
5. 撤销接口只记录撤销时间/人，未做“撤销原因必填”的流程约束（按需再补）。
