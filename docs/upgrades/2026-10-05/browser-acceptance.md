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

## 6. 顺带验证到的发布身份契约（B18/F08）

页面顶部发布横幅真实触发并给出明确提示：

```
前后端发布标识不一致（app_commit:35ce3f3da1349ce94fb31e4169d243ba9f48be11 != 9b5d00cada0b640aaa139aa5d234f064d9e11f25），请联系运维核对本次发布。
```

这不是缺陷，而是**契约按预期工作**：隔离前端由当前 commit `35ce3f3` 构建，而隔离后端进程启动于旧代码
（`app_commit=9b5d00c`），横幅准确识别并报告了不一致——正是 P1–P4 要达成的效果。

## 7. 未完成 / 边界

1. 本轮**未覆盖**F02（Skill 离开确认与草稿恢复）、F05（三处表单成功/失败重置）、F06（查询失败回退）、
   F07（引用定位跳转）、F08（建轮次自动绑定发布身份）、F09（指标说明）的**逐项点击**；
   这些仍需在隔离环境中构造对应数据后逐条验证（合成库目前没有 Skill 草稿、没有智能体任务）。
2. 未做**登录令牌续期**（refresh rotation）的浏览器实测。
3. `read_image` 在本模型不可用，故**未做像素级视觉检查**（布局/溢出/字体外观未目视确认）；
   结论均基于 DOM 文本、元素可见性与状态断言。
4. 未在真实网络条件（403/500/断网）下验证错误态渲染。
