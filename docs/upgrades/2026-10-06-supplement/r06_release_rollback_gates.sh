#!/usr/bin/env bash
# R06 回归：发布/回滚门禁（复制的真实脚本 + 假 docker/curl/git/sleep + 合成 .env）。
#
# 复现（docs/reviews/2026-10-06-followup/rollback-repro-result.json）：
#   all_ready_probes_failed: {"count": 40, "exit_code": 0, "tag_after": "release-A"}   ← 从未就绪却成功
#   compose_up_failed: {"exit_code": 99, "initial_tag": "release-B", "tag_after_failure": "release-A"}
#     ← compose 失败后 .env 已经改了，旧脚本仍按“成功/未声明”路径继续
#   release-server.sh：先 export 新 TAG，再从该变量取 PREVIOUS_TAG → “上一版”被记成当前版
#
# 只用合成 fixture；不执行任何真实部署、不接触业务库与镜像仓库。
set -uo pipefail

RELEASE_SRC="${1:?用法: r06_release_rollback_gates.sh <release-server.sh> <rollback-server.sh>}"
ROLLBACK_SRC="${2:?用法: r06_release_rollback_gates.sh <release-server.sh> <rollback-server.sh>}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

fail=0
check() {
  local label="$1" expected="$2" actual="$3"
  if [[ "$expected" == "$actual" ]]; then
    echo "  PASS  $label"
  else
    echo "  FAIL  $label（期望 [$expected]，实际 [$actual]）"
    fail=$((fail + 1))
  fi
}

mkdir -p "$WORK/bin" "$WORK/src/scripts/deploy" "$WORK/state" "$WORK/src/backend" "$WORK/src/frontend"
cp "$RELEASE_SRC" "$WORK/src/scripts/deploy/release-server.sh"
cp "$ROLLBACK_SRC" "$WORK/src/scripts/deploy/rollback-server.sh"
chmod +x "$WORK/src/scripts/deploy/"*.sh
touch "$WORK/src/docker-compose.yml" "$WORK/src/docker-compose.server.yml"

# ---------------- 假 docker：镜像身份 + compose 行为可编排 ----------------
cat > "$WORK/bin/docker" <<'FAKE'
#!/usr/bin/env bash
set -euo pipefail
STATE="${FAKE_STATE:?}"
args=("$@")
case "${args[0]:-}" in
  build)
    tag=""; commit=""; btime=""
    for a in "${args[@]}"; do
      case "$a" in
        ybt-backend:*|ybt-frontend:*) tag="$a" ;;
        NEXT_PUBLIC_APP_COMMIT=*) commit="${a#NEXT_PUBLIC_APP_COMMIT=}" ;;
        APP_COMMIT=*) [ -n "$commit" ] || commit="${a#APP_COMMIT=}" ;;
        NEXT_PUBLIC_BUILD_TIME=*) btime="${a#NEXT_PUBLIC_BUILD_TIME=}" ;;
        BUILD_TIME=*) [ -n "$btime" ] || btime="${a#BUILD_TIME=}" ;;
      esac
    done
    printf '%s %s %s\n' "$tag" "$commit" "$btime" >> "$STATE/images.log"
    ;;
  image)
    image="${args[2]:-}"; fmt="${args[4]:-}"
    line="$(grep -F "$image " "$STATE/images.log" | tail -n1 || true)"
    [[ -n "$line" ]] || exit 1
    if [[ "$fmt" == *"org.ybt.build.time"* ]]; then
      printf '%s\n' "$(printf '%s' "$line" | awk '{print $3}')"
    else
      printf '%s\n' "$(printf '%s' "$line" | awk '{print $2}')"
    fi
    ;;
  images) printf 'ybt-backend:test id\n' ;;
  compose)
    # `up -d` 可用 COMPOSE_UP_RC 编排失败。
    if [[ "${args[1]:-}" == "up" && -n "${COMPOSE_UP_RC:-}" ]]; then
      echo "[fake compose up rc=$COMPOSE_UP_RC]" >> "$STATE/compose.log"
      exit "$COMPOSE_UP_RC"
    fi
    if [[ "${args[1]:-}" == "exec" ]]; then
      # worker/beat 的上报：component_name() 返回角色名；build_version_info() 返回身份 JSON。
      if [[ "${args[4]:-}" == "python" ]]; then
        script="${args[6]:-}"
        if [[ "$script" == *component_name* ]]; then
          printf '%s\n' "${args[3]:-}"
        else
          printf '{"app_commit":"%s","build_time":"%s"}\n' "$(cat "$STATE/target_commit")" "$(cat "$STATE/target_build")"
        fi
        exit 0
      fi
      if [[ "${args[3]:-}" == "postgres" && "${args[6]:-}" == *pg_restore* ]]; then
        for i in $(seq 1 150); do echo "; entry $i"; done
      fi
    fi
    exit 0
    ;;
esac
exit 0
FAKE
chmod +x "$WORK/bin/docker"

