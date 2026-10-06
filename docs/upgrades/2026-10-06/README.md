# 2026-10-06 修复任务书：C01–C11 逐项交付台账

审查基线：`dsh/banking-semantic-agent-v2` @ `fd7a532`。
本台账按**任务编号**逐项给出：修复前证据 → 修改文件 → commit → 修复后结果 → 验证边界。

| 编号 | 优先级 | 主题 | Commit | 结论 |
| --- | --- | --- | --- | --- |
| C01 | P1 | 会话切换与退出 | `bad980e` | 修复前 1 passed/6 failed → 修复后 **7/7** |
| C02 | P1 | 草稿账号隔离 | `8f0a43c` | 修复前 9 passed/3 failed → 修复后 **12/12** |
| C03 | P1 | 重试后补偿派发 | `8e780bb` | 见 C03/C04/C05 合计 |
| C04 | P1 | 重复消费改写终态 | `8e780bb` | 见 C03/C04/C05 合计 |
| C05 | P1 | 心跳异常静默停止 | `8e780bb` | C03/C04/C05 修复前 6 failed/3 passed → 修复后 **9/9** |
| C06 | P1 | 评测模型标签错配 | `9fbf0e5` | 见 C06/C07/C08 合计 |
| C07 | P1 | 降级回答算满分 | `9fbf0e5` | 见 C06/C07/C08 合计 |
| C08 | P2 | 数据集版本不完整 | `9fbf0e5` | C06/C07/C08 修复前 14 failed/3 passed → 修复后 **17/17** |
| C09 | P1 | 连续发布身份与回滚 | `7329f8b` | 修复前 4 failed/8 passed → 修复后 **12/12** |
| C10 | P1 | Redis 验收隔离 | `1ea7440` | 修复前无守卫（源码确认）→ 修复后 **12/12** + 负例拒绝 |
| C11 | P2 | 轮询故障恢复 | `639166e` | 修复前 8 passed/2 failed → 修复后 **10/10** |
| — | — | 依赖安全（新公告） | `7d11b62` | `source-map-js` 1 high → **0** |

逐项详情见同目录下 `C01-…md` … `C11-…md` 与 `security-source-map-js.md`。

---

## 一、P1 逐项摘要

### C01 会话切换与退出（`bad980e`）
- **修复前**：`frontend-state-reproduction.json` 显示 A 的晚到续期把令牌写成 `A-access-new`（期望 `B-access`）；退出只清本地存储，从不调用服务端 logout。
- **改动**：`lib/api.ts`（`sessionEpoch` 代次、续期绑定 `{epoch, refreshToken}` 并在写回前双重校验、新增 `logoutSession()`）、`lib/http-response.mjs`（`isCurrentSession` 判定）、`lib/http-response.d.mts`、`components/AppShell.tsx`。
- **修复后**：新增 7 项回归驱动**真实** `lib/api.ts`（真实刷新路径、真实 401 处理），覆盖：并发 401 只续期一次、退出后晚到不写回、A→B 切换不被覆盖、旧 401 不清新会话、同会话 401 原行为不变、logout 调服务端、logout 抛错本地仍完成。
- **边界**：未真实浏览器重放；代次为每标签页进程内；未验证服务端审计落库。

### C02 草稿账号隔离（`8f0a43c`）
- **修复前**：A/B 的 key 逐字相同（`skill-draft:project:11:none:…`），B 读到 A 的私有正文。
- **改动**：`lib/unsaved-changes.mjs`（key 内含 actor、载荷记 `owner`、读取严格校验、无身份不读写）、`.d.mts`、`app/ai-control/skills/page.tsx`（actor 取自服务端 `capabilities.actor_id`）。
- **修复后**：12/12；覆盖"无身份""跨账号""无 owner 历史草稿"。
- **边界**：未真实浏览器双账号验证；旧草稿不迁移（有意）。

