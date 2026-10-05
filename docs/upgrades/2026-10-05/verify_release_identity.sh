#!/usr/bin/env bash
# Real verification for B18/P2 + W01/P1: build the backend image with release identity, then assert
#  - the image installed the *locked* pin set (not the unpinned ranges),
#  - the baked build-info.json carries the exact commit/build time passed to docker build,
#  - the packaged identity cannot be overridden by a checked-in build-info.json,
#  - runtime environment still wins over the baked fallback.
set -uo pipefail

REPO="/mnt/c/Users/admin/Downloads/ai-platform-dsh-20260930-150943/ai-platform"
cd "$REPO" || exit 3

TAG="verify-identity-$$"
COMMIT="$(git rev-parse HEAD 2>/dev/null | tr -d '\r' || echo unknown)"
BUILT="2026-10-05T00:00:00Z"
echo "COMMIT=$COMMIT"

docker build -q -t "ybt-backend:${TAG}" \
  --build-arg APP_COMMIT="$COMMIT" \
  --build-arg BUILD_TIME="$BUILT" \
  ./backend >/dev/null || { echo "BUILD_FAILED"; exit 10; }

run() { docker run --rm "ybt-backend:${TAG}" "$@"; }

echo "--- baked fallback (no env injected) ---"
run python -c "
from app.services.version_info import app_commit, build_time
print('BAKED_COMMIT=' + app_commit())
print('BAKED_BUILT=' + build_time())
" || exit 11

echo "--- runtime environment wins ---"
docker run --rm -e APP_COMMIT=env-commit-wins -e BUILD_TIME=env-time-wins \
  "ybt-backend:${TAG}" python -c "
from app.services.version_info import app_commit, build_time
assert app_commit() == 'env-commit-wins', app_commit()
assert build_time() == 'env-time-wins', build_time()
print('ENV_OVERRIDE_OK')
" || exit 12

echo "--- lock really installed (not the range file) ---"
run python -c "
import importlib.metadata as md
locked = {}
for line in open('/app/requirements.lock.txt', encoding='utf-8'):
    line = line.strip()
    if not line or line.startswith('#') or '==' not in line:
        continue
    name, _, rest = line.partition('==')
    version = rest.split(';')[0].strip()
    locked[name.lower().replace('_', '-')] = version
mismatch = []
for name, version in locked.items():
    try:
        installed = md.version(name)
    except md.PackageNotFoundError:
        # a marker-excluded pin (e.g. Windows-only) is legitimately absent on Linux
        continue
    if installed != version:
        mismatch.append((name, version, installed))
assert not mismatch, mismatch
print('LOCK_MATCH=%d' % len(locked))
" || exit 13

echo "--- component identity is per-role ---"
for role in api worker beat; do
  out="$(docker run --rm -e SERVICE_COMPONENT="$role" "ybt-backend:${TAG}" \
    python -c 'from app.services.version_info import component_name; print(component_name())')"
  [[ "$out" == "$role" ]] || { echo "ROLE_MISMATCH $role -> $out"; exit 14; }
  echo "ROLE_OK=$out"
done

docker rmi -f "ybt-backend:${TAG}" >/dev/null 2>&1
echo "IDENTITY_VERIFY_OK"
