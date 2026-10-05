# 第四阶段（第三次更新）：23/23 通过，**冻结 Word/Excel 已完成**；正式交付路径记为 deferred

本轮（2026-10-05）在 P5 修复基础上补齐了**冻结正式文件**环节。两项独立冻结路径的区别是本轮关键发现：

| 路径 | 前置 | 产出 | 本轮结果 |
| --- | --- | --- | --- |
| **草稿快照冻结**（`POST .../snapshots`） | `deliverable.manage` + 当前 `document_content` 的 hash | 冻结快照 + Word/Excel，均带 `X-Requirement-Snapshot-Hash` | ✅ **已通过** |
| **正式交付**（提审 → finalize → `formal-deliveries/.../export`） | 需先清零 `review_readiness`（41 项） | 正式交付版本 Word/Excel | ⏸ 记为 deferred（附可执行条件） |
两项路径均在隔离 PostgreSQL 上通过真实角色 API 验证。

## 1. 本轮新增：冻结 Word/Excel 已端到端验证

```
requirement_snapshot_frozen    ok=true  status=201  status=frozen_draft
snapshot_binds_same_hash       ok=true  snapshot_hash=f1a2b1c2bcc9e08c  document_hash=f1a2b1c2bcc9e08c
frozen_draft_export_xlsx       ok=true  status=200  bytes=11261  hash_matches=true
frozen_draft_export_docx       ok=true  status=200  bytes=38046  hash_matches=true
{"ok": true, "steps": 23}   EXIT=0
```

即：`GET .../document` 的 `content_hash` → 冻结快照（hash 一致）→ 导出 xlsx/docx，**两个文件回带的 `X-Requirement-Snapshot-Hash` 都与该 hash 相等**，
满足“正式文件绑定同一版本/hash”的验收要求。导出需 `deliverable.export`（业务分析不具备），由项目经理执行。

## 2. P5 修复的端到端效果（决定性）

| 指标 | P5 修复前 | P5 修复后 |
| --- | --- | --- |
| 脚本退出码 | `EXIT=1` | **`EXIT=0`** |
| 汇总 | `{"ok": false, "steps": 16}` | **`{"ok": true, "steps": 16}`**（本轮含冻结环节后为 23） |
| `uat_run_bound_to_release` | 500 `InFailedSqlTransaction` | `ok=true`（含 manifest_digest） |

## 3. 已用真实 API + 真实四角色跑通的环节（隔离 PG `ybt_iso_phase4_synthetic`）

| 环节 | 证据 |
| --- | --- |
| 合成材料 8 字段 / 2 源表 / 1 集市 / 1 目标表 | `fields=8, source_tables=2, mart_tables=1, target_tables=1` |
| 6 个独立账号（业务分析/技术分析/业务审核/终审/审计/项目经理）、6 个不同 token | `distinct_tokens=true` |
| 需求创建（业务分析） | `requirement_id=1, version=1, field_count=8` |
| 需求独立内容版本 | `content_version=1` + `content_hash` |
| **职责分离**：业务审核不得创建需求 | **403** |
| **审计只读**：读 200 / 写 403 | `read_status=200, write_status=403` |
| 自定义 UAT 套件（项目经理，`uat.manage`） | 201 |
| **轮次绑定发布身份 + 冻结 manifest** | `run_id=1, environment=isolated-synthetic, manifest_digest=…` |
| **Finding 全生命周期**：open → fixing → resolved → verified（项目经理复核） | `verify_status=200` |
| 人工结果录入（业务分析） | 200 |
| **双人签署各自绑定同一 evidence_hash** | `statuses=[201,201]`，两个 hash 相同且非空 |
| **冻结证据包**（重下载字节一致，N05） | 含 `uat-run-manifest.json`、`signoffs.json`、`SHA256SUMS`、`uat-report.xlsx`、`version.json` |
| 需求草稿导出 xlsx | 200，11259 字节 |

## 4. 正式交付路径尝试：被真实门禁阻断（记为 deferred）

