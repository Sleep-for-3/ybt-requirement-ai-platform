from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from io import BytesIO

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Response, UploadFile
from openpyxl import Workbook
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import (
    AuditLog, BackgroundJob, BackgroundJobItem, CaliberComparison, DeliverableEvidenceItem,
    DeliverableFieldItem, DeliverablePackage, DeliverablePackageVersion, DeliverableTemplate,
    DeliverableTemplateVersion, HistoricalCaliberImport, HistoricalCaliberItem, MappingEvidenceReference,
    MartToYbtMapping, PendingQuestion, ProductScenario, Project, ProjectMembership, ReviewDecision, ReviewTask, ScenarioBusinessMapping,
    ScenarioTechnicalLineage, SourceToMartMapping, StoredFile, TargetField, TargetTable,
    TemplateColumnMapping, TemplateSheetMapping, WorkflowInstance,
)
from app.services.auth.dependencies import CurrentPrincipal
from app.services.auth.permission_service import PermissionService
from app.schemas.deliverables import (
    DeliverableCreateRequest,
    PendingQuestionCreateRequest,
    PendingQuestionUpdateRequest,
    TemplateConfigureRequest,
)
from app.services.deliverables.historical import parse_historical_workbook, semantic_diff
from app.services.deliverables.mart_to_ybt_compiler import compile_mart_to_ybt
from app.services.deliverables.readiness_service import field_readiness, table_readiness
from app.services.deliverables.source_to_mart_compiler import compile_source_to_mart
from app.services.deliverables.template_validation import validate_template_version
from app.services.deliverables.validation_service import validate_package
from app.services.deliverables.workbook import inspect_workbook, render_workbook
from app.services.governance.audit import record_audit
from app.services.governance.notifications import notify_user
from app.services.governance.workflow import start_workflow
from app.services.storage import get_storage_service
from app.services.security import redact_content
from app.services.task_queue import get_task_queue

router = APIRouter(tags=["deliverables"])
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
TEMPLATE_TYPES = {"business_traceability", "source_to_mart", "mart_to_ybt", "full_delivery_package", "pending_questions", "evidence_matrix", "change_comparison"}
SECTIONS = {"target_field", "scenario_business_mapping", "scenario_technical_lineage", "source_to_mart", "mart_to_ybt", "pending_question", "evidence", "review_record", "lineage", "change_impact"}


@router.post("/projects/{project_id}/deliverable-templates/upload", status_code=201)
async def upload_template(project_id: int, principal: CurrentPrincipal, file: UploadFile = File(...), template_name: str = Form(""), template_type: str = Form("full_delivery_package"), description: str | None = Form(None), template_id: int | None = Form(None), db: Session = Depends(get_db)) -> dict:
    project = _permission(db, principal, project_id, "template.manage")
    if template_type not in TEMPLATE_TYPES: raise HTTPException(400, "Invalid template_type")
    if not (file.filename or "").lower().endswith(".xlsx"): raise HTTPException(400, "Only .xlsx templates are supported")
    content = await file.read()
    digest = hashlib.sha256(content).hexdigest()
    if template_id:
        template = _resource(db, DeliverableTemplate, template_id, project_id)
    else:
        template = DeliverableTemplate(institution_id=project.institution_id, project_id=project_id, template_name=template_name or file.filename or "交付模板", template_type=template_type, description=description, created_by=principal.user_id)
        db.add(template); db.flush()
    duplicate = db.scalar(select(DeliverableTemplateVersion).where(DeliverableTemplateVersion.template_id == template.id, DeliverableTemplateVersion.file_hash == digest))
    if duplicate:
        return _template_detail(db, template, duplicate)
    metadata = inspect_workbook(content)
    stored = _store_file(db, project, principal.user_id, file.filename or "template.xlsx", content, XLSX)
    version = DeliverableTemplateVersion(project_id=project_id, template_id=template.id, version_no=template.current_version_no + 1, stored_file_id=stored.id, file_hash=digest, sheet_config_json=metadata["sheets"], layout_config_json={"sheet_order": metadata["sheet_names"]}, parse_status="parsed", created_by=principal.user_id)
    db.add(version); db.flush(); template.current_version_no = version.version_no
    for sheet in metadata["sheets"]:
        db.add(TemplateSheetMapping(project_id=project_id, template_version_id=version.id, business_section="target_field", sheet_name=sheet["sheet_name"], header_row_start=sheet["header_row_start"], header_row_end=sheet["header_row_end"], data_start_row=sheet["header_row_end"] + 1, enabled=False))
    record_audit(db, action="upload_template", resource_type="deliverable_template_version", resource_id=version.id, actor_user_id=principal.user_id, institution_id=project.institution_id, project_id=project_id, after={"file_hash": digest, "template_type": template_type, "sheet_count": len(metadata["sheets"])})
    db.commit(); return _template_detail(db, template, version)


