# 2026-10-06 补交任务（3db4db6）：R01–R08 逐项交付台账

复核基线：`dsh/banking-semantic-agent-v2` @ `3db4db6516a2c2cd495fe4109701a5a6451cb393`。
本台账按**补交编号**逐项给出：问题 → 修改文件 → commit → 修复前证据 → 修复后结果 → 验证边界。

| 编号 | 优先级 | 主题 | Commit | 修复前 → 修复后 |
| --- | --- | --- | --- | --- |
| R01 | P1 | 正常续期后原请求仍失败 / 旧响应归属 | `4e99ce1` | 8 passed / 5 failed → **13 / 0** |
| R02 | P1 | 失租后领域提交与重复结果 | `1e5b837` | 3 failed / 1 passed → **4 / 0** |
| R03 | P2 | 默认模型摘要保真 | `0881b7e` | （与 R04/R05 同批） |
| R04 | P1 | 回答评分与结果页接线 | `0881b7e` + `090b7aa` | 后端 8 failed → **25 / 0**；前端新增 4 条 |
| R05 | P1 | 执行与评分使用不可变快照 | `0881b7e` | 同上 |
| R06 | P1/P2 | 发布与回滚门禁 | `54d2c81` | 8 failed / 6 passed → **14 / 14** |
| R07 | P1 | 真实队列验收有效性 | `229c6e4` | 空断言通过 → **13/13，退出码 0** |
| R08 | P2 | 持续恢复、按任务隔离、公共进度区 | `9427cb6` | 10 passed / 4 failed → **14 / 0** |

逐项详情见同目录 `R01-…md` … `R08-…md`。

---

## 保留的已成立能力（复核确认成立，本轮未回退）

C02 草稿账号隔离、C03 重试后补投恢复、C04 历史终态保护、C06 显式选择 B 时实际执行为 B、
C07 timeout 不计作生成成功、C08 关键字段 hash 与稳定排序。

本轮回归中这些能力的既有用例全部保留并通过（见最终全量计数）。

---

## 一、P1 逐项摘要

### R01 正常续期后原请求仍失败（`4e99ce1`）
- **问题**：`saveSession()` 每次都自增身份代次，续期成功也调用它，于是外层 `epoch === currentSessionEpoch()`
  必然不相等 → **正常 401→refresh 200 之后原请求从不重放**，仍返回 401；
  401 分支先续期再判断归属，旧 A 请求晚到的 401 会为新登录的 B 启动续期。
- **修改**：`frontend/lib/api.ts` —— 拆分「身份转换」（`saveSession`，自增代次）与
  「同身份令牌轮换」（内部 `writeTokens`，不动代次）；续期前核验归属；飞行记录只清自己。
- **验证**：新增 6 条**真实 API 客户端**回归，断言**业务结果**（GET 返回 `{id,status}`、
  POST 返回 `{request_id,status}` 且两次请求体逐字相同、下载拿到 blob 与文件名、并发两条都成功且只续期一次、
  旧 A 晚到 401 不启动 B 续期）。
- **边界**：未真实浏览器验证；代次为每标签页进程内。

### R02 失租后领域提交与重复结果（`1e5b837`）
- **问题**：执行权检查在 handler **返回之后**，真实领域 handler 通过 `_complete()` 无条件 commit，
  已落库 StoredFile/通知/审计；接管后同一 job 再落一份（各 2 条）。
- **修改**：新增 `attempt.py` 执行权协议（不可变 owner token + `still_owns` + 同事务 `fence_commit`）；
  `_complete()` 在本次尝试的执行权之下发布，失败整体回滚；`project_manifest_export_handler`
  发布栅栏失败时**回收已写外部对象**；对 6 个在领域服务内部 commit 的 handler 加执行权预检。
- **验证**：4 条回归驱动**真实队列 + 真实 handler**，断言 StoredFile/通知/审计**各 0**、
  job 保持接管者状态、外部对象被回收、接管后**恰好各 1 条**。
- **边界**：后 6 个 handler 的领域服务**内部**提交点未接入执行权（已明确列出）；
  未在真实 PostgreSQL 验证并发接管。

