#!/usr/bin/env bash
# Verify the pinned lock actually installs on the release platform (Linux), not just on the
# developer's Windows host. The lock carries a sys_platform marker for the Windows-only pin, so a
# container install must succeed and `pip check` must report a consistent dependency set.
set -uo pipefail

WORKDIR="/mnt/c/Users/admin/Downloads/ai-platform-dsh-20260930-150943/ai-platform/backend"
cd "$WORKDIR" || exit 3

docker run --rm -v "$(pwd):/w" -w /w python:3.12-slim sh -c '
  pip install --no-cache-dir -q -r requirements.lock.txt || exit 10
  pip check || exit 11
  python -c "import fastapi, sqlalchemy, alembic, celery, pymilvus; print(\"LINUX-LOCK-OK\")" || exit 12
  python -m pip list --format=freeze > /tmp/installed.txt || exit 13
  echo "INSTALLED_COUNT=$(wc -l < /tmp/installed.txt)"
'
rc=$?
echo "CONTAINER_RC=$rc"
exit $rc
