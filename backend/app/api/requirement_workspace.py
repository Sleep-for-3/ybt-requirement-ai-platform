from time import perf_counter

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.performance import count_database_queries, response_payload_bytes
from app.core.settings import get_settings
from app.services.auth.dependencies import CurrentPrincipal
from app.services.auth.permission_service import PermissionService
from app.services.requirement_workspace_projection import RequirementWorkspaceProjectionService


router = APIRouter(tags=["requirement workspace"])


@router.get("/projects/{project_id}/requirement-workspace")
def requirement_workspace(
    project_id: int,
    principal: CurrentPrincipal,
    response: Response,
    target_table_id: int | None = Query(None),
    scenario_id: int | None = Query(None),
    db: Session = Depends(get_db),
):
    started = perf_counter()
    try:
        diagnostics_enabled = get_settings().environment.lower() in {"development", "test"}
        with count_database_queries(db, enabled=diagnostics_enabled) as query_count:
            PermissionService(db, principal).require_project_permission(project_id, "project.view")
            result = RequirementWorkspaceProjectionService(db).projection(project_id, target_table_id, scenario_id)
        response.headers["Server-Timing"] = f"workspace_projection;dur={(perf_counter() - started) * 1000:.2f}"
        response.headers["X-Workspace-Projection-Version"] = "requirement-workspace-v2"
        response.headers["X-Workspace-Initial-Request-Budget"] = "1"
        response.headers["X-Response-Payload-Bytes"] = str(response_payload_bytes(result))
        if diagnostics_enabled:
            response.headers["X-DB-Query-Count"] = str(query_count.value)
        return result
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/projects/{project_id}/requirement-workspace/fields/{field_id}")
def requirement_workspace_field(
    project_id: int,
    field_id: int,
    principal: CurrentPrincipal,
    response: Response,
    scenario_id: int | None = Query(None),
    db: Session = Depends(get_db),
):
    started = perf_counter()
    try:
        diagnostics_enabled = get_settings().environment.lower() in {"development", "test"}
        with count_database_queries(db, enabled=diagnostics_enabled) as query_count:
            PermissionService(db, principal).require_project_permission(project_id, "project.view")
            result = RequirementWorkspaceProjectionService(db).field_detail(project_id, field_id, scenario_id)
        response.headers["Server-Timing"] = f"workspace_field_detail;dur={(perf_counter() - started) * 1000:.2f}"
        response.headers["X-Response-Payload-Bytes"] = str(response_payload_bytes(result))
        if diagnostics_enabled:
            response.headers["X-DB-Query-Count"] = str(query_count.value)
        return result
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/projects/{project_id}/requirement-workspace/fields/{field_id}/evidence")
def requirement_workspace_field_evidence(
    project_id: int,
    field_id: int,
    principal: CurrentPrincipal,
    scenario_id: int | None = Query(None),
    db: Session = Depends(get_db),
):
    PermissionService(db, principal).require_project_permission(project_id, "project.view")
    try:
        return RequirementWorkspaceProjectionService(db).field_evidence(project_id, field_id, scenario_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