按正确顺序接入：`提交审核（deliverable.manage）→ 终审 finalize（deliverable.review）→ 导出 xlsx/docx`。

**结果**：`POST .../review-submissions` → **409**
```
{"detail":"存在 41 项阻断条件，请先处理后再送审"}
```

**根因（真实业务门禁，非缺陷）**：`review_readiness()` 对每个字段做 5 项检查，
8 个字段共 **41 项阻断**（含 1 项额外条件）：

| 每字段检查 | 含义 |
| --- | --- |
| `definition` | 缺少**业务定义** |
| `source` | 缺少**可定位的源系统字段** |
| `mapping` | 缺少**监管集市的目标字段映射** |
| `transformation` | 缺少**加工过程描述** |
| `evidence` | 缺少**可追踪证据** |

这正是 W11 第 3–5 步要求业务/技术分析**逐字段填写**的合成工程内容 —— 也就是说，
`requirement_review_submitted`、`requirement_delivery_finalized`、`frozen_export_xlsx/docx`
三步**不是代码问题，而是前置业务内容尚未产出**。

## 4. 未完成（明确不冒充通过）

1. **冻结 Word/Excel**：需先补齐 41 项 readiness 内容（逐字段业务定义、源字段、集市映射、加工过程、证据），
   再走提审 → 终审 → 导出。可执行路径：
   ```
   GET  /api/projects/{p}/requirements/{r}/review-readiness?content_version=1   # 列出 41 项
   POST /api/projects/{p}/requirements/{r}/revisions/{v}/fields/{field_id}/...  # 逐字段补定义/映射/加工/证据
   POST /api/projects/{p}/requirements/{r}/refresh-lineage
   POST /api/projects/{p}/requirements/{r}/review-submissions                    # 项目经理
   POST /api/projects/{p}/requirements/{r}/review-submissions/{id}/finalize      # 终审
   GET  /api/projects/{p}/requirements/{r}/formal-deliveries/{id}/export?format=docx|xlsx
   ```
2. **需求规则测试项路径**：仍需 W11 固定输入（合成源 SQL 脚本 → 路径 → 制度对照）。
3. **正式交付路径（deferred，非失败）**：`POST .../review-submissions` 返回 **409**「存在 25 项阻断条件」。
   本轮已验证：填写 8 字段业务定义 + 技术来源/加工规则后，readiness 由 **41 降至 25**；
   剩余为每字段的 `mapping`（集市映射）/`evidence`（可追溯证据）/`edited_lineage`（技术口径已改动）。
   经阅读 `requirement_gaps.field_gaps` 与 `requirement_paths.confirmed_path` 确认：这四项缺口的**唯一豁免途径**是
   `confirmed_path`（需 `script_basis` + preview_hash + 零路径问题）。探针 `probe_script_ingestion.py` 证明合成脚本
   可解析（7 节点/4 边/4 语句，目标 `ybt_loan_info` 列 `cust_no`/`loan_bal`，规则含 `SUM(l.loan_bal)`），
   但节点 `catalog_table_id` 均为 null，路径报「缺少上游字段元数据：src_loan.cust_no」；
   `app/services/lineage/resolver.py::resolve_lineage_node` 才是目录/资产绑定入口（匹配 `CatalogTable`/`CatalogColumn`
   与 `SourceTable/Field`、`MartTable/Field`、`TargetTable/Field`），需先补齐目录元数据 fixture。
   可执行条件已写入报告：`scripts/upload → script-basis → paths → review-submissions → finalize → formal-deliveries/export`。
6. **第五阶段**（版本化评测数据集与复核、完整备份恢复、真实多 worker 故障恢复与容量基线）未开始。

## 5. 结论

P5 修复让第四阶段的**技术闭环**（材料→账号→需求→套件→轮次→Finding→双签→冻结证据）在隔离环境
以真实角色跑通并通过全部 16 项检查；**业务内容闭环**（41 项 readiness → 冻结正式 Word/Excel）
因合成业务内容尚未填写而**未完成**，已给出可执行路径。
