# VNEXT Phase5 — 需求工作台前端只读审计

- 审计日期：2026-10-21
- HEAD：`7495676`（docs(交付): 交付物同步 D 包结果，全量回归更新为 1886 passed）
- 范围：`frontend/components/requirement-workspace/` 与前端需求页面（挂载点 `frontend/app/workspace/page.tsx`）
- 性质：只读审计，未修改任何源码/测试
- 状态口径：**IMPLEMENTED**（代码存在且链路闭合）/ **TESTED_MOCK**（仅有 mock 或 harness 级测试）/ **UNVERIFIED**（无法在本环境验证，如浏览器验收）/ **BLOCKED**（缺依赖或环境不可用）

---

## 1. 主流程连通性

挂载：`frontend/app/workspace/page.tsx:1` `import { RequirementWorkspace }`，`:4` `return <RequirementWorkspace />`。页内 Tab 定义于 `frontend/components/requirement-workspace/RequirementWorkspace.tsx:63`：`"structured" | "lineage" | "evidence" | "questions" | "document"`。

| 环节 | 组件（file:line） | 前端 API 调用（file:line） | 后端端点（backend/app/api/file:line） | 状态 |
|---|---|---|---|---|
| 查看需求/范围 | `RequirementWorkspace.tsx:344` → `RequirementScopePanel.tsx` | `RequirementWorkspace.tsx:82` `workspaceProjectionOptions(...)` | `requirement_workspace.py:46` GET `/projects/{project_id}/requirement-workspace` | IMPLEMENTED |
| 字段明细 | `RequirementWorkspace.tsx:397` → `DocumentPreview.tsx:37` | `RequirementWorkspace.tsx:89` `apiGet`（document 投影） | `requirements.py:595` GET `/requirements/{id}/document` | IMPLEMENTED |
| 字段详情 | `DocumentPreview.tsx:7` → `SelectedFieldEditor.tsx` | `SelectedFieldEditor.tsx:7` `apiPut` | `requirements.py:681` PUT `/requirements/{id}/fields/{field_id}` | IMPLEMENTED |
| 来源映射 | `DocumentPreview.tsx:8` → `RequirementLineagePanel.tsx` | `RequirementLineagePanel.tsx:21` `useQuery`、`:26` `fixed` | `requirements.py:699` GET `/revisions/{v}/lineage` | IMPLEMENTED |
| 证据查看 | `EvidenceDrawer.tsx:19`（`open/items/loading/error`） | `RequirementWorkspace.tsx:434` `evidenceQuery`（projection evidence） | `requirement_workspace.py:96` GET `/requirement-workspace/fields/{field_id}/evidence` | IMPLEMENTED |
| 确认规则（对照） | `RequirementPolicyPanel.tsx:20` | `RequirementPolicyPanel.tsx:23-24` `base=.../policy-comparison` | `requirements.py:226/:236` GET/POST policy-comparison | IMPLEMENTED |
| 修改候选 | `RequirementGenerationPanel.tsx:30` | `:34` base、`:130` retry、`:150/158` adopt/reject | `requirements.py:313` 建 run、`:349` 列 run、`:427` adopt、`:449` reject | IMPLEMENTED |
| 候选采用落库 | `RequirementGenerationPanel.tsx:150` | `apiPost(.../adopt)` 后 `runs.refetch()` | `requirements.py:427` | IMPLEMENTED |
| 复核 | `RequirementRecheckPanel.tsx:16` | `:21` rows、`:29` `rechecks/{id}/{kind}` | `requirements.py:68/:80` | IMPLEMENTED |
| 审核送审 | `RequirementDeliveryPanel.tsx:40` | `:55` base、`:68` readiness、`:73` submissions | `requirements.py:752` review-readiness、`:763` review-submissions、`:811` finalize | IMPLEMENTED |
| 导出（需求页） | `RequirementWorkspace.tsx:294-297` | `apiDownload('/projects/{pid}/requirements/{rid}/export')` | `requirements.py:920` GET `/requirements/{id}/export` | IMPLEMENTED |
| 导出（未建需求时） | `RequirementWorkspace.tsx:297` | `/target-tables/{tid}/export/traceability-workbook` | 见 `mapping_export`/traceability 路由 | IMPLEMENTED |
| 快照冻结 | `RequirementSnapshotsPanel.tsx:5` | `:29` refetch、`:48-51` 权限门 | `requirement_workspace.py:111/:155` | IMPLEMENTED |
| UAT 关联 | `RequirementUatPanel.tsx:7` | `:27` `apiPost(base,...)` | `requirements.py:144/:156` | IMPLEMENTED |

要点：
- 主链在代码层是**闭合**的：范围 → 文档投影 → 字段编辑 → 血缘 → 证据 Drawer → 规则对照 → 候选采用 → 送审/终审 → 导出的每个跳转都有对应的 `apiGet/apiPost/apiPut/apiDownload` 与后端路由。
- 导出前置校验：`RequirementWorkspace.tsx:294` `if (scopeDirty) { setError("请先保存需求说明后导出。"); return; }`，未保存时阻断导出（IMPLEMENTED）。
- 主流程无浏览器实测，端到端点击链路为 **UNVERIFIED**（见第 6 节）。