@router.get("/projects/{project_id}/deliverable-templates")
def list_templates(project_id: int, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> list[dict]:
    _permission(db, principal, project_id, "deliverable.view")
    result = []
    for item in db.scalars(select(DeliverableTemplate).where(DeliverableTemplate.project_id == project_id).order_by(DeliverableTemplate.id.desc())).all():
        row = _row(item)
        version = db.scalar(select(DeliverableTemplateVersion).where(DeliverableTemplateVersion.template_id == item.id, DeliverableTemplateVersion.version_no == item.current_version_no))
        row["current_version_id"] = version.id if version else None
        result.append(row)
    return result


@router.get("/deliverable-templates/{template_id}")
def get_template(template_id: int, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> dict:
    template = _resource_visible(db, principal, DeliverableTemplate, template_id)
    versions = list(db.scalars(select(DeliverableTemplateVersion).where(DeliverableTemplateVersion.template_id == template.id).order_by(DeliverableTemplateVersion.version_no.desc())).all())
    result = _row(template); result["versions"] = [_row(version) for version in versions]; return result


@router.get("/deliverable-template-versions/{version_id}/preview")
def preview_template(version_id: int, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> dict:
    version = _resource_visible(db, principal, DeliverableTemplateVersion, version_id)
    return {**_row(version), "sheet_mappings": [_row(item) for item in _sheet_mappings(db, version.id)], "column_mappings": [_row(item) for item in _column_mappings(db, version.id)]}


@router.post("/deliverable-template-versions/{version_id}/configure")
def configure_template(version_id: int, principal: CurrentPrincipal, payload: TemplateConfigureRequest, db: Session = Depends(get_db)) -> dict:
    version = _resource_visible(db, principal, DeliverableTemplateVersion, version_id, "template.manage")
    referenced = db.scalar(select(DeliverablePackage.id).where(DeliverablePackage.template_version_id == version.id).limit(1))
    if version.parse_status == "active" or referenced is not None:
        raise HTTPException(409, "Activated or referenced template versions are immutable; upload a new version")
    configured = payload.model_dump()
    available_sheets = {item["sheet_name"] for item in version.sheet_config_json}
    for item in configured["sheet_mappings"]:
        if item["sheet_name"] not in available_sheets:
            raise HTTPException(400, "Configured sheet does not exist in the workbook")
    for existing in _column_mappings(db, version.id): db.delete(existing)
    db.flush()
    for existing in _sheet_mappings(db, version.id): db.delete(existing)
    db.flush()
    for item in configured["sheet_mappings"]:
        sheet = TemplateSheetMapping(project_id=version.project_id, template_version_id=version.id, business_section=item["business_section"], sheet_name=item["sheet_name"], header_row_start=item["header_row_start"], header_row_end=item["header_row_end"], data_start_row=item["data_start_row"], repeat_direction=item["repeat_direction"], enabled=item["enabled"])
        db.add(sheet); db.flush()
        for column in item["columns"]:
            db.add(TemplateColumnMapping(project_id=version.project_id, template_sheet_mapping_id=sheet.id, business_field=column["business_field"], excel_column=column["excel_column"], excel_header=column["excel_header"], write_mode=column["write_mode"], merge_strategy=column["merge_strategy"], required=column["required"], default_value=column["default_value"], format_config_json=column["format_config_json"]))
    db.flush()
    validation = validate_template_version(db, version.id)
    structural_errors = [
        issue for issue in validation["issues"]
        if issue["severity"] == "error" and issue["code"] != "required_section_missing"
    ]
    if structural_errors:
        db.rollback()
        raise HTTPException(400, {"message": "Invalid template configuration", "issues": structural_errors})
    version.column_mapping_json = configured["sheet_mappings"]
    version.warnings_json = validation["issues"]
    record_audit(db, action="configure_template_mapping", resource_type="deliverable_template_version", resource_id=version.id, actor_user_id=principal.user_id, project_id=version.project_id, after={"sheet_mapping_count": len(configured["sheet_mappings"])})
    db.commit(); return preview_template(version.id, principal, db)


@router.post("/deliverable-template-versions/{version_id}/activate")
def activate_template(version_id: int, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> dict:
    version = _resource_visible(db, principal, DeliverableTemplateVersion, version_id, "template.manage")
    template = db.get(DeliverableTemplate, version.template_id)
    validation = validate_template_version(db, version.id)
    if not validation["valid"]:
        raise HTTPException(409, {"message": "Template validation failed", "validation": validation})
    siblings = list(db.scalars(select(DeliverableTemplate).where(DeliverableTemplate.project_id == template.project_id, DeliverableTemplate.template_type == template.template_type)).all())
    for sibling in siblings: sibling.is_default = sibling.id == template.id
    template.current_version_no = version.version_no; template.enabled = True; version.parse_status = "active"
    record_audit(db, action="activate_template_version", resource_type="deliverable_template_version", resource_id=version.id, actor_user_id=principal.user_id, project_id=version.project_id)
    db.commit(); return _row(template)


@router.post("/deliverable-template-versions/{version_id}/validate")
def validate_template(version_id: int, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> dict:
    version = _resource_visible(db, principal, DeliverableTemplateVersion, version_id, "template.manage")
    result = validate_template_version(db, version.id)
    version.warnings_json = result["issues"]
    db.commit()
    return result


@router.post("/deliverable-template-versions/{version_id}/preview-render")
def preview_render(version_id: int, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> Response:
    version = _resource_visible(db, principal, DeliverableTemplateVersion, version_id, "template.manage")
    template_content = _read_stored(db, version.stored_file_id)
    rendered, warnings = render_workbook(template_content, _sheet_mappings(db, version.id), _column_mappings(db, version.id), _sample_records(), preview_limit=20)
    return Response(rendered, media_type=XLSX, headers={"Content-Disposition": "attachment; filename=deliverable-preview.xlsx", "X-Preview-Warnings": str(len(warnings))})


@router.post("/projects/{project_id}/historical-calibers/upload", status_code=201)
async def upload_historical(project_id: int, principal: CurrentPrincipal, file: UploadFile = File(...), document_type: str = Form("unknown"), import_name: str = Form(""), db: Session = Depends(get_db)) -> dict:
    project = _permission(db, principal, project_id, "historical_caliber.import")
    content = await file.read(); inspect_workbook(content)
    stored = _store_file(db, project, principal.user_id, file.filename or "historical.xlsx", content, XLSX)
    document = HistoricalCaliberImport(institution_id=project.institution_id, project_id=project.id, stored_file_id=stored.id, import_name=import_name or file.filename or "历史口径", document_type=document_type, status="parsing", created_by=principal.user_id)
    db.add(document); db.flush()
    items, warnings = parse_historical_workbook(content, db, project.id, document.id)
    db.add_all(items); document.status = "parsed"; document.warnings_json = warnings; document.parse_summary_json = {"item_count": len(items), "matched_count": sum(item.match_status == "matched" for item in items), "ambiguous_count": sum(item.match_status == "ambiguous" for item in items)}
    record_audit(db, action="import_historical_caliber", resource_type="historical_caliber_import", resource_id=document.id, actor_user_id=principal.user_id, institution_id=project.institution_id, project_id=project.id, after=document.parse_summary_json)
    db.commit(); return {**_row(document), "items": [_row(item) for item in items[:100]]}


@router.get("/historical-calibers/{import_id}/preview")
def preview_historical(import_id: int, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> dict:
    document = _resource_visible(db, principal, HistoricalCaliberImport, import_id)
    items = list(db.scalars(select(HistoricalCaliberItem).where(HistoricalCaliberItem.historical_import_id == document.id).order_by(HistoricalCaliberItem.id).limit(500)).all())
    return {**_row(document), "items": [_row(item) for item in items]}


@router.post("/historical-calibers/{import_id}/apply")
def apply_historical(import_id: int, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> dict:
    document = _resource_visible(db, principal, HistoricalCaliberImport, import_id, "historical_caliber.reuse")
    ambiguous = db.scalar(select(HistoricalCaliberItem.id).where(HistoricalCaliberItem.historical_import_id == document.id, HistoricalCaliberItem.match_status == "ambiguous").limit(1))
    if ambiguous: raise HTTPException(409, "Ambiguous historical rows require manual confirmation")
    document.status = "applied"; db.commit(); return _row(document)


@router.get("/target-fields/{field_id}/historical-calibers")
def field_historical(field_id: int, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> list[dict]:
    field = _resource_visible(db, principal, TargetField, field_id)
    return [_row(item) for item in db.scalars(select(HistoricalCaliberItem).where(HistoricalCaliberItem.matched_target_field_id == field.id).order_by(HistoricalCaliberItem.id.desc())).all()]


@router.post("/historical-caliber-items/{item_id}/reuse")
def reuse_historical(item_id: int, principal: CurrentPrincipal, payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    item = _resource_visible(db, principal, HistoricalCaliberItem, item_id, "historical_caliber.reuse")
    if item.match_status != "matched" or not item.matched_target_field_id: raise HTTPException(409, "Historical item must be uniquely matched")
    if not item.matched_scenario_id: raise HTTPException(409, "Scenario requires manual confirmation")
    business = db.scalar(select(ScenarioBusinessMapping).where(ScenarioBusinessMapping.target_field_id == item.matched_target_field_id, ScenarioBusinessMapping.scenario_id == item.matched_scenario_id))
    technical = db.scalar(select(ScenarioTechnicalLineage).where(ScenarioTechnicalLineage.target_field_id == item.matched_target_field_id, ScenarioTechnicalLineage.scenario_id == item.matched_scenario_id))
    if item.business_content:
        if business is None: business = ScenarioBusinessMapping(project_id=item.project_id, target_field_id=item.matched_target_field_id, scenario_id=item.matched_scenario_id); db.add(business)
        business.ai_generated_content = f"[历史建议 #{item.id} {item.source_sheet_name}!{item.source_cell_range}]\n{item.business_content}"
    if item.technical_content:
        if technical is None: technical = ScenarioTechnicalLineage(project_id=item.project_id, target_field_id=item.matched_target_field_id, scenario_id=item.matched_scenario_id); db.add(technical)
        technical.ai_generated_content = f"[历史建议 #{item.id} {item.source_sheet_name}!{item.source_cell_range}]\n{item.technical_content}"
    record_audit(db, action="reuse_historical_caliber", resource_type="historical_caliber_item", resource_id=item.id, actor_user_id=principal.user_id, project_id=item.project_id, after={"target_field_id": item.matched_target_field_id, "scenario_id": item.matched_scenario_id})
    db.commit(); return {"item_id": item.id, "business_mapping_id": business.id if business else None, "technical_lineage_id": technical.id if technical else None, "final_content_overwritten": False}


@router.post("/historical-caliber-items/{item_id}/resolve-match")
def resolve_historical_match(item_id: int, principal: CurrentPrincipal, payload: dict = Body(...), db: Session = Depends(get_db)) -> dict:
    item = _resource_visible(db, principal, HistoricalCaliberItem, item_id, "historical_caliber.reuse")
    field = _resource(db, TargetField, int(payload["target_field_id"]), item.project_id)
    scenario = _resource(db, ProductScenario, int(payload["scenario_id"]), item.project_id) if payload.get("scenario_id") is not None else None
    item.matched_target_field_id = field.id; item.matched_scenario_id = scenario.id if scenario else None; item.match_status = "matched"
    record_audit(db, action="resolve_historical_caliber_match", resource_type="historical_caliber_item", resource_id=item.id, actor_user_id=principal.user_id, project_id=item.project_id, after={"target_field_id": field.id, "scenario_id": scenario.id if scenario else None})
    db.commit(); return _row(item)


@router.post("/projects/{project_id}/caliber-comparisons", status_code=201)
def create_comparison(project_id: int, payload: dict, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> dict:
    _permission(db, principal, project_id, "deliverable.view")
    for key, model in (("historical_import_id", HistoricalCaliberImport), ("target_field_id", TargetField), ("left_package_version_id", DeliverablePackageVersion), ("right_package_version_id", DeliverablePackageVersion)):
        if payload.get(key) is not None:
            _resource(db, model, int(payload[key]), project_id)
    left, right = payload.get("left", {}), payload.get("right", {})
    if payload.get("left_package_version_id") and payload.get("right_package_version_id"):
        left = _snapshot_comparable(db.get(DeliverablePackageVersion, int(payload["left_package_version_id"])).content_snapshot_json)
        right = _snapshot_comparable(db.get(DeliverablePackageVersion, int(payload["right_package_version_id"])).content_snapshot_json)
    keys = sorted(set(left) | set(right)); result = {key: {"left": left.get(key), "right": right.get(key), "difference_type": semantic_diff(left.get(key), right.get(key))} for key in keys}
    comparison = CaliberComparison(project_id=project_id, historical_import_id=payload.get("historical_import_id"), target_field_id=payload.get("target_field_id"), left_package_version_id=payload.get("left_package_version_id"), right_package_version_id=payload.get("right_package_version_id"), result_json=result, created_by=principal.user_id)
    db.add(comparison); db.flush(); record_audit(db, action="compare_versions", resource_type="caliber_comparison", resource_id=comparison.id, actor_user_id=principal.user_id, project_id=project_id, after={"field_count": len(result)}); db.commit(); return _row(comparison)


@router.get("/caliber-comparisons/{comparison_id}")
def get_comparison(comparison_id: int, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> dict:
    return _row(_resource_visible(db, principal, CaliberComparison, comparison_id))


@router.get("/target-fields/{field_id}/delivery-readiness")
def get_field_readiness(field_id: int, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> dict:
    field = _resource_visible(db, principal, TargetField, field_id); return field_readiness(db, field.id)


@router.get("/target-tables/{table_id}/delivery-readiness")
def get_table_readiness(table_id: int, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> dict:
    table = _resource_visible(db, principal, TargetTable, table_id); return table_readiness(db, table.id)


@router.post("/projects/{project_id}/questions", status_code=201)
def create_question(project_id: int, payload: PendingQuestionCreateRequest, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> dict:
    values = payload.model_dump()
    project = _permission(db, principal, project_id, "question.manage")
    table = _resource(db, TargetTable, values["target_table_id"], project_id)
    if values["target_field_id"] is not None:
        target_field = _resource(db, TargetField, values["target_field_id"], project_id)
        if target_field.target_table_id != table.id: raise HTTPException(400, "Target field does not belong to target table")
    if values["scenario_id"] is not None:
        _resource(db, ProductScenario, values["scenario_id"], project_id)
    if values["assigned_user_id"] is not None:
        membership = db.scalar(select(ProjectMembership.id).where(ProjectMembership.project_id == project_id, ProjectMembership.user_id == values["assigned_user_id"], ProjectMembership.status == "active"))
        if membership is None: raise HTTPException(400, "Assigned user is not an active project member")
    question = PendingQuestion(institution_id=project.institution_id, project_id=project_id, target_table_id=table.id, target_field_id=values["target_field_id"], scenario_id=values["scenario_id"], question_type=values["question_type"], question_text=values["question_text"], priority=values["priority"], assigned_role=values["assigned_role"], assigned_user_id=values["assigned_user_id"], source_type=values["source_type"], source_id=values["source_id"], question_status="assigned" if values["assigned_user_id"] or values["assigned_role"] else "open")
    db.add(question); db.flush(); record_audit(db, action="create_question", resource_type="pending_question", resource_id=question.id, actor_user_id=principal.user_id, institution_id=project.institution_id, project_id=project_id, after={"question_type": question.question_type, "priority": question.priority})
    if question.assigned_user_id:
        notify_user(db, question.assigned_user_id, "pending_question_assigned", "新的待确认问题", question.question_text[:200], project_id=project_id, resource_type="pending_question", resource_id=question.id)
    db.commit(); return _row(question)


@router.get("/projects/{project_id}/questions")
def list_questions(project_id: int, principal: CurrentPrincipal, status: str | None = None, target_field_id: int | None = None, db: Session = Depends(get_db)) -> list[dict]:
    _permission(db, principal, project_id, "deliverable.view"); query = select(PendingQuestion).where(PendingQuestion.project_id == project_id)
    if status: query = query.where(PendingQuestion.question_status == status)
    if target_field_id: query = query.where(PendingQuestion.target_field_id == target_field_id)
    return [_row(item) for item in db.scalars(query.order_by(PendingQuestion.id.desc())).all()]


@router.patch("/questions/{question_id}")
def update_question(question_id: int, payload: PendingQuestionUpdateRequest, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> dict:
    values = payload.model_dump(exclude_unset=True)
    question = _resource_visible(db, principal, PendingQuestion, question_id, "question.manage")
    if values.get("assigned_user_id") is not None:
        membership = db.scalar(select(ProjectMembership.id).where(ProjectMembership.project_id == question.project_id, ProjectMembership.user_id == values["assigned_user_id"], ProjectMembership.status == "active"))
        if membership is None: raise HTTPException(400, "Assigned user is not an active project member")
    for key, value in values.items(): setattr(question, key, value)
    record_audit(db, action="assign_question" if "assigned_user_id" in values or "assigned_role" in values else "update_question", resource_type="pending_question", resource_id=question.id, actor_user_id=principal.user_id, project_id=question.project_id, after=values)
    if "assigned_user_id" in values and question.assigned_user_id:
        notify_user(db, question.assigned_user_id, "pending_question_assigned", "待确认问题已分派", question.question_text[:200], project_id=question.project_id, resource_type="pending_question", resource_id=question.id)
    db.commit(); return _row(question)


@router.post("/questions/{question_id}/answer")
def answer_question(question_id: int, payload: dict, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> dict:
    question = _resource_visible(db, principal, PendingQuestion, question_id, "question.answer")
    question.resolution_text = payload.get("resolution_text", ""); question.resolved_by = principal.user_id; question.question_status = "answered"
    record_audit(db, action="answer_question", resource_type="pending_question", resource_id=question.id, actor_user_id=principal.user_id, project_id=question.project_id, after={"question_status": "answered"}); db.commit(); return _row(question)


@router.post("/questions/{question_id}/{decision}")
def decide_question(question_id: int, decision: str, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> dict:
    if decision not in {"accept", "reject", "close"}: raise HTTPException(404, "Unknown action")
    question = _resource_visible(db, principal, PendingQuestion, question_id, "question.manage")
    question.question_status = {"accept": "accepted", "reject": "rejected", "close": "closed"}[decision]
    if decision in {"accept", "close"}: question.resolved_at = datetime.now(timezone.utc); question.resolved_by = principal.user_id
    record_audit(db, action=f"{decision}_question", resource_type="pending_question", resource_id=question.id, actor_user_id=principal.user_id, project_id=question.project_id, after={"question_status": question.question_status}); db.commit(); return _row(question)


@router.get("/projects/{project_id}/questions/export")
def export_questions(project_id: int, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> Response:
    _permission(db, principal, project_id, "deliverable.export"); rows = list(db.scalars(select(PendingQuestion).where(PendingQuestion.project_id == project_id).order_by(PendingQuestion.id)).all())
    workbook = Workbook(); sheet = workbook.active; sheet.title = "待确认问题"; sheet.append(["问题ID", "类型", "问题", "状态", "优先级", "负责人角色", "回答"])
    for row in rows: sheet.append([row.id, row.question_type, _safe_excel_text(row.question_text), row.question_status, row.priority, row.assigned_role, _safe_excel_text(row.resolution_text)])
    stream = BytesIO(); workbook.save(stream); return Response(stream.getvalue(), media_type=XLSX, headers={"Content-Disposition": "attachment; filename=pending-questions.xlsx"})


@router.post("/projects/{project_id}/deliverables", status_code=201)
def create_deliverable(project_id: int, payload: DeliverableCreateRequest, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> dict:
    project = _permission(db, principal, project_id, "deliverable.manage")
    table = _resource(db, TargetTable, payload.target_table_id, project_id)
    version = _resource(db, DeliverableTemplateVersion, payload.template_version_id, project_id)
    template = _resource(db, DeliverableTemplate, version.template_id, project_id)
    stored = db.get(StoredFile, version.stored_file_id)
    if version.parse_status != "active" or not template.enabled:
        raise HTTPException(409, "An active enabled template version is required")
    if template.template_type != payload.package_type:
        raise HTTPException(409, "Template type is not compatible with package_type")
    if stored is None or stored.project_id != project_id or not stored.enabled:
        raise HTTPException(409, "Template source file is unavailable")
    template_validation = validate_template_version(db, version.id)
    if not template_validation["valid"]:
        raise HTTPException(409, {"message": "Template validation failed", "validation": template_validation})
    package = DeliverablePackage(institution_id=project.institution_id, project_id=project_id, package_name=payload.package_name or f"{table.table_name}正式交付包", package_type=payload.package_type, target_table_id=table.id, template_version_id=version.id, created_by=principal.user_id)
    db.add(package); db.flush(); _ensure_field_items(db, package); db.commit(); return _package_detail(db, package)


@router.get("/projects/{project_id}/deliverables")
def list_deliverables(project_id: int, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> list[dict]:
    _permission(db, principal, project_id, "deliverable.view"); return [_package_detail(db, item) for item in db.scalars(select(DeliverablePackage).where(DeliverablePackage.project_id == project_id).order_by(DeliverablePackage.id.desc())).all()]


@router.get("/deliverables/{package_id}")
def get_deliverable(package_id: int, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> dict:
    return _package_detail(db, _resource_visible(db, principal, DeliverablePackage, package_id))


@router.post("/deliverables/{package_id}/generate")
def generate_deliverable(package_id: int, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> dict:
    package = _resource_visible(db, principal, DeliverablePackage, package_id, "deliverable.generate")
    package.status = "generating"; db.commit()
    job = get_task_queue().enqueue(db, job_type="deliverable_generate_field_items", institution_id=package.institution_id, project_id=package.project_id, created_by=principal.user_id or 0, idempotency_key=uuid.uuid4().hex, payload_summary={"package_id": package.id}, handler=_deliverable_generate_handler)
    package = db.get(DeliverablePackage, package.id); package.generation_job_id = job.id; db.commit()
    return {"package": _package_detail(db, package), "job": _row(job)}


def _deliverable_generate_handler(db: Session, job: BackgroundJob) -> dict:
    package = db.get(DeliverablePackage, int(job.payload_summary_json["package_id"]))
    if package is None or package.project_id != job.project_id: raise ValueError("Deliverable package not found")
    items = _ensure_field_items(db, package); success = failed = 0
    prior_items = {row.item_key: row for row in db.scalars(select(BackgroundJobItem).where(BackgroundJobItem.background_job_id == job.id)).all()}
    completed = {key for key, row in prior_items.items() if row.status == "completed"}
    for index, item in enumerate(items, 1):
        db.refresh(job)
        if job.status == "cancelled": break
        if str(item.target_field_id) in completed:
            success += 1; continue
        try:
            _sync_evidence_items(db, package, item.target_field_id)
            readiness = field_readiness(db, item.target_field_id); item.field_status = readiness["status"]; item.evidence_completeness = readiness["evidence_completeness"]; item.open_question_count = readiness["open_question_count"]
            business = list(db.scalars(select(ScenarioBusinessMapping).where(ScenarioBusinessMapping.target_field_id == item.target_field_id)).all()); technical = list(db.scalars(select(ScenarioTechnicalLineage).where(ScenarioTechnicalLineage.target_field_id == item.target_field_id)).all())
            item.business_summary = "\n".join(row.final_content or row.ai_generated_content or "待确认" for row in business); item.technical_summary = "\n".join(row.final_content or row.ai_generated_content or "待确认" for row in technical)
            item.confidence_level = "confirmed" if readiness["status"] == "approved" else "evidence_supported" if readiness["evidence_completeness"] >= .5 else "unverified"
            job_item = prior_items.get(str(item.target_field_id)) or BackgroundJobItem(background_job_id=job.id, item_key=str(item.target_field_id), result_summary_json={})
            job_item.status = "completed"; job_item.result_summary_json = {"readiness": item.field_status}; job_item.error_message = None; db.add(job_item); success += 1
        except Exception as exc:
            job_item = prior_items.get(str(item.target_field_id)) or BackgroundJobItem(background_job_id=job.id, item_key=str(item.target_field_id), result_summary_json={})
            job_item.status = "failed"; job_item.result_summary_json = {}; job_item.error_message = str(exc)[:1000]; db.add(job_item); failed += 1
        job.progress = int(index / max(len(items), 1) * 100)
    package.status = "draft" if job.status != "cancelled" else "generating"
    result = {"success_count": success, "failed_count": failed, "total_count": len(items)}
    record_audit(db, action="generate_deliverable", resource_type="deliverable_package", resource_id=package.id, actor_user_id=job.created_by, project_id=package.project_id, after=result); db.commit(); return result


@router.post("/deliverables/{package_id}/validate")
def validate_deliverable(package_id: int, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> dict:
    package = _resource_visible(db, principal, DeliverablePackage, package_id, "deliverable.manage"); result = validate_package(db, package.id); record_audit(db, action="validate_deliverable", resource_type="deliverable_package", resource_id=package.id, actor_user_id=principal.user_id, project_id=package.project_id, after={"error_count": result["error_count"], "warning_count": result["warning_count"]}); db.commit(); return result


@router.post("/deliverables/{package_id}/submit-review")
def submit_deliverable(package_id: int, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> dict:
    package = _resource_visible(db, principal, DeliverablePackage, package_id, "deliverable.manage")
    if package.status != "generated":
        raise HTTPException(409, "Only a generated deliverable can be submitted for review")
    template_validation = validate_template_version(db, package.template_version_id)
    if not template_validation["valid"]:
        raise HTTPException(409, {"message": "Template validation failed", "validation": template_validation})
    _verify_rendered_file(db, package)
    validation = validate_package(db, package.id, update_status=False)
    if validation["error_count"]: db.rollback(); raise HTTPException(409, {"message": "Deliverable validation failed", "validation": validation})
    package.status = "pending_review"; db.flush()
    instance = start_workflow(db, project_id=package.project_id, workflow_key="project_export_review", target_type="deliverable_package", target_id=package.id, created_by=principal.user_id or 0, assignments={})
    snapshot_hash = _review_content_hash(db, package)
    submission_hash = _review_submission_hash(instance.id, package.generated_file_id, package.content_hash, snapshot_hash)
    package.summary_json = {**(package.summary_json or {}), "review_submission": {"workflow_instance_id": instance.id, "generated_file_id": package.generated_file_id, "content_hash": package.content_hash, "review_snapshot_hash": snapshot_hash, "review_submission_hash": submission_hash}}
    record_audit(db, action="submit_deliverable_review", resource_type="deliverable_package", resource_id=package.id, actor_user_id=principal.user_id, project_id=package.project_id, after={"workflow_instance_id": instance.id, "generated_file_id": package.generated_file_id, "content_hash": package.content_hash}); db.commit()
    return {"package": _row(package), "workflow_instance": _row(instance)}


@router.post("/deliverables/{package_id}/render")
def render_deliverable(package_id: int, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> dict:
    package = _resource_visible(db, principal, DeliverablePackage, package_id, "deliverable.export")
    template_validation = validate_template_version(db, package.template_version_id)
    if not template_validation["valid"]:
        package.status = "render_failed"
        package.generated_file_id = None
        package.content_hash = None
        package.summary_json = {key: value for key, value in (package.summary_json or {}).items() if key != "review_submission"} | {"render_validation": template_validation}
        package.warnings_json = template_validation["issues"]
        db.commit()
        return {"package": _row(package), "file_id": None, "issues": template_validation["issues"]}
    version = db.get(DeliverableTemplateVersion, package.template_version_id); template_content = _read_stored(db, version.stored_file_id)
    records = _package_records(db, package); rendered, warnings = render_workbook(template_content, _sheet_mappings(db, version.id), _column_mappings(db, version.id), records)
    render_validation = {"valid": not any(item["severity"] == "error" for item in warnings), "error_count": sum(item["severity"] == "error" for item in warnings), "warning_count": sum(item["severity"] == "warning" for item in warnings), "issues": warnings}
    base_summary = {key: value for key, value in (package.summary_json or {}).items() if key != "review_submission"}
    if not render_validation["valid"]:
        package.generated_file_id = None
        package.content_hash = None
        package.status = "render_failed"
        package.warnings_json = warnings
        package.summary_json = base_summary | {"render_validation": render_validation, "rendered_at": datetime.now(timezone.utc).isoformat()}
        record_audit(db, action="render_deliverable_failed", resource_type="deliverable_package", resource_id=package.id, actor_user_id=principal.user_id, institution_id=package.institution_id, project_id=package.project_id, after={"error_count": render_validation["error_count"], "warning_count": render_validation["warning_count"]})
        db.commit()
        return {"package": _row(package), "file_id": None, "issues": warnings}
    project = db.get(Project, package.project_id); stored = _store_file(db, project, principal.user_id, f"{package.package_name}-v{package.version_no + 1}.xlsx", rendered, XLSX)
    package.generated_file_id = stored.id; package.content_hash = stored.content_hash; package.status = "generated"; package.warnings_json = warnings; package.summary_json = base_summary | {"rendered_at": datetime.now(timezone.utc).isoformat(), "render_validation": render_validation}
    record_audit(db, action="render_deliverable_excel", resource_type="deliverable_package", resource_id=package.id, actor_user_id=principal.user_id, institution_id=package.institution_id, project_id=package.project_id, after={"file_id": stored.id, "content_hash": stored.content_hash, "warning_count": len(warnings)}); db.commit(); return {"package": _row(package), "file_id": stored.id, "issues": warnings, "warnings": warnings}


@router.get("/deliverables/{package_id}/download")
def download_deliverable(package_id: int, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> Response:
    package = _resource_visible(db, principal, DeliverablePackage, package_id, "deliverable.export")
    if not package.generated_file_id: raise HTTPException(409, "Deliverable has not been rendered")
    stored = db.get(StoredFile, package.generated_file_id); content = get_storage_service().read(stored.storage_key); record_audit(db, action="download_deliverable_excel", resource_type="deliverable_package", resource_id=package.id, actor_user_id=principal.user_id, project_id=package.project_id, after={"file_id": stored.id}); db.commit(); return Response(content, media_type=XLSX, headers={"Content-Disposition": f"attachment; filename=deliverable-{package.id}.xlsx"})


@router.post("/deliverables/{package_id}/approve")
def approve_deliverable(package_id: int, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> dict:
    package = _resource_visible(db, principal, DeliverablePackage, package_id, "deliverable.review")
    submission = (package.summary_json or {}).get("review_submission") or {}
    workflow_id = submission.get("workflow_instance_id")
    if package.status == "approved" and workflow_id:
        existing = db.scalar(select(DeliverablePackageVersion).where(DeliverablePackageVersion.project_id == package.project_id, DeliverablePackageVersion.deliverable_package_id == package.id, DeliverablePackageVersion.workflow_instance_id == workflow_id))
        if existing is not None:
            return {"package": _row(package), "version": _row(existing), "idempotent": True}
    if package.status != "pending_review":
        raise HTTPException(409, "Only a pending-review deliverable can be approved")
    template_validation = validate_template_version(db, package.template_version_id)
    if not template_validation["valid"]:
        raise HTTPException(409, {"message": "Template validation failed", "validation": template_validation})
    _verify_rendered_file(db, package)
    validation = validate_package(db, package.id, update_status=False)
    if validation["error_count"]: db.rollback(); raise HTTPException(409, {"message": "Deliverable validation failed", "validation": validation})
    workflow = db.get(WorkflowInstance, workflow_id) if workflow_id else None
    if workflow is not None and (workflow.project_id != package.project_id or workflow.target_type != "deliverable_package" or workflow.target_id != package.id):
        workflow = None
    if workflow is None or workflow.status != "approved": raise HTTPException(409, "Deliverable final review task has not been approved")
    snapshot_hash = _review_content_hash(db, package)
    expected_submission_hash = _review_submission_hash(workflow.id, package.generated_file_id, package.content_hash, snapshot_hash)
    if submission.get("workflow_instance_id") != workflow.id or submission.get("generated_file_id") != package.generated_file_id or submission.get("content_hash") != package.content_hash or submission.get("review_snapshot_hash") != snapshot_hash or submission.get("review_submission_hash") != expected_submission_hash:
        raise HTTPException(409, "The current rendered deliverable has not completed final review")
    existing = db.scalar(select(DeliverablePackageVersion).where(DeliverablePackageVersion.project_id == package.project_id, DeliverablePackageVersion.deliverable_package_id == package.id, DeliverablePackageVersion.workflow_instance_id == workflow.id))
    if existing is not None:
        package.status = "approved"; package.version_no = existing.version_no; db.commit()
        return {"package": _row(package), "version": _row(existing), "idempotent": True}
    package.version_no += 1; package.status = "approved"; package.approved_at = datetime.now(timezone.utc); package.approved_by = principal.user_id
    snapshot = _package_snapshot(db, package); version = DeliverablePackageVersion(project_id=package.project_id, deliverable_package_id=package.id, version_no=package.version_no, generated_file_id=package.generated_file_id, workflow_instance_id=workflow.id, content_hash=package.content_hash or "", review_snapshot_hash=snapshot_hash, review_submission_hash=expected_submission_hash, content_snapshot_json=snapshot, change_summary_json={}, approved_by=principal.user_id, approved_at=package.approved_at)
    db.add(version); db.flush(); record_audit(db, action="approve_deliverable_version", resource_type="deliverable_package_version", resource_id=version.id, actor_user_id=principal.user_id, project_id=package.project_id, after={"version_no": version.version_no, "content_hash": version.content_hash}); db.commit(); return {"package": _row(package), "version": _row(version)}


@router.get("/deliverables/{package_id}/versions")
def list_deliverable_versions(package_id: int, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> list[dict]:
    package = _resource_visible(db, principal, DeliverablePackage, package_id); return [_row(item) for item in db.scalars(select(DeliverablePackageVersion).where(DeliverablePackageVersion.deliverable_package_id == package.id).order_by(DeliverablePackageVersion.version_no.desc())).all()]


@router.get("/deliverable-package-versions/{version_id}")
def get_deliverable_version(version_id: int, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> dict:
    return _row(_resource_visible(db, principal, DeliverablePackageVersion, version_id))


@router.get("/deliverable-package-versions/{version_id}/download")
def download_deliverable_version(version_id: int, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> Response:
    version = _resource_visible(db, principal, DeliverablePackageVersion, version_id, "deliverable.export")
    stored = db.get(StoredFile, version.generated_file_id)
    if stored is None or not stored.enabled: raise HTTPException(404, "Version file not found")
    record_audit(db, action="download_deliverable_version", resource_type="deliverable_package_version", resource_id=version.id, actor_user_id=principal.user_id, project_id=version.project_id, after={"version_no": version.version_no}); db.commit()
    return Response(get_storage_service().read(stored.storage_key), media_type=XLSX, headers={"Content-Disposition": f"attachment; filename=deliverable-version-{version.version_no}.xlsx"})


@router.post("/source-to-mart-mappings/{mapping_id}/compile")
def compile_source(mapping_id: int, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> dict:
    mapping = _resource_visible(db, principal, SourceToMartMapping, mapping_id, "deliverable.generate"); result = compile_source_to_mart(db, mapping.id); record_audit(db, action="compile_source_to_mart", resource_type="source_to_mart_mapping", resource_id=mapping.id, actor_user_id=principal.user_id, project_id=mapping.project_id); db.commit(); return result


@router.post("/mart-to-ybt-mappings/{mapping_id}/compile")
def compile_ybt(mapping_id: int, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> dict:
    mapping = _resource_visible(db, principal, MartToYbtMapping, mapping_id, "deliverable.generate"); result = compile_mart_to_ybt(db, mapping.id); record_audit(db, action="compile_mart_to_ybt", resource_type="mart_to_ybt_mapping", resource_id=mapping.id, actor_user_id=principal.user_id, project_id=mapping.project_id); db.commit(); return result


def _permission(db, principal, project_id, permission): return PermissionService(db, principal).require_project_permission(project_id, permission)
def _resource(db, model, resource_id, project_id):
    item = db.get(model, resource_id)
    if item is None or item.project_id != project_id: raise HTTPException(404, "Resource not found")
    return item
def _resource_visible(db, principal, model, resource_id, permission="deliverable.view"):
    item = db.get(model, resource_id)
    if item is None: raise HTTPException(404, "Resource not found")
    _permission(db, principal, item.project_id, permission); return item
def _row(item): return {column.key: getattr(item, column.key) for column in item.__table__.columns}
def _sheet_mappings(db, version_id): return list(db.scalars(select(TemplateSheetMapping).where(TemplateSheetMapping.template_version_id == version_id).order_by(TemplateSheetMapping.id)).all())
def _column_mappings(db, version_id):
    sheet_ids = select(TemplateSheetMapping.id).where(TemplateSheetMapping.template_version_id == version_id)
    return list(db.scalars(select(TemplateColumnMapping).where(TemplateColumnMapping.template_sheet_mapping_id.in_(sheet_ids)).order_by(TemplateColumnMapping.id)).all())
def _template_detail(db, template, version): return {"template": _row(template), "version": _row(version), "sheet_mappings": [_row(item) for item in _sheet_mappings(db, version.id)]}
def _read_stored(db, file_id):
    row = db.get(StoredFile, file_id)
    if row is None or not row.enabled: raise HTTPException(404, "Stored template file not found")
    return get_storage_service().read(row.storage_key)
def _store_file(db, project, user_id, file_name, content, content_type):
    digest = hashlib.sha256(content).hexdigest(); existing = db.scalar(select(StoredFile).where(StoredFile.project_id == project.id, StoredFile.content_hash == digest, StoredFile.enabled.is_(True)))
    if existing: return existing
    saved = get_storage_service().save(content, file_name=file_name, project_id=project.id); row = StoredFile(institution_id=project.institution_id or 0, project_id=project.id, storage_key=saved.storage_key, original_file_name=file_name, content_type=content_type, byte_size=saved.byte_size, content_hash=saved.content_hash, classification=project.confidentiality_level, created_by=user_id or 0, enabled=True); db.add(row); db.flush(); return row
def _ensure_field_items(db, package):
    existing = {item.target_field_id: item for item in db.scalars(select(DeliverableFieldItem).where(DeliverableFieldItem.deliverable_package_id == package.id)).all()}; fields = list(db.scalars(select(TargetField).where(TargetField.target_table_id == package.target_table_id).order_by(TargetField.id)).all()); result = []
    for order, field in enumerate(fields, 1):
        item = existing.get(field.id) or DeliverableFieldItem(project_id=package.project_id, deliverable_package_id=package.id, target_table_id=package.target_table_id, target_field_id=field.id, field_order=order); db.add(item); result.append(item)
    db.flush(); return result
def _package_detail(db, package):
    result = _row(package); items = list(db.scalars(select(DeliverableFieldItem).where(DeliverableFieldItem.deliverable_package_id == package.id).order_by(DeliverableFieldItem.field_order)).all()); result["items"] = [_row(item) for item in items]; result["field_count"] = len(items); result["approved_field_count"] = sum(item.field_status == "approved" for item in items); return result
def _package_snapshot(db, package):
    snapshot = {"package": _row(package), "fields": _package_detail(db, package)["items"], "records": _package_records(db, package), "approved_at": package.approved_at.isoformat() if package.approved_at else None}
    return json.loads(json.dumps(snapshot, ensure_ascii=False, default=str))
def _package_records(db, package):
    fields = list(db.scalars(select(TargetField).where(TargetField.target_table_id == package.target_table_id).order_by(TargetField.id)).all()); field_records=[]; business_records=[]; technical_records=[]
    for order, field in enumerate(fields, 1):
        base={"target_table_code": db.get(TargetTable, field.target_table_id).table_code, "target_table_name": db.get(TargetTable, field.target_table_id).table_name, "target_field_code": field.field_code, "target_field_name": field.field_name, "regulatory_definition": field.regulatory_description or field.regulatory_original_definition, "data_type": field.field_type, "field_order": order}; field_records.append(base)
        businesses=list(db.scalars(select(ScenarioBusinessMapping).where(ScenarioBusinessMapping.target_field_id==field.id)).all()); technical=list(db.scalars(select(ScenarioTechnicalLineage).where(ScenarioTechnicalLineage.target_field_id==field.id)).all())
        for item in businesses:
            scenario=db.get(ProductScenario,item.scenario_id); business_records.append({**base,"scenario_code":scenario.scenario_code,"scenario_name":scenario.scenario_name,"business_final_content":item.final_content,"business_ai_draft":item.ai_generated_content,"business_confirm_status":item.business_confirm_status,"business_confidence_level":item.confidence_level,"business_open_questions":item.open_questions})
        for item in technical:
            scenario=db.get(ProductScenario,item.scenario_id); technical_records.append({**base,"scenario_code":scenario.scenario_code,"scenario_name":scenario.scenario_name,"technical_final_content":item.final_content,"source_system_name":item.source_system_name,"database_name":item.source_database_name,"schema_name":item.source_schema_name,"source_table_name":item.source_table_english_name,"source_field_name":item.source_field_english_name,"technical_confirm_status":item.tech_confirm_status,"lineage_status":item.lineage_status})
    field_ids = [field.id for field in fields]
    questions=[_row(item) for item in db.scalars(select(PendingQuestion).where(PendingQuestion.project_id==package.project_id,PendingQuestion.target_table_id==package.target_table_id)).all()]
    evidence=[{"target_field_id":item.target_field_id,"evidence_type":item.evidence_type,"evidence_source":item.citation_summary_json.get("source_name"),"evidence_location":item.citation_summary_json.get("location"),"evidence_summary":item.claim_text,"citation":json.dumps(item.citation_summary_json,ensure_ascii=False),"claim_type":item.claim_type} for item in db.scalars(select(DeliverableEvidenceItem).where(DeliverableEvidenceItem.deliverable_package_id==package.id)).all()]
    mart_mappings = list(db.scalars(select(MartToYbtMapping).where(MartToYbtMapping.target_field_id.in_(field_ids))).all())
    mart_field_ids = [item.mart_field_id for item in mart_mappings if item.mart_field_id]
    source_rows=[{"mapping_id":item.id,"source_to_mart_final_content":item.final_content,"source_to_mart_status":item.mapping_status,"source_system_name":item.source_system_summary,"source_field_name":item.source_fields_summary,"filter_condition":item.filter_condition,"join_condition":item.join_condition,"code_mapping_rule":item.code_mapping_rule,"priority_rule":item.priority_rule,"null_handling_rule":item.null_handling_rule} for item in db.scalars(select(SourceToMartMapping).where(SourceToMartMapping.project_id==package.project_id, SourceToMartMapping.mart_field_id.in_(mart_field_ids))).all()]
    mart_rows=[{"mapping_id":item.id,"target_field_id":item.target_field_id,"mart_to_ybt_final_content":item.final_content,"mart_to_ybt_status":item.mapping_status,"filter_condition":item.filter_condition,"join_condition":item.join_condition,"code_mapping_rule":item.code_mapping_rule,"null_handling_rule":item.null_handling_rule} for item in mart_mappings]
    version_ids = [str(item) for item in db.scalars(select(DeliverablePackageVersion.id).where(DeliverablePackageVersion.deliverable_package_id == package.id)).all()]
    reviews=[{"action":item.action,"resource_type":item.resource_type,"resource_id":item.resource_id,"reviewer":item.actor_user_id,"approved_at":item.created_at,"review_comment":json.dumps(item.after_summary_json,ensure_ascii=False)} for item in db.scalars(select(AuditLog).where(AuditLog.project_id==package.project_id,AuditLog.action.in_(("approve","approve_deliverable_version","submit_deliverable_review")),or_(
        (AuditLog.resource_type == "deliverable_package") & (AuditLog.resource_id == str(package.id)),
        (AuditLog.resource_type == "deliverable_package_version") & (AuditLog.resource_id.in_(version_ids)),
    )).order_by(AuditLog.id)).all()]
    workflow_ids = select(WorkflowInstance.id).where(WorkflowInstance.project_id == package.project_id, WorkflowInstance.workflow_key == "project_export_review", WorkflowInstance.target_type == "deliverable_package", WorkflowInstance.target_id == package.id)
    decisions = db.execute(select(ReviewDecision, ReviewTask).join(ReviewTask, ReviewTask.id == ReviewDecision.review_task_id).where(ReviewTask.workflow_instance_id.in_(workflow_ids)).order_by(ReviewDecision.id)).all()
    reviews.extend({"action":decision.decision,"resource_type":"review_task","resource_id":task.id,"reviewer":decision.decided_by,"approved_at":decision.decided_at,"review_comment":redact_content(decision.comment or "")} for decision, task in decisions)
    return {"target_field":field_records,"scenario_business_mapping":business_records,"scenario_technical_lineage":technical_records,"pending_question":questions,"evidence":evidence,"source_to_mart":source_rows,"mart_to_ybt":mart_rows,"review_record":reviews,"lineage":technical_records,"change_impact":[]}
def _sample_records(): return {"target_field":[{"target_table_code":"YBT_SAMPLE","target_table_name":"脱敏示例表","target_field_code":f"FIELD_{i:03d}","target_field_name":f"脱敏示例字段{i}","regulatory_definition":"用于模板预览的脱敏模拟定义","data_type":"VARCHAR","field_order":i} for i in range(1,21)],"scenario_business_mapping":[],"scenario_technical_lineage":[],"pending_question":[],"evidence":[],"source_to_mart":[],"mart_to_ybt":[],"review_record":[],"lineage":[],"change_impact":[]}


def _snapshot_comparable(snapshot):
    records = snapshot.get("records", {}) if isinstance(snapshot, dict) else {}
    result = {}
    for section in ("scenario_business_mapping", "scenario_technical_lineage", "source_to_mart", "mart_to_ybt"):
        for index, row in enumerate(records.get(section, [])):
            identity = row.get("target_field_code") or row.get("target_field_id") or row.get("mapping_id") or index
            result[f"{section}:{identity}:{index}"] = json.dumps(row, ensure_ascii=False, sort_keys=True, default=str)
    return result


def _sync_evidence_items(db, package, field_id):
    mappings = []
    businesses = list(db.scalars(select(ScenarioBusinessMapping).where(ScenarioBusinessMapping.target_field_id == field_id)).all())
    technical = list(db.scalars(select(ScenarioTechnicalLineage).where(ScenarioTechnicalLineage.target_field_id == field_id)).all())
    mappings.extend(("scenario_business", item.id, item.scenario_id, item.business_confirm_status == "confirmed") for item in businesses)
    mappings.extend(("scenario_technical", item.id, item.scenario_id, item.tech_confirm_status == "confirmed") for item in technical)
    existing = {(item.mapping_type, item.mapping_id, item.evidence_type, item.evidence_id): item for item in db.scalars(select(DeliverableEvidenceItem).where(DeliverableEvidenceItem.deliverable_package_id == package.id, DeliverableEvidenceItem.target_field_id == field_id)).all()}
    for mapping_type, mapping_id, scenario_id, confirmed in mappings:
        refs = db.scalars(select(MappingEvidenceReference).where(MappingEvidenceReference.mapping_type == mapping_type, MappingEvidenceReference.mapping_id == mapping_id)).all()
        for ref in refs:
            key = (mapping_type, mapping_id, ref.evidence_type, ref.evidence_id)
            # Formal deliverables only carry curated summaries. Raw quoted
            # evidence may be confidential/restricted and is never copied to
            # package snapshots or exported workbooks.
            safe_summary = redact_content(ref.evidence_summary) if ref.evidence_summary else f"已绑定 {ref.evidence_type} 证据，摘要待人工补充"
            citation_summary = {"source_name": redact_content(ref.source_name), "location": redact_content(ref.location_text or "")}
            if key in existing:
                existing[key].claim_text = safe_summary; existing[key].citation_summary_json = citation_summary
                continue
            row = DeliverableEvidenceItem(project_id=package.project_id, deliverable_package_id=package.id, target_field_id=field_id, scenario_id=scenario_id, mapping_type=mapping_type, mapping_id=mapping_id, evidence_type=ref.evidence_type, evidence_id=ref.evidence_id, claim_type="confirmed" if confirmed else "evidence_supported", claim_text=safe_summary, citation_summary_json=citation_summary)
            db.add(row); existing[key] = row


def _review_content_hash(db, package) -> str:
    records = _package_records(db, package); records.pop("review_record", None)
    payload = {"records": records, "fields": _package_detail(db, package)["items"]}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def _review_submission_hash(workflow_instance_id: int, generated_file_id: int | None, content_hash: str | None, snapshot_hash: str) -> str:
    payload = f"{workflow_instance_id}:{generated_file_id}:{content_hash or ''}:{snapshot_hash}"
    return hashlib.sha256(payload.encode()).hexdigest()


def _verify_rendered_file(db, package: DeliverablePackage) -> StoredFile:
    if not package.generated_file_id or not package.content_hash:
        raise HTTPException(409, "Render the deliverable before continuing")
    stored = db.get(StoredFile, package.generated_file_id)
    if stored is None or stored.project_id != package.project_id or not stored.enabled:
        raise HTTPException(409, "Rendered deliverable file is unavailable")
    content = get_storage_service().read(stored.storage_key)
    actual_hash = hashlib.sha256(content).hexdigest()
    if actual_hash != package.content_hash or actual_hash != stored.content_hash:
        raise HTTPException(409, "Rendered deliverable content hash mismatch")
    return stored


def _safe_excel_text(value):
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value