### C03/C04/C05 队列三项（`8e780bb`）
- **C03 修复前**：retry 后仍带旧 `dispatched_at`，补偿 sweep `candidates: 0`，broker 恢复也补投不到。
  **改动**：新增 `background_jobs.queued_at`（迁移 `202610060001`，含回填）+ `retry()` 同事务清投递标记 + sweep 按 attempt 队列时间计时。
- **C04 修复前**：completed 任务重投被改写成 cancelled/failed（机构停用分支、无 handler 分支都在 `_claim_job` **之前**写终态）。
  **改动**：入口终态短路 + 两个前置分支改为"先领取再写" + 新增 `_record_terminal_state`（带 `lease_owner` 条件的受限 UPDATE）。
- **C05 修复前**：一次续租异常即永久退出线程且 `lease_lost=false`。
  **改动**：`HEARTBEAT_RETRY_ATTEMPTS=3` 有界重试 + 用尽即显式置 `lost`；心跳签名改为固定 `job_id`。
- **修复后**：9/9；并证明**未执行**任务的机构停用守卫未被削弱。
- **边界**：未在真实 PostgreSQL 验证并发补投；未用真实 broker 验证 retry→补偿。
- **迁移验证**：`202610060001` 已在**全新隔离库 `ybt_iso_c03_migration`** 上从空库跑到 head 成功（链完整，exit 0），
  并在 `ybt_iso_phase5_workers` 上应用（此前该库由旧 `create_all` 建表无迁移版本，已重建到 head）；
  **业务库 `ybt_dsh_handoff_v2` 未应用任何迁移**。

### C06/C07/C08 评测三项（`9fbf0e5`）
- **C06 修复前**：指定 profile B，实际 runtime 是 A（`get_prompt_runtime` 永远取最小 id）。
  **改动**：`get_prompt_runtime(..., model_profile_id=)` 显式校验存在/启用；`grounded_answer` 透传；评测每调用都显式传 run 选择；配置新增 `chat_profile_id`。
- **C07 修复前**：模型超时降级后仍 `successful=1 / groundedness=1 / correctness=1`，`execution_metadata=null`。
  **改动**：按 `answer_status` 区分**检索质量 / 生成可用性 / 回答质量**；降级不计入回答成功与正确率；新增 `degraded_query_count`、`retrieval_only_query_count`、`answer_correctness_denominator`；每例持久化 `execution_metadata_json`（含 `answer_status`、`degraded_reason`）。
- **C08 修复前**：6 个语义字段改了 hash 不变；行顺序变化 hash 反而变。
  **改动**：hash 纳入全部评分相关输入 + 按 id 稳定排序 + `DATASET_VERSION_SCHEMA` 版本标记。
- **修复后**：17/17，且原有评测用例仍通过（18 passed）。
- **边界**：未调用真实模型（spy）；未接真实 Milvus；新增指标未接入前端展示。

### C09 连续发布身份与回滚（`7329f8b`）
- **修复前**：身份从 `.env` 继承上一版；`YBT_RELEASE_TAG` 从不写回，compose 仍选旧镜像；门禁只比较标签互相一致。
- **改动**：身份只来自构建清单或本次 git HEAD（否则停止发布）；**备份后立即写回 TAG**；成功后再写 `APP_COMMIT/BUILD_TIME/TAG`；新增**镜像层身份核对**（Dockerfile `LABEL org.ybt.app.commit`）；新增 `rollback-server.sh`（同时恢复镜像与身份，失败不改 `.env`）。
- **修复后**：12/12（含"连续发布 A→B，B 报 B""回滚同时恢复身份""身份不符非零退出""无镜像拒绝回滚"）。
- **边界**：未在真实 Docker 执行；`YBT_RELEASE_COMMIT` 未接入 CI；未验证真实 compose 选镜像。

