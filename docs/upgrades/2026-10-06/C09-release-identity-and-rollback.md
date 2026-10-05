# C09（P1）：连续发布身份与回滚错配

基线 `fd7a532`。评审对 C09 只做了**源码确认**（`release-identity-repro-result.json` 记录 WSL 子进程
`E_ACCESSDENIED`，未执行模拟发布），因此本轮补上了**可执行的动态回归**。

## 1. 修复前证据（源码确认 + 本轮动态复现）

评审源码确认点：`scripts/deploy/release-server.sh` 的 39 / 59 / 63 行沿用 `.env` 中的
`APP_COMMIT` / `BUILD_TIME`，177—178 行写回这两个值但**不写 `TAG`**；
`docker-compose.server.yml:29` 按 `.env` 的标签选镜像。

本轮动态复现（`docs/upgrades/2026-10-06/c09_release_identity.sh`，假 docker/curl/git + 独立 fixture）：

```
== C09-1 连续发布 A -> B：B 必须报告 B，且 compose 仍选 B ==
  release A exit=0        ← 首次发布"成功"，但报告的是 .env 里继承的旧身份
  release B exit=1
  FAIL  发布 B 后 .env 的 TAG 指向 B（实际仍是 release-A）→ compose 仍选 A 镜像
  FAIL  发布 B 后 .env 的 commit 是 B（实际仍是 A）
  发布身份不一致：镜像内为 COMMIT_A，本次发布为 COMMIT_B_SHA   ← 门禁拦下了错误发布
== C09-3 镜像身份与本次发布不符 ==  mismatch exit=0   FAIL（旧门禁放行）
C09 RESULT: 4 check(s) failed
```

两个后果都在复现里出现：
1. **发布 B 会带着 A 的身份**（`.env` 继承）——即便门禁拦住，运维也拿不到“B 已发布”的结论；
2. **`YBT_RELEASE_TAG` 从不写回**，于是下一次 `docker compose up -d`（正是文档里的回滚步骤）
   仍然选上一版镜像，而 `.env` 里的 `APP_COMMIT` 已被改成新版 —— 镜像与身份错配。

## 2. 修改文件

| 文件 | 改动 |
| --- | --- |
| `scripts/deploy/release-server.sh` | ① `unset APP_COMMIT BUILD_TIME`，身份只来自**显式构建清单**（`YBT_RELEASE_COMMIT` / `YBT_RELEASE_BUILD_TIME`，供 CI）或**本次 git HEAD**；都没有即**停止发布**。② 备份完 `.env` 之后立即 `set_env_value YBT_RELEASE_TAG "$TAG"`（compose 按 .env 选镜像，必须**先**写回）。③ 成功后再写回 `APP_COMMIT` / `BUILD_TIME` / `YBT_RELEASE_TAG`。④ 新增**镜像层身份核对**：`docker image inspect --format '{{index .Config.Labels "org.ybt.app.commit"}}'`，缺标签或不一致即非零退出（不再只比较“几份标签是否互相一致”）。⑤ 备份记录中新增 `previous_tag` / `previous_app_commit` / `previous_build_time`。 |
| `backend/Dockerfile` | 新增 `LABEL org.ybt.app.commit` / `org.ybt.build.time`（由 `APP_COMMIT` / `BUILD_TIME` 构建参数注入） |
| `frontend/Dockerfile` | 同上，用 `NEXT_PUBLIC_APP_COMMIT` / `NEXT_PUBLIC_BUILD_TIME` |
| `scripts/deploy/rollback-server.sh` | **新增回滚脚本**：校验目标镜像存在并读出其自带身份 → 原子写回 `YBT_RELEASE_TAG` / `APP_COMMIT` / `BUILD_TIME` → 拉起 compose → 核对 `/version` 与目标身份一致；任一步失败即非零退出且**不改写 .env** |
| `docs/upgrades/2026-10-06/c09_release_identity.sh` | **新增动态回归**（假工具链，独立 fixture，不用真实部署/数据库/镜像） |

## 3. 修复后证据

```
== C09-1 连续发布 A -> B ==
  PASS  发布 A 成功
  PASS  发布 B 成功（身份自洽）
  PASS  发布 B 后 .env 的 TAG 指向 B（compose 因此选 B）
  PASS  发布 B 后 .env 的 commit 是 B
  PASS  镜像 release-B 烘焙的是 B 的 commit
  PASS  镜像 release-A 未被 B 污染
== C09-2 回滚到 A ==
  PASS  回滚脚本成功
  PASS  回滚后 .env 的 TAG 回到 A
  PASS  回滚后 .env 的 commit 回到 A
== C09-3 镜像身份与本次发布不符 ==
  发布身份不一致：镜像内为 WRONG_COMMIT，本次发布为 COMMIT_B_SHA
  PASS  身份不符时非零退出
== C09-4 回滚目标不存在 ==
  PASS  无镜像时回滚被拒绝（非零退出）
  PASS  拒绝回滚时不改写 .env 的 TAG
C09 RESULT: all checks passed
```

对比：**修复前 4 failed / 8 passed → 修复后 12/12 passed。**

命令与环境：
```
wsl bash docs/upgrades/2026-10-06/c09_release_identity.sh \
  scripts/deploy/release-server.sh scripts/deploy/rollback-server.sh
→ C09 RESULT: all checks passed（exit 0）
```
环境：WSL bash 5.2 + **假 `docker`/`curl`/`git`/`sha256sum`** + `mktemp` 独立 fixture；
**未执行任何真实发布、未接触业务数据库与镜像仓库、未改动 3000/8000 服务**。

> 回归保真度说明：假 `docker compose up -d` 之后，假 `curl` 按 **`.env` 实时的
> `YBT_RELEASE_TAG`** 决定“当前运行的镜像”，并返回**该镜像自己烘焙的** commit ——
> 因此“TAG 没写回就会起旧镜像”这一时序被真实建模。我起初用拷贝快照实现，
> 那会掩盖该时序（当时 C09-1 假通过），已改为 symlink 指向实时 `.env`。

## 4. 验证边界（未验证项）

1. **未在真实 Docker/Compose 上执行**：镜像标签门禁只由假 `docker` 验证（未真实 `docker build`）；
2. **未接入 CI**：`YBT_RELEASE_COMMIT` 构建清单尚未在任何流水线中注入（脚本已支持，接线未做）；
3. 未验证 `docker-compose.server.yml` 是否真的按 `${YBT_RELEASE_TAG}` 选镜像（本轮按源码确认接受该前提，未跑真实 compose）；
4. 回滚脚本**不负责数据库回滚**（与原 runbook 一致：DB 不回滚，兼容性另行确认）；
5. 未验证并发发布（同一主机两次 release 同时执行）；
6. `rollback-server.sh` 未加入离线 shell 静态检查（本机 WSL 无 shellcheck）。
