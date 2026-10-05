# 第四阶段（第四次更新）：W11 固定输入打通 —— 路径确认成功，阻断 45 → 12

本轮（2026-10-05）按上一轮给出的可执行条件，实现了 **W11 固定输入链**，把此前"未跑通"的正式交付
前置条件从 **41 项阻断** 推进到 **12 项**，并首次让 **`paths_confirmed` 返回 201**。

脚本：`docs/upgrades/2026-10-05/phase4_w11_fixed_input.py`（新增，N13 守卫先于任何 DDL）
前置：先跑 `phase4_synthetic_uat_closed_loop.py` 建立已知状态（23/23 通过）

## 1. 链路与逐步证据

| 步骤 | 结果 |
| --- | --- |
| `catalog_metadata_seeded` | 建立 `DataSource`/`CatalogSchema`/`CatalogTable`/`CatalogColumn`（3 张表 × 全部需求字段列） |
| `template_version_ready` | `TemplateVersion`（含 `parsed_snapshot_json` 携带监管表码 `YBT_LOAN`，并回填 `TemplateDocument.current_version_id`） |
| `script_ingested` | 合成源脚本解析成功（节点/边已产出） |
| `lineage_nodes_resolved` | **`unresolved=[]`，`with_catalog=7`** —— 全部血缘节点解析到目录资产 |
| `requirement_located` | `requirement_id=1, content_version=17` |
| `script_preview_built` | `targets=1, rules=10, gaps=[]`（无缺口） |
| **`script_basis_confirmed`** | **`201`，`bindings=8`**（8 个需求字段全部绑定到脚本输出列） |
| `paths_preview` | `200`，issues **8**（此前 40） |
| **`paths_confirmed`** | **`201`** —— 路径人工确认成功，`content_version` 推进到 19 |
| `review_readiness_after_fixed_input` | `blocking_count=12`（此前 41 → 25 → 45 → **12**） |

## 2. 逐一解决的四个关键障碍（均为本轮实证定位）

1. **目标列不足**：原合成脚本只写 2 列，而需求有 8 个字段 → `path_preview` 对无法绑定的字段报
   "尚未确认目标字段或缺少字段级写入规则"。**修复**：脚本改为按需求 `field_code` **动态生成**，
   保证目标表写出全部 8 列。
2. **上游字段元数据缺失**：目录里只登记了部分列 → 报"缺少上游字段元数据：src_loan.cust_no"。
   **修复**：目录播种改为**按需求字段动态生成**列。
3. **标识符不一致**：`path_preview` 要求血缘节点与目录行的 `(database, schema, table)` 严格相等，
   而我的目录行带 `database_name="core"`、脚本无库名 → 仍报"缺少上游字段元数据：未标注.未标注.…"。
   **修复**：脚本改为 `public.<table>` 限定、目录行 `database_name=None`、`schema_name="public"`，两侧身份对齐。
4. **模板漂移误判**：`script_basis_changes` 认为模板已变化（返回"固定依据已变化，请先重新确认脚本依据"）
   → 原因是 `TemplateDocument.current_version_id` 未指向该版本。**修复**：fixture 回填该外键。

> 这四处都不是产品缺陷，而是**合成 fixture 必须满足的真实契约**；定位过程全部基于服务端返回码与
> 代码路径（不在报告里下"疑似"结论）。

## 3. 当前剩余 12 项阻断：全部收敛到"制度对照"

```
scope:script:0                 缺少依据：没有明确选择且当前有效的制度条款；脚本事实不能替代制度要求
scope:policy:missing_basis     缺少有效制度依据
scope:policy:rule:script-edge-1..10   制度条款与脚本规则的逐条对照尚未人工确认（每条规则一项）
```

对应 `requirement_policy_comparison.confirm_comparison`，入参契约为
`ConfirmPolicyComparison{expected_content_version, basis_hash, decisions[]}`，且需要
`knowledge.search` / `knowledge.manage` 权限（技术分析具备）。

**下一轮可执行路径**：
```
POST /api/projects/{p}/knowledge/documents/upload      # 录入合成监管条款（knowledge.manage）
GET  /api/projects/{p}/requirements/{r}/policy-comparison   # 取 basis_hash 与待对照规则
POST /api/projects/{p}/requirements/{r}/policy-comparison   # 逐条给 decisions
GET  /api/projects/{p}/requirements/{r}/review-readiness    # 期望 blocking_count=0
POST /api/projects/{p}/requirements/{r}/review-submissions  # 项目经理提审
POST .../review-submissions/{id}/finalize                   # 终审冻结
GET  .../formal-deliveries/{id}/export?format=docx|xlsx     # 冻结正式文件
```

## 4. 未达成 / 待验收条件

1. **正式交付（formal delivery）仍未跑通**：需先清零上述 12 项制度对照阻断。
2. **真实银行制度条款、真实源脚本、真实数据目录**未接入；本轮全部为合成 fixture。
3. 未在真实浏览器逐项点击该链路（本轮走 API；浏览器验收仍受"项目无数据"限制）。
4. 四角色矩阵 / 输入 manifest / 证据清单逐行填写仍未做。

## 5. 结论

W11 固定输入链**已打通到路径确认**（`script_basis` 201 + `paths` 201），阻断由 41 降至 **12**，
且剩余项**性质明确、契约明确、路径明确**（制度对照）。正式交付是**下一轮可完成后置**，本轮不冒充通过。
