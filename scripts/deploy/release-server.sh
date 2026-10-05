#!/usr/bin/env bash
# 服务器端发布脚本：备份 -> 构建不可变镜像 -> 迁移 -> 滚动重启 -> 健康门禁。
#
#   scripts/deploy/release-server.sh <release-tag>
#
# 约定：
#   * 在源码目录（含 docker-compose.yml 与 .env 的目录）执行；
#   * 只使用本机已有的基础镜像与国内依赖源，不依赖 Docker Hub / GitHub 直连；
#   * 不删除任何数据卷，不执行 `docker compose down -v`；
#   * 迁移由 compose 的 migrate 一次性服务执行，API/Worker/Beat 必须等它成功。
#
# 回滚：把 .env 里的 YBT_RELEASE_TAG 改回上一版标签，再执行
#   docker compose -f docker-compose.yml -f docker-compose.server.yml up -d
# 数据库不需要回滚（回滚目标与当前 revision 的兼容性见《发布与恢复 Runbook》）。

set -euo pipefail

TAG="${1:?用法: scripts/deploy/release-server.sh <release-tag>}"
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$SOURCE_DIR"

[[ -f .env ]] || { echo "缺少 .env（生产密钥不在 Git 里，需要服务器本地维护）" >&2; exit 1; }

# 不能直接 `source .env`：生产 .env 里存在带空格的值（例如 APP_NAME），
# shell 会把空格后面的部分当成命令执行。这里按 KEY=VALUE 逐行安全加载。
load_env_file() {
  local file="$1" line key value
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ "$line" =~ ^[[:space:]]*# ]] && continue
    [[ "$line" != *=* ]] && continue
    key="${line%%=*}"
    value="${line#*=}"
    key="${key//[[:space:]]/}"
    [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
    export "$key=$value"
  done < "$file"
}

load_env_file ./.env

export COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml:docker-compose.server.yml}"
# 用命令行参数覆盖 .env 里的标签，保证“构建的镜像”与“启动的镜像”是同一个。
export YBT_RELEASE_TAG="$TAG"
COMPOSE=(docker compose)
BACKUP_ROOT="${YBT_BACKUP_ROOT:-/data/ybt/backups}"
# N12/P3: a backup directory must never be reused. Re-releasing the same tag used to overwrite the
# previous ``db.dump`` with a fresh one, silently destroying the only copy of the pre-release state.
# The directory is therefore made unique per run; the tag stays in the name so operators can find it.
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP_DIR="${BACKUP_ROOT}/release-${TAG}-${STAMP}-$$"
[[ -e "$BACKUP_DIR" ]] && { echo "备份目录已存在，拒绝覆盖：$BACKUP_DIR" >&2; exit 1; }
PIP_INDEX_URL="${PIP_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple}"
NPM_REGISTRY="${NPM_REGISTRY:-https://registry.npmmirror.com}"
API_BASE_URL="${NEXT_PUBLIC_API_BASE_URL:-http://localhost:8000/api}"

# B18/P2 + C09: resolve the release identity *once* and give the same values to the backend containers
# and the frontend build, so all four components are comparable afterwards. A dirty worktree produces
# a suffixed commit (<sha>-dirty) instead of silently pretending to be the clean revision.
#
# C09: the identity must describe **this** build. ``load_env_file`` above exports the APP_COMMIT /
# BUILD_TIME that a previous release wrote back into .env, so reading them here would make release B
# inherit release A's identity. Only an explicit build manifest (CI-provided) or this worktree's git
# HEAD may decide it; anything else stops the release instead of guessing.
unset APP_COMMIT BUILD_TIME 2>/dev/null || true
MANIFEST_COMMIT="${YBT_RELEASE_COMMIT:-}"
MANIFEST_BUILD_TIME="${YBT_RELEASE_BUILD_TIME:-}"
if [[ -n "$MANIFEST_COMMIT" ]]; then
  APP_COMMIT="$MANIFEST_COMMIT"
else
  APP_COMMIT="$(git rev-parse HEAD 2>/dev/null || echo unknown)"
fi
if [[ "$APP_COMMIT" != unknown ]] && ! git diff --quiet HEAD -- 2>/dev/null; then
  APP_COMMIT="${APP_COMMIT}-dirty"
fi
# Same reasoning for the build time: a manifest value wins, otherwise stamp this run.
BUILD_TIME="${MANIFEST_BUILD_TIME:-$(date -u +%Y-%m-%dT%H:%M:%SZ)}"
SCHEMA_HEAD="${SCHEMA_HEAD:-}"
export APP_COMMIT BUILD_TIME SCHEMA_HEAD

if [[ "$APP_COMMIT" == unknown ]]; then
  echo "无法确定发布提交（不在 git 工作区且未提供 YBT_RELEASE_COMMIT 构建清单），停止发布" >&2
  exit 1
