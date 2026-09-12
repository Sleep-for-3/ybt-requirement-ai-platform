"""Dependency-free liveness probes for container orchestrators.

Compose healthchecks must not depend on the application having finished
importing heavy optional providers, and the slim runtime image has no ``curl``.
These probes therefore use only the standard library and the container's own
``/proc`` view.

Usage::

    python -m app.container_probe api
    python -m app.container_probe worker
    python -m app.container_probe beat

Exit code 0 means alive, 1 means not alive.  The probes deliberately check
process liveness only: dependency reachability is already reported by
``/health/ready`` and must not turn a transient provider outage into a
container restart loop.
"""

from __future__ import annotations

import os
import sys
import urllib.request

DEFAULT_API_URL = "http://127.0.0.1:8000/health/live"


def api_probe() -> int:
    url = os.environ.get("CONTAINER_PROBE_API_URL", DEFAULT_API_URL)
    timeout = float(os.environ.get("CONTAINER_PROBE_TIMEOUT_SECONDS", "3"))
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return 0 if int(getattr(response, "status", 0)) == 200 else 1
    except Exception:
        return 1


def celery_process_probe(role: str) -> int:
    """Return 0 when a celery process for ``role`` (worker/beat) is running."""

    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            with open(f"/proc/{entry}/cmdline", "rb") as handle:
                command = handle.read().decode("utf-8", "ignore")
        except OSError:
            continue
        if "celery" in command and role in command:
            return 0
    return 1


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments:
        print("usage: python -m app.container_probe api|worker|beat", file=sys.stderr)
        return 2
    mode = arguments[0].strip().lower()
    if mode == "api":
        return api_probe()
    if mode in {"worker", "beat"}:
        return celery_process_probe(mode)
    print(f"unsupported probe mode: {mode}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
