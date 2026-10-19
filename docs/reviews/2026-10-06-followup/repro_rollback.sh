#!/bin/bash
# Review fixture only. Docker/curl/sleep are fake; real service commands never run.
set -euo pipefail
OUT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$OUT/../../.." && pwd)"
WORK="$OUT/rollback-mock-$$"
mkdir -p "$WORK/src/scripts/deploy" "$WORK/bin" "$WORK/state"
cp "$ROOT/scripts/deploy/rollback-server.sh" "$WORK/src/scripts/deploy/rollback-server.sh"
printf '# synthetic compose\n' > "$WORK/src/docker-compose.yml"
printf '# synthetic compose override\n' > "$WORK/src/docker-compose.server.yml"
cat > "$WORK/bin/docker" <<'FAKE'
#!/bin/bash
if [[ "$1" == image && "$2" == inspect ]]; then
  if [[ "$*" == *org.ybt.app.commit* ]]; then printf 'SYNTHETIC_A\n'
  elif [[ "$*" == *org.ybt.build.time* ]]; then printf '2026-01-01T00:00:00Z\n'; fi
  exit 0
fi
if [[ "$1" == compose && "$2" == up ]]; then
  [[ "${FAKE_COMPOSE_FAIL:-0}" == 1 ]] && exit 99
  exit 0
fi
if [[ "$1" == compose && "$2" == ps ]]; then exit 0; fi
echo 'unsupported fake Docker call' >&2
exit 91
FAKE
cat > "$WORK/bin/curl" <<'FAKE'
#!/bin/bash
printf '%s\n' "$*" >> "$FAKE_STATE/curl-trace.log"
if [[ "$*" == *'/health/ready'* ]]; then exit 22; fi
if [[ "$*" == *'/version'* ]]; then
  printf '{"app_commit":"SYNTHETIC_A","build_time":"2026-01-01T00:00:00Z","schema_head":"202610060001"}\n'
  exit 0
fi
echo 'unsupported fake curl call' >&2
exit 92
FAKE
printf '#!/bin/bash\nexit 0\n' > "$WORK/bin/sleep"
chmod +x "$WORK/bin/"* "$WORK/src/scripts/deploy/rollback-server.sh"
reset_env() {
  printf 'YBT_RELEASE_TAG=release-B\nAPP_COMMIT=SYNTHETIC_B\nBUILD_TIME=2026-02-01T00:00:00Z\n' > "$WORK/src/.env"
}
reset_env
set +e
env -i PATH="$WORK/bin:/usr/bin:/bin" FAKE_STATE="$WORK/state" \
  /bin/bash "$WORK/src/scripts/deploy/rollback-server.sh" release-A > "$WORK/state/unhealthy.log" 2>&1
rc_unhealthy=$?
set -e
cp "$WORK/src/.env" "$WORK/state/unhealthy.env"
ready_failures="$(grep -c /health/ready "$WORK/state/curl-trace.log")"
reset_env
set +e
env -i PATH="$WORK/bin:/usr/bin:/bin" FAKE_STATE="$WORK/state" FAKE_COMPOSE_FAIL=1 \
  /bin/bash "$WORK/src/scripts/deploy/rollback-server.sh" release-A > "$WORK/state/compose-failed.log" 2>&1
rc_compose=$?
set -e
cp "$WORK/src/.env" "$WORK/state/compose-failed.env"
tag_unhealthy="$(sed -n 's/^YBT_RELEASE_TAG=//p' "$WORK/state/unhealthy.env")"
tag_failed="$(sed -n 's/^YBT_RELEASE_TAG=//p' "$WORK/state/compose-failed.env")"
cat > "$OUT/rollback-repro-result.json" <<JSON
{
  "reviewed_commit": "3db4db6",
  "scope": "copied real rollback script; fake docker/curl/sleep; synthetic env; no live service actions",
  "mock_directory": "$WORK",
  "all_ready_probes_failed": {"count": $ready_failures, "exit_code": $rc_unhealthy, "tag_after": "$tag_unhealthy"},
  "compose_up_failed": {"exit_code": $rc_compose, "initial_tag": "release-B", "tag_after_failure": "$tag_failed"}
}
JSON
cat "$OUT/rollback-repro-result.json"
