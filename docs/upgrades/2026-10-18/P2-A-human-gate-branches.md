# P2-A 交付说明：人工门四条决策分支的回归与一处 outbox 缺陷修复

- 日期：2026-10-18
- 范围：`.planning/_prompts.md` 中「P2-A　人工门只测了 approve，三条负向分支没有断言」一项
- 仓库：`ai-platform`（branch `dsh/banking-semantic-agent-v2`）
- 状态：测试补齐 + 暴露并修复一处真实回归；**未提交 git**

---

## 0　结论摘要

原状态：`decide()` 有五条路径（approve / edit_and_approve / reject / request_reanalysis / 双人复核的部分批准），但 `tests/test_agent_runtime.py` 里只有一条用例测 approve，且用的是持有 `task.manage` 的身份。负向分支没有任何断言。

本轮做了两件事：

1. **补齐三条负向分支的回归**（+363 行，只动测试）。
2. **测试暴露出一处真实回归并已修复**：clarification 分支在 `decide()` 里提前 `return`，绕过了本会话新增的 outbox staging。人选定主体后任务停在 `running`，队列里没有作业——门看起来关了，实际没有任何工作被排上。这是本会话引入的回归，不是历史缺陷。

修复后 `tests/test_agent_runtime.py` **20 passed**（原 16 + 新 4，含投递失败用例）。

---

## 1　为什么这处 outbox 缺陷是「本会话引入的」

`decide()` 的尾部原本是：提交决策 → 再单独创建一个后台作业。本会话把后者改成了 outbox 语义（`runtime.py:996-1033` 的 `_stage_continuation`）：

> 决策与该决策排出的作业在**同一个事务**里提交；提交后由 `_dispatch_staged` 投递。此前决策在这里提交、作业在第二个独立事务里创建（其内部自己 commit），中间崩溃或权限/actor 报错会让「步骤已决策」而「没东西会去跑它」并存。先 stage 让「决策已记录」与「工作已排队」成为一个变更单元。

`git diff` 里这段是新增的（`@@ -1503,15 +1618,25 @@`）。但 clarification 那条分支是**旧代码**，它在 replan 之后自己 `db.commit()` 然后 `return task_snapshot(...)`：

```python
if clarification:
    replan(db, task, reason_code="subject_clarified")
    db.commit()
    db.refresh(task)
    return task_snapshot(db, task)      # ← 绕过整个新尾段
```

于是这条路径既没进 outbox，也因此没清 `pending_gate`、没写 `agent_human_decision` 审计。outbox 改造没有把这条 early return 一起收编，是这次遗漏的成因。

p2a-gate-owner 的用例当时只能显式调用 `runtime.resume_task(db, analyst, task)` 才能把任务跑完，并在注释里把它标成 `Known outbox gap` —— 那个标注意味着「测试绕着缺陷走」，不能就这么留着。

## 2　修复

`backend/app/services/agent/runtime.py:1569` 起，把 early return 改成 fall through：

```python
        if clarification:
            # The human picked the subject: rebuild the plan for the chosen field.  Control then
            # falls through to the shared tail so the gate is cleared, the decision is audited
            # and the continuation is staged - all in this one transaction.  An early return
            # here (the pre-outbox shape) committed the replan and left the task RUNNING with
            # nothing queued, so the gate looked closed while no work was scheduled.
            replan(db, task, reason_code="subject_clarified")
```

`replan()` 内部以 `db.flush()` 结束（`runtime.py:1397`）不提交，因此直接落进统一尾段是安全的：清 `pending_gate`（:1596）、`_refresh_task_status`、写 `agent_human_decision` 审计（:1599）、`_stage_continuation` + `db.commit()`（:1625）、`_record_case_memory`、`_dispatch_staged`。

同时修正了测试里围着缺陷写下的断言：

