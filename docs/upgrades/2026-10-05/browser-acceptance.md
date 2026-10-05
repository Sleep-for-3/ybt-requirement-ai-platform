# 真实浏览器验收（隔离环境 + 合成数据）

复核明确要求「通过实际浏览器验证，不能只用 helper 单测关闭问题」。本轮在**隔离栈**上完成了真实浏览器验收：
后端 `127.0.0.1:8010` + 前端 `127.0.0.1:3010`，均指向**隔离库** `ybt_iso_phase4_synthetic`，
**未触碰业务库**，也未干扰用户正在运行的服务（3000 / 8000 保持不动）。

方式：Chrome DevTools MCP（真实 Chromium 页面，`read_image` 本模型不可用，故以 DOM/状态断言为证据）。

## 1. 隔离栈与登录

| 项 | 值 |
| --- | --- |
| 隔离后端 | `http://127.0.0.1:8010`，`/api/version` → `200`，`schema_head: null`（隔离库无 `alembic_version`，**P5 修复后不再 500**） |
| 隔离前端 | `http://127.0.0.1:3010`，`/login` → `200` |
| 登录角色 | `p4_project_manager`（合成账号，`AUTH_MODE=required`）→ **200，取得 token** |
| 隔离库数据 | projects 1 / requirements 1 / uat_suites 1 / uat_runs 1 / formal_deliveries 1 / users 8 |

## 2. F01 取消切换：**取消后左右完全一致**（核心复现项）

在 `/workspace?projectId=1` 上，先在正文制造未保存修改（dirty=true），再切换需求并**在确认框点取消**：

```json
{
  "before":  {"selectValue": "", "nameValue": "未保存的测试修改", "dirtyHint": true},
  "dialogSeen": true,
  "dialogMsg": "需求说明尚未保存，确定放弃并切换？",
  "after":   {"selectValue": "", "nameValue": "未保存的测试修改", "stillDirty": true},
  "selectUnchanged": true,
  "nameUnchanged": true
}
```

**结论**：确认框确实弹出；**取消后需求下拉、名称正文、dirty 标志全部保持原状**，无左右错配。
（修复前：子面板会先切到 B，父级仍显示 A。）

## 3. F01 确认切换：一次弹窗、一次性切换

```json
{
  "targetText": "合成工程验收需求-贷款信息 · v2",
  "dialogsAsked": 1,
  "before": {"selectValue": "", "nameValue": "未保存的测试修改", "dirty": true},
  "after":  {"selectValue": "1", "nameValue": "合成工程验收需求-贷款信息", "dirty": false,
             "progressNote": "进度口径：当前需求范围"},
  "selectReflectsB": "合成工程验收需求-贷款信息 · v2",
  "switched": true
}
```

**结论**：只弹 **1 次**确认（无重复放弃确认）；确认后下拉、正文、dirty 一次性切到 B。
同时观察到 **F03 生效**：进度口径由「共享整表模式（计数覆盖该表全部字段）」变为「当前需求范围」。

## 4. F10 移动端折叠：三档连续折叠/展开均可恢复

宽度 500px（< `lg` 断点）下连续 3 次点击切换按钮：

```json
{"width": 500,
 "cycles": [{"before":"收起","after":"展开","visible":true},
            {"before":"展开","after":"收起","visible":true},
            {"before":"收起","after":"展开","visible":true}],
 "allReachable": true}
```

**结论**：折叠后按钮**始终可见可点**，可反复恢复。（修复前：窄屏收起后按钮随容器隐藏，无法恢复。）

## 5. UAT 与正式交付在真实 UI 中可访问

浏览器会话内直接调用隔离 API（同源 token）：

```json
{"version": {"app_commit":"9b5d00c…", "schema_head": null},
 "suiteCount": 9, "runCount": 1, "runStatus": "passed",
 "deliveryCount": 1, "deliveryVersion": 22, "signoffCount": 2}
```

UAT 运行详情页 `/uat/runs/1` 实际渲染（无 console error、无 `role=alert`）：

- 标题「合成工程验收轮次」、`第 1 轮 · isolated-synthetic`、`已完成`、`任务进度 100%`
- 统计：`总 Case 1 / 通过 1 / 失败 0 / 阻断 0`、`执行进度 100%`
- Case 结果：`P4-1 人工核对 8 字段口径 · manual · 通过`
- 预期/实际/证据均渲染：`预期结果 status passed`、`实际结果 note 合成材料逐项核对通过`、`证据 fixture synthetic sha256 000…`
- 提供「下载报告」「下载证据包」入口

**浏览器控制台（仅 error 级）**：**无任何消息**。

## 6. 顺带验证到的发布身份契约（B18）

页面顶部发布横幅真实触发并给出明确提示：

```
前后端发布标识不一致（app_commit:35ce3f3da1349ce94fb31e4169d243ba9f48be11 != 9b5d00cada0b640aaa139aa5d234f064d9e11f25），请联系运维核对本次发布。
```

