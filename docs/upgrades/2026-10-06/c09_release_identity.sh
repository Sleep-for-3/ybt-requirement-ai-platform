#!/usr/bin/env bash
# C09 回归：连续发布身份与回滚（用假 docker/curl/git 在独立 fixture 中驱动真实脚本）。
#
# 复现前的问题：
#   * release-server.sh 从 .env 继承 APP_COMMIT / BUILD_TIME（上一版发布自己写回的），
#     于是发布 B 会报告 A 的 commit；
#   * 成功后只写 APP_COMMIT / BUILD_TIME，**不写 YBT_RELEASE_TAG**；
#   * 门禁只比较“几份标签是否互相一致”，不检查真正构建出来的镜像。
#
# 模型（尽量贴近真实语义）：
#   * `docker build` 把身份写进镜像（这里记到 images.log）；
#   * `docker compose up -d` 按 .env 里的 YBT_RELEASE_TAG 选镜像；
#   * `/version` 报告**当前被选中镜像**自己烘焙的 commit —— 因此如果 .env 的 TAG 没被写对，
#     起来的仍是上一版镜像，它会如实报告上一版的 commit。
#
# 本脚本只用合成 fixture，不接触任何真实部署、数据库或镜像仓库。
set -uo pipefail

SCRIPT_SRC="${1:?用法: c09_release_identity.sh <release-server.sh 路径> <rollback-server.sh 路径>}"
ROLLBACK_SRC="${2:?用法: c09_release_identity.sh <release-server.sh> <rollback-server.sh>}"
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

mkdir -p "$WORK/bin" "$WORK/src/scripts/deploy" "$WORK/state"
cp "$SCRIPT_SRC" "$WORK/src/scripts/deploy/release-server.sh"
cp "$ROLLBACK_SRC" "$WORK/src/scripts/deploy/rollback-server.sh"
chmod +x "$WORK/src/scripts/deploy/"*.sh
touch "$WORK/src/docker-compose.yml" "$WORK/src/docker-compose.server.yml"
: > "$WORK/state/images.log"

# ---------------------------------------------------------------- 假工具链
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
    # 后门：模拟“镜像烘焙的身份与本次发布不符”的事故。
    [ -n "${FAKE_BUILD_COMMIT:-}" ] && commit="$FAKE_BUILD_COMMIT"
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
  images)
    printf 'ybt-backend:test %s\n' "$(date -u +%Y%m%dT%H%M%SZ)"
    ;;
  compose)
    # `docker compose exec -T <role> python -c '...'` → 让 worker/beat 按自身角色上报。
    if [[ "${args[1]:-}" == "exec" && "${args[4]:-}" == "python" ]]; then
      printf '%s\n' "${args[3]:-}"
      exit 0
    fi
    # `docker compose exec -T postgres sh -c '<script>'` → [0]=compose [1]=exec [2]=-T
    # [3]=postgres [4]=sh [5]=-c [6]=<script>
    if [[ "${args[1]:-}" == "exec" && "${args[3]:-}" == "postgres" && "${args[6]:-}" == *pg_restore* ]]; then
      for i in $(seq 1 150); do echo "; entry $i"; done
    fi
    exit 0
    ;;
esac
exit 0
FAKE
chmod +x "$WORK/bin/docker"

cat > "$WORK/bin/curl" <<'FAKE'
#!/usr/bin/env bash
set -euo pipefail
STATE="${FAKE_STATE:?}"
args=("$@")
url="${args[${#args[@]}-1]}"
case "$url" in
  */health/ready) echo '{"status":"ready"}' ;;
  */version)
    # 当前被选中的镜像 = 脚本刚刚写入的 .env 里 YBT_RELEASE_TAG 对应的镜像。
    # 必须读**实时** .env：脚本会在发布过程中改写它（这正是本项回归要验证的时序）。
    tag="$(grep -E '^YBT_RELEASE_TAG=' "${FAKE_STATE}/live.env" 2>/dev/null | cut -d= -f2- || true)"
    if [[ -z "$tag" ]]; then
      echo '{"app_commit":"unknown","build_time":"unknown","schema_head":"x"}'
      exit 0
    fi
    line="$(grep -F "ybt-backend:${tag} " "$STATE/images.log" | tail -n1 || true)"
    if [[ -z "$line" ]]; then
      echo '{"app_commit":"unknown","build_time":"unknown","schema_head":"x"}'
      exit 0
    fi
    printf '{"app_commit":"%s","build_time":"%s","schema_head":"202610060001"}\n' \
      "$(printf '%s' "$line" | awk '{print $2}')" "$(printf '%s' "$line" | awk '{print $3}')"
    ;;
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
echo "0000000000000000000000000000000000000000000000000000000000000000  $1"
FAKE
chmod +x "$WORK/bin/sha256sum"

export PATH="$WORK/bin:$PATH"
export FAKE_STATE="$WORK/state"

