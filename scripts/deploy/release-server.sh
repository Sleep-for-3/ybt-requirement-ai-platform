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
BACKUP_DIR="${YBT_BACKUP_ROOT:-/data/ybt/backups}/release-${TAG}"
PIP_INDEX_URL="${PIP_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple}"
NPM_REGISTRY="${NPM_REGISTRY:-https://registry.npmmirror.com}"
API_BASE_URL="${NEXT_PUBLIC_API_BASE_URL:-http://localhost:8000/api}"

log() { printf '\n[%s] %s\n' "$(date -u +%H:%M:%S)" "$*"; }

log "1/6 备份：数据库 + 编排配置 + 当前镜像"
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
cp -a docker-compose.yml docker-compose.server.yml "$BACKUP_DIR/"
docker images --format '{{.Repository}}:{{.Tag}} {{.ID}} {{.CreatedAt}}' > "$BACKUP_DIR/images.txt"
sha256sum "$BACKUP_DIR/db.dump" | tee "$BACKUP_DIR/db.dump.sha256"
log "备份完成：$BACKUP_DIR（pg_restore 条目 $ENTRIES）"

log "2/6 构建后端镜像 ybt-backend:${TAG}"
docker build -t "ybt-backend:${TAG}" --build-arg "PIP_INDEX_URL=${PIP_INDEX_URL}" ./backend

log "3/6 构建前端镜像 ybt-frontend:${TAG}"
docker build -t "ybt-frontend:${TAG}" \
  --build-arg "NPM_REGISTRY=${NPM_REGISTRY}" \
  --build-arg "NEXT_PUBLIC_API_BASE_URL=${API_BASE_URL}" ./frontend

log "4/6 应用迁移（migrate 一次性服务）"
"${COMPOSE[@]}" run --rm migrate

log "5/6 启动全部服务"
"${COMPOSE[@]}" up -d

log "6/6 健康门禁"
for _ in $(seq 1 40); do
  if curl -fsS "http://127.0.0.1:${BACKEND_HOST_PORT:-8000}/health/ready" >/dev/null 2>&1; then
    curl -fsS "http://127.0.0.1:${BACKEND_HOST_PORT:-8000}/health/ready"; echo
    curl -fsS -o /dev/null -w 'frontend HTTP %{http_code}\n' "http://127.0.0.1:${FRONTEND_HOST_PORT:-3000}/"
    log "发布完成：${TAG}"
    "${COMPOSE[@]}" ps
    exit 0
  fi
  sleep 5
done

echo "健康检查未通过，请查看 docker compose logs backend migrate" >&2
"${COMPOSE[@]}" ps
exit 1