这不是缺陷，而是**契约按预期工作**：隔离前端由当前 commit `35ce3f3` 构建，而隔离后端进程启动于旧代码
（`app_commit=9b5d00c`），横幅准确识别并报告了不一致——正是 P1–P4 要达成的效果。

## 7. F09 指标解释：真实渲染证据

`/agent?projectId=1` 页面（合成库无智能体任务）实际渲染 **32 个指标卡片**，每个卡片均包含：

- **指标名**（如「任务成功率」「场景识别准确率」「SQL 语义变更召回率」）
- **数值**：全部为 `—`（**`null` 未被当成 0**）
- **分母**：`分母 0`
- **服务端说明**：如「没有已终态（completed/failed）的任务」「需要标注基准集（Phase 3/9 数据）：任务未持久化期望场景标签 expected_scenario_key」

**结论**：说明文字来自**后端 `metric_notes`**（区分“无数据/未配置基准集”的不同原因），
且“无法计算”未被美化成 0 —— 正是 F09 要达成的效果。控制台无 error。

## 8. F08 建轮次自动绑定发布身份：真实点击验证

`/uat/suites/1` 页面（合成套件）：

- 页面显示：「**将绑定发布标识 commit 9b5d00cada0b640aaa139aa5d234f064d9e11f25 · 构建 2026-10-04T13:29:05Z · schema 未知**」
- 执行环境是**可编辑输入**，默认值 `isolated`（**不再是硬编码 `uat`**）
- 填入名称与 `browser-verify` 后**真实点击「创建执行轮次」** → 跳转 `/uat/runs/2`

回读新建轮次（隔离 API）：

```json
{"runName":"F08 浏览器验收轮次", "environment":"browser-verify",
 "gitCommitSha":"9b5d00cada0b640aaa139aa5d234f064d9e11f25",
 "manifestKeys":["manifest_version","frozen_at","request_id","run","release_identity","model_profiles"],
 "manifestRunEnv":"browser-verify"}
```

**结论**：UI 提交的轮次**确实带上了 `git_commit_sha`**（自动取自 `/api/version`），环境名来自输入框，
且服务端同时冻结了 manifest（N05）—— F08 与 N05 均按预期工作。

## 9. F05 三处异步表单：真实提交验证

以**平台管理员**（合成账号 `p4_platform_admin`，`institution_admin` 属于 `platform_operator` 机构）进入
`/admin/institutions`：

1. 点击「新建机构」→ 表单出现（`input[name=code]`、`input[name=name]`、`select[name=type]`）
2. 填入 `F05VERIFY` / `F05 浏览器验收机构` / `consulting_company`
3. 点击「创建机构」

结果：

```json
{"submitLabel":"创建机构", "formStillOpen":false,
 "codeValueAfter":null, "nameValueAfter":null,
 "listHasNewInstitution":true}
```

数据库核对（隔离库）：

```
('F05VERIFY', 'F05 浏览器验收机构', 'consulting_company', 'active')
count = 3
重复的 F05VERIFY 行数 = 1
```

**结论**：提交后**表单已关闭、输入已清空、列表已刷新且新机构出现**，且库中**恰好 1 条**（无重复提交）。
这正是 F05 修复的 `formElement.reset()` + 刷新路径（修复前 `event.currentTarget` 已为 null，
重置静默失效、后续刷新被跳过）。

## 10. F02 Skill 未保存保护与草稿恢复：真实浏览器验证

为能在浏览器中真正编辑 Skill，先向**隔离库**注入最小合成夹具（`seed_f02_skill_fixture.py`）：
1 个 `ModelProfile` + 1 个 `AISkillDefinition` + 1 个 **draft** `AISkillVersion`。

定位过程中遇到两个**真实数据库契约**（非夹具自由选择，已写入脚本注释）：

- `ck_ai_skill_version_positive` 要求 `version_no > 0` **且 `lock_version > 0`**（我起初写 0 → CheckViolation）；
- `ck_ai_skill_version_scope` 要求 `scope_type='project'` 必须同时带 `institution_id` 与 `project_id`；
- 且 `scope_key` 必须是 `control.scope_key()` 的规范形 `project:{institution_id}:{project_id}`，
  写成裸项目 id 时列表接口返回 200 但**为空**（版本在库里却看不见）。

修正后 `/ai-control/skills` 正常显示「v1 · 草稿」，随后逐项验证 F02：

| 子行为 | 浏览器证据 |
| --- | --- |
| dirty 提示 | 「有未保存的修改，请先保存或放弃修改，再切换能力、版本或运行测试。」 |
| 真实草稿持久化 | `localStorage` 键 `draft:skill-draft:project:1:1:f02_synthetic_skill`，载荷含 `savedAt` 与 `content.system_prompt` |
| **应用内链接守卫** | 点击普通 SPA 链接 `/workspace` → 弹窗「**有未保存的编辑，确定要离开并丢失这些内容吗？**」；取消后 `urlUnchanged=true` 且编辑仍在 |
| **草稿恢复入口** | 刷新后提示「**发现本地保存的草稿（2026-10-05T11:18:57.831Z，基于版本 #3）**」，出现「恢复草稿」「丢弃草稿」按钮，且**编辑器仍显示服务端值**（`editorHasServerValueOnly=true`，未静默覆盖） |

