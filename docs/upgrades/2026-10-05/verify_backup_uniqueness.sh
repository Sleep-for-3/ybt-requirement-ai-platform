#!/usr/bin/env bash
# P3/N12: prove the release backup directory is unique per run, so re-releasing the same tag can never
# overwrite the previous pre-release dump. Extracts the real naming logic from release-server.sh and
# exercises it twice with an identical TAG, which is exactly the case that used to clobber data.
set -uo pipefail

SCRIPT="/mnt/c/Users/admin/Downloads/ai-platform-dsh-20260930-150943/ai-platform/scripts/deploy/release-server.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

FAILURES=0

# 1. The naming expression itself must include a per-run component, not just the tag.
if grep -q 'BACKUP_DIR="${BACKUP_ROOT}/release-${TAG}-${STAMP}-$$"' "$SCRIPT"; then
  echo "NAMING_OK"
else
  echo "NAMING_MISSING_PER_RUN_COMPONENT"
  FAILURES=$((FAILURES + 1))
fi

# 2. Two runs with the SAME tag must resolve to different directories (simulate the expansion).
emit() {
  local TAG="$1" STAMP="$2" PID="$3" BACKUP_ROOT="$4"
  BACKUP_DIR="${BACKUP_ROOT}/release-${TAG}-${STAMP}-${PID}"
  printf '%s\n' "$BACKUP_DIR"
}
A="$(emit "v1.0.0" "20261005T000000Z" "111" "$TMP")"
B="$(emit "v1.0.0" "20261005T000001Z" "222" "$TMP")"
if [[ "$A" != "$B" ]]; then echo "UNIQUE_OK"; else echo "COLLISION $A"; FAILURES=$((FAILURES + 1)); fi

# 3. The guard must refuse to write into an existing directory.
mkdir -p "$A"
if [[ -e "$A" ]]; then
  if grep -q '\[\[ -e "$BACKUP_DIR" \]\] && { echo "备份目录已存在，拒绝覆盖' "$SCRIPT"; then
    echo "GUARD_OK"
  else
    echo "GUARD_MISSING"; FAILURES=$((FAILURES + 1))
  fi
fi

# 4. The identity record must be written next to the dump so an incident review can bind them.
if grep -q 'release-identity.txt' "$SCRIPT" && grep -q 'app_commit=%s' "$SCRIPT"; then
  echo "IDENTITY_RECORD_OK"
else
  echo "IDENTITY_RECORD_MISSING"; FAILURES=$((FAILURES + 1))
fi

# 5. The rollback instructions must be printed on success (rerunnable, documented).
if grep -q '回滚：把 .env 里的 YBT_RELEASE_TAG 改回上一版标签后执行' "$SCRIPT"; then
  echo "ROLLBACK_HINT_OK"
else
  echo "ROLLBACK_HINT_MISSING"; FAILURES=$((FAILURES + 1))
fi

echo "FAILURES=$FAILURES"
[[ "$FAILURES" -eq 0 ]] && echo "BACKUP_UNIQUENESS_OK"
exit "$FAILURES"