| 位置 | 原断言（绕开缺陷） | 现断言（契约） |
| --- | --- | --- |
| `test_agent_runtime.py:604-608` | `BackgroundJob` 恰好 1 个、`background_job_id` 仍指向旧 job，然后手动 `resume_task` | 多出一个 continuation job 且 `task.background_job_id` 已换；不再手动 resume |
| `test_agent_runtime.py:585` | `task.status == TASK_RUNNING` | `in {TASK_RUNNING, TASK_COMPLETED}` —— inline 队列下 continuation 在 `decide()` 内就派发跑完了，queued 队列下才会停在 running |
| `test_agent_runtime.py:568-570` | 注释说明「`pending_gate` 由于 early return 不会清」并只看 step 行 | `assert "pending_gate" not in summary` |

## 3　三条新增用例与各自锁住的契约

均在 `backend/tests/test_agent_runtime.py`，helper `_clarify_tool` / `_clarify_plan` 在同文件 505 行之后。

### 3.1　`test_edit_and_approve_on_a_clarification_gate_replans_for_the_chosen_field`（:542）

- 审核人是 `analyst_principal`（business_analyst）。用例先实测断言 `"task.manage" not in permissions` 且 `"business.edit" in permissions`，再让这个身份关掉门 —— 直接锁住上一轮那个 403：**审核人靠门的权限关，不需要 `task.manage`**。
- subject 落为 `human_clarified` / `resolved`，`selected_by` 记到 analyst。
- plan 重建为 v2，只含未执行步骤 `["finish"]`；plan v1 的 `finish` 行不删不改（仍是 `pending`、`attempt_count == 0`），新的 v2 行跑完 —— 「只重建未执行步骤」不等于「抹掉历史」。
- artifact `confirmed` + `confirmed_by`；`call.human_confirmed` / `call.adopted` 均 True；`ReviewDecision.decision == "approved"`。
- 新增的 outbox 断言（见 §2 表）。

### 3.2　`test_request_reanalysis_reopens_the_gate_and_reruns_the_step`（:623）

- 真的是第二次执行：`seen == [1, 2]`、`attempt_count == 2`（不是复用旧输出）。
- 重分析后**重新开门**并回到 `waiting_human`；旧 artifact `superseded`。
- plan 版本与 `replanning_count` 不变 —— reanalysis 不走 replan，这是它与 edit_and_approve 的关键区别。
- gap `human_reanalysis_requested` 写入；staged 了新的 continuation job 且 `background_job_id` 已换。

### 3.3　`test_reject_stops_the_task_without_staging_more_work`（:688）

- `task.blocked` + `step.blocked`、`error_code == "human_rejected"`、gap 与 message 正确、artifact `rejected`、`pending_gate` 已清。
- **不派发**：`BackgroundJob` 计数仍为 1、`background_job_id` 不变（`decide()` 尾部 `if decision != sm.DECISION_REJECT` 的那道闸）。
- 下游 `finish` 停在 `pending`、`seen == [1]`。

## 4　验收

```
cd ai-platform/backend
$env:AUTH_MODE='optional'; $env:TASK_QUEUE_PROVIDER='inline'
.\.venv\Scripts\python.exe -m pytest tests\test_agent_runtime.py -q -p no:randomly
→ 20 passed  (10.62s)
```

全量回归（ENVIRONMENT=test AUTH_MODE=optional DATABASE_URL=sqlite:///./.ci.db STORAGE_PROVIDER=local TASK_QUEUE_PROVIDER=inline VECTOR_STORE_PROVIDER=mock LLM_PROVIDER=mock EMBEDDING_PROVIDER=mock LINEAGE_GIT_ENABLED=false）：

```
.\.venv\Scripts\python.exe -m pytest tests -q -p no:randomly
→ 1725 passed / 1 skipped, 12 warnings  (26m31s, exit 0)
```

基线：P1-A 交付时 1689 passed / 1 skipped；本单修完回归后为 1725（含 P1-B 与 P2-B 的新增）。1 skipped 是既有项 `test_version_consistency.py:136`。

改动文件：