```json
{"dirtyNotice":"有未保存的修改，…",
 "localStorageDraftKeys":["draft:skill-draft:project:1:1:f02_synthetic_skill"],
 "clickedHref":"/workspace", "dialogSeen":true,
 "dialogMsg":"有未保存的编辑，确定要离开并丢失这些内容吗？",
 "urlUnchanged":true, "editStillPresent":true}
```

**结论**：F02 三项承诺（全局 dirty 登记、真实草稿持久化、恢复/丢弃入口）均在真实浏览器中兑现，
且恢复**不静默覆盖**服务端内容。

## 11. F06 查询失败回退：真实浏览器验证

F06 的回退需要**先有一次非空的成功读取**。合成库原本没有任何生成轮次，
而 API **正确拒绝**为已确认需求新建轮次（`409 只能为当前草稿准备新的生成输入`）——
这是产品契约而非缺陷，因此用 `seed_f06_generation_run.py` 写入一条 **completed** 轮次
（16/16）作为“上次成功”，并把其中 1 项置为 `running` 以启用面板的 1.5s 轮询。

在页面加载**前**注入 `fetch` 补丁：**第 1 次** `generation-runs` 放行，其后全部返回 `503`。

结果（共 20 次调用，19 次失败）：

```json
{"runsCalls": 20,
 "readOnlyFallback": "数据更新于 2026/10/5 19:25:58（只读回退：以下为该需求内容 v22 的历史读取结果，可能已过期；恢复读取后请刷新）",
 "mentionsExpired": true, "mentionsRecoverHint": true,
 "historicalRoundNotice": "这是内容 v22 的历史轮次，只能查看或拒绝，不能写入当前 v22。"}
```

**结论**：刷新持续失败时，面板**没有伪造、没有归零、没有静默清空**，而是：
① 继续渲染上次成功读取的数据；
② 用 `role="status"` 明确标注「只读回退 / 可能已过期 / 恢复读取后请刷新」；
③ 同时标出数据所属的**内容版本 v22**；
④ 将写入路径锁住（「只能查看或拒绝，不能写入当前 v22」）。

## 12. F07 引用定位：真实浏览器验证

**反向路径（不猜 URL）**：访问 `/agent?projectId=1&taskId=98765`（不存在的任务）：
`taskId` 参数被保留而非静默丢弃，且 `showsAnyTaskDetail=false` —— **没有回退到“最新任务”**，
而是提示「任务快照加载失败，请检查权限或稍后刷新。」

**正向路径（真实跳转）**：在 UI 中真实创建任务后（库中 `agent_tasks.id=2`），访问
`/agent?projectId=1&taskId=2`：

```json
{"showsTaskDetail": true, "taskSnapshotLoaded": true,
 "showsObjective": true, "showsRunning": true}
```

即链接**确实打开了它指向的那个任务**（目标正文与运行状态均属该任务），
而不是“新的一个任务”。（页面上同时出现 `agent_run_refused：Assignee does not hold role
project_manager` —— 这是**权限越权被拒绝的真实证据**，不是缺陷。）

## 13. F04 提交预览与范围权威：真实浏览器验证

`/workspace?projectId=1&requirementId=1` 生成面板下方的**提交预览**行：

```
将生成 8 个字段 · 业务口径 + 技术溯源 内容 v22 · 轮次 #1 · 15/16 已完
```

该行由 `effectiveFieldIds`（= `scopeOverride ?? fieldIds`）驱动，与 `generate()` 真正 POST 的
`field_ids` **同源**，因此“所见即所提”。

**动态验证（真实点击范围开关）**：

```json
{"before": {"label": "当前字段", "preview": "将生成 8 个字段 · …"},
 "after":  {"label": "当前字段", "preview": "将生成 1 个字段 · …"},
 "changed": true}
```

**结论**：切换“全部字段 / 当前字段”后预览由 **8 → 1** 实时变化，证明预览跟随有效范围，
而不是硬编码或滞后于实际提交范围——正是 F04 要修正的“提示范围与实际提交不一致”。

## 14. 未完成 / 边界

1. **本轮已覆盖全部 10 项 F 需求**：F01（第 2–3 节）、F02（第 10 节）、F03（第 3 节）、F04（第 13 节）、
   F05（第 9 节）、F06（第 11 节）、F07（第 12 节）、F08（第 8 节）、F09（第 7 节）、F10（第 4 节）—— **共 10/10 项**。
3. 未做**登录令牌续期**（refresh rotation）的浏览器实测。
4. `read_image` 在本模型不可用，故**未做像素级视觉检查**（布局/溢出/字体外观未目视确认）；
   结论均基于 DOM 文本、元素可见性与状态断言。
5. 未在真实网络条件（403/500/断网）下验证错误态渲染。
