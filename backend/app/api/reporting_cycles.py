from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import Project, ReportingCycle
from app.schemas.analytics import ReportingCycleCreate, ReportingCycleRead
from app.services.auth.dependencies import CurrentPrincipal
from app.services.auth.permission_service import PermissionService


router = APIRouter(tags=["reporting cycles"])


@router.get("/projects/{project_id}/reporting-cycles", response_model=list[ReportingCycleRead])
def list_reporting_cycles(project_id: int, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> list[ReportingCycle]:
    project = PermissionService(db, principal).require_project_permission(project_id, "project.view")
    return list(db.scalars(select(ReportingCycle).where(ReportingCycle.project_id == project.id).order_by(ReportingCycle.period_start.desc(), ReportingCycle.id.desc())).all())


@router.post("/projects/{project_id}/reporting-cycles", response_model=ReportingCycleRead, status_code=201)
def create_reporting_cycle(project_id: int, payload: ReportingCycleCreate, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> ReportingCycle:
    project = PermissionService(db, principal).require_project_permission(project_id, "project.manage")
    if payload.period_end <= payload.period_start:
        raise HTTPException(status_code=422, detail="period_end must be after period_start")
    if payload.submission_deadline and payload.submission_deadline < payload.period_end:
        raise HTTPException(status_code=422, detail="submission_deadline must not precede period_end")
    cycle = ReportingCycle(project_id=project.id, institution_id=project.institution_id, **payload.model_dump())
    db.add(cycle)
    db.commit()
    db.refresh(cycle)
    return cycle

