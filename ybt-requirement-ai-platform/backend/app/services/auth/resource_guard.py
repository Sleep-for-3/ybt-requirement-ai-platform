from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import (
    BusinessSystem, CandidateSourceRecommendation, CatalogColumn, CatalogTable, ColumnProfileTask,
    DataSource, DbProfileTask, FieldMappingDraft, KnowledgeDocument, KnowledgeUnit, MappingEvidenceReference,
    MartField, MartTable, MartToYbtMapping, MetadataImportDocument, MetadataSyncTask, NaturalLanguageTask,
    ProductScenario, RagEvaluationCase, RagEvaluationRun, ScenarioBusinessMapping, ScenarioTechnicalLineage,
    SourceField, SourceTable, SourceToMartMapping, TargetField, TargetTable, TemplateDocument,
    TraceabilityTemplateDocument, CodeRepository, LineageNode, ScriptFile, ScriptChangeSet, ImpactAnalysis,
)
from app.services.auth.dependencies import Principal, get_current_principal
from app.services.auth.permission_service import PermissionService


async def guard_project_resource(
    request: Request,
    principal: Annotated[Principal, Depends(get_current_principal)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    if principal.is_legacy_system:
        return
    permission = _permission(request.method, request.url.path)
    if _authorize_global_route(db, principal, request.method, request.url.path):
        return
    path_project_id = request.path_params.get("project_id")
    if path_project_id is not None:
        PermissionService(db, principal).require_project_permission(int(path_project_id), permission)
        return
    resource = _path_resource(db, request.url.path, request.path_params)
    if resource is not None:
        if isinstance(resource, MappingEvidenceReference):
            permission = _mapping_permission(resource.mapping_type, request.method)
        resolved_project_id = getattr(resource, "project_id", None)
        if resolved_project_id is None:
            raise HTTPException(status_code=404, detail="Resource not found")
        query_project_id = request.query_params.get("project_id")
        if query_project_id is not None and int(query_project_id) != int(resolved_project_id):
            raise HTTPException(status_code=404, detail="Resource not found")
        PermissionService(db, principal).require_project_permission(int(resolved_project_id), permission)
        return
    query_project_id = request.query_params.get("project_id")
    if query_project_id is not None:
        PermissionService(db, principal).require_project_permission(int(query_project_id), permission)
        return
    body_project_id = await _body_project_id(request)
    if body_project_id is not None:
        PermissionService(db, principal).require_project_permission(body_project_id, permission)
        return
    raise HTTPException(status_code=404, detail="Project-scoped resource could not be resolved")


def _permission(method: str, path: str) -> str:
    if "export" in path:
        return "export"
    if "/lineage" in path or "/scripts" in path:
        if "resolution-candidates" in path or path.endswith("/unbind"):
            return "lineage.manage"
        return "lineage.view" if method == "GET" else "script.upload"
    if "/code-repositories" in path:
        return "lineage.view" if method == "GET" else "script.sync"
    if "/impacts" in path:
        return "impact.view" if method == "GET" else "impact.review"
    if "/knowledge" in path or "/documents" in path:
        return "knowledge.search" if method == "GET" or path.endswith(("/search", "/ask")) else "knowledge.manage"
    if any(part in path for part in ["/datasources", "/metadata-", "/catalog"]):
        return "catalog.search" if method == "GET" or path.endswith("/search") else "catalog.manage"
    if "profile" in path:
        return "profile.request"
    if "scenario-business-mappings" in path or "business-mapping" in path or "scenario_business" in path:
        return "business.review" if path.endswith(("/confirm", "/reject")) else "business.edit"
    if "scenario-technical-lineages" in path or "technical-lineage" in path or "scenario_technical" in path:
        return "technical.review" if path.endswith(("/confirm", "/reject")) else "technical.edit"
    if "source-to-mart-mappings" in path or "mart-to-ybt-mappings" in path or "source_to_mart" in path or "mart_to_ybt" in path:
        return "technical.review" if path.endswith(("/approve", "/reject")) else "technical.edit"
    if "source-recommendations" in path:
        return "technical.edit"
    return "project.view" if method == "GET" else "project.manage"


def _path_resource(db: Session, path: str, params: dict):
    candidates = [
        ("datasource_id", DataSource), ("column_id", CatalogColumn), ("recommendation_id", CandidateSourceRecommendation),
        ("lineage_id", ScenarioTechnicalLineage), ("scenario_id", ProductScenario), ("system_id", BusinessSystem),
        ("run_id", RagEvaluationRun), ("case_id", RagEvaluationCase), ("unit_id", KnowledgeUnit),
        ("node_id", LineageNode), ("script_file_id", ScriptFile), ("change_set_id", ScriptChangeSet),
        ("impact_id", ImpactAnalysis),
        ("repository_id", CodeRepository),
    ]
    for key, model in candidates:
        if key in params:
            return db.get(model, int(params[key]))
    if "mapping_id" in params:
        model = ScenarioBusinessMapping
        mapping_type = params.get("mapping_type")
        if mapping_type == "scenario_technical": model = ScenarioTechnicalLineage
        elif mapping_type == "source_to_mart" or "source-to-mart" in path: model = SourceToMartMapping
        elif mapping_type == "mart_to_ybt" or "mart-to-ybt" in path: model = MartToYbtMapping
        return db.get(model, int(params["mapping_id"]))
    if "mart_field_id" in params:
        return db.get(MartField, int(params["mart_field_id"]))
    if "field_id" in params:
        model = TargetField
        if "source-fields" in path: model = SourceField
        elif "mart-fields" in path: model = MartField
        return db.get(model, int(params["field_id"]))
    if "table_id" in params:
        model = TargetTable
        if "/catalog/tables" in path: model = CatalogTable
        elif "source-tables" in path: model = SourceTable
        elif "mart-tables" in path: model = MartTable
        return db.get(model, int(params["table_id"]))
    if "task_id" in params:
        model = NaturalLanguageTask
        if "profile-tasks" in path: model = ColumnProfileTask
        elif "db-profile" in path: model = DbProfileTask
        elif "metadata-sync-tasks" in path: model = MetadataSyncTask
        return db.get(model, int(params["task_id"]))
    if "document_id" in params:
        model = KnowledgeDocument if "/knowledge/" in path else MetadataImportDocument if "metadata-imports" in path else TemplateDocument
        return db.get(model, int(params["document_id"]))
    if "template_id" in params:
        model = TraceabilityTemplateDocument if "traceability-templates" in path else TemplateDocument
        return db.get(model, int(params["template_id"]))
    if "draft_id" in params:
        return db.get(FieldMappingDraft, int(params["draft_id"]))
    if "evidence_id" in params:
        return db.get(MappingEvidenceReference, int(params["evidence_id"]))
    return None


async def _body_project_id(request: Request) -> int | None:
    if request.method not in {"POST", "PUT", "PATCH"}:
        return None
    content_type = request.headers.get("content-type", "")
    try:
        if content_type.startswith("application/json"):
            body = await request.json()
            value = body.get("project_id") if isinstance(body, dict) else None
        elif content_type.startswith(("multipart/form-data", "application/x-www-form-urlencoded")):
            value = (await request.form()).get("project_id")
        else:
            value = None
    except Exception:
        return None
    return int(value) if value is not None else None


def _mapping_permission(mapping_type: str, method: str) -> str:
    if mapping_type == "scenario_business":
        return "business.edit" if method != "GET" else "project.view"
    if mapping_type in {"scenario_technical", "source_to_mart", "mart_to_ybt"}:
        return "technical.edit" if method != "GET" else "project.view"
    return "project.manage"


def _authorize_global_route(db: Session, principal: Principal, method: str, path: str) -> bool:
    if method == "GET" and path.endswith("/coze/status"):
        return True
    if path.endswith("/model-profiles") or path.endswith("/prompt-versions"):
        if PermissionService(db, principal).is_platform_admin():
            return True
        raise HTTPException(status_code=403, detail="Platform administrator required")
    return False