### C10 Redis 验收隔离（`1ea7440`）
- **修复前**：固定 `celery` 队列 + 默认 DB0 + 直接 `delete` 队列；父进程与子进程配置不一致。
- **改动**：每次运行 UUID 队列、默认专用 DB15、`assert_dedicated_redis()` 共享 broker 拒绝、发布者与 worker 同队列、子进程允许列表环境 + 强制 mock、只清理自己的队列、隔离库先迁到 head、**重复投递改走真实 broker + 第二个真实 worker**。
- **修复后**：12/12；DB0 哨兵消息在验收前后**完全未被消费或删除**；指向 DB0 时**非零退出且不改动哨兵**。
- **边界**：未多机；未验证 broker 高可用；`--allow-shared-broker` 逃生门未端到端验证。

---

## 二、P2 逐项摘要

### C08 数据集版本
见上（P2 但在 P1 批次一并修复）。

### C11 轮询故障恢复（`639166e`）
- **修复前**：三次失败后 `registry_size=0`，网络/可见性恢复都不再查询，hook 无 `onPollingError`，界面永久停在旧状态且无提示。
- **改动**：达到上限只置 `failed`（停轮询、保留订阅）；新增 `online` 订阅与 `resumeStalled()`；新增 `isStalled()`/`resume()`；重新订阅即重拉；**修掉定时器陈旧令牌导致恢复判断永不成立的 bug**；hook 暴露 `useJobPollingStatus()`（保持原返回值不变）；`app/jobs/[jobId]` 增加可见提示条与「立即重试」。
- **修复后**：10/10。
- **边界**：未真实浏览器断网验证；仅主状态页接入提示条；状态读取为 1s 轮询折中。

---

## 三、本轮的关键方法论修正（如实记录）

1. **C04 的两条用例最初假通过**：`execute_existing(..., handler)` 会把 handler 写进**模块级** `_handlers`，
   同一 `job_type` 二次调用会解析到旧 handler，"无 handler"分支根本进不去。已改为先跑成一次、
   再把 `job_type` 换成从未注册的类型，并加 `assert _resolve_handler(...) is None` 固定前提。
2. **C09 的回归最初假通过**：假 `curl` 用**拷贝快照**读 `.env`，掩盖了"TAG 没写回就起旧镜像"的时序。
   已改为 symlink 指向实时 `.env`，随后真实复现出 `镜像内为 COMMIT_A，本次发布为 COMMIT_B_SHA`。
3. **C11 的一条既有用例断言的是缺陷本身**（`size()===0`，即丢弃订阅）。已替换为更新的正确契约，
   **未删除或跳过任何断言**。
4. **C10 的隔离库 schema 陈旧**（旧脚本用 `create_all` 建表却不写 alembic 版本）导致新迁移报
   `DuplicateColumn` —— 判定为环境未就绪而非产品缺陷，脚本现在自行迁到 head。

## 四、依赖安全（本轮新增发现）

最终验收重跑 `npm audit --omit=dev` 时由 0 变 **1 high**：`source-map-js` GHSA-68fv-2mgg-jv7q
（区间 1.0.0–1.2.1，来源 `postcss`）。
**这不是本轮改动引入的**（本轮未触碰 postcss/source-map-js，属新公布公告），但已修复：
override 到 `^1.2.2` → 实际安装 **1.2.2**，审计回到 **total 0**，测试 267/0，tsc/lint/build 均 exit 0。

## 五、本轮**未验证 / 待验收**（不得当作通过）

1. 真实银行资料与签署人仍缺失（W11 银行验收未完成，见 `docs/upgrades/2026-10-03/w11/`）；
2. 未在业务库应用任何迁移；本轮新增迁移 `202610060001` 只在**全新隔离库**验证到 head；
3. 未改动 3000/8000 服务；未清共享 Redis（DB0 哨兵全程保留）；
4. 未调用未批准的真实模型（C06/C07 的模型边界为 spy，C10 子进程强制 mock）；
5. 未多机部署、未验证 broker/数据库高可用、未做容器镜像层扫描、未在 CI 上执行以上检查；
6. C09 的真实 Docker/Compose 执行未做（假工具链验证）。
