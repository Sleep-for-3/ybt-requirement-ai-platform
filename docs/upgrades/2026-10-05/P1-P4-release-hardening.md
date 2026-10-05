# 第三阶段：发布固化（lock/SBOM、发布身份、不可覆盖备份、失败退出与回滚）

本轮（2026-10-05）工作包之十一，对应复核项 **W01/N10/P1（lock 未进实际构建）**、**B18/P2（发布身份未注入未核对）**、**N12/P3（备份可被覆盖）** 与 **P4（失败未明确退出/回滚不可复跑）**。

## 1. 问题（修复前）

| 编号 | 问题 |
| --- | --- |
| P1 | `backend/requirements.lock.txt`（96 条精确 pin）与 `requirements.sbom.json` 只被单测检查**文件形态**，`backend/Dockerfile` 与 CI 三个后端作业全部安装**未固定的 `requirements.txt`**，重建可静默漂移。且 lock 在 Windows 上生成，含仅 Windows 的 `win32_setctime`，Linux 无法原样安装。 |
| P2 | `docker-compose.yml` 的 `backend`/`worker`/`beat` 共用 `*backend_environment`，**没有** `APP_COMMIT`/`BUILD_TIME`/`IMAGE_DIGEST`，三者都上报 `api`；前端构建只传 `NEXT_PUBLIC_API_BASE_URL`，不烘焙 `NEXT_PUBLIC_APP_COMMIT`/`BUILD_TIME`。发布脚本也不注入这些值，`/api/version` 只能显示打包回退值或 `unknown`。 |
| N12/P3 | `release-server.sh` 的 `BACKUP_DIR=".../backups/release-${TAG}"` —— **同一 TAG 重发会覆盖上一版 `db.dump`**，而那是回滚唯一的依据。 |
| P4 | 发布脚本只在 `/health/ready` 探活，**不核对** commit/schema/组件是否一致；失败时虽有 `exit 1`，但缺少“身份不一致即失败”的门禁与可复跑回滚说明。 |

## 2. 改动（修复后）

### 2.1 lock 真正进入构建（P1）

- `backend/requirements.lock.txt`：Windows 专属 pin 加上 PEP 508 标记
  `win32_setctime==1.2.0 ; sys_platform == "win32"`，使同一个 lock 能在 Linux 原样安装。
- `backend/Dockerfile`：改为
  ```dockerfile
  COPY requirements.txt requirements.lock.txt ./
  RUN pip install --no-cache-dir --index-url "${PIP_INDEX_URL}" -r requirements.lock.txt \
   && pip check
  ```
- `.github/workflows/ci.yml`（三个后端作业）与 `.github/workflows/smoke.yml`：`cache-dependency-path`
  与安装命令都改为 lock，并追加 `python -m pip check`。

### 2.2 发布身份自动注入并强制核对（P2/P4）

- `docker-compose.yml`：共享锚点新增 `APP_COMMIT`/`BUILD_TIME`/`IMAGE_DIGEST`（默认 `unknown`，**故意可见**）
  与 `SERVICE_COMPONENT: api`；`worker`/`beat` 用 YAML merge 覆盖为各自的角色名
  （`<<: *backend_environment` + `SERVICE_COMPONENT: worker|beat`），使四个组件可被**比对**而不是都自称 `api`。
- `docker-compose.yml` 前端 `build.args` 增加 `NEXT_PUBLIC_APP_COMMIT`/`NEXT_PUBLIC_BUILD_TIME`/`NEXT_PUBLIC_SCHEMA_HEAD`；
  `frontend/Dockerfile` 增加对应 `ARG`/`ENV`。
- `.env.production.example`：补声明四个新变量（满足“compose 用到的变量必须在模板声明”的既有契约）。
- `backend/Dockerfile`：新增 `ARG APP_COMMIT/BUILD_TIME`，并在 **`COPY . .` 之后**写入
  `/app/build-info.json` 作为 `version_info` 的打包回退（放在 COPY 之后，仓库内的同名文件无法覆盖注入值）。
- `scripts/deploy/release-server.sh`：
  - 身份**只解析一次**（`git rev-parse HEAD`，脏工作区得到 `<sha>-dirty`；无法确定则拒绝发布），
    同一组值分别传给后端 `--build-arg` 与前端 `--build-arg`；
  - 新增**发布身份门禁**：`/version` 的 `app_commit` 为空/`unknown` → 失败；与本次发布不一致 → 失败；
    `schema_head` 读不到 → 失败（“读不到”不能被当成“一致”）；
  - 逐个进入 `worker`/`beat` 容器执行 `component_name()`，角色不符即失败；
  - 成功后把身份写回 `.env`（键缺失时追加，不只是 `sed`），并打印**可复跑的回滚步骤**。

### 2.3 备份不可覆盖（N12/P3）

- `BACKUP_DIR="${BACKUP_ROOT}/release-${TAG}-${STAMP}-$$"`（UTC 时间戳 + PID），并在创建前
  `[[ -e "$BACKUP_DIR" ]] && exit 1` 拒绝覆盖。