### R04 回答评分与结果页接线（`0881b7e` + `090b7aa`）
- **问题**：回答与引文合并算关键词，导致“回答不含预期词、只有引文命中”仍满分；
  摘要没有覆盖率/状态计数/实际模型/口径说明，页面只显示绿色 completed 与无分母 100%；
  metadata 合并用顶层 null 覆盖已有拒绝原因。
- **修改**：回答代理（`keyword_coverage`，只看回答文本）与证据代理（`evidence_keyword_coverage`，只看引文）**分开**；
  摘要新增 `generation_coverage`、`status_counts`、`actual_chat_model`、`metric_notes`；
  `_merge_execution_metadata()` 保留非空原因；新增 `evaluation-results-view.mjs` 作为页面与回归**共用**口径，
  结果页新增覆盖率/分母/计数/实际模型/逐条状态与原因/「不适用」说明。
- **验证**：后端 4 条（仅引文命中不得满分、部分降级展示覆盖率与逐条状态、拒绝原因不被覆盖、全不可生成时“不适用”）；
  前端 4 条用 `renderToStaticMarkup` 断言**真实 HTML**（`生成覆盖率 1/2（50%）`、
  `回答代理 不适用`、`原因：timeout`、`confidentiality_policy` 等）。
- **边界**：未真实浏览器验证；前端 4 条的“修复前”状态是**功能不存在**（已在记录中明说，未伪装成失败回归）。

### R05 执行与评分使用不可变快照（`0881b7e`）
- **问题**：只存 hash，执行持有可被其他 Session 修改的 ORM 用例；运行中编辑会让实际执行新 query/真值，
  而 run 仍报告旧 hash。
- **修改**：`build_dataset_snapshot()` 冻结全部输入与真值 + schema；`SnapshotCase` 只读视图；
  `dataset_version_from_snapshot()` 可从快照重算；快照存入现有 `retrieval_config_json`（**无需迁移**）。
- **验证**：运行中编辑、运行后编辑均不改变该运行用的输入/真值，且能从快照重算版本。
- **边界**：未验证大用例集的 JSON 体积；未验证“从快照恢复并重跑”。

### R06 发布与回滚门禁（`54d2c81`）
- **问题**：`PREVIOUS_TAG` 读已 export 的新标签 →“上一版”记成当前版；回滚就绪循环耗尽后无失败判断，
  40 次 ready 全失败仍可 exit 0；compose 失败后 `.env` 已变却未声明。
- **修改**：`PREVIOUS_TAG` 改从 `.env` 文件读 + 拒绝相同标签；回滚脚本先保存原 manifest，
  就绪耗尽/compose 失败/前端无响应均**非零退出**并如实说明 `.env` 已被修改；身份核验扩展到 commit + build_time
  并核对 worker/beat 组件。
- **验证**：独立假工具回归 14 项（A→B 的 previous 仍为 A、ready 全失败必失败、compose 失败后的配置与日志、
  正常回滚核验组件、无镜像拒绝回滚）。
- **边界**：未在真实 Docker/Compose 执行。**并修正**了 C09 记录中“失败不改 .env”的笼统说法 ——
  该结论只对镜像校验阶段成立。

### R07 真实队列验收有效性（`229c6e4`）
- **问题**：夹具缺 `datasource_id` 实际必 failed，脚本却接受 failed；`attempt_count` 不存在导致 0→0 空断言；
  guard 对 `celery-task-meta-*` 字符串键调 `LLEN` 触发 WRONGTYPE；`--allow-reset-existing` 声明却未生效。
- **修改**：换成 `project_manifest_export`（真实领域结果：StoredFile + 审计 + 通知）；
  幂等键按运行唯一；首次断言**必须是 completed** 且**领域计数增量恰好 1**；
  重投用真实领域计数证明“只执行一次”；guard 先用 `TYPE` 区分键类型；
  `allow_existing=args.allow_reset_existing`；父子共用同一存储根与 mock 配置。
