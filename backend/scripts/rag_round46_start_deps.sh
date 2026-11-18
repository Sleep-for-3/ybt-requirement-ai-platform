#!/usr/bin/env sh
set -eu

expected_milvus_id="${1:?verified round45 Milvus container ID required}"
postgres_env="${2:?private PostgreSQL env file required}"
prefix="rag-p0-r46"

case "$expected_milvus_id" in
  *[!0-9a-f]*|'') echo "invalid_round45_identity" >&2; exit 2 ;;
esac
[ "${#expected_milvus_id}" -eq 64 ] || { echo "invalid_round45_identity" >&2; exit 2; }
case "$postgres_env" in
  */.local-run/rag-long-run/private-round46/postgres.env) ;;
  *) echo "postgres_env_must_be_in_private_round46_directory" >&2; exit 2 ;;
esac
[ -r "$postgres_env" ] || { echo "private_postgres_env_unavailable" >&2; exit 2; }

actual_milvus_id="$(docker inspect --format '{{.Id}}' rag-p0-r45-milvus)"
milvus_status="$(docker inspect --format '{{.State.Status}}' rag-p0-r45-milvus)"
[ "$actual_milvus_id" = "$expected_milvus_id" ] || { echo "round45_milvus_identity_changed" >&2; exit 3; }
[ "$milvus_status" = "running" ] || { echo "round45_milvus_not_running" >&2; exit 3; }
docker exec rag-p0-r45-milvus curl -fsS --max-time 3 http://127.0.0.1:9091/healthz >/dev/null

for name in "$prefix-pg" "$prefix-redis"; do
  if docker ps -a --format '{{.Names}}' | grep -Fxq "$name"; then
    echo "round46_container_collision:$name" >&2
    exit 4
  fi
done
for volume in "$prefix-pg-data" "$prefix-redis-data"; do
  if docker volume ls --format '{{.Name}}' | grep -Fxq "$volume"; then
    echo "round46_volume_collision:$volume" >&2
    exit 4
  fi
done
if ss -H -ltn | awk '{print $4}' | grep -Eq ':(15441|16391)$'; then
  echo "round46_wsl_port_collision" >&2
  exit 4
fi

docker image inspect postgres:16 >/dev/null
docker image inspect redis:7-alpine >/dev/null
docker volume create "$prefix-pg-data" >/dev/null
docker volume create "$prefix-redis-data" >/dev/null
docker run -d --name "$prefix-pg" \
  --label rag.longrun.owner=round46 \
  --publish 127.0.0.1:15441:5432 \
  --mount "type=volume,src=$prefix-pg-data,dst=/var/lib/postgresql/data" \
  --env-file "$postgres_env" \
  --health-cmd "pg_isready -U ragp0 -d ragp0" \
  --health-interval 5s --health-timeout 5s --health-retries 20 \
  postgres:16 >/dev/null
docker run -d --name "$prefix-redis" \
  --label rag.longrun.owner=round46 \
  --publish 127.0.0.1:16391:6379 \
  --mount "type=volume,src=$prefix-redis-data,dst=/data" \
  --health-cmd "redis-cli ping" \
  --health-interval 5s --health-timeout 3s --health-retries 20 \
  redis:7-alpine redis-server --appendonly yes >/dev/null

wait_healthy() {
  name="$1"
  attempts=0
  while [ "$attempts" -lt 60 ]; do
    state="$(docker inspect --format '{{.State.Health.Status}}' "$name")"
    [ "$state" = "healthy" ] && return 0
    case "$state" in unhealthy|exited|dead) echo "round46_container_unhealthy:$name" >&2; return 5 ;; esac
    attempts=$((attempts + 1))
    sleep 2
  done
  echo "round46_container_health_timeout:$name" >&2
  return 6
}
wait_healthy "$prefix-pg"
wait_healthy "$prefix-redis"

printf '{"runtime":"round46","status":"dependencies_ready","milvus_container_id":"%s","postgres_container_id":"%s","redis_container_id":"%s","postgres_image_id":"%s","redis_image_id":"%s","provider_requests":0}\n' \
  "$actual_milvus_id" \
  "$(docker inspect --format '{{.Id}}' "$prefix-pg")" \
  "$(docker inspect --format '{{.Id}}' "$prefix-redis")" \
  "$(docker image inspect --format '{{.Id}}' postgres:16)" \
  "$(docker image inspect --format '{{.Id}}' redis:7-alpine)"
