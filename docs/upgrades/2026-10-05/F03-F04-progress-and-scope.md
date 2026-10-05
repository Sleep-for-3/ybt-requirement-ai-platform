# F03 / F04：当前需求进度口径与历史生成范围

本轮（2026-10-05）前端工作包之二，对应复核项 **F03（P1）** 与 **F04（P1）**。

## 1. F03：需求进度仍读共享整表，不能代表当前需求

**问题（修复前）**：`RequirementWorkspace` 在需求模式下已经构建了**当前需求独立文档**的 `records`
（`:122-125`），但传给 `requirementProgress` 的仍是 **`projection?.records`（共享整表）**（`:298`），
并用该结果驱动 `StepBar` 的“AI 口径分析 / 人工校核与导出”完成态（`:310`）。于是：

- 共享整表 8 个字段都有旧口径、当前需求只选 2 个字段且正文未完成时，可能显示**整表 8/8 已完成**；
- 反过来当前需求 2/2 已完成、整表另外 6 个为空时，显示**未完成**；
- 一个字段只有业务 final 也会被计为“双层口径完成”。

复核证据：`docs/reviews/2026-10-04/frontend-followup-review.md` §F03。

**改动**：
- 进度来源改为**当前需求模式用 `records`（当前需求独立文档），共享模式用 `summaryRecords`**：
  ```tsx
  const progressRecords = requirement ? records : summaryRecords;
  const progressScope: "requirement" | "shared" = requirement ? "requirement" : "shared";
  const progress = requirementProgress(progressRecords);
  ```
- `StepBar` 新增 `scope` 属性，并在步骤条下方**显式标注进度口径**：
  需求模式显示「当前需求范围」，共享整表模式显示「共享整表模式（计数覆盖该表全部字段）」，
  不再让两种语义共用一个未标注的数字。

## 2. F04：复用历史生成范围后，显示范围与实际请求不一致

**问题（修复前）**：`applyRoundScope` 只用 `if(scope.business)setBusiness(true)` / `if(scope.lineage)setLineage(true)`
——**只打开、不关闭**；而初始 `business`/`lineage` 都是 `true`，所以复用“仅业务”的历史轮次后技术勾选仍然打开。
另外点击“全部字段 / 当前字段”只 `setMode(...)`，**不清除 `scopeOverride`**（`:156-157`），
于是界面显示“当前字段”，POST 仍发送历史轮次的 1、2 号字段；生成按钮又按 `fieldIds` 而非
`effectiveFieldIds` 判断范围（`:160`）。属于错范围生成，影响模型费用与后续审阅内容。

复核证据：`frontend-followup-review.md` §F04（`RequirementGenerationPanel.tsx:99-101`、`:93`、`:156-157`、`:110-111`、`:160`）。

**改动**：
- `applyRoundScope` 改为**精确还原**：`setBusiness(scope.business)`、`setLineage(scope.lineage)`（true/false 都写），
  并把 `setMode("scope")` 固定下来；提示文案同时列出业务/技术勾选状态。
- 两个范围按钮（全部字段 / 当前字段）在切换时**清除 `scopeOverride`**，避免旧 override 静默生效。
- 生成按钮的禁用条件改用 **`effectiveFieldIds`**（与实际 POST 一致）。
- 按钮下方新增**提交预览**：`将生成 N 个字段 · 业务口径 + 技术溯源`（按历史轮次范围时追加标注），
  使界面范围与 POST 参数可见地一致。

## 3. 验证（本轮已完成）

```
cd frontend
<node> node_modules/typescript/bin/tsc --noEmit --incremental false   → exit 0
<node> --test tests/*.test.mjs                                        → 253 passed / 0 failed
<node> node_modules/next/dist/bin/next lint --no-cache                → exit 0
<node> node_modules/next/dist/bin/next build                          → exit 0（重建后前端已重启，/login 200）
```

### 真实浏览器（Chrome DevTools MCP，隔离于运行实例的只读观测）

| 检查 | 结果 |
| --- | --- |
| F10 折叠/展开入口可达（500px 宽） | 点击「收起」后按钮变为「展开」，**仍可见可点**（`visible=true`、`stillClickable=true`）——修复前该宽度下按钮会随容器隐藏 |
| F03 进度口径标注 | 未选需求（共享整表模式）时页面显示「进度口径：共享整表模式（计数覆盖该表全部字段）」，与数据来源一致 |
| 页面渲染 | `/workspace?projectId=5` 正常渲染，无未捕获异常 |

## 4. 未验证 / 边界（不得当作通过）

1. **F01 取消切换的“点击→弹窗→取消”真实交互尚未实测**：项目 5 当前只有「新建需求」一个选项，
   无法在不向业务库写入测试需求的前提下构造“同表同场景的两个需求”。
   复现步骤（隔离/合成数据集上执行）：
   ① 打开需求 A 并在正文做未保存修改；② 左侧选择需求 B；③ 在确认框点“取消”；
   ④ 断言：需求下拉、名称、字段范围、正文、两个 dirty 标志**全部仍为 A**；⑤ 点“确认”后一次性变为 B。
2. **F05 三处表单的成功/失败提示未实测**：创建用户/机构/集市表属业务库写入，按既有授权边界不在本轮执行。
   需在隔离环境验证“成功只创建一次、表单清空、失败保留输入”。
3. F02、F06、F07、F08、F09 尚未实施（Skill/全局 dirty 登记、草稿恢复入口、错误缓存、
   引用定位、指标解释）。
