# 第四阶段（第五次更新）：**正式交付闭环打通** —— readiness 清零、24/24 全通过

本轮（2026-10-05）继续 W11 固定输入链，完成了上一轮列为“下一轮可执行路径”的全部剩余步骤：
**readiness 由 12 降至 0**，并首次跑通 **提审 → 三级审核 → 冻结正式交付 → 导出 Word/Excel**。

脚本：`docs/upgrades/2026-10-05/phase4_w11_fixed_input.py`（N13 守卫先于任何 DDL）
前置：`phase4_synthetic_uat_closed_loop.py` 建立已知状态
**结果：`{"ok": true, "steps": 24}` / `EXIT=0`**
## 1. 链路与逐步证据

| 步骤 | 结果 |
| --- | --- |
| `catalog_metadata_seeded` | 建立 `DataSource`/`CatalogSchema`/`CatalogTable`/`CatalogColumn` |
| `template_version_ready` | `TemplateVersion` + `parsed_snapshot_json`（含监管表码）+ 回填 `current_version_id` |
| `script_ingested` | 合成源脚本解析成功 |
| `lineage_nodes_resolved` | **`unresolved=[]`，`with_catalog=7`** |
| `script_basis_confirmed` | 201，`bindings=8` |
| `paths_confirmed` | **201** |
| `normative_document_seeded` | 合成监管条款（`regulatory_formal`）+ 活跃版本 + `current_version_id` |
| `requirement_policy_document_attached` | 制度文档挂到需求范围（否则 `policy_snapshot` 为空） |
| `policy_comparison_confirmed` | **201**，10 条脚本规则全部关联到制度单元 |
| `paths_reconfirmed` | **201**（制度对照改变了 basis_hash，需按新依据重确） |
| **`review_readiness_after_fixed_input`** | **`blocking_count=0`** |
| `formal_review_submitted` | 201，`content_version=22`，`content_hash` 已记录 |
| `review_tasks_listed` / `review_chain_approved` | 3 个步骤 **业务 → 技术 → 终审** 全部通过 |
| `formal_delivery_finalized` | **201**，冻结交付（`content_version=22`、`content_hash` 与提审一致、`file_hash` 已生成） |
| `frozen_formal_delivery_binds_version` | **ok=true** —— 正式交付绑定同一版本与 hash |
| `frozen_formal_export_xlsx` / `_docx` | 均 **200**（16,885 / 39,237 字节） |
| `formal_export_identities_agree` | **ok=true** —— Word 与 Excel 快照 hash 完全一致 |
## 2. 本轮新解决的四个障碍（均为实证定位）

5. **制度文档未被需求选中**：`policy_snapshot.allowed.document_ids` 取自**需求范围**，而需求创建时
   `document_ids=[]` → `normative_units` 为空，`missing_basis` 永远清不掉。**修复**：把制度文档
   挂到需求范围（真实流程即 `PUT /requirements/{id}` 重新声明固定输入）。
6. **制度版本不可见**：`governed_unit_predicates` 要求 `lifecycle_status="active"` **且**
   `KnowledgeDocument.current_version_id` 指向该版本；否则单元对对照不可见。**修复**：fixture 补齐这两个关联
   （同时补上 `KnowledgeDocumentVersion` 必填的 `file_name`/`parse_status`）。
7. **对照后 basis_hash 变化**：确认对照会重写 `policy_snapshot`（属 basis 一部分）→ 先前
   `confirmed_path` 失效，readiness 报 `{field}:path:0`。这是**正确的产品语义**，
   **修复**：对照后按新依据**重新确认路径**（`paths_reconfirmed` 201）。
8. **正式交付需完整审核链**：`finalize_formal_delivery` 要求 `requirement_document_review` 工作流
   `status == approved` 且 `submission.status == approved`；直接 finalize 会得到 409
   “送审记录尚未通过完整审核”。**修复**：显式走完 3 个审核步骤（业务→技术→终审）。

> 上一轮的四个障碍（目标列不足 / 上游元数据缺失 / 标识符不一致 / 模板漂移误判）已在本轮继续有效；
> 全部八项都是**合成 fixture 必须满足的真实契约**，不是产品缺陷。

## 3. 正式交付的可核对细节

| 项 | 值 |
| --- | --- |
| 提审 `content_version` | 22 |
| 提审 `content_hash` | `933c2b4d0d1c2699…` |
| 冻结交付 `content_version` | 22（与提审**一致**） |
| 冻结交付 `content_hash` | `933c2b4d0d1c2699…`（与提审**一致**） |
| 冻结交付 `file_hash` | `9adbb8daaadfe0d8…` |
| 导出 xlsx / docx | 16,885 / 39,237 字节，均 200 |
| 导出快照 hash | 两种格式**完全相同**（`94f9bff0539b6c8c…`） |

> **一项契约澄清**：导出响应头 `X-Requirement-Snapshot-Hash` 是 `content_digest(row.content_json)`，
> 即**快照 hash**（包含 `formal_delivery` 块），与提审的 `content_hash` **按设计不同**。
> 我最初的断言写成“两者应相等”，经阅读 `load_formal_delivery` 的校验逻辑后修正为：
> 两种格式的头部必须相等且稳定，`content_version`/`content_hash` 的绑定由冻结交付本身保证。
> （这是**修正错误断言**，不是放宽测试。）

## 4. 未达成 / 待验收条件

1. **真实银行制度条款、真实源脚本、真实数据目录**未接入；本轮全部为合成 fixture。
2. 未在真实浏览器逐项点击该链路（本轮走 API；浏览器验收仍受“项目无数据”限制）。
3. 四角色矩阵 / 输入 manifest / 证据清单逐行填写仍未做。
4. 本轮未在业务库应用迁移 `202610050001`/`202610050002`；本地后端仍为旧进程。

## 5. 结论
第四阶段的**业务闭环已完整跑通**：合成材料 → 6 个角色账号 → 需求与内容版本 → 目录/模板/脚本固定输入 →
脚本依据与路径确认 → 制度对照 → **readiness 清零** → 提审 → **三级独立审核** → **冻结正式交付** →
**导出 Word/Excel**（快照 hash 一致）。`{"ok": true, "steps": 24}` / `EXIT=0`。
唯一剩余的是银行侧真实输入与浏览器逐项验收。
