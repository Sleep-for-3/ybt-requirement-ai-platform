# C02（P1）：Skill 草稿的账号隔离

基线 `fd7a532`。本项修复“不同账号在相同范围能读到同一份本地草稿”。

## 1. 修复前证据（复现）

评审复现产物 `docs/reviews/2026-10-06/frontend-state-reproduction.json`：

```json
{"actorless_draft": {
  "actor_a": 17, "actor_b": 18,
  "actor_a_key": "skill-draft:project:11:none:requirement_candidate_generation",
  "actor_b_key": "skill-draft:project:11:none:requirement_candidate_generation",
  "actual_read_by_actor_b": "A unsaved private content",
  "note": "Actual key expression and actual draft helpers; UI readDraft/pendingDraft path verified statically.",
  "reproduced": true}}
```

A 与 B 的 key **逐字相同**，因此 B 能读到 A 未保存的私有正文。

## 2. 根因

- `frontend/app/ai-control/skills/page.tsx:127` 的 key 只含 `scope_type/project/institution/skill_key`，**不含账号**；
- `frontend/lib/unsaved-changes.mjs` 的 `draftKey/saveDraft/readDraft/clearDraft` 都没有 actor 概念，
  读回时也不校验归属，因此任意账号写入的草稿都会被下一个登录者当成“自己的草稿”提示恢复。

## 3. 修改文件

| 文件 | 改动 |
| --- | --- |
| `frontend/lib/unsaved-changes.mjs` | `draftKey(scope, actorId)` 生成 `draft:actor:{id}:{scope}`；**未取得身份时返回 `null`**；`saveDraft` 在载荷中写入 `owner`；`readDraft` 校验 `owner` 与当前 actor **严格相等**，否则返回 `null`（含无 owner 的历史草稿）；`clearDraft` 同样按 actor 命名空间 |
| `frontend/lib/unsaved-changes.d.mts` | 同步新签名（含 `DraftActorId` 与返回 `string \| null`） |
| `frontend/app/ai-control/skills/page.tsx` | `actorId` 取自服务端 `/ai-skills/permissions` 的 **`capabilities.actor_id`**（可信登录用户 ID，非本地可伪造值）；key 内嵌 actor；未取得身份时**完全不读写草稿**；“丢弃草稿”也按 actor 清理 |
| `frontend/tests/unsaved-changes.test.mjs` | **新增 3 项 C02 回归**（无身份、跨账号、无 owner 历史草稿），并把原有草稿用例升级为带 actor |

## 4. 修复后证据

同一份测试在**修复前源码**与**修复后源码**上的对比（`git stash` 临时还原产品文件）：

| 用例 | 修复前 | 修复后 |
| --- | --- | --- |
| C02 未取得身份时不读写草稿 | ✖ | ✔ |
| C02 不同账号在相同范围互不可见 | ✖ | ✔ |
| C02 无 owner 的历史草稿不被自动归属 | ✖ | ✔ |
| 原有草稿保存/读回/清除（升级签名后） | ✔ | ✔ |
| 其余既有用例（脏登记、链接守卫等） | ✔ | ✔ |
| **合计** | **9 passed / 3 failed** | **12 passed / 0 failed** |

命令与环境：
```
cd frontend
<node> --test tests/unsaved-changes.test.mjs                  → 12 passed / 0 failed
<node> node_modules/typescript/bin/tsc --noEmit ...            → exit 0
```
环境：隔离（内存 storage 替身，**无真实浏览器存储、无后端**）。

## 5. 覆盖范围核对（任务书要求“检查其他本地业务草稿”）

| 键 | 用途 | 是否含业务内容 | 处理 |
| --- | --- | --- | --- |
| `draft:skill-draft:...`（旧） / `draft:actor:{id}:skill-draft:...`（新） | Skill 编辑器正文 | **是** | 本项修复 |
| `ProjectContext` 的 `STORAGE_KEY` | 记住上次所选**项目 ID** | 否（UI 偏好，无业务正文） | 不需隔离 |
| `GlobalSearch` 的 `recentKey(projectId)` | 最近搜索词 | 否（无业务正文） | 不需隔离 |

即：产品中唯一承载**未保存业务正文**的本地草稿就是 Skill 草稿，已隔离。

## 6. 验证边界（未验证项）

1. 未做**真实浏览器**双账号手工验证（本轮为真实 helper + 真实 key 表达式 + 真实页面调用链的静态核对）；
2. 未验证跨设备/跨浏览器的一致性（`localStorage` 本就按浏览器隔离）；
3. 未做**旧版草稿的迁移**：升级前写入的无 owner 草稿会被忽略（**有意为之**，避免误归属），
   用户会看到“无可恢复草稿”，需重新编辑；
4. 未覆盖 `actor_id` 从服务端缺失时的 UI 提示（当前行为是静默不提示草稿）。