fi

# C09: remember the identity the *previous* release left in .env, so a rollback can restore both the
# image tag and the reported identity instead of leaving .env describing the release being undone.
PREVIOUS_TAG="$(printf '%s' "${YBT_RELEASE_TAG:-}")"
PREVIOUS_APP_COMMIT="$(grep -E '^APP_COMMIT=' ./.env 2>/dev/null | head -n1 | cut -d= -f2- || true)"
PREVIOUS_BUILD_TIME="$(grep -E '^BUILD_TIME=' ./.env 2>/dev/null | head -n1 | cut -d= -f2- || true)"
log() { printf '\n[%s] %s\n' "$(date -u +%H:%M:%S)" "$*"; }

# C09: ``docker compose up -d`` selects images by ``YBT_RELEASE_TAG`` from .env, so the tag must be
# pinned **before** any compose call in this release. Previously it was written only after the health
# gate, so compose brought up the PREVIOUS image while the gate expected this release's commit.
set_env_value() {
  local key="$1" value="$2" file=".env"
  if grep -q "^${key}=" "$file" 2>/dev/null; then
    sed -i "s|^${key}=.*|${key}=${value}|" "$file"
  else
    printf '%s=%s\n' "$key" "$value" >> "$file"
  fi
}


log "1/6 备份：数据库 + 编排配置 + 当前镜像（不可覆盖目录）"
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"
"${COMPOSE[@]}" exec -T postgres sh -c \
  'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc -f /tmp/release.dump'
"${COMPOSE[@]}" exec -T postgres sh -c 'pg_restore --list /tmp/release.dump' > "$BACKUP_DIR/db.contents.txt"
"${COMPOSE[@]}" exec -T postgres sh -c 'cat /tmp/release.dump' > "$BACKUP_DIR/db.dump"
"${COMPOSE[@]}" exec -T postgres rm -f /tmp/release.dump
ENTRIES="$(grep -c ';' "$BACKUP_DIR/db.contents.txt" || true)"
[[ "$ENTRIES" -gt 100 ]] || { echo "备份条目数异常（$ENTRIES），停止发布" >&2; exit 1; }
cp -a .env "$BACKUP_DIR/env"
# C09: only now (after the pre-release .env is safely backed up) pin the tag this release will run.
set_env_value YBT_RELEASE_TAG "$TAG"
cp -a docker-compose.yml docker-compose.server.yml "$BACKUP_DIR/"
docker images --format '{{.Repository}}:{{.Tag}} {{.ID}} {{.CreatedAt}}' > "$BACKUP_DIR/images.txt"
# B18/P2: record the identity this release claims, so a later incident review can tell which build
# produced the dump without guessing from timestamps.
printf 'release_tag=%s\napp_commit=%s\nbuild_time=%s\nprevious_tag=%s\nprevious_app_commit=%s\nprevious_build_time=%s\n' \
  "$TAG" "$APP_COMMIT" "$BUILD_TIME" "$PREVIOUS_TAG" "$PREVIOUS_APP_COMMIT" "$PREVIOUS_BUILD_TIME" > "$BACKUP_DIR/release-identity.txt"
sha256sum "$BACKUP_DIR/db.dump" | tee "$BACKUP_DIR/db.dump.sha256"
log "备份完成：$BACKUP_DIR（pg_restore 条目 $ENTRIES）"

log "2/6 构建后端镜像 ybt-backend:${TAG}（commit ${APP_COMMIT}）"
docker build -t "ybt-backend:${TAG}" \
  --build-arg "PIP_INDEX_URL=${PIP_INDEX_URL}" \
  --build-arg "APP_COMMIT=${APP_COMMIT}" \
  --build-arg "BUILD_TIME=${BUILD_TIME}" ./backend

log "3/6 构建前端镜像 ybt-frontend:${TAG}"
docker build -t "ybt-frontend:${TAG}" \
  --build-arg "NPM_REGISTRY=${NPM_REGISTRY}" \
  --build-arg "NEXT_PUBLIC_API_BASE_URL=${API_BASE_URL}" \
  --build-arg "NEXT_PUBLIC_APP_COMMIT=${APP_COMMIT}" \
  --build-arg "NEXT_PUBLIC_BUILD_TIME=${BUILD_TIME}" \
  --build-arg "NEXT_PUBLIC_SCHEMA_HEAD=${SCHEMA_HEAD}" ./frontend

log "4/6 应用迁移（migrate 一次性服务）"
"${COMPOSE[@]}" run --rm migrate

log "5/6 启动全部服务"
"${COMPOSE[@]}" up -d

