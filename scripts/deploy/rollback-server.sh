#!/usr/bin/env bash
# C09: 回滚脚本 —— 同时恢复**镜像标签**与**上报身份**。
#
#   scripts/deploy/rollback-server.sh <release-tag>
#
# 修复前的问题：发布脚本成功后会改写 .env 里的 APP_COMMIT / BUILD_TIME，却**不写 YBT_RELEASE_TAG**。
# 回滚文档让运维手工把 YBT_RELEASE_TAG 改回上一版，但 .env 里的身份仍是“被回滚那一版”的 commit，
# 于是镜像回到 A 而 /version 仍报 B —— 回滚后的系统会用错误的身份继续运行。
#
# 本脚本按顺序做三件事，任何一步失败即中止：
#   1. 校验目标标签的镜像确实存在，并读出它自带的构建身份（LABEL org.ybt.app.commit）；
#   2. 把 TAG / APP_COMMIT / BUILD_TIME 一起写回 .env（同一事务语义：先写临时文件再原子替换）；
#   3. 重新拉起 compose，并再次核对 /version 报告的身份与目标标签一致。
set -euo pipefail

TARGET_TAG="${1:?用法: scripts/deploy/rollback-server.sh <release-tag>}"
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$SOURCE_DIR"

[[ -f .env ]] || { echo "缺少 .env" >&2; exit 1; }

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml:docker-compose.server.yml}"
export COMPOSE_FILE
COMPOSE=(docker compose)

BACKEND_IMAGE="ybt-backend:${TARGET_TAG}"
FRONTEND_IMAGE="ybt-frontend:${TARGET_TAG}"

for IMAGE in "$BACKEND_IMAGE" "$FRONTEND_IMAGE"; do
  if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
    echo "回滚目标镜像不存在：$IMAGE（无法回滚到未构建过的标签）" >&2
    exit 1
  fi
done

# 以镜像自带的身份为准：这是当时真正构建出来的东西，而不是 .env 里可能已被覆盖的记录。
TARGET_COMMIT="$(docker image inspect "$BACKEND_IMAGE" \
  --format '{{index .Config.Labels "org.ybt.app.commit"}}' 2>/dev/null || true)"
TARGET_BUILD_TIME="$(docker image inspect "$BACKEND_IMAGE" \
  --format '{{index .Config.Labels "org.ybt.build.time"}}' 2>/dev/null || true)"
if [[ -z "$TARGET_COMMIT" ]]; then
  echo "镜像 $BACKEND_IMAGE 缺少构建身份标签，无法确定回滚后的身份，拒绝回滚" >&2
  exit 1
fi

echo "[回滚] 目标标签 $TARGET_TAG（commit $TARGET_COMMIT，build $TARGET_BUILD_TIME）"

# 原子写回：先写临时文件，全部成功后一次替换，避免中途失败留下自相矛盾的 .env。
TMP_ENV="$(mktemp ./.env.rollback.XXXXXX)"
trap 'rm -f "$TMP_ENV"' EXIT
set_env_value() {
  local key="$1" value="$2"
  if grep -q "^${key}=" "$TMP_ENV" 2>/dev/null; then
    sed -i "s|^${key}=.*|${key}=${value}|" "$TMP_ENV"
  else
    printf '%s=%s\n' "$key" "$value" >> "$TMP_ENV"
  fi
}
# R06: 在改动 .env **之前**保存原 manifest，并在失败时如实说明配置已被修改。
ORIGINAL_ENV_BACKUP=".env.pre-rollback"
cp -a .env "$ORIGINAL_ENV_BACKUP"
printf 'previous_tag=%s\nprevious_app_commit=%s\nprevious_build_time=%s\ntarget_tag=%s\ntarget_commit=%s\n' \
  "$(grep -E '^YBT_RELEASE_TAG=' ./.env | head -n1 | cut -d= -f2- || true)" \
  "$(grep -E '^APP_COMMIT=' ./.env | head -n1 | cut -d= -f2- || true)" \
  "$(grep -E '^BUILD_TIME=' ./.env | head -n1 | cut -d= -f2- || true)" \
  "$TARGET_TAG" "$TARGET_COMMIT" > "$ORIGINAL_ENV_BACKUP.manifest"

