from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.observability import render_metrics, set_job_metrics
from app.core.settings import get_settings
from app.models import BackgroundJob
from app.services.storage import get_storage_service


router = APIRouter(tags=["health and observability"])


@router.get("/health/live")
def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready")
def ready(response: Response, db: Session = Depends(get_db)) -> dict:
    checks = {"database": False, "storage": False, "redis": "disabled", "vector_store": "disabled"}
    try: db.execute(text("select 1")); checks["database"] = True
    except Exception: checks["database"] = False
    try: checks["storage"] = get_storage_service().is_ready()
    except Exception: checks["storage"] = False
    settings = get_settings()
    if settings.task_queue_provider == "celery":
        try:
            from redis import Redis
            checks["redis"] = bool(Redis.from_url(settings.redis_url, socket_timeout=2).ping())
        except Exception: checks["redis"] = False
    if settings.vector_store_provider != "mock": checks["vector_store"] = "configured"
    ok = checks["database"] is True and checks["storage"] is True and checks["redis"] is not False
    if not ok: response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ready" if ok else "not_ready", "checks": checks}


@router.get("/metrics")
def metrics(db: Session = Depends(get_db)) -> Response:
    rows = db.execute(select(BackgroundJob.status, func.count(BackgroundJob.id)).group_by(BackgroundJob.status)).all()
    set_job_metrics({key: count for key, count in rows})
    return Response(render_metrics(), media_type="text/plain; version=0.0.4")