| 文件 | +/- | 说明 |
| --- | --- | --- |
| `backend/tests/test_agent_runtime.py` | +363 / -0（p2a）+ 本轮修订 | 4 条新用例（含 5.3 的投递失败用例）+ 2 个 helper；围绕 outbox 缺陷的断言已改为契约断言 |
| `backend/app/services/agent/runtime.py` | -6 / +7（本轮） | clarification 分支改为 fall through，回到统一尾段 |

产品代码的改动只有 `runtime.py` 那一处，且是**修回归**，不是改语义：replan、gate 关闭、审计、排队这四件事本来就该在同一个事务里。

## 5　仍然遗留、需要产品决策的三点

以下三点都是**真实行为**，本轮没有擅自改，测试按真实行为断言并在代码里注明。

### 5.1　reject 后 `ReviewTask.status` 是 `returned` 而不是 `rejected`

`DECISION_TO_REVIEW_STATUS`（`runtime.py:110-115`）把 reject 映射为 `"rejected"`，但 `decide()` 在调 `decide_task` 前有守卫 `elif review_task.status not in {"approved","rejected","returned"}`（:1540）。一旦 `review_task` 已是 `returned`（reanalysis 后**复用同一条 instance**），reject 就不再走 `decide_task`，于是 workflow instance 记为 rejected 而 `ReviewTask` 停在 `returned`。

是否算缺陷取决于产品口径：如果审核台上要区分「被打回重做」和「被否决」，现在的数据区分不了。要区分就得改守卫的语义（`returned` 是否应允许再次终结），属于产品决策。

### 5.2　reanalysis 复用的是同一条 ReviewTask / workflow instance

`start_workflow`（`runtime.py:160-166`）命中 `status in ("draft", "in_progress", "rejected")` 时直接返回既有 instance，不新建。所以「重新分析」在数据上表现为同一条复核单被重开，而不是开一张新单。这是有意的复用（避免垃圾单），但意味着**同一条 ReviewTask 会承载多轮决定**，统计「一条复核单被驳回几次」时要注意口径。

### 5.3　`veP` 分支投递失败：已由用例锁住（原“本轮未做”，已补）

投递失败不会回滚决策（这是 outbox 的设计：作业行已持久化，由补偿扫描接管）。clarification 路径此前从不投递，修复后第一次真正暴露在这条路径上，因此本轮最后补上了 `tests/test_agent_runtime.py:812 test_a_clarified_subject_survives_a_continuation_dispatch_failure`：

- 注入 `InlineTaskQueue.dispatch_staged` 抛 `RuntimeError("queue is unavailable")`，断言**决策与 replan 都成功、只有投递失败**：`plan_version == 2`、clarify step 仍 `completed`、`background_job_id` 换成新 job、`AgentHumanDecision` 恰好 1 条。
- 断言**门是 settled 的**（`pending_gate` 已清）——锁定修复的那半：清 marker 与决策在同一事务提交，不会留下一个再也决定不了的假门。
- 断言**作业行是恢复源**：新 job `status == "queued"`、`started_at is None`、`dispatch_failed` / `dispatch_alert` 均 True、`error_message` 含 `queue is unavailable`，任务未被 park。
- 断言**可恢复**：把 `queued_at` / `created_at` 拨到 5 分钟前、恢复真实 `dispatch_staged`、调 `dispatch_undelivered(db)`，新 job 出现在 `report["dispatched"]`，任务最终 `TASK_COMPLETED`、下游 `finish` 为 `completed`。

一个实测细节：该用例最初断 `seen == [1, 1]` 失败，实际是 `[1]`——clarify step 已由人工决策置 completed，补偿投递只跑下游 `finish`，不会重入已确认的门工具。这是**正向信号**（补偿扫描没有重复执行已确认的门），已按真实行为修正并加注释。

## 6　边界说明

- 未改 `state_machine.py` 的任何常量或映射。
- 未改权限模型、未改 `decide()` 的签名。
- 未放松任何既有断言：原有 16 条用例全部通过。
- 未提交 git。
