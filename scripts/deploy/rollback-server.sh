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
cp -a .env "$TMP_ENV"
set_env_value YBT_RELEASE_TAG "$TARGET_TAG"
set_env_value APP_COMMIT "$TARGET_COMMIT"
set_env_value BUILD_TIME "$TARGET_BUILD_TIME"
mv -f "$TMP_ENV" .env
trap - EXIT

echo "[回滚] .env 已更新（标签与身份同步恢复）"
"${COMPOSE[@]}" up -d

API="http://127.0.0.1:${BACKEND_HOST_PORT:-8000}"
for _ in $(seq 1 40); do
  if curl -fsS "$API/health/ready" >/dev/null 2>&1; then
    break
  fi
  sleep 5
done

REPORT="$(curl -fsS "$API/version")" || { echo "回滚后无法读取 /version" >&2; exit 1; }
echo "$REPORT"
REPORTED="$(printf '%s' "$REPORT" | sed -n 's/.*"app_commit"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')"
if [[ "$REPORTED" != "$TARGET_COMMIT" ]]; then
  echo "回滚身份不一致：期望 $TARGET_COMMIT，实际 $REPORTED" >&2
  exit 1
fi

echo "[回滚] 完成：$TARGET_TAG（commit $REPORTED），身份与镜像一致"
"${COMPOSE[@]}" ps
exit 0
