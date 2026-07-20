import re
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.settings import get_settings
from app.models import BackgroundJob, BackgroundJobItem, CodeRepository, ImpactAnalysis, LineageEdge, LineageNode, LineageResolutionCandidate, Project, ReviewTask, ScriptChangeItem, ScriptChangeSet, ScriptDependency, ScriptFile, ScriptFileVersion, StoredFile, WorkflowInstance
from app.services.auth.dependencies import CurrentPrincipal
from app.services.auth.permission_service import PermissionService
from app.services.lineage.archive_ingestion import read_safe_script_archive
from app.services.lineage.ingestion import ScriptIngestionService, ensure_actor_user_id
from app.services.lineage.exporter import export_lineage_workbook
from app.services.lineage.git_repository import validate_repository_location
from app.services.lineage.jobs import lineage_export_handler, script_archive_ingestion_handler, script_repository_sync_handler
from app.services.lineage.resolver import select_resolution_candidate, unbind_lineage_node
from app.services.storage import get_storage_service
from app.services.task_queue import get_task_queue


router = APIRouter(tags=["lineage"])


@router.post("/projects/{project_id}/code-repositories")
def create_code_repository(project_id: int, payload: dict, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> dict:
    project = PermissionService(db, principal).require_project_permission(project_id, "script.sync")
    repository_url = str(payload.get("repository_url") or "").strip()
    _validate_repository_location(repository_url)
    credential_env_name = payload.get("credential_env_name")
    if credential_env_name and not re.fullmatch(r"[A-Z][A-Z0-9_]{1,127}", str(credential_env_name)):
        raise HTTPException(status_code=400, detail="credential_env_name must be an environment variable name")
    repository_type = str(payload.get("repository_type") or "git_repository")
    if repository_type not in {"git_repository", "github", "gitee", "filesystem_snapshot"}:
        raise HTTPException(status_code=400, detail="Unsupported repository type")
    row = CodeRepository(
        institution_id=project.institution_id, project_id=project.id,
        repository_name=str(payload.get("repository_name") or "").strip(),
        repository_type=repository_type, repository_url=repository_url,
        default_branch=str(payload.get("default_branch") or "main"),
        credential_env_name=credential_env_name, enabled=True,
        created_by=ensure_actor_user_id(db, principal.user_id),
    )
    if not row.repository_name or not row.repository_url:
        raise HTTPException(status_code=400, detail="repository_name and repository_url are required")
    db.add(row); db.commit(); db.refresh(row)
    return _repository_dict(row)


@router.get("/projects/{project_id}/code-repositories")
def list_code_repositories(project_id: int, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> list[dict]:
    PermissionService(db, principal).require_project_permission(project_id, "lineage.view")
    return [_repository_dict(item) for item in db.scalars(select(CodeRepository).where(CodeRepository.project_id == project_id).order_by(CodeRepository.id.desc())).all()]


@router.post("/code-repositories/{repository_id}/sync")
def sync_code_repository(repository_id: int, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> dict:
    repository = PermissionService(db, principal).load_project_resource_or_404(CodeRepository, repository_id, "script.sync")
    actor_id = ensure_actor_user_id(db, principal.user_id)
    job = get_task_queue().enqueue(
        db, job_type="script_repository_sync", institution_id=repository.institution_id,
        project_id=repository.project_id, created_by=actor_id,
        idempotency_key=f"repository:{repository.id}:{uuid.uuid4().hex}",
        payload_summary={"repository_id": repository.id, "branch": repository.default_branch},
        handler=script_repository_sync_handler,
    )
    return _job_dict(job, db)


@router.post("/projects/{project_id}/scripts/upload")
async def upload_script(
    project_id: int,
    principal: CurrentPrincipal,
    file: UploadFile = File(...),
    relative_path: str | None = Form(None),
    dialect: str | None = Form(None),
    change_note: str | None = Form(None),
    db: Session = Depends(get_db),
) -> dict:
    project = PermissionService(db, principal).require_project_permission(project_id, "script.upload")
    data = await file.read(get_settings().max_upload_bytes + 1)
    if len(data) > get_settings().max_upload_bytes:
        raise HTTPException(status_code=413, detail="Script is too large")
    try:
        result = ScriptIngestionService(db, get_storage_service()).ingest(
            project=project,
            data=data,
            file_name=Path(file.filename or "").name,
            relative_path=relative_path,
            dialect=dialect,
            actor_user_id=principal.user_id,
            change_note=change_note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "script_file_id": result.script_file.id,
        "version_id": result.version.id,
        "version_no": result.version.version_no,
        "parse_status": result.version.parse_status,
        "warnings": result.version.warnings_json,
        "deduplicated": result.deduplicated,
        "storage_key": result.stored_file.storage_key,
        "node_count": result.node_count,
        "edge_count": result.edge_count,
        "change_set_id": result.change_set.id if result.change_set else None,
        "impact_id": result.impact.id if result.impact else None,
        "change_categories": list(result.change_categories),
        "impact_severity": result.impact.severity if result.impact else None,
    }


@router.post("/projects/{project_id}/scripts/upload-zip")
async def upload_script_archive(
    project_id: int,
    principal: CurrentPrincipal,
    file: UploadFile = File(...),
    dialect: str | None = Form(None),
    db: Session = Depends(get_db),
) -> dict:
    project = PermissionService(db, principal).require_project_permission(project_id, "script.upload")
    settings = get_settings()
    data = await file.read(settings.max_upload_bytes + 1)
    try:
        archived = read_safe_script_archive(
            data,
            max_archive_bytes=settings.max_upload_bytes,
            max_total_bytes=settings.lineage_zip_max_total_bytes,
            max_file_count=settings.lineage_zip_max_file_count,
            max_file_bytes=settings.lineage_script_max_bytes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    actor_id = ensure_actor_user_id(db, principal.user_id)
    saved = get_storage_service().save(data, file_name=Path(file.filename or "archive.zip").name, project_id=project.id)
    stored = db.scalar(select(StoredFile).where(
        StoredFile.institution_id == project.institution_id, StoredFile.project_id == project.id,
        StoredFile.content_hash == saved.content_hash, StoredFile.enabled.is_(True),
    ))
    if stored is None:
        stored = StoredFile(
            institution_id=project.institution_id, project_id=project.id, storage_key=saved.storage_key,
            original_file_name=Path(file.filename or "archive.zip").name, content_type="application/zip",
            byte_size=saved.byte_size, content_hash=saved.content_hash, classification=project.confidentiality_level,
            created_by=actor_id, enabled=True,
        )
        db.add(stored); db.commit(); db.refresh(stored)
    job = get_task_queue().enqueue(
        db, job_type="script_upload_ingestion", institution_id=project.institution_id,
        project_id=project.id, created_by=actor_id, idempotency_key=f"archive:{saved.content_hash}",
        payload_summary={"stored_file_id": stored.id, "file_name": stored.original_file_name, "file_count": len(archived), "dialect": dialect},
        handler=script_archive_ingestion_handler,
    )
    return _job_dict(job, db)


@router.get("/projects/{project_id}/scripts")
def list_scripts(project_id: int, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> list[dict]:
    PermissionService(db, principal).require_project_permission(project_id, "lineage.view")
    rows = db.scalars(select(ScriptFile).where(ScriptFile.project_id == project_id).order_by(ScriptFile.relative_path)).all()
    return [_script_dict(row) for row in rows]


@router.get("/scripts/{script_file_id}")
def get_script(script_file_id: int, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> dict:
    row = PermissionService(db, principal).load_project_resource_or_404(ScriptFile, script_file_id, "lineage.view")
    versions = db.scalars(select(ScriptFileVersion).where(ScriptFileVersion.script_file_id == row.id).order_by(ScriptFileVersion.version_no.desc())).all()
    dependencies = db.scalars(select(ScriptDependency).where(ScriptDependency.parent_script_file_id == row.id).order_by(ScriptDependency.id)).all()
    return {
        **_script_dict(row),
        "versions": [{"id": item.id, "version_no": item.version_no, "file_hash": item.file_hash, "normalized_hash": item.normalized_hash, "parse_status": item.parse_status, "dialect": item.dialect, "warnings": item.warnings_json, "git_commit_sha": item.git_commit_sha, "created_at": item.created_at} for item in versions],
        "dependencies": [{"id": item.id, "child_script_file_id": item.child_script_file_id, "dependency_type": item.dependency_type, "call_expression": item.call_expression, "condition_expression": item.condition_expression, "source_line_start": item.source_line_start, "source_line_end": item.source_line_end, "confidence_level": item.confidence_level, "warnings": item.warnings_json} for item in dependencies],
    }


@router.get("/projects/{project_id}/lineage/graph")
def project_lineage_graph(
    project_id: int,
    principal: CurrentPrincipal,
    direction: str = "both",
    depth: int = 3,
    limit: int = 1000,
    db: Session = Depends(get_db),
) -> dict:
    PermissionService(db, principal).require_project_permission(project_id, "lineage.view")
    if direction not in {"upstream", "downstream", "both"} or not 1 <= depth <= 10:
        raise HTTPException(status_code=400, detail="Invalid graph direction or depth")
    capped = min(max(limit, 1), 2000)
    nodes = list(db.scalars(select(LineageNode).where(LineageNode.project_id == project_id).limit(capped)).all())
    node_ids = {item.id for item in nodes}
    edges = list(db.scalars(select(LineageEdge).where(
        LineageEdge.project_id == project_id,
        LineageEdge.enabled.is_(True),
        LineageEdge.source_node_id.in_(node_ids),
        LineageEdge.target_node_id.in_(node_ids),
    ).limit(capped * 2)).all()) if node_ids else []
    return {
        "nodes": [_node_dict(item) for item in nodes],
        "edges": [_edge_dict(item) for item in edges],
        "direction": direction,
        "depth": depth,
        "truncated": len(nodes) == capped or len(edges) == capped * 2,
    }


@router.get("/target-fields/{field_id}/lineage")
def target_field_lineage(field_id: int, principal: CurrentPrincipal, direction: str = "both", depth: int = 3, limit: int = 1000, db: Session = Depends(get_db)) -> dict:
    from app.models import TargetField
    field = PermissionService(db, principal).load_project_resource_or_404(TargetField, field_id, "lineage.view")
    seeds = list(db.scalars(select(LineageNode.id).where(LineageNode.project_id == field.project_id, LineageNode.target_field_id == field.id)).all())
    return _walk_graph(db, field.project_id, seeds, direction, depth, limit)


@router.get("/mart-fields/{field_id}/lineage")
def mart_field_lineage(field_id: int, principal: CurrentPrincipal, direction: str = "both", depth: int = 3, limit: int = 1000, db: Session = Depends(get_db)) -> dict:
    from app.models import MartField
    field = PermissionService(db, principal).load_project_resource_or_404(MartField, field_id, "lineage.view")
    seeds = list(db.scalars(select(LineageNode.id).where(LineageNode.project_id == field.project_id, LineageNode.mart_field_id == field.id)).all())
    return _walk_graph(db, field.project_id, seeds, direction, depth, limit)


@router.get("/catalog/columns/{column_id}/lineage")
def catalog_column_lineage(column_id: int, principal: CurrentPrincipal, direction: str = "both", depth: int = 3, limit: int = 1000, db: Session = Depends(get_db)) -> dict:
    from app.models import CatalogColumn
    column = PermissionService(db, principal).load_project_resource_or_404(CatalogColumn, column_id, "lineage.view")
    seeds = list(db.scalars(select(LineageNode.id).where(LineageNode.project_id == column.project_id, LineageNode.catalog_column_id == column.id)).all())
    return _walk_graph(db, column.project_id, seeds, direction, depth, limit)


@router.get("/scripts/{script_file_id}/lineage")
def script_lineage(script_file_id: int, principal: CurrentPrincipal, direction: str = "both", depth: int = 3, limit: int = 1000, db: Session = Depends(get_db)) -> dict:
    script = PermissionService(db, principal).load_project_resource_or_404(ScriptFile, script_file_id, "lineage.view")
    seeds = list(db.scalars(select(LineageNode.id).where(LineageNode.project_id == script.project_id, LineageNode.script_file_id == script.id)).all())
    return _walk_graph(db, script.project_id, seeds, direction, depth, limit)


@router.post("/lineage/nodes/{node_id}/resolution-candidates/{candidate_id}/select")
def select_candidate(node_id: int, candidate_id: int, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> dict:
    node = PermissionService(db, principal).load_project_resource_or_404(LineageNode, node_id, "lineage.manage")
    candidate = db.get(LineageResolutionCandidate, candidate_id)
    if candidate is None or candidate.project_id != node.project_id or candidate.lineage_node_id != node.id:
        raise HTTPException(status_code=404, detail="Resolution candidate not found")
    try:
        select_resolution_candidate(db, node, candidate)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit(); db.refresh(node)
    return _node_dict(node)


@router.post("/lineage/nodes/{node_id}/unbind")
def unbind_node(node_id: int, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> dict:
    node = PermissionService(db, principal).load_project_resource_or_404(LineageNode, node_id, "lineage.manage")
    unbind_lineage_node(db, node)
    db.commit(); db.refresh(node)
    return _node_dict(node)


@router.get("/lineage/changes/{change_set_id}")
def get_change_set(change_set_id: int, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> dict:
    row = PermissionService(db, principal).load_project_resource_or_404(ScriptChangeSet, change_set_id, "impact.view")
    items = db.scalars(select(ScriptChangeItem).where(ScriptChangeItem.change_set_id == row.id).order_by(ScriptChangeItem.id)).all()
    impact = db.scalar(select(ImpactAnalysis).where(ImpactAnalysis.change_set_id == row.id))
    return {
        "id": row.id, "project_id": row.project_id, "script_file_id": row.script_file_id,
        "from_version_id": row.from_version_id, "to_version_id": row.to_version_id,
        "change_type": row.change_type, "status": row.status, "summary": row.summary_json,
        "items": [{"id": item.id, "change_category": item.change_category, "entity_type": item.entity_type, "old_value": item.old_value_json, "new_value": item.new_value_json, "severity": item.severity} for item in items],
        "impact": None if impact is None else {"id": impact.id, "status": impact.status, "severity": impact.severity, "affected_target_field_ids": impact.affected_target_field_ids_json, "affected_mart_field_ids": impact.affected_mart_field_ids_json, "affected_mapping_ids": impact.affected_mapping_ids_json, "summary": impact.summary_json, "open_questions": impact.open_questions_json},
    }


@router.get("/projects/{project_id}/lineage/changes")
def list_change_sets(project_id: int, principal: CurrentPrincipal, limit: int = 100, db: Session = Depends(get_db)) -> list[dict]:
    PermissionService(db, principal).require_project_permission(project_id, "impact.view")
    rows = db.scalars(select(ScriptChangeSet).where(ScriptChangeSet.project_id == project_id).order_by(ScriptChangeSet.id.desc()).limit(min(max(limit, 1), 500))).all()
    impacts = {item.change_set_id: item for item in db.scalars(select(ImpactAnalysis).where(ImpactAnalysis.change_set_id.in_([row.id for row in rows]))).all()} if rows else {}
    return [{"id": row.id, "script_file_id": row.script_file_id, "from_version_id": row.from_version_id, "to_version_id": row.to_version_id, "change_type": row.change_type, "status": row.status, "summary": row.summary_json, "severity": impacts[row.id].severity if row.id in impacts else "low", "impact_id": impacts[row.id].id if row.id in impacts else None, "created_at": row.created_at} for row in rows]


@router.get("/projects/{project_id}/lineage/impacts")
def list_impacts(project_id: int, principal: CurrentPrincipal, limit: int = 100, db: Session = Depends(get_db)) -> list[dict]:
    PermissionService(db, principal).require_project_permission(project_id, "impact.view")
    rows = db.scalars(select(ImpactAnalysis).where(ImpactAnalysis.project_id == project_id).order_by(ImpactAnalysis.id.desc()).limit(min(max(limit, 1), 500))).all()
    return [_impact_dict(row) for row in rows]


@router.get("/lineage/impacts/{impact_id}")
def get_impact(impact_id: int, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> dict:
    row = PermissionService(db, principal).load_project_resource_or_404(ImpactAnalysis, impact_id, "impact.view")
    instance = db.scalar(select(WorkflowInstance).where(WorkflowInstance.workflow_key == "lineage_change_review", WorkflowInstance.target_type == "impact_analysis", WorkflowInstance.target_id == row.id).order_by(WorkflowInstance.id.desc()).limit(1))
    tasks = list(db.scalars(select(ReviewTask).where(ReviewTask.workflow_instance_id == instance.id).order_by(ReviewTask.id)).all()) if instance else []
    return {**_impact_dict(row), "workflow": None if instance is None else {"id": instance.id, "status": instance.status, "current_step": instance.current_step, "tasks": [{"id": item.id, "step_key": item.step_key, "status": item.status, "assignee_user_id": item.assignee_user_id, "assignee_role": item.assignee_role} for item in tasks]}}


@router.get("/projects/{project_id}/lineage/unresolved")
def list_unresolved_nodes(project_id: int, principal: CurrentPrincipal, limit: int = 200, db: Session = Depends(get_db)) -> list[dict]:
    PermissionService(db, principal).require_project_permission(project_id, "lineage.view")
    rows = db.scalars(select(LineageNode).where(LineageNode.project_id == project_id, LineageNode.unresolved_flag.is_(True)).order_by(LineageNode.id.desc()).limit(min(max(limit, 1), 1000))).all()
    result = []
    for row in rows:
        candidates = db.scalars(select(LineageResolutionCandidate).where(LineageResolutionCandidate.lineage_node_id == row.id).order_by(LineageResolutionCandidate.score.desc())).all()
        result.append({**_node_dict(row), "candidates": [{"id": item.id, "candidate_type": item.candidate_type, "candidate_id": item.candidate_id, "score": item.score, "match_reason": item.match_reason, "selected_flag": item.selected_flag} for item in candidates]})
    return result


@router.get("/projects/{project_id}/export/lineage-workbook")
def export_project_lineage(project_id: int, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> Response:
    PermissionService(db, principal).require_project_permission(project_id, "export")
    return _workbook_response(export_lineage_workbook(db, project_id), f"project-{project_id}-lineage.xlsx")


@router.post("/projects/{project_id}/export/lineage-workbook/jobs")
def enqueue_project_lineage_export(project_id: int, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> dict:
    project = PermissionService(db, principal).require_project_permission(project_id, "export")
    actor_id = ensure_actor_user_id(db, principal.user_id)
    job = get_task_queue().enqueue(
        db,
        job_type="lineage_export",
        institution_id=project.institution_id,
        project_id=project.id,
        created_by=actor_id,
        idempotency_key=f"project-lineage:{project.id}:{uuid.uuid4().hex}",
        payload_summary={"file_name": f"project-{project.id}-lineage.xlsx"},
        handler=lineage_export_handler,
    )
    return _job_dict(job, db)


@router.get("/target-fields/{field_id}/export/lineage-workbook")
def export_target_lineage(field_id: int, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> Response:
    from app.models import TargetField
    field = PermissionService(db, principal).load_project_resource_or_404(TargetField, field_id, "export")
    return _workbook_response(export_lineage_workbook(db, field.project_id, target_field_id=field.id), f"target-field-{field.id}-lineage.xlsx")


@router.get("/scripts/{script_file_id}/export/change-impact-workbook")
def export_script_impact(script_file_id: int, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> Response:
    script = PermissionService(db, principal).load_project_resource_or_404(ScriptFile, script_file_id, "export")
    return _workbook_response(export_lineage_workbook(db, script.project_id, script_file_id=script.id), f"script-{script.id}-change-impact.xlsx")


def _script_dict(row: ScriptFile) -> dict:
    return {"id": row.id, "project_id": row.project_id, "relative_path": row.relative_path, "file_name": row.file_name, "file_type": row.file_type, "logical_target_name": row.logical_target_name, "enabled": row.enabled, "current_version_no": row.current_version_no}


def _node_dict(row: LineageNode) -> dict:
    return {"id": row.id, "node_type": row.node_type, "logical_name": row.logical_name, "database_name": row.database_name, "schema_name": row.schema_name, "table_name": row.table_name, "column_name": row.column_name, "catalog_table_id": row.catalog_table_id, "catalog_column_id": row.catalog_column_id, "source_field_id": row.source_field_id, "mart_field_id": row.mart_field_id, "target_field_id": row.target_field_id, "unresolved_flag": row.unresolved_flag, "metadata": row.metadata_json}


def _edge_dict(row: LineageEdge) -> dict:
    return {"id": row.id, "source_node_id": row.source_node_id, "target_node_id": row.target_node_id, "edge_type": row.edge_type, "transformation_type": row.transformation_type, "transformation_expression": row.transformation_expression, "join_condition": row.join_condition, "filter_condition": row.filter_condition, "aggregation_rule": row.aggregation_rule, "code_mapping_rule": row.code_mapping_rule, "source_line_start": row.source_line_start, "source_line_end": row.source_line_end, "confidence_level": row.confidence_level, "evidence": row.evidence_json}


def _job_dict(job: BackgroundJob, db: Session) -> dict:
    items = db.scalars(select(BackgroundJobItem).where(BackgroundJobItem.background_job_id == job.id).order_by(BackgroundJobItem.id)).all()
    return {"job_id": job.id, "job_type": job.job_type, "status": job.status, "progress": job.progress, "result": job.result_summary_json, "items": [{"item_key": item.item_key, "status": item.status, "result": item.result_summary_json, "error_message": item.error_message} for item in items]}


def _repository_dict(row: CodeRepository) -> dict:
    return {"id": row.id, "project_id": row.project_id, "repository_name": row.repository_name, "repository_type": row.repository_type, "repository_url": row.repository_url, "default_branch": row.default_branch, "credential_env_name": row.credential_env_name, "enabled": row.enabled, "last_sync_commit": row.last_sync_commit, "last_synced_at": row.last_synced_at}


def _impact_dict(row: ImpactAnalysis) -> dict:
    return {"id": row.id, "project_id": row.project_id, "change_set_id": row.change_set_id, "status": row.status, "severity": row.severity, "affected_target_field_ids": row.affected_target_field_ids_json, "affected_mart_field_ids": row.affected_mart_field_ids_json, "affected_mapping_ids": row.affected_mapping_ids_json, "affected_scenario_mapping_ids": row.affected_scenario_mapping_ids_json, "affected_lineage_edge_ids": row.affected_lineage_edge_ids_json, "summary": row.summary_json, "open_questions": row.open_questions_json, "created_at": row.created_at, "completed_at": row.completed_at}


def _workbook_response(content: bytes, file_name: str) -> Response:
    return Response(content=content, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": f'attachment; filename="{file_name}"', "Cache-Control": "no-store"})


def _validate_repository_location(repository_url: str) -> None:
    settings = get_settings()
    try:
        validate_repository_location(
            repository_url,
            allowed_hosts=settings.lineage_git_allowed_host_list,
            allowed_local_roots=settings.lineage_git_allowed_local_root_list,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _walk_graph(db: Session, project_id: int, seed_ids: list[int], direction: str, depth: int, limit: int) -> dict:
    if direction not in {"upstream", "downstream", "both"} or not 1 <= depth <= 10:
        raise HTTPException(status_code=400, detail="Invalid graph direction or depth")
    capped = min(max(limit, 1), 2000)
    visited = set(seed_ids[:capped]); frontier = set(visited); edge_map: dict[int, LineageEdge] = {}
    for _ in range(depth):
        if not frontier or len(visited) >= capped: break
        conditions = []
        if direction in {"upstream", "both"}: conditions.append(LineageEdge.target_node_id.in_(frontier))
        if direction in {"downstream", "both"}: conditions.append(LineageEdge.source_node_id.in_(frontier))
        condition = conditions[0] if len(conditions) == 1 else conditions[0] | conditions[1]
        rows = list(db.scalars(select(LineageEdge).where(LineageEdge.project_id == project_id, LineageEdge.enabled.is_(True), condition).limit(capped * 2)).all())
        next_frontier: set[int] = set()
        for edge in rows:
            edge_map[edge.id] = edge
            for node_id in (edge.source_node_id, edge.target_node_id):
                if node_id not in visited and len(visited) < capped:
                    visited.add(node_id); next_frontier.add(node_id)
        frontier = next_frontier
    nodes = list(db.scalars(select(LineageNode).where(LineageNode.project_id == project_id, LineageNode.id.in_(visited))).all()) if visited else []
    return {"nodes": [_node_dict(item) for item in nodes], "edges": [_edge_dict(item) for item in edge_map.values()], "direction": direction, "depth": depth, "truncated": len(visited) >= capped}
