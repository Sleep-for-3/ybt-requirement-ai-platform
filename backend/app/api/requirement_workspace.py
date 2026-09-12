from time import perf_counter

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.performance import count_database_queries, response_payload_bytes
from app.core.settings import get_settings
from app.models import StructuredRequirementSnapshot
from app.services.auth.dependencies import CurrentPrincipal
from app.services.governance.audit import record_audit
from app.services.auth.permission_service import PermissionService
from app.services.requirement_snapshot import RequirementSnapshotService
from app.services.requirement_workspace_projection import RequirementWorkspaceProjectionService
from app.schemas.requirement_snapshot import RequirementSnapshotCreate, RequirementSnapshotRead, RequirementSnapshotSummary


router = APIRouter(tags=["requirement workspace"])


def _snapshot_summary(row: StructuredRequirementSnapshot) -> dict:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "target_table_id": row.target_table_id,
        "scenario_id": row.scenario_id,
        "scope_key": row.scope_key,
        "snapshot_no": row.snapshot_no,
        "requirement_version": row.requirement_version,
        "schema_version": row.schema_version,
        "model_version": row.model_version,
        "catalog_revision": row.catalog_revision,
        "lineage_revision": row.lineage_revision,
        "status": row.status,
        "content_hash": row.content_hash,
        "change_note": row.change_note,
        "created_by": row.created_by,
        "created_at": row.created_at,
    }


def _snapshot_detail(row: StructuredRequirementSnapshot, *, idempotent: bool = False) -> dict:
    return {**_snapshot_summary(row), "content_snapshot_json": row.content_snapshot_json or {}, "idempotent": idempotent}


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


@router.post(
    "/projects/{project_id}/requirement-workspace/snapshots",
    response_model=RequirementSnapshotRead,
    status_code=201,
)
def create_requirement_snapshot(
    project_id: int,
    payload: RequirementSnapshotCreate,
    principal: CurrentPrincipal,
    response: Response,
    db: Session = Depends(get_db),
):
    """Freeze the current governed workspace into an immutable structured snapshot."""
    project = PermissionService(db, principal).require_project_permission(project_id, "deliverable.generate")
    try:
        row, idempotent = RequirementSnapshotService(db).create(
            project_id=project_id,
            target_table_id=payload.target_table_id,
            scenario_id=payload.scenario_id,
            created_by=principal.user_id,
            change_note=payload.change_note,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if not idempotent:
        record_audit(
            db,
            action="create_requirement_snapshot",
            resource_type="structured_requirement_snapshot",
            resource_id=row.id,
            actor_user_id=principal.user_id,
            institution_id=project.institution_id,
            project_id=project_id,
            after={
                "snapshot_no": row.snapshot_no,
                "requirement_version": row.requirement_version,
                "content_hash": row.content_hash,
            },
        )
        db.commit()
    response.status_code = 200 if idempotent else 201
    return _snapshot_detail(row, idempotent=idempotent)


@router.get(
    "/projects/{project_id}/requirement-workspace/snapshots",
    response_model=list[RequirementSnapshotSummary],
)
def list_requirement_snapshots(
    project_id: int,
    principal: CurrentPrincipal,
    target_table_id: int | None = Query(None, gt=0),
    scenario_id: int | None = Query(None, gt=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    PermissionService(db, principal).require_project_permission(project_id, "deliverable.view")
    rows = RequirementSnapshotService(db).list(
        project_id=project_id,
        target_table_id=target_table_id,
        scenario_id=scenario_id,
        limit=limit,
    )
    return [_snapshot_summary(row) for row in rows]


@router.get(
    "/projects/{project_id}/requirement-workspace/snapshots/{snapshot_id}",
    response_model=RequirementSnapshotRead,
)
def get_requirement_snapshot(
    project_id: int,
    snapshot_id: int,
    principal: CurrentPrincipal,
    db: Session = Depends(get_db),
):
    PermissionService(db, principal).require_project_permission(project_id, "deliverable.view")
    try:
        row = RequirementSnapshotService(db).get(project_id=project_id, snapshot_id=snapshot_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _snapshot_detail(row)
