from datetime import UTC, datetime
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import Institution, Project
from app.services.analytics.metric_query_service import build_project_overview
from app.services.auth.dependencies import RealPrincipal
from app.services.auth.permission_service import PermissionService


router = APIRouter(tags=["institution cockpit"])
logger = logging.getLogger("app.cockpit")


@router.get("/cockpit")
def institution_cockpit(request: Request, principal: RealPrincipal, db: Session = Depends(get_db)) -> dict:
    """Institution-level view over only projects visible to the current principal."""
    permissions = PermissionService(db, principal)
    if not permissions.capabilities()["can_view_institution_cockpit"]:
        raise HTTPException(status_code=403, detail="Institution cockpit permission required")
    visible_ids = permissions.visible_project_ids()
    statement = select(Project).order_by(Project.id.desc())
    if visible_ids is not None:
        statement = statement.where(Project.id.in_(visible_ids))
    projects = list(db.scalars(statement).all())
    institution_names = dict(db.execute(select(Institution.id, Institution.institution_name).where(
        Institution.id.in_({project.institution_id for project in projects if project.institution_id is not None}),
    )).all())
    rows = []
    for project in projects:
        try:
            overview = build_project_overview(db, project.id)
            readiness = overview["metrics"]["readiness_score"]
            risk_total = sum(item["value"] for item in overview["risk_distribution"])
        except SQLAlchemyError:
            raise
        except Exception as exc:
            trace_id = getattr(request.state, "request_id", None)
            logger.exception(
                "cockpit_project_unavailable",
                extra={"project_id": project.id, "request_id": trace_id},
            )
            rows.append({
                "project_id": project.id,
                "project_name": project.name,
                "institution_name": institution_names.get(project.institution_id) or project.bank_name,
                "readiness": {"value": None, "numerator": 0, "denominator": 0},
                "risk_total": 0,
                "risk_distribution": [],
                "as_of": datetime.now(UTC).isoformat(),
                "dashboard_href": f"/projects/{project.id}/dashboard",
                "data_status": "unavailable",
                "data_issues": [{"code": "analytics_calculation_failed", "message": "分析数据暂不可用"}],
                "trace_id": trace_id,
            })
            continue
        rows.append({
            "project_id": project.id,
            "project_name": project.name,
            "institution_name": institution_names.get(project.institution_id) or project.bank_name,
            "readiness": readiness,
            "risk_total": risk_total,
            "risk_distribution": overview["risk_distribution"],
            "as_of": overview["as_of"],
            "dashboard_href": f"/projects/{project.id}/dashboard",
            "data_status": "ready",
            "data_issues": [],
            "trace_id": None,
        })
    unavailable_count = sum(item["data_status"] == "unavailable" for item in rows)
    if rows and unavailable_count == len(rows):
        raise HTTPException(
            status_code=500,
            detail={"error_code": "cockpit_data_unavailable", "message": "驾驶舱数据计算失败"},
        )
    rows.sort(key=lambda item: (item["readiness"]["value"] is None, -(item["readiness"]["value"] or 0), -item["risk_total"]))
    return {
        "dataset_id": "institution-cockpit",
        "as_of": max((item["as_of"] for item in rows), default=None),
        "project_count": len(rows),
        "data_status": "partial" if unavailable_count else "ready",
        "unavailable_project_count": unavailable_count,
        "projects": rows,
    }