- **验证**：专用 Redis DB15 + 隔离 PostgreSQL 实跑 **13/13、退出码 0**（首次经 broker 且 completed、
  领域计数增量 1、真实 broker 重投零新增效果）；预置结果键后不再 WRONGTYPE；
  不带 flag 时被 N13 拒绝且隔离库行数与迁移版本未变；共享 DB0 哨兵全程保留。
- **边界**：未多机；未验证 broker 高可用；“缺输入必失败”为间接保证（首次必须 completed）。

---

## 二、P2 逐项摘要

### R03 默认模型摘要保真（`0881b7e`）
- **问题**：未指定 profile 时实际跑 A/id1，但 `chat_model`/`chat_profile_id` 仍为 null/环境默认。
- **修改**：运行开始时用 `get_prompt_runtime` 解析并**固定**实际档案（回写 `run.model_profile_id`），
  摘要、逐条 metadata 与模型调用三者一致；运行中新增更小 id 的启用档案不会改变本次执行。
- **验证**：2 条回归（摘要一致、运行中配置变化不换模型）。
- **边界**：未调用真实模型（模型边界替身）。

### R08 持续恢复、按任务隔离与公共进度区（`9427cb6`）
- **问题**：visibility 恢复读到 `running` 但 `failed` 未清 → 不再排程（继续停轮询）；
  `pollingUnavailable` 是全局字符串，一个 job 的故障污染无关 job 且恢复后不清；
  只有主任务详情页接了提示条。
- **修改**：`poll()` 成功即清 `failed`/`lastError` 并记 `lastSuccessAt`；统一 `recover(jobId)` 供
  visibility / online / 手动共用；错误状态**按 job**（`errorFor`/`lastSuccessAt`/`clearError`/`reset`）；
  新增 `subscribeState`；**公共进度区 `JobProgressPanel`** 内部接入提示与「立即重试」（该组件被 9 个页面渲染）；
  退出登录调用 `resetJobPollingState()`。
- **验证**：4 条真实 registry 回归（三次失败→visibility 读 running→继续轮询→completed；
  双 job 不串提示；身份变化清空；终态与解除订阅后无提示），既有 10 条保留。
- **边界**：**未做真实浏览器验证**（需访问运行中的 3000/8000 与真实业务作业，本轮不操作既有服务）；
  “9 个页面自动获得提示”是**静态覆盖推理**；未加该组件的渲染回归（Next 运行时依赖）。

---

## 三、与复核结论不同之处（提供动态行为与精确代码证据）

1. **R06 的“失败不改 `.env`”**：复核指出该笼统描述不成立，本轮**确认并修正** ——
   镜像校验阶段确实不改（R06-5 验证通过），但 `compose up` 之后失败**会**留下已修改的 `.env`；
   脚本现在明确输出这一点，文档同步修正。
2. **R07 的“必然 failed 却算通过”**：本轮实证 —— 换成 `project_manifest_export` 后首次投递
   真的经 broker（`queue_depth: 1`）并成功（`completed`，领域计数增量 1）。此前“通过”是因为
   夹具必失败 + 终态断言接受 failed + 复用旧幂等键。
3. **R08 的 visibility 剩余问题**：复核说“读到 running 但 failed 仍 true、后续没有 timer”，
   本轮先复现该失败（4 条新用例修复前全红），再修复。

## 四、最终全量验证

见 `final-verification.md`（真实计数、环境与退出码）。

## 五、本轮**未验证 / 待验收**（不得当作通过）

1. R08 的真实浏览器验证**未执行**（需运行中的 3000/8000 与真实业务作业）；
2. R02 后 6 个 handler 的领域服务**内部**提交点未接入执行权；
3. R06 未在真实 Docker/Compose 执行；`YBT_RELEASE_COMMIT` 未接入 CI；
4. R07 未多机、未验证 broker 高可用；
5. R05 未验证大用例集体积与“从快照重跑”；
6. 真实银行资料与签署人仍缺失（W11 未完成）；
7. 未操作业务库、未部署、未清共享 Redis、未调用未批准真实模型 ——
   **源码补交完成不等于现有运行实例已生效**。
