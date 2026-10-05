# 第四阶段（第二次更新）：P5 修复后闭环 16/16 通过；冻结正式文件被 readiness 门禁阻断

本轮（2026-10-05）在修复 **P5**（`schema_head` savepoint，见 [P5-schema-probe-transaction-poisoning.md](P5-schema-probe-transaction-poisoning.md)）
之后，重新在隔离 PostgreSQL 上执行合成工程闭环。

## 1. P5 修复的端到端效果（决定性）

| 指标 | P5 修复前 | P5 修复后 |
| --- | --- | --- |
| 脚本退出码 | `EXIT=1` | **`EXIT=0`** |
| 汇总 | `{"ok": false, "steps": 16}` | **`{"ok": true, "steps": 16}`** |
| `uat_run_bound_to_release` | 500 `InFailedSqlTransaction` | `ok=true`（含 manifest_digest） |

## 2. 现在已用真实 API + 真实四角色跑通的环节（隔离 PG `ybt_iso_phase4_synthetic`）

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

## 3. 本轮新增尝试：冻结 Word/Excel —— 被真实门禁阻断（未取得正向证据）

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
3. **变更复核**：返回 409「变化依据已更新，请先复核」——语义正确（旧依据已变），但未取得**正向**通过证据。
4. **真实浏览器 UI 操作**：本轮走 API；F 系列浏览器验收仍待补。
5. **四角色矩阵 / 输入 manifest / 证据清单**逐行填写（`docs/upgrades/2026-10-03/w11/`）未做。
6. **第五阶段**（版本化评测数据集与复核、完整备份恢复、真实多 worker 故障恢复与容量基线）未开始。

## 5. 结论

P5 修复让第四阶段的**技术闭环**（材料→账号→需求→套件→轮次→Finding→双签→冻结证据）在隔离环境
以真实角色跑通并通过全部 16 项检查；**业务内容闭环**（41 项 readiness → 冻结正式 Word/Excel）
因合成业务内容尚未填写而**未完成**，已给出可执行路径。
