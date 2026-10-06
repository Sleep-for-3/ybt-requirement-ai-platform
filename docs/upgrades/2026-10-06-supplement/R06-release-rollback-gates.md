# R06【C09，P1/P2】发布与回滚门禁

基线 `3db4db6`。复核复现：`docs/reviews/2026-10-06-followup/rollback-repro-result.json`
（复制真实脚本 + 假 docker/curl/sleep，未执行真实部署）。

## 1. 修复前证据

```json
{"reviewed_commit": "3db4db6",
 "all_ready_probes_failed": {"count": 40, "exit_code": 0, "tag_after": "release-A"},
 "compose_up_failed": {"exit_code": 99, "initial_tag": "release-B", "tag_after_failure": "release-A"}}
```

三个缺陷：

1. **「上一版」被记成当前版**（源码确认）：`release-server.sh` 先在 44 行 `export YBT_RELEASE_TAG="$TAG"`，
   再在第 87 行用 `${YBT_RELEASE_TAG:-}` 取 `PREVIOUS_TAG` —— 读到的是**本次**标签，
   回滚提示因此指向错误标签；
2. **就绪门禁形同虚设**：`rollback-server.sh` 的 `for _ in $(seq 1 40)` 循环耗尽后**没有失败判断**，
   只要 `/version` 可读且 commit 相符就 `exit 0` —— 40 次 `ready` 全失败也会被当成回滚成功；
3. **compose 失败后配置已变却未声明**：`docker compose up -d` 返回 99 时，`.env` 已经从 B 改成 A，
   而脚本按原路径继续，报告里“失败不改 `.env`”的笼统描述不成立。

## 2. 修复

| 文件 | 改动 |
| --- | --- |
| `scripts/deploy/release-server.sh` | `PREVIOUS_TAG` 改为**从 `.env` 文件**读取（不再读已 export 的变量），与 `PREVIOUS_APP_COMMIT` / `PREVIOUS_BUILD_TIME` 一致；新增「本次标签必须与上一版不同」的拒绝（相同标签无法区分两版） |
| `scripts/deploy/rollback-server.sh` | ① 改动 `.env` **之前**保存 `.env.pre-rollback` 与原 manifest（`previous_tag/previous_app_commit/previous_build_time/target_*`）；② 就绪循环用 `READY` 标志，40 次耗尽即**非零退出**并说明 `.env` 已是目标标签；③ `compose up` 失败即**非零退出**，并如实声明「`.env` 已经被改为 …（备份在 …）」与「未完成」；④ 身份核验扩展到 **commit + build_time**；⑤ 新增 **worker/beat 按自身角色上报**与实际组件核对；⑥ 前端 HTTP 探测失败即非零退出 |

> **诚实修正**：C09 记录里“失败不改 `.env`”只对**镜像校验阶段**成立（那一阶段确实还没碰 `.env`，
> R06-5 仍验证此点）；`compose up` 之后失败**确实会**留下已修改的 `.env`。本轮把这一点写进脚本输出与本文档，
> 不再笼统声称“失败不改 `.env`”。

## 3. 修复后证据

`docs/upgrades/2026-10-06-supplement/r06_release_rollback_gates.sh`（复制真实脚本 + 假 docker/curl/git/sleep）：

| 场景 | 断言 | 修复前 | 修复后 |
| --- | --- | --- | --- |
| R06-1 从 A 发布 B | 发布成功；备份记录 `previous_tag=release-A`（**不是** `release-B`）；确实写出 1 份身份记录 | ✖ | ✔ |
| R06-2 ready 始终失败 | **非零退出**；确实探测了 40 次；日志明确说明“始终未就绪” | ✖ | ✔ |
| R06-3 compose up 失败（rc=99） | 非零退出；`.env` 已被改为目标标签；日志**如实说明**已改动；保留 `.env` 备份与 manifest | ✖ | ✔ |
| R06-4 正常回滚 | 成功；身份为 `COMMIT_A`；核验了 **worker** 与 **beat** 组件 | ✖ | ✔ |
| R06-5 目标镜像不存在 | 非零退出；`.env` 未变；未在改动前产生备份（确实提前退出） | ✔ | ✔ |
| **合计** | | **8 failed / 6 passed** | **14/14 passed** |

命令与环境：
```
wsl bash docs/upgrades/2026-10-06-supplement/r06_release_rollback_gates.sh \
  scripts/deploy/release-server.sh scripts/deploy/rollback-server.sh
→ R06 RESULT: all checks passed（exit 0）
```
`bash -n` 对两个脚本均通过。环境：WSL bash + **假 `docker`/`curl`/`git`/`sleep`** + 合成 `.env` 与 fixture 备份根；
**未执行任何真实发布/回滚、未接触业务库、未改动 3000/8000 服务**。

「修复前」由 `git stash push -- scripts/deploy/*.sh` 后重跑同一份回归测得。

## 4. 保留的已成立能力

- C09：发布身份只来自构建清单或本次 git HEAD；备份后立即写回 `YBT_RELEASE_TAG`；
  镜像层 `LABEL org.ybt.app.commit` 核对；
- 「无目标镜像则拒绝回滚且不改动 `.env`」（R06-5 复验仍通过）。

## 5. 验证边界（未验证项）

1. **未在真实 Docker/Compose 上执行**：门禁与组件核对只由假工具链验证；
2. **未验证 `docker-compose.server.yml` 的真实选镜像行为**（沿用 C09 的源码确认前提）；
3. `worker`/`beat` 的 `component_name()` 真实返回值未在真实容器中核对（测试桩模拟角色上报）；
4. 未验证并发发布/回滚（同主机两个 release 同时执行）；
5. 未验证 `.env.pre-rollback` 的清理策略（脚本只写不删，长期多次回滚会累积文件）；
6. 未把 `YBT_RELEASE_COMMIT` 构建清单接入任何 CI；
7. 回滚不负责数据库回滚（与原 runbook 一致）。
