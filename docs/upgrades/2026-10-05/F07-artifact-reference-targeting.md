# F07：需求/任务引用链接真正打开指定对象

本轮（2026-10-05）前端工作包之五，对应复核项 **F07（P2）**。

## 1. 问题（修复前）

`lib/artifact-links.mjs`：

- 需求引用只拼 `projectId` + `requirementId`（`:18-19`），**丢掉了 tableId/scenarioId**。
  工作区确实支持从 URL 恢复这两项（`RequirementWorkspace.tsx:151-157`：`positiveId("tableId")`、
  `positiveId("scenarioId")`），所以补上参数即可落到同一张表/同一个场景；不补则工作区会回落到
  投影默认值，操作者看到的是**另一个场景**的需求。
- `agent_task` 引用直接返回固定 `/agent`（`:47`），而智能体页的任务选择来自本地 `pickedTaskId`
  （`agent/page.tsx:97,112`，`activeTaskId = pickedTaskId ?? tasks.data?.[0]?.id`），**不读 URL**。
  结果：点“智能体任务 #99”打开的是**列表里最新的那个任务**，而不是 #99。

复核证据：`docs/reviews/2026-10-04/frontend-followup-review.md` §F07。

## 2. 改动

`frontend/lib/artifact-links.mjs`：

- `artifactRefHref(refType, refId, projectId, context?)` 新增第 4 个参数（可选上下文）：
  - `requirement`：在 `projectId`/`requirementId` 基础上，当 `context.tableId`/`scenarioId` 为正整数时
    追加 `tableId`/`scenarioId`；缺省时行为与原来一致（向后兼容）。
  - `agent_task`：改为 `/agent?projectId={p}&taskId={id}`（无 projectId 时 `/agent?taskId={id}`）。
  - `target_field` 与“无直接页面”的类型保持不变（宁可不链也不拼错）。
- `artifactCompleteness` 的可链接性判定同步传入 `artifact.ref_context`。

`frontend/app/agent/page.tsx`：

- `pickedTaskId` 的初值改为**从 URL 的 `taskId` 读取**（校验为正整数），使链接真正恢复指定任务；
  用户手动点选仍然覆盖它。
- 产物卡片渲染处把 `artifact.ref_context` 传给 `artifactRefHref`。

`frontend/lib/artifact-links.d.mts`：声明同步（`artifactRefHref` 增加第 4 参数、`artifactCompleteness`
入参增加 `ref_context`），保持类型声明覆盖测试通过。

## 3. 验证（本轮已完成）

```
cd frontend
<node> node_modules/typescript/bin/tsc --noEmit --incremental false   → exit 0
<node> --test tests/*.test.mjs                                        → 253 passed / 0 failed
<node> --test tests/type-declaration-coverage.test.mjs                → 1 passed
<node> node_modules/next/dist/bin/next lint --no-cache                → exit 0
```

`tests/artifact-links.test.mjs` 增补 4 条断言（新的 `tableId/scenarioId` 组合、`scenarioId=0` 不追加、
`agent_task` 带/不带 projectId），原先断言“`agent_task` → `/agent`”的旧契约已按新语义更新（不是删除断言）。

## 4. 未验证 / 边界（不得当作通过）

1. **真实浏览器点击未实测**：需要智能体任务产物与需求引用实际存在，才能点击验证“落到指定任务/指定场景”。
   本轮未向业务库写入数据。
2. **`ref_context` 的来源**：前端已支持该字段，但**后端产物响应目前是否返回 `ref_context` 未核实**；
   若后端不返回，需求链接仍会缺少 tableId/scenarioId（退化为修复前行为，不会更糟）。
   待办：核对 `/agent/tasks/{id}` 的 artifact 结构，必要时在服务端补充该上下文。
3. 未新增“跨版本引用”提示：若需求修订已过期，链接仍指向工作区当前内容，未额外提示版本差异。