# ---------------- 假 curl：ready 与 /version 可编排 ----------------
cat > "$WORK/bin/curl" <<'FAKE'
#!/usr/bin/env bash
set -euo pipefail
STATE="${FAKE_STATE:?}"
args=("$@")
url="${args[${#args[@]}-1]}"
case "$url" in
  */health/ready)
    echo "probe" >> "$STATE/ready.log"
    [[ "${FAKE_READY_OK:-0}" == "1" ]] || exit 22
    echo '{"status":"ready"}' ;;
  */version)
    printf '{"app_commit":"%s","build_time":"%s","schema_head":"x"}\n' \
      "$(cat "$STATE/target_commit")" "$(cat "$STATE/target_build")" ;;
  *) exit 0 ;;
esac
FAKE
chmod +x "$WORK/bin/curl"

cat > "$WORK/bin/git" <<'FAKE'
#!/usr/bin/env bash
set -euo pipefail
STATE="${FAKE_STATE:?}"
case "${1:-}" in
  rev-parse) cat "$STATE/head" ;;
  diff) exit 0 ;;
esac
exit 0
FAKE
chmod +x "$WORK/bin/git"

cat > "$WORK/bin/sha256sum" <<'FAKE'
#!/usr/bin/env bash
echo "0000  $1"
FAKE
chmod +x "$WORK/bin/sha256sum"

# sleep 立即返回，让 40 次就绪探测瞬间跑完。
printf '#!/usr/bin/env bash\nexit 0\n' > "$WORK/bin/sleep"
chmod +x "$WORK/bin/sleep"

export PATH="$WORK/bin:$PATH"
export FAKE_STATE="$WORK/state"

sync_env() { ln -sfn "$WORK/src/.env" "$WORK/state/live.env"; }
env_value() { grep -E "^$1=" "$WORK/src/.env" | head -n1 | cut -d= -f2-; }

setup_env() {
  cat > "$WORK/src/.env" <<'ENV'
POSTGRES_USER=ybt
YBT_RELEASE_TAG=release-A
APP_COMMIT=COMMIT_A
BUILD_TIME=2026-01-01T00:00:00Z
ENV
  sync_env
  echo COMMIT_B > "$WORK/state/head"
  echo COMMIT_A > "$WORK/state/target_commit"
  echo 2026-01-01T00:00:00Z > "$WORK/state/target_build"
  : > "$WORK/state/images.log"
  : > "$WORK/state/ready.log"
  : > "$WORK/state/compose.log"
  rm -f "$WORK/src/.env.pre-rollback" "$WORK/src/.env.pre-rollback.manifest"
}

# ---------------------------------------------------------------- R06-1
echo "== R06-1 从 A 发布 B：'上一版'必须记录为 A（不是新标签 B） =="
setup_env
printf 'ybt-backend:release-A COMMIT_A 2026-01-01T00:00:00Z\nybt-frontend:release-A COMMIT_A 2026-01-01T00:00:00Z\n' >> "$WORK/state/images.log"
printf 'ybt-backend:release-B COMMIT_B 2026-02-02T00:00:00Z\n' >> "$WORK/state/images.log"
echo COMMIT_B > "$WORK/state/target_commit"
echo 2026-02-02T00:00:00Z > "$WORK/state/target_build"
( cd "$WORK/src" && FAKE_READY_OK=1 YBT_RELEASE_COMMIT=COMMIT_B YBT_RELEASE_BUILD_TIME=2026-02-02T00:00:00Z \
    YBT_BACKUP_ROOT="$WORK/backups" \
    bash scripts/deploy/release-server.sh release-B >"$WORK/state/release-b.log" 2>&1 )
rc=$?
sync_env
PREV="$(grep -rh '^previous_tag=' "$WORK/backups" 2>/dev/null | head -n1 | cut -d= -f2- || true)"
check "发布 B 成功" "0" "$rc"
[[ $rc -eq 0 ]] || tail -6 "$WORK/state/release-b.log" | sed 's/^/    /'
check "备份记录里的 previous_tag 是 A" "release-A" "$PREV"
PREV_MANIFEST="$(grep -rh '^previous_tag=' "$WORK/backups" 2>/dev/null | wc -l | tr -d ' ')"
check "确实写出了 1 份身份记录" "1" "$PREV_MANIFEST"

# ---------------------------------------------------------------- R06-2
echo "== R06-2 ready 始终失败：回滚必须非零退出 =="
setup_env
printf 'ybt-backend:release-A COMMIT_A 2026-01-01T00:00:00Z\nybt-frontend:release-A COMMIT_A 2026-01-01T00:00:00Z\n' >> "$WORK/state/images.log"
echo COMMIT_A > "$WORK/state/target_commit"
echo 2026-01-01T00:00:00Z > "$WORK/state/target_build"
( cd "$WORK/src" && FAKE_READY_OK=0 bash scripts/deploy/rollback-server.sh release-A \
    >"$WORK/state/rb-unhealthy.log" 2>&1 )
