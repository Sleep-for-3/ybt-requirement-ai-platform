# 第四阶段（第七次更新）：**Finding 整改重测 + 四角色签署 + 变更复核全部闭环** —— 41/41 通过

本轮（2026-10-05）补齐了任务书要求但此前未真实走过的三项，**结果：`{"ok": true, "steps": 41}` / `EXIT=0`**（上轮 28/28）。

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
| `script_v2_uploaded` | 上传同源脚本 **v2**（新增注释），新旧版本并存，旧依据文件本身不变 |
| `change_impacts_listed` | `200`，`count=1`，检出变更：`script:1 脚本 … 已变化或停用（frozen v1 → current v2）` |
| **`change_review_opened`** | **201** —— 变更复核开启，`change_hash=13840fa78689335e…` |
| `change_review_detail` | `recheck_id=1`，`status=pending`，已生成 **1 个复核任务** |
| **`uat_finding_created`** | **201** —— Finding #2（`data` / `high`，指派技术分析） |
| **`uat_finding_resolved`** | **200**，`status=resolved` |
| **`uat_finding_verified`** | **200**，`status=verified` —— **整改重测闭环成立** |
| **`uat_signoff_chain_completed`** | `project_manager` + `final_acceptance` 均签署成功 |
| **`uat_signoff_all_four_approved`** | **`[business_owner, final_acceptance, project_manager, technical_owner]`** —— **四角色齐全** |
| **`change_review_closed`** | **`status=reviewed`**，`replacement_content_version=26` |
## 2. 本轮新解决的障碍（均为实证定位）

11. **Finding 需真实失败/缺陷才能建**：`finding_type` 枚举不含 `data_mismatch`（合法值为
    `functional/data/document/workflow/security/performance/usability/deployment/other`），
    `severity` 为 `critical/high/medium/low`。我先前两个自造值均被 422 拒绝。
12. **verify 不是审核人的权限**：`/uat-findings/{id}/verify` 要求 `uat.finding.manage`，
    审核角色不持有；用 `project_manager` 才得到 200。
13. **`revise` 返回的是“修订文档”而非需求对象**：`content_version` 嵌在 `revision.content_version` 下
    （我起初按顶层取，KeyError）。
14. **重绑依据必须重新预览**：用旧 `preview_hash` 重绑得 409「解析事实与单元数据已变化，请重新预览」。
15. **顺序不能颠倒**：制度对照会重写 `policy_snapshot`（属 basis），**先确认路径再对照**必然失效；
    正确顺序是 **对照 → 路径 → 关闭**。
16. **我造的 v2 脚本一度不可解析**：尾部追加裸注释使解析器报 “No expression was parsed” 并置为
    `partially_parsed`，导致下游路径确认全部 409。改为扩展 WHERE 谓词（语义等价且可完整解析）。
    注：生成器输出是 `... IS NOT NULL\nGROUP BY ...;`，所以替换目标必须是**谓词**而不是分号 ——
    写错会得到与 v1 完全相同的字节，被入库去重，根本没产生漂移。已加 `assert` 防回归。
17. **变更复核的状态不由 `/resolution` 翻转**：`/resolution` 只绑定替代修订；真正闭需
    `review_recheck`，它只经**治理工作流任务审批**可达，且**拒绝作者本人** —— 因此必须由
    另一位用户（技术审核）批准该任务，之后 `status` 才变为 `reviewed`。

9. **变更复核不可凭空开启**：`create_recheck` 会把入参哈希与**服务端** `impact_summary` 比对，
   而 `impact_summary` 仅在 `script_basis_changes` 检出漂移时才返回结果 —— 所以“自己造一个 change_hash”
   必然被 409「变化依据已更新」拒绝（此前多轮就是这样卡住的）。**修复**：先上传**同源脚本 v2**
   触发可检测的版本漂移，再从 `GET .../change-impacts` 取**服务端**哈希提交复核。
10. **我写错了一处验收断语**：最初断言导出头的 `X-Requirement-Snapshot-Hash` 应等于提审 `content_hash`，
   实测不等。阅读 `load_formal_delivery` 后确认导出头是**快照 hash**（含 `formal_delivery` 块），
   与提审哈希**按设计不同**。已改为验证“两种格式头部相等且稳定”——这是**纠正错误断言**，不是放宽测试。

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

> 第 1–10 项为前几轮已解决的同类障碍，均为 fixture 必须满足的真实契约，不是产品缺陷。

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
第四阶段的**业务闭环已完整跑通**（`{"ok": true, "steps": 41}` / `EXIT=0`）：
合成材料 → 6 个角色账号 → 需求与内容版本 → 目录/模板/脚本固定输入 → 脚本依据与路径确认 →
制度对照 → **readiness 清零** → 提审 → **三级独立审核** → **冻结正式交付** → **导出 Word/Excel** →
**变更复核开启** → **Finding 创建/整改/复核** → **四角色 UAT 签署齐全** →
**变更复核关闭**（`status=reviewed`，替代修订 v26）。
唯一剩余的是银行侧真实输入与签署人。
