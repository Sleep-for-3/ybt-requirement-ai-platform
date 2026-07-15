import json
import logging
import threading
import time
import uuid
from collections import defaultdict, deque

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.core.settings import get_settings


logger = logging.getLogger("app.request")
_lock = threading.Lock()
_request_counts: dict[tuple[str, str, int], int] = defaultdict(int)
_request_duration_ms: dict[tuple[str, str], float] = defaultdict(float)
_rate_windows: dict[str, deque[float]] = defaultdict(deque)
_job_counts: dict[str, int] = defaultdict(int)


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        started = time.perf_counter()
        request_id = _request_id(request.headers.get("X-Request-ID"))
        request.state.request_id = request_id
        limited = _rate_limited(_client_key(request))
        if limited:
            response = JSONResponse({"detail": "Rate limit exceeded"}, status_code=429)
        else:
            response = await call_next(request)
        elapsed_ms = (time.perf_counter() - started) * 1000
        route = request.scope.get("route")
        route_path = getattr(route, "path", request.url.path)
        with _lock:
            _request_counts[(request.method, route_path, response.status_code)] += 1
            _request_duration_ms[(request.method, route_path)] += elapsed_ms
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Cache-Control"] = response.headers.get("Cache-Control", "no-store")
        logger.info(json.dumps({"event": "http_request", "request_id": request_id, "method": request.method, "route": route_path, "status": response.status_code, "duration_ms": round(elapsed_ms, 2)}, ensure_ascii=False))
        return response


def render_metrics() -> str:
    lines = ["# HELP ybt_http_requests_total Total HTTP requests", "# TYPE ybt_http_requests_total counter"]
    with _lock:
        for (method, route, status), count in sorted(_request_counts.items()):
            lines.append(f'ybt_http_requests_total{{method="{_escape(method)}",route="{_escape(route)}",status="{status}"}} {count}')
        lines += ["# HELP ybt_http_request_duration_ms_total Total HTTP request duration", "# TYPE ybt_http_request_duration_ms_total counter"]
        for (method, route), duration in sorted(_request_duration_ms.items()):
            lines.append(f'ybt_http_request_duration_ms_total{{method="{_escape(method)}",route="{_escape(route)}"}} {duration:.3f}')
        lines += ["# HELP ybt_background_jobs_total Background jobs by status", "# TYPE ybt_background_jobs_total gauge"]
        for status, count in sorted(_job_counts.items()):
            lines.append(f'ybt_background_jobs_total{{status="{_escape(status)}"}} {count}')
    return "\n".join(lines) + "\n"


def set_job_metrics(values: dict[str, int]) -> None:
    with _lock:
        _job_counts.clear(); _job_counts.update(values)


def _request_id(value: str | None) -> str:
    if value and 8 <= len(value) <= 64 and all(char.isalnum() or char in "-_" for char in value):
        return value
    return uuid.uuid4().hex


def _client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _rate_limited(key: str) -> bool:
    limit = get_settings().request_rate_limit_per_minute
    now = time.monotonic(); window = _rate_windows[key]
    while window and window[0] < now - 60: window.popleft()
    if len(window) >= limit: return True
    window.append(now); return False


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")