rc=$?
sync_env
check "ready 全失败时非零退出" "1" "$([[ $rc -ne 0 ]] && echo 1 || echo 0)"
[[ $rc -ne 0 ]] || tail -6 "$WORK/state/rb-unhealthy.log" | sed 's/^/    /'
check "就绪探测确实跑了 40 次" "40" "$(wc -l < "$WORK/state/ready.log" | tr -d ' ')"
grep -q "始终未就绪" "$WORK/state/rb-unhealthy.log" \
  && echo "  PASS  日志明确说明就绪失败" || { echo "  FAIL  日志未说明就绪失败"; fail=$((fail + 1)); }

# ---------------------------------------------------------------- R06-3
echo "== R06-3 compose up 失败：非零退出且如实说明 .env 已被修改 =="
setup_env
printf 'ybt-backend:release-A COMMIT_A 2026-01-01T00:00:00Z\nybt-frontend:release-A COMMIT_A 2026-01-01T00:00:00Z\n' >> "$WORK/state/images.log"
echo COMMIT_A > "$WORK/state/target_commit"
echo 2026-01-01T00:00:00Z > "$WORK/state/target_build"
( cd "$WORK/src" && FAKE_READY_OK=1 COMPOSE_UP_RC=99 bash scripts/deploy/rollback-server.sh release-A \
    >"$WORK/state/rb-composefail.log" 2>&1 )
rc=$?
sync_env
check "compose 失败时非零退出" "1" "$([[ $rc -ne 0 ]] && echo 1 || echo 0)"
# 诚实：.env 确实已被改动，脚本必须这么说，而不是声称“失败不改 .env”。
check "回滚后 .env 的 TAG 已被改为目标标签" "release-A" "$(env_value YBT_RELEASE_TAG)"
grep -q "已经" "$WORK/state/rb-composefail.log" \
  && echo "  PASS  日志如实说明 .env 已改动" || { echo "  FAIL  日志未说明 .env 已改动"; fail=$((fail + 1)); }
[[ -f "$WORK/src/.env.pre-rollback" ]] \
  && echo "  PASS  保留了改动前的 .env 备份" || { echo "  FAIL  未保留 .env 备份"; fail=$((fail + 1)); }
[[ -f "$WORK/src/.env.pre-rollback.manifest" ]] \
  && echo "  PASS  保留了改动前的 manifest" || { echo "  FAIL  未保留 manifest"; fail=$((fail + 1)); }

# ---------------------------------------------------------------- R06-4
echo "== R06-4 正常回滚：ready 通过 + 完整身份（含 build_time 与组件）一致 =="
setup_env
printf 'ybt-backend:release-A COMMIT_A 2026-01-01T00:00:00Z\nybt-frontend:release-A COMMIT_A 2026-01-01T00:00:00Z\n' >> "$WORK/state/images.log"
echo COMMIT_A > "$WORK/state/target_commit"
echo 2026-01-01T00:00:00Z > "$WORK/state/target_build"
( cd "$WORK/src" && FAKE_READY_OK=1 bash scripts/deploy/rollback-server.sh release-A \
    >"$WORK/state/rb-ok.log" 2>&1 )
rc=$?
sync_env
check "正常回滚成功" "0" "$rc"
[[ $rc -eq 0 ]] || tail -8 "$WORK/state/rb-ok.log" | sed 's/^/    /'
check "回滚后 .env 的 commit 是目标" "COMMIT_A" "$(env_value APP_COMMIT)"
grep -q "worker 身份" "$WORK/state/rb-ok.log" \
  && echo "  PASS  核验了 worker 组件" || { echo "  FAIL  未核验 worker"; fail=$((fail + 1)); }
grep -q "beat 身份" "$WORK/state/rb-ok.log" \
  && echo "  PASS  核验了 beat 组件" || { echo "  FAIL  未核验 beat"; fail=$((fail + 1)); }

# ---------------------------------------------------------------- R06-5
echo "== R06-5 目标镜像不存在：拒绝回滚且不改动 .env =="
setup_env
: > "$WORK/state/images.log"
( cd "$WORK/src" && FAKE_READY_OK=1 bash scripts/deploy/rollback-server.sh release-Z \
    >"$WORK/state/rb-noimg.log" 2>&1 )
rc=$?
sync_env
check "无镜像时非零退出" "1" "$([[ $rc -ne 0 ]] && echo 1 || echo 0)"
check "拒绝回滚时 .env 的 TAG 未变" "release-A" "$(env_value YBT_RELEASE_TAG)"
[[ ! -f "$WORK/src/.env.pre-rollback" ]] \
  && echo "  PASS  未在改动 .env 前产生备份（确实提前退出）" \
  || { echo "  FAIL  提前退出前已改动 .env"; fail=$((fail + 1)); }

echo
if [[ "$fail" -eq 0 ]]; then
  echo "R06 RESULT: all checks passed"
  exit 0
fi
echo "R06 RESULT: $fail check(s) failed"
exit 1