echo "[回滚] 原 .env 已保存到 $ORIGINAL_ENV_BACKUP（manifest: $ORIGINAL_ENV_BACKUP.manifest）"
cp -a .env "$TMP_ENV"
set_env_value YBT_RELEASE_TAG "$TARGET_TAG"
set_env_value APP_COMMIT "$TARGET_COMMIT"
set_env_value BUILD_TIME "$TARGET_BUILD_TIME"
mv -f "$TMP_ENV" .env
trap - EXIT

echo "[回滚] .env 已更新（标签与身份同步恢复）。注意：从这一刻起 .env 不再是改动前的配置。"
# R06: compose up 失败时不得默默继续 —— .env 已经改了，必须明确报告“已完成与未完成”的状态。
if ! "${COMPOSE[@]}" up -d; then
  echo "[回滚] 失败：docker compose up -d 未成功。.env **已经**被改为 ${TARGET_TAG}（旧配置备份在 $ORIGINAL_ENV_BACKUP）。" >&2
  echo "[回滚] 未完成：服务未按目标标签拉起，请修复后重跑，或用 $ORIGINAL_ENV_BACKUP 手动恢复配置。" >&2
  exit 1
fi
echo "[回滚] .env 已更新（标签与身份同步恢复）"
# （compose up 已在上方失败即退出的分支中处理）

API="http://127.0.0.1:${BACKEND_HOST_PORT:-8000}"
# R06 修复：就绪循环耗尽后必须**非零退出**。
# 旧实现在 40 次 ready 全失败后仍然继续，只要 /version 能读且 commit 相符就 exit 0 ——
# 一个“健康检查从未通过”的回滚会被当成成功。
READY=0
for _ in $(seq 1 40); do
  if curl -fsS "$API/health/ready" >/dev/null 2>&1; then
    READY=1
    break
  fi
  sleep 5
done
if [[ "$READY" -ne 1 ]]; then
  echo "[回滚] 失败：$API/health/ready 在 40 次探测内始终未就绪。.env 已是 ${TARGET_TAG}（备份 $ORIGINAL_ENV_BACKUP）。" >&2
  exit 1
fi

REPORT="$(curl -fsS "$API/version")" || { echo "回滚后无法读取 /version" >&2; exit 1; }
echo "$REPORT"
# R06: 核验**完整身份**（commit + build_time）而不只是 commit。
REPORTED="$(printf '%s' "$REPORT" | sed -n 's/.*"app_commit"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')"
REPORTED_BUILD="$(printf '%s' "$REPORT" | sed -n 's/.*"build_time"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')"
if [[ "$REPORTED" != "$TARGET_COMMIT" ]]; then
  echo "回滚身份不一致：期望 commit $TARGET_COMMIT，实际 $REPORTED" >&2
  exit 1
fi
if [[ -n "$TARGET_BUILD_TIME" && "$REPORTED_BUILD" != "$TARGET_BUILD_TIME" ]]; then
  echo "回滚身份不一致：期望 build_time $TARGET_BUILD_TIME，实际 $REPORTED_BUILD" >&2
  exit 1
fi
# R06: 与实际组件核对 —— worker/beat 也必須按自身角色上报同一身份。
for ROLE in worker beat; do
  ROLE_REPORT="$("${COMPOSE[@]}" exec -T "$ROLE" python -c \
    'import json;from app.services.version_info import build_version_info;print(json.dumps(build_version_info()))' 2>/dev/null || true)"
  if [[ -z "$ROLE_REPORT" ]]; then
    echo "回滚：$ROLE 未按自身角色上报身份，停止声明回滚成功" >&2
    exit 1
  fi
  ROLE_COMMIT="$(printf '%s' "$ROLE_REPORT" | sed -n 's/.*"app_commit"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')"
  if [[ "$ROLE_COMMIT" != "$TARGET_COMMIT" ]]; then
    echo "回滚：$ROLE 身份为 $ROLE_COMMIT，与目标 $TARGET_COMMIT 不一致" >&2
    exit 1
  fi
  echo "[回滚] $ROLE 身份：$ROLE_COMMIT"
done
curl -fsS -o /dev/null -w 'frontend HTTP %{http_code}\n' "http://127.0.0.1:${FRONTEND_HOST_PORT:-3000}/" || {
  echo "回滚：前端未响应，停止声明回滚成功" >&2
  exit 1
}

echo "[回滚] 完成：$TARGET_TAG（commit $REPORTED），身份与镜像一致"
"${COMPOSE[@]}" ps
exit 0
