from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.observability import render_metrics, set_job_metrics
from app.core.settings import get_settings
from app.models import BackgroundJob
from app.services.auth.dependencies import CurrentPrincipal
from app.services.auth.permission_service import PermissionService
from app.services.health_checks import readiness_summary, run_health_checks


router = APIRouter(tags=["health and observability"])


@router.get("/health/live")
def live() -> dict[str, str]:
    return {"status": "healthy", "application": get_settings().app_name}


@router.get("/health/ready")
def ready(response: Response, db: Session = Depends(get_db)) -> dict:
    summary = readiness_summary(run_health_checks(db, get_settings()))
    if summary["status"] != "ready":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return summary


@router.get("/health/details")
def details(principal: CurrentPrincipal, db: Session = Depends(get_db)) -> dict:
    settings = get_settings()
    if not settings.health_details_public and not PermissionService(db, principal).is_platform_admin():
        raise HTTPException(status_code=403, detail="Platform administrator permission is required")
    return run_health_checks(db, settings)


@router.get("/metrics")
def metrics(db: Session = Depends(get_db)) -> Response:
    rows = db.execute(select(BackgroundJob.status, func.count(BackgroundJob.id)).group_by(BackgroundJob.status)).all()
    set_job_metrics({key: count for key, count in rows})
    return Response(render_metrics(), media_type="text/plain; version=0.0.4")
