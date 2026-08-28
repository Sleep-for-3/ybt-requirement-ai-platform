from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import Project
from app.services.analytics.metric_query_service import build_project_overview
from app.services.auth.dependencies import RealPrincipal
from app.services.auth.permission_service import PermissionService


router = APIRouter(tags=["institution cockpit"])


@router.get("/cockpit")
def institution_cockpit(principal: RealPrincipal, db: Session = Depends(get_db)) -> dict:
    """Institution-level view over only projects visible to the current principal."""
    visible_ids = PermissionService(db, principal).visible_project_ids()
    statement = select(Project).order_by(Project.id.desc())
    if visible_ids is not None:
        statement = statement.where(Project.id.in_(visible_ids))
    projects = list(db.scalars(statement).all())
    rows = []
    for project in projects:
        overview = build_project_overview(db, project.id)
        readiness = overview["metrics"]["readiness_score"]
        risk_total = sum(item["value"] for item in overview["risk_distribution"])
        rows.append({
            "project_id": project.id,
            "project_name": project.name,
            "institution_name": project.bank_name,
            "readiness": readiness,
            "risk_total": risk_total,
            "risk_distribution": overview["risk_distribution"],
            "as_of": overview["as_of"],
            "dashboard_href": f"/projects/{project.id}/dashboard",
        })
    rows.sort(key=lambda item: (item["readiness"]["value"] is None, -(item["readiness"]["value"] or 0), -item["risk_total"]))
    return {
        "dataset_id": "institution-cockpit",
        "as_of": max((item["as_of"] for item in rows), default=None),
        "project_count": len(rows),
        "projects": rows,
    }