log "6/6 健康与发布身份门禁"
API="http://127.0.0.1:${BACKEND_HOST_PORT:-8000}"
READY=0
for _ in $(seq 1 40); do
  if curl -fsS "$API/health/ready" >/dev/null 2>&1; then
    READY=1
    break
  fi
  sleep 5
done

if [[ "$READY" -ne 1 ]]; then
  echo "健康检查未通过，请查看 docker compose logs backend migrate" >&2
  "${COMPOSE[@]}" ps
  exit 1
fi

curl -fsS "$API/health/ready"; echo

# B18/P2: a release is only trustworthy when every component reports the same commit/build time.
# This gate is deliberately fail-closed: ``unknown`` never passes, because "we could not tell" must
# not be presented as "the versions match".
log "核对发布身份（期望 commit ${APP_COMMIT}）"
REPORT="$(curl -fsS "$API/version")" || { echo "无法读取 /version" >&2; exit 1; }
echo "$REPORT"
EXPECTED_COMMIT="$(printf '%s' "$REPORT" | sed -n 's/.*"app_commit"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')"
REPORTED_SCHEMA="$(printf '%s' "$REPORT" | sed -n 's/.*"schema_head"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')"

if [[ -z "$EXPECTED_COMMIT" || "$EXPECTED_COMMIT" == unknown ]]; then
  echo "API 未能上报发布提交（app_commit=$EXPECTED_COMMIT），停止发布" >&2
  exit 1
fi
if [[ "$EXPECTED_COMMIT" != "$APP_COMMIT" ]]; then
  echo "发布身份不一致：镜像内为 $EXPECTED_COMMIT，本次发布为 $APP_COMMIT" >&2
  exit 1
fi
if [[ -z "$REPORTED_SCHEMA" || "$REPORTED_SCHEMA" == null ]]; then
  echo "API 未能读取数据库 schema 版本，无法证明迁移已生效，停止发布" >&2
  exit 1
fi

# The worker and beat must independently report the *same* identity; if either still says "api" the
# component override was lost and the comparison would be meaningless.
for ROLE in worker beat; do
  ROLE_REPORT="$("${COMPOSE[@]}" exec -T "$ROLE" python -c \
    'from app.services.version_info import component_name; print(component_name())' 2>/dev/null | tr -d '\r' || true)"
  if [[ "$ROLE_REPORT" != "$ROLE" ]]; then
    echo "$ROLE 未按自身角色上报（返回：$ROLE_REPORT），停止发布" >&2
    exit 1
  fi
  echo "$ROLE 身份：$ROLE_REPORT"
done

# C09: the gate must check the **actual running components**, not just prove that a few (possibly
# identically wrong) labels agree with each other. Each published image carries its own identity; if a
# stale image is still running under the new tag, the labels below would agree while the process is old.
for IMAGE in "ybt-backend:${TAG}" "ybt-frontend:${TAG}"; do
  IMAGE_COMMIT="$(docker image inspect "$IMAGE" \
    --format '{{index .Config.Labels "org.ybt.app.commit"}}' 2>/dev/null || true)"
  if [[ -z "$IMAGE_COMMIT" ]]; then
    echo "镜像 $IMAGE 缺少构建身份标签，无法核对本次构建，停止发布" >&2
    exit 1
  fi
  if [[ "$IMAGE_COMMIT" != "$APP_COMMIT" ]]; then
    echo "镜像 $IMAGE 的身份为 $IMAGE_COMMIT，与本次发布 $APP_COMMIT 不一致，停止发布" >&2
    exit 1
  fi
  echo "$IMAGE 镜像标签身份：$IMAGE_COMMIT"
done

curl -fsS -o /dev/null -w 'frontend HTTP %{http_code}\n' "http://127.0.0.1:${FRONTEND_HOST_PORT:-3000}/"
# P2: persist the identity back into .env so a later manual ``docker compose up -d`` (the documented
# rollback step) keeps reporting the same release instead of silently reverting to ``unknown``.
# ``sed`` alone would do nothing when the key is absent, so append in that case.
# C09: persist the **tag** as well. Without it, the next ``docker compose ... up -d`` (the documented
# rollback step) would rebuild the identity from .env while compose still selected the image by the
# old tag, so commit and image could disagree.
set_env_value APP_COMMIT "$APP_COMMIT"
set_env_value BUILD_TIME "$BUILD_TIME"
set_env_value YBT_RELEASE_TAG "$TAG"
log "发布完成：${TAG}（commit ${APP_COMMIT}，schema ${REPORTED_SCHEMA}，上一版 ${PREVIOUS_TAG:-无}）"
# C09: roll back with the helper, which restores the image tag **and** the reported identity together.
log "回滚：scripts/deploy/rollback-server.sh ${PREVIOUS_TAG:-<上一版标签>}（备份与身份记录见 $BACKUP_DIR）"
"${COMPOSE[@]}" ps
exit 0