- 备份目录内新增 `release-identity.txt`（`release_tag`/`app_commit`/`build_time`），使事故复盘能把
  dump 与具体构建绑定，而不是靠时间戳猜。

## 3. 验证（本轮已完成，全部新鲜执行）

### 3.1 单元/契约测试

```
cd backend; $env:TASK_QUEUE_PROVIDER='inline'; $env:AUTH_MODE='optional'
.venv\Scripts\python.exe -m pytest tests/test_deployment_contract.py tests/test_release_baseline.py -q
→ 22 passed
```

新增契约断言（既有断言未被删除，只按新语义细化）：
- `test_docker_and_ci_install_from_the_lock_not_the_range_file`：Dockerfile 含 lock 且**不含** `-r requirements.txt`；
  CI 中**不得**出现 `-r backend/requirements.txt`，且 lock 安装 ≥3 处。
- `test_the_lock_marks_platform_specific_pins_instead_of_shipping_them_blindly`：平台专属 pin 必须带标记。
- `test_release_identity_is_injected_and_never_fabricated`、`test_the_frontend_bakes_the_same_release_identity`。
- `test_api_worker_beat_and_migrate_share_one_environment_contract`：**只**豁免 `SERVICE_COMPONENT`，其余键仍必须完全一致。
- `test_the_release_backup_directory_can_never_be_reused`、`test_the_release_script_injects_and_verifies_release_identity`、
  `test_the_packaged_build_info_is_written_after_the_source_copy`。

### 3.2 真实 Linux 容器验证（WSL Docker）

**lock 可安装**（`docs/upgrades/2026-10-05/verify_lock_linux.sh`，`python:3.12-slim`）：
```
No broken requirements found. / LINUX-LOCK-OK / INSTALLED_COUNT=96 / CONTAINER_RC=0
```

**发布身份真实构建**（`docs/upgrades/2026-10-05/verify_release_identity.sh`）：
```
COMMIT=0cd19ff06d1d264e418747a7eeb4aed18c955594
--- baked fallback (no env injected) ---   BAKED_COMMIT=0cd19ff06d1d264e418747a7eeb4aed18c955594
                                           BAKED_BUILT=2026-10-05T00:00:00Z
--- runtime environment wins ---            ENV_OVERRIDE_OK
--- lock really installed (not the range) --- LOCK_MATCH=96
--- component identity is per-role ---      ROLE_OK=api / ROLE_OK=worker / ROLE_OK=beat
IDENTITY_VERIFY_OK   (exit 0)
```
即：镜像内安装的 96 个包版本与 lock **逐一相符**（marker 排除的 Windows 包允许缺失），
打包身份等于传入的 commit，环境变量仍优先，三个角色各自上报正确组件名。

**备份唯一性**（`docs/upgrades/2026-10-05/verify_backup_uniqueness.sh`）：
```
NAMING_OK / UNIQUE_OK / GUARD_OK / IDENTITY_RECORD_OK / ROLLBACK_HINT_OK / FAILURES=0 / BACKUP_UNIQUENESS_OK
```

**Shell 语法**：`bash -n scripts/deploy/release-server.sh` → exit 0（容器内无 shellcheck，未做 lint）。

## 4. 未验证 / 边界（不得当作通过）

1. **未在真实服务器执行端到端发布**：本机没有 Ubuntu 22.04 + `/data/ybt` 的生产目标机，
   也未跑 `docker compose up`（会改动本机运行中的实例）。因此身份门禁的**运行期**分支
   （`/version` 比对、worker/beat 进容器探测、`.env` 写回）只做了静态契约 + 语法制约，
    **没有真实触发过 `exit 1` 路径**。待验收条件：在目标机执行
   `scripts/deploy/release-server.sh <tag>`，并用一个故意错误的 `APP_COMMIT` 复跑，确认发布被拒绝。
2. **SBOM 仍是“源侧清单”**：`requirements.sbom.json` 由开发机 venv 生成，本轮使其与**实际安装集合**
   通过 lock 对齐（`LOCK_MATCH=96`），但**尚未由构建产物反向生成**（例如扫描镜像）。若需镜像级 SBOM，
   应接入 `syft`/`docker sbom` 并在 CI 中比对 lock，属后续工作。
3. **`IMAGE_DIGEST` 仍为 `unknown`**：变量已贯通 compose，但发布脚本未在 `docker build` 后回填镜像
   digest（需要 `docker images --digests` 或 `buildx --provenance`），因此该字段目前只是可注入占位。
4. **Docker 基础镜像未固定 digest**：`python:3.12-slim`、`node:24-alpine` 仍按 tag 拉取，
   镜像级可复现性未闭环。
5. **前端 schema 头未核对**：`NEXT_PUBLIC_SCHEMA_HEAD` 可注入但发布门禁未比对它与后端实际 schema。
6. 本轮只覆盖发布面；**第四阶段（合成工程 UAT 闭环）与第五阶段（评测/恢复/容量）尚未开始**。