# env 每次变更后同步到 state，供假 curl 读取（模拟“容器按 .env 选镜像”）。
# 脚本改写 .env 后，假 curl 必须能看到最新内容（模拟 compose/容器读取实时配置）。
# 用 symlink 而非拷贝，避免“快照”掩盖本项回归要验证的时序问题。
sync_env() { ln -sfn "$WORK/src/.env" "$WORK/state/live.env"; }

setup() {
  cat > "$WORK/src/.env" <<'ENV'
POSTGRES_USER=ybt
POSTGRES_DB=ybt
APP_NAME=银行 智能 平台
YBT_RELEASE_TAG=release-A
APP_COMMIT=COMMIT_A
BUILD_TIME=2026-01-01T00:00:00Z
ENV
  sync_env
}

release() {
  local tag="$1" commit="$2"
  # 没有 git 工作区时，发布脚本要求显式构建清单（YBT_RELEASE_COMMIT）——这正是 C09 引入的门禁。
  ( cd "$WORK/src" && YBT_RELEASE_COMMIT="$commit" \
      YBT_RELEASE_BUILD_TIME="2026-02-02T00:00:00Z" \
      bash scripts/deploy/release-server.sh "$tag" >"$WORK/state/release-${tag}.log" 2>&1 )
  local rc=$?
  if [[ $rc -ne 0 ]]; then
    echo "  --- release ${tag} 日志（末 12 行）---"
    tail -12 "$WORK/state/release-${tag}.log" | sed 's/^/    /'
  fi
  sync_env
  return $rc
}

env_value() { grep -E "^$1=" "$WORK/src/.env" | cut -d= -f2-; }
image_commit() { grep -F "ybt-backend:$1 " "$WORK/state/images.log" | tail -n1 | awk '{print $2}'; }

echo "== C09-1 连续发布 A -> B：B 必须报告 B，且 compose 仍选 B =="
setup
# 先让 release-A 的镜像存在（模拟上一版已发布）。
: > "$WORK/state/images.log"
printf 'ybt-backend:release-A COMMIT_A 2026-01-01T00:00:00Z\n' >> "$WORK/state/images.log"
printf 'ybt-frontend:release-A COMMIT_A 2026-01-01T00:00:00Z\n' >> "$WORK/state/images.log"
release release-A COMMIT_A; rc_a=$?
echo "  release A exit=$rc_a"
release release-B COMMIT_B_SHA; rc_b=$?
echo "  release B exit=$rc_b"
check "发布 A 成功" "0" "$rc_a"
check "发布 B 成功（身份自洽）" "0" "$rc_b"
check "发布 B 后 .env 的 TAG 指向 B（compose 因此选 B）" "release-B" "$(env_value YBT_RELEASE_TAG)"
check "发布 B 后 .env 的 commit 是 B" "COMMIT_B_SHA" "$(env_value APP_COMMIT)"
check "镜像 release-B 烘焙的是 B 的 commit" "COMMIT_B_SHA" "$(image_commit release-B)"
check "镜像 release-A 未被 B 污染" "COMMIT_A" "$(image_commit release-A)"

echo "== C09-2 回滚到 A：镜像与身份同时恢复 =="
( cd "$WORK/src" && bash scripts/deploy/rollback-server.sh release-A >"$WORK/state/rollback.log" 2>&1 )
rc_rb=$?
sync_env
echo "  rollback exit=$rc_rb"
check "回滚脚本成功" "0" "$rc_rb"
check "回滚后 .env 的 TAG 回到 A" "release-A" "$(env_value YBT_RELEASE_TAG)"
check "回滚后 .env 的 commit 回到 A" "COMMIT_A" "$(env_value APP_COMMIT)"

echo "== C09-3 镜像身份与本次发布不符：必须非零退出 =="
setup
# 通过构建清单要求一个与 git HEAD 不同的 commit，并让镜像“烘焙失败”（烘入别的 commit），
# 模拟“构建产物身份与本次发布不符”的真实事故，门禁必须非零退出。
printf 'ybt-backend:release-C WRONG_COMMIT 2026-03-03T00:00:00Z\n' >> "$WORK/state/images.log"
export FAKE_BUILD_COMMIT="WRONG_COMMIT"
release release-C COMMIT_B_SHA; rc_mismatch=$?
unset FAKE_BUILD_COMMIT
echo "  mismatch exit=$rc_mismatch"
check "身份不符时非零退出" "1" "$([[ $rc_mismatch -ne 0 ]] && echo 1 || echo 0)"

echo "== C09-4 回滚目标不存在：必须拒绝 =="
setup
( cd "$WORK/src" && bash scripts/deploy/rollback-server.sh release-Z >"$WORK/state/nolabel.log" 2>&1 )
rc_nolabel=$?
sync_env
check "无镜像时回滚被拒绝（非零退出）" "1" "$([[ $rc_nolabel -ne 0 ]] && echo 1 || echo 0)"
check "拒绝回滚时不改写 .env 的 TAG" "release-A" "$(env_value YBT_RELEASE_TAG)"

echo
if [[ "$fail" -eq 0 ]]; then
  echo "C09 RESULT: all checks passed"
  exit 0
fi
echo "C09 RESULT: $fail check(s) failed"
exit 1
