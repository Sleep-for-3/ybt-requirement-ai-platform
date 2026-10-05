# F01 / F05 / F10：前端人工编辑与集成修复（第一批）

本轮（2026-10-05）前端工作包之一，对应复核项 **F01（P1）**、**F05（P1）**、**F10（P2）**。

## 1. F01：取消需求切换后左右状态错配

**问题（修复前）**：`RequirementScopePanel.choose()` 在调用 `onSelect` **之前**就写入了自己的
`selected/name/objective/background/date/inclusion/exclusion/ids/dirty` 并 `onDirty(false)`；
而统一决策（`scopeDirty`/`editorDirty` 确认）在**父组件** `selectRequirement` 里。用户在“当前字段有未保存修改”
的确认框上点**取消**时，子面板已切到需求 B，父级 `requirement` 与正文仍是 A —— 左右错配。
复核证据：`docs/reviews/2026-10-04/frontend-followup-review.md` §F01（`RequirementScopePanel.tsx:27`、
`RequirementWorkspace.tsx:213-221`、`:184`）。

**改动**：
- `RequirementScopePanel` 新增 `confirmSwitch?: () => boolean` 属性：`choose()` **第一件事**就是调用它，
  返回 false 立刻 `return`，**任何子状态变更都不发生**（`busy` 检查之后、`restored.current` 之前）。
- `onSelect` 签名扩展为 `(scope, options?: { userSwitch?: boolean })`；面板切换成功时传
  `{userSwitch: true}`，表示“决策已通过”，父级不再重复弹窗。
- `RequirementWorkspace` 抽出**唯一决策函数** `canLeaveCurrentEdits()`（先问 scope dirty，再问 editor dirty），
  同时供面板 `confirmSwitch` 与内部切换使用；`selectRequirement` 在 `userSwitch` 路径只做状态落地，
  否则先 `canLeaveCurrentEdits()` 再落地。

**效果**：取消时需求 ID、名称、字段范围、正文、两个 dirty 标志**全部保持 A**；确认时一次性切到 B；
范围与正文同时 dirty 时也只按顺序各问一次，不会出现重复放弃确认。

## 2. F05：三处异步表单的 `event.currentTarget`

**问题（修复前）**：`admin/users`、`admin/institutions`、`mart` 三处在 `await apiPost(...)` **之后**
执行 `event.currentTarget.reset()`。React 在事件派发结束后会清空 `currentTarget`，因此重置**静默失效**
（也可能抛错），服务端已创建成功但表单未清空、后续刷新/关闭被跳过、用户重试会得到重复对象错误。
（`model-profiles` 早已按 B10 修好，这三处漏修。）

**改动**：三处均在**第一个 await 之前**捕获 `const formElement = event.currentTarget`，`FormData` 与
`reset()` 都改用该局部节点。

## 3. F10：移动端折叠后无法再展开

**问题（修复前）**：唯一的收起/展开按钮位于 `inputPanelOpen ? "min-w-0" : "hidden lg:block"` 容器**内部**。
窄于 `lg` 时点击“收起”会把包含“展开”按钮的整个容器隐藏，用户**无法恢复**。
复核证据：`frontend-followup-review.md` §F10（`RequirementWorkspace.tsx:315`、`:318-320`）。

**改动**：左侧列改为**单一网格子节点** `<div className="min-w-0">`，其中**表头（含切换按钮）永不可隐藏**，
只有面板**内容**随状态切换 `hidden`。列布局（`lg:grid-cols-[minmax(280px,340px)_minmax(0,1fr)]`）保持
两个子节点，因此桌面双栏不变；任何宽度下都能连续折叠/展开。

## 4. 验证（本轮已完成）

```
cd frontend
<node> node_modules/typescript/bin/tsc --noEmit --incremental false   → exit 0
<node> --test tests/*.test.mjs                                        → 253 passed / 0 failed
<node> node_modules/next/dist/bin/next lint --no-cache                → exit 0
```

## 5. 未验证 / 边界（不得当作通过）

1. **真实浏览器交互尚未执行**（复核明确要求“不能只用 helper 单测关闭问题”）：取消切换的“点击→弹窗→取消”
   实际行为、390/768/桌面三档连续折叠恢复、三处表单的成功/失败提示，均需在真实浏览器中逐项确认。
   本机此前无 Playwright 浏览器；本轮已具备 Chrome DevTools MCP 通道，列为下一步待办。
2. F02、F03、F04、F06、F07、F08、F09 尚未实施（dirty 全局登记、草稿恢复入口、当前需求进度、
   历史范围、错误缓存、引用定位、指标解释）。
