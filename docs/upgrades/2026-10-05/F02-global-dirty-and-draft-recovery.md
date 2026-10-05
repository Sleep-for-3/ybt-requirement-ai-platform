# F02：Skill 编辑器接入全局未保存保护并提供草稿恢复入口

本轮（2026-10-05）前端工作包之三，对应复核项 **F02（P1）**。

## 1. 问题（修复前）

全产品只有需求工作区调用了 `useUnsavedChanges`（`RequirementWorkspace.tsx:66-67`）。Skill 编辑页虽然计算了 `dirty`
（`page.tsx:121`），但只做两件局部的事：把 dirty 通过 `onLockedChange` 锁住本页的能力选择（`:123`），
以及自己挂一个 `beforeunload`（`:124-129`）。因此：

- 编辑 Skill 草稿后点击侧栏其它页面（普通 SPA 链接）或**顶栏切换项目**，新离开保护**看不到** Skill 的 dirty；
- `beforeunload` **不会**因客户端路由切换触发，所以“存在 beforeunload”不等于“不存在丢失风险”；
- `lib/unsaved-changes.mjs` 的 `saveDraft/readDraft/clearDraft` 只被测试调用，**产品里没有任何保存/恢复入口**，
  即 W06 曾承诺的“本地草稿恢复”实际未交付。

复核证据：`docs/reviews/2026-10-04/frontend-followup-review.md` §F02。

## 2. 改动

`frontend/app/ai-control/skills/page.tsx`：

1. **接入共享 dirty 登记**：`useUnsavedChanges(\`skill-editor:${project_id}:${institution_id}:${skill_key}\`, dirty)`，
   与需求工作区使用同一注册表，因此顶栏项目切换（`ProjectContext.confirmLeave`）与应用内链接守卫
   （捕获阶段 click 监听）都能看到 Skill 的未保存状态。
2. **真实草稿持久化**：dirty 时按 `(scope_type, project_id, institution_id, skill_key)` 为键写入
   `window.localStorage`，载荷为 `{ content, basedOnVersionId }`（使用既有 `saveDraft(storage, scope, payload)`）；
   保存成功后 `clearDraft`，草稿不再是恢复候选。
3. **恢复/丢弃入口**：读取到草稿且当前不脏时，在编辑区顶部显示提示条，含草稿时间与**基线版本**；
   - 若草稿的 `basedOnVersionId` 与当前 `active.id` 不同，明确提示「该草稿基于其他版本，恢复前请核对基线」——
     **不静默覆盖**较新的服务端内容；
   - 提供「恢复草稿」「丢弃草稿」两个按钮，均受 `busy`/`readOnly` 约束。

## 3. 验证（本轮已完成）

```
cd frontend
<node> node_modules/typescript/bin/tsc --noEmit --incremental false   → exit 0
<node> --test tests/*.test.mjs                                        → 253 passed / 0 failed
<node> node_modules/next/dist/bin/next lint --no-cache                → exit 0
```

说明：`lib/unsaved-changes.mjs` 的 `saveDraft/readDraft/clearDraft`（含配额与损坏数据不抛错）已有 8 例既有单测
（`tests/unsaved-changes.test.mjs`），本轮首次由**产品代码**真实调用；签名按 `.d.mts` 声明
`(storage, scope, payload)` / `(storage, scope)` 使用。

## 4. 未验证 / 边界（不得当作通过）

1. **真实浏览器交互未实测**：需要验证「编辑 Skill → 点侧栏链接 → 弹确认 → 取消后仍停留且草稿保留」、
   「刷新后出现恢复提示条 → 恢复/丢弃」、「切换项目时的确认」三条路径。本机项目 5 无可用 Skill 编辑数据，
   未在运行实例上写入业务数据；应在隔离/合成环境执行。
2. 草稿按 `localStorage` 存储，**未按用户隔离**（同一浏览器多账号会共用键）。当前键包含 scope_type/project/
   institution/skill_key，未包含 user id；如需多用户隔离需在同一键上追加用户标识（待确认优先级）。
3. F06–F09 尚未实施（错误缓存、引用定位、UAT 版本绑定、指标解释）。
