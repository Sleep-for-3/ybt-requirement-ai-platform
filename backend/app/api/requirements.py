"""Editable, versioned requirement scopes; existing review APIs remain authoritative."""
import hashlib
import json
from typing import Any, Literal
from urllib.parse import quote
from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Query, Response, UploadFile
from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ConfigDict, Field
from app.core.database import get_db
from app.models import (
    KnowledgeDocument,
    MartTable,
    Project,
    Requirement,
    RequirementDelivery,
    RequirementFormalDelivery,
    RequirementReviewSubmission,
    RequirementRevision,
    SourceTable,
    TargetTable,
    User,
)
from app.services.requirement_revisions import lock_requirement, load_revision, revision_document, initialize_content, edit_field, refresh_lineage, resolve_gap
from app.services.auth.dependencies import CurrentPrincipal, RealPrincipal
from app.services.auth.permission_service import PermissionService
from app.services.governance.audit import record_audit
from app.services.requirement_export_stability import StabilityError, build_stability
from app.services.requirement_replay_manifest import build_replay_manifest
from app.services.requirement_scope import ScopeInput, validate_scope, requirement_dict, load_requirement, document_content, export_document
from app.services.requirement_scope import content_digest
from app.services.requirement_batch_archive import BatchArchiveError, build_archive
from app.services.requirement_delivery import freeze_draft, load_frozen_draft, snapshot_summary
from app.services.requirement_script_basis_decision import (
    DECISION_CHOICES as SCRIPT_BASIS_DECISION_CHOICES,
    ScriptBasisDecisionError,
    record_decision as record_script_basis_decision,
)
from app.services.requirement_script_basis_diff import (
    bound_field_codes as script_basis_bound_field_codes,
    build_script_basis_diff,
)
from app.services.requirement_delivery_audit import build_delivery_audit
from app.services.requirement_delivery_status import (
    build_delivery_status,
    build_script_basis_freshness,
    gap_breakdown,
)
from app.services.requirement_field_worklist import build_field_worklist
from app.services.requirement_rejection_followup import build_rejection_followup
from app.services.requirement_field_coverage import CoverageError, build_field_coverage
from app.services.requirement_field_dispatch import (
    DispatchError,
    record_dispatch,
    serialize as serialize_dispatch,
)
from app.services.requirement_worklist_archive import WorklistArchiveError, build_worklist_archive
from app.services.requirement_table_coverage import build_table_coverage
from app.services.template_column_coverage import (
    MAX_GAP_ROWS,
    gaps_for_column,
    build_template_coverage,
)
from app.services.requirement_template_render import (
    RENDERER_VERSION as template_renderer_version,
    CustomerTemplateRenderError,
    render_requirement_artifact,
)
from app.services.requirement_survey_export import export_survey_document, renderer_version as survey_renderer_version
from app.services.requirement_render_artifact import (
    ArtifactRequest,
    LEGACY_RENDERERS,
    MEDIA_TYPES,
    RenderArtifactError,
    ensure_artifact,
    find_artifact,
    get_artifact,
    list_artifacts,
    read_artifact_bytes,
    render_identity,
)
from app.services.requirement_artifact_preview import (
    ArtifactPreviewError,
    preview_artifact,
)
from app.services.requirement_delivery_checklist import check_delivery, list_checks, record_check
from app.services.requirement_acceptance import AcceptanceError, run_acceptance, run_acceptance_batch
from app.services.requirement_artifact_attestation import (
    ATTESTATION_VERSION,
    AttestationError,
    attestations_for_project,
    record_attestation,
    serialize as serialize_attestation,
)
from app.services.requirement_docx_structure_check import (
    DocxStructureCheckError,
    check_docx_structure,
)
from app.services.requirement_survey_fidelity import (
    FidelityError,
    check_template_fidelity,
)
from app.services.requirement_survey_structure_check import (
    StructureCheckError,
    check_survey_structure,
)

def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


router = APIRouter(tags=["requirements"])


@router.post("/projects/{project_id}/requirements/{requirement_id}/revisions/{content_version}/document-assistance")
async def document_assistance(project_id: int, requirement_id: int, content_version: int,
                              principal: RealPrincipal, db: Session = Depends(get_db)):
    from app.services.ai_skills.document_context import assist_document
    result = await assist_document(db, principal, project_id, requirement_id, content_version)
    db.commit()
    return result

from app.services.requirement_generation import PrepareGenerationInput, prepare_input, input_summary
from app.services.requirement_script_basis import ScriptSelection, ConfirmScriptBasis
from app.services.requirement_policy_comparison import ConfirmPolicyComparison
from app.services.requirement_paths import ConfirmPaths
from app.services.requirement_script_batch import CreateScriptRequirements


class RecheckCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_content_version: int = Field(gt=0)
    change_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class RecheckRevision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_content_version: int = Field(gt=0)
    reason: str = Field(min_length=1, max_length=10000)


@router.get("/projects/{project_id}/requirements/change-impacts")
def requirement_change_impacts(project_id: int, principal: CurrentPrincipal,
                              after_id: int = Query(default=0, ge=0), db: Session = Depends(get_db)):
    PermissionService(db, principal).require_project_permission(project_id, "project.view")
    from app.services.requirement_recheck import impact_summary
    rows = list(db.scalars(select(Requirement).where(Requirement.project_id == project_id,
        Requirement.id > after_id).order_by(Requirement.id).limit(51)))
    impacts = [impact for row in rows[:50] if (impact := impact_summary(db, row))]
    return {"items": impacts, "next_after_id": rows[49].id if len(rows) > 50 else None}


@router.get("/projects/{project_id}/requirements/{requirement_id}/rechecks")
def requirement_rechecks(project_id: int, requirement_id: int, principal: CurrentPrincipal,
                         db: Session = Depends(get_db)):
    PermissionService(db, principal).require_project_permission(project_id, "project.view")
    load_requirement(db, project_id, requirement_id)
    from app.models.requirement import RequirementRecheck
    from app.services.requirement_recheck import recheck_view
    return [recheck_view(db, row) for row in db.scalars(select(RequirementRecheck).where(
        RequirementRecheck.project_id == project_id, RequirementRecheck.requirement_id == requirement_id)
        .order_by(RequirementRecheck.id.desc()))]


@router.post("/projects/{project_id}/requirements/{requirement_id}/rechecks", status_code=201)
def open_requirement_recheck(project_id: int, requirement_id: int, payload: RecheckCreate,
                             principal: CurrentPrincipal, db: Session = Depends(get_db)):
    PermissionService(db, principal).require_project_permission(project_id, "technical.edit")
    from app.services.requirement_recheck import create_recheck, recheck_view
    requirement = lock_requirement(db, project_id, requirement_id)
    row = create_recheck(db, requirement, payload.expected_content_version, payload.change_hash, principal.user_id)
    response = recheck_view(db, row)
    db.commit()
    return response


def recheck_or_404(db, project_id, requirement_id, recheck_id):
    from app.models.requirement import RequirementRecheck
    row = db.scalar(select(RequirementRecheck).where(RequirementRecheck.id == recheck_id,
        RequirementRecheck.project_id == project_id, RequirementRecheck.requirement_id == requirement_id).with_for_update())
    if row is None:
        raise HTTPException(404, "复核记录不存在或不可见")
    return row


@router.post("/projects/{project_id}/requirements/{requirement_id}/rechecks/{recheck_id}/revise", status_code=201)
def revise_for_recheck(project_id: int, requirement_id: int, recheck_id: int, payload: RecheckRevision,
                       principal: CurrentPrincipal, db: Session = Depends(get_db)):
    project = PermissionService(db, principal).require_project_permission(project_id, "business.edit")
    from app.services.requirement_recheck import new_recheck_revision
    requirement = lock_requirement(db, project_id, requirement_id)
    row = recheck_or_404(db, project_id, requirement_id, recheck_id)
    revision = new_recheck_revision(db, requirement, row, payload.expected_content_version, payload.reason, principal.user_id)
    record_audit(db, action="revise_requirement_for_recheck", resource_type="requirement_recheck", resource_id=row.id,
        actor_user_id=principal.user_id, project_id=project_id, institution_id=project.institution_id,
        after={"content_version": revision.content_version, "reason": payload.reason})
    result = revision_document(revision)
    db.commit()
    return result


@router.post("/projects/{project_id}/requirements/{requirement_id}/rechecks/{recheck_id}/resolution")
def resolve_requirement_recheck(project_id: int, requirement_id: int, recheck_id: int, payload: RecheckRevision,
                                principal: CurrentPrincipal, db: Session = Depends(get_db)):
    project = PermissionService(db, principal).require_project_permission(project_id, "technical.edit")
    requirement = lock_requirement(db, project_id, requirement_id)
    row = recheck_or_404(db, project_id, requirement_id, recheck_id)
    if row.status == "reviewed" or requirement.content_version != payload.expected_content_version:
        raise HTTPException(409, "复核已关闭或需求版本已变化")
    revision = load_revision(db, project_id, requirement_id, payload.expected_content_version)
    from app.services.requirement_recheck import replacement_revision, recheck_view
    with db.begin_nested():
        row.replacement_revision_id = revision.id
        row.resolution = payload.reason.strip()
        replacement_revision(db, row)
        db.flush()
    record_audit(db, action="resolve_requirement_recheck", resource_type="requirement_recheck", resource_id=row.id,
        actor_user_id=principal.user_id, project_id=project_id, institution_id=project.institution_id,
        after={"replacement_content_version": revision.content_version, "resolution": row.resolution})
    db.commit()
    return recheck_view(db, row)


class RequirementUatCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_content_version: int = Field(gt=0)


@router.get("/projects/{project_id}/requirements/{requirement_id}/uat-suites")
def requirement_uat_suites(project_id: int, requirement_id: int, principal: CurrentPrincipal,
                           db: Session = Depends(get_db)):
    PermissionService(db, principal).require_project_permission(project_id, "uat.view")
    load_requirement(db, project_id, requirement_id)
    from app.models.requirement import RequirementUatLink
    from app.services.requirement_uat import link_view
    return [link_view(db, row) for row in db.scalars(select(RequirementUatLink).where(
        RequirementUatLink.project_id == project_id, RequirementUatLink.requirement_id == requirement_id)
        .order_by(RequirementUatLink.id.desc()))]


@router.post("/projects/{project_id}/requirements/{requirement_id}/uat-suites", status_code=201)
def create_requirement_uat_suite(project_id: int, requirement_id: int, payload: RequirementUatCreate,
                                 principal: CurrentPrincipal, db: Session = Depends(get_db)):
    permissions = PermissionService(db, principal)
    project = permissions.require_project_permission(project_id, "uat.manage")
    permissions.require_project_permission(project_id, "lineage.view")
    from app.services.requirement_uat import create_requirement_suite, link_view
    requirement = lock_requirement(db, project_id, requirement_id)
    link = create_requirement_suite(db, requirement, payload.expected_content_version, principal.user_id)
    record_audit(db, action="create_requirement_uat", resource_type="uat_suite", resource_id=link.suite_id,
        actor_user_id=principal.user_id, institution_id=project.institution_id, project_id=project_id,
        after={"requirement_id": requirement_id, "content_version": payload.expected_content_version})
    db.commit()
    return link_view(db, link)


@router.get("/projects/{project_id}/requirements/import-batch/{batch_id}/scripts")
def imported_requirement_scripts(project_id: int, batch_id: int, principal: CurrentPrincipal,
                                 db: Session = Depends(get_db)):
    PermissionService(db, principal).require_project_permission(project_id, "lineage.view")
    from app.services.requirement_script_batch import import_script_versions
    return import_script_versions(db, project_id, batch_id)


@router.post("/projects/{project_id}/requirements/from-scripts", status_code=201)
def create_requirements_from_scripts(project_id: int, payload: CreateScriptRequirements,
                                    principal: CurrentPrincipal, db: Session = Depends(get_db)):
    permissions = PermissionService(db, principal)
    project = permissions.require_project_permission(project_id, "technical.edit")
    permissions.require_project_permission(project_id, "business.edit")
    permissions.require_project_permission(project_id, "lineage.view")
    if any(t.scope.document_ids for t in payload.targets):
        if not ({"knowledge.search", "knowledge.manage"} & set(permissions.effective_project_permissions(project_id))):
            raise HTTPException(403, "无权将制度纳入需求依据")
    from app.services.requirement_script_batch import create_script_requirements
    result = create_script_requirements(db, project_id, payload, principal.user_id)
    if not result["deduplicated"]:
        record_audit(db, action="create_script_requirement_batch", resource_type="requirement_script_batch",
            resource_id=result["batch_id"], actor_user_id=principal.user_id,
            institution_id=project.institution_id, project_id=project_id, after=result)
    db.commit()
    return result


@router.post("/projects/{project_id}/requirements/author-preview")
def preview_script_authoring(project_id: int, payload: dict, principal: CurrentPrincipal,
                             db: Session = Depends(get_db)):
    """只读：告诉界面这些监管表能不能一键建需、原因是什么。"""
    permissions = PermissionService(db, principal)
    permissions.require_project_permission(project_id, "technical.edit")
    permissions.require_project_permission(project_id, "business.edit")
    from app.services.requirement_script_authoring import MAX_TABLES, author_candidates
    codes = _authoring_codes(payload)
    if len(codes) > MAX_TABLES:
        raise HTTPException(422, f"一次最多检查 {MAX_TABLES} 张监管表")
    return {"items": author_candidates(db, project_id, codes)}


@router.post("/projects/{project_id}/requirements/author-from-scripts", status_code=201)
def author_requirements_from_scripts(project_id: int, payload: dict, principal: CurrentPrincipal,
                                     db: Session = Depends(get_db)):
    """把"脚本可建需"的监管表批量变成需求草稿：走与手工建需完全相同的脚本依据冻结流程。"""
    permissions = PermissionService(db, principal)
    project = permissions.require_project_permission(project_id, "technical.edit")
    permissions.require_project_permission(project_id, "business.edit")
    permissions.require_project_permission(project_id, "lineage.view")
    from app.services.requirement_script_authoring import author_requirements
    codes = _authoring_codes(payload)
    scenario_id = payload.get("scenario_id")
    if scenario_id is not None and not isinstance(scenario_id, int):
        raise HTTPException(422, "scenario_id 必须是正整数")
    try:
        result = author_requirements(db, project_id, table_codes=codes, actor_id=principal.user_id,
                                     scenario_id=scenario_id)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    record_audit(db, action="author_requirements_from_scripts", resource_type="requirement", resource_id=project_id,
        actor_user_id=principal.user_id, institution_id=project.institution_id, project_id=project_id,
        after={"table_codes": codes, "created_count": result["created_count"], "item_count": result["item_count"]})
    db.commit()
    return result


def _authoring_codes(payload: dict) -> list[str]:
    raw = payload.get("table_codes")
    if not isinstance(raw, list) or not raw:
        raise HTTPException(422, "需要 table_codes：监管表编号数组，例如 [\"T_8_1\"]")
    codes: list[str] = []
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            raise HTTPException(422, "监管表编号必须是非空字符串")
        code = item.strip()
        if code not in codes:
            codes.append(code)
    return codes


@router.get("/projects/{project_id}/requirements/{requirement_id}/paths")
def preview_requirement_paths(project_id: int, requirement_id: int, principal: CurrentPrincipal,
                              content_version: int = Query(gt=0), db: Session = Depends(get_db)):
    PermissionService(db, principal).require_project_permission(project_id, "lineage.view")
    from app.services.requirement_paths import path_preview, path_issues
    content = load_revision(db, project_id, requirement_id, content_version).content_json
    return {**path_preview(content), "issues": path_issues(content)}


@router.post("/projects/{project_id}/requirements/{requirement_id}/paths", status_code=201)
def confirm_requirement_paths(project_id: int, requirement_id: int, payload: ConfirmPaths,
                              principal: CurrentPrincipal, db: Session = Depends(get_db)):
    permissions = PermissionService(db, principal)
    project = permissions.require_project_permission(project_id, "technical.edit")
    permissions.require_project_permission(project_id, "lineage.view")
    from app.services.requirement_paths import confirm_paths
    requirement = lock_requirement(db, project_id, requirement_id)
    revision = confirm_paths(db, requirement, payload, principal.user_id)
    record_audit(db, action="confirm_requirement_paths", resource_type="requirement", resource_id=requirement_id,
        actor_user_id=principal.user_id, institution_id=project.institution_id, project_id=project_id,
        after={"content_version": revision.content_version, "preview_hash": payload.preview_hash})
    result = revision_document(revision)
    db.commit()
    return result


@router.get("/projects/{project_id}/requirements/{requirement_id}/policy-comparison")
def get_policy_comparison(project_id: int, requirement_id: int, principal: CurrentPrincipal,
                          content_version: int = Query(gt=0), db: Session = Depends(get_db)):
    PermissionService(db, principal).require_project_permission(project_id, "project.view")
    from app.services.requirement_policy_comparison import comparison_view, ai_suggestions
    revision = load_revision(db, project_id, requirement_id, content_version)
    return {"content_version": revision.content_version, **comparison_view(revision.content_json),
        "ai_suggestions": ai_suggestions(db, project_id, requirement_id, revision.content_json)}


@router.post("/projects/{project_id}/requirements/{requirement_id}/policy-comparison", status_code=201)
def save_policy_comparison(project_id: int, requirement_id: int, payload: ConfirmPolicyComparison,
                           principal: CurrentPrincipal, db: Session = Depends(get_db)):
    permissions = PermissionService(db, principal)
    project = permissions.require_project_permission(project_id, "technical.edit")
    if not ({"knowledge.search", "knowledge.manage"} & set(permissions.effective_project_permissions(project_id))):
        raise HTTPException(403, "无权确认制度依据")
    from app.services.requirement_policy_comparison import confirm_comparison
    requirement = lock_requirement(db, project_id, requirement_id)
    revision = confirm_comparison(db, requirement, payload, principal.user_id)
    record_audit(db, action="confirm_requirement_policy_comparison", resource_type="requirement",
        resource_id=requirement_id, actor_user_id=principal.user_id, institution_id=project.institution_id,
        project_id=project_id, after={"content_version": revision.content_version,
            "unit_ids": [d.unit_id for d in payload.decisions]})
    result = revision_document(revision)
    db.commit()
    return result


@router.get("/projects/{project_id}/requirements/script-options")
def requirement_script_options(project_id: int, principal: CurrentPrincipal, db: Session = Depends(get_db)):
    PermissionService(db, principal).require_project_permission(project_id, "lineage.view")
    from app.models import ScriptFile, ScriptFileVersion, TemplateVersion
    rows = db.execute(select(ScriptFileVersion, ScriptFile).join(ScriptFile,
        ScriptFile.id == ScriptFileVersion.script_file_id).where(ScriptFile.project_id == project_id,
        ScriptFileVersion.project_id == project_id, ScriptFile.enabled.is_(True))
        .order_by(ScriptFileVersion.id.desc()).limit(201)).all()
    templates = list(db.scalars(select(TemplateVersion).where(TemplateVersion.project_id == project_id)
        .order_by(TemplateVersion.id.desc()).limit(201)))
    return {"versions": [{"id": v.id, "path": s.relative_path, "version_no": v.version_no,
        "script_file_id": s.id, "parse_status": v.parse_status} for v, s in rows[:200]],
        "templates": [{"id": t.id, "template_code": t.template_code, "version_no": t.version_no,
            "status": t.status, "regulatory_version": t.regulatory_version} for t in templates[:200]],
        "truncated": len(rows) > 200 or len(templates) > 200}


@router.post("/projects/{project_id}/requirements/script-preview")
def preview_requirement_scripts(project_id: int, payload: ScriptSelection,
                                principal: CurrentPrincipal, db: Session = Depends(get_db)):
    PermissionService(db, principal).require_project_permission(project_id, "lineage.view")
    from app.services.requirement_script_basis import script_preview
    preview = script_preview(db, project_id, payload.script_version_ids)
    from app.services.requirement_script_batch import target_suggestions
    return {**preview, "regulatory_targets": target_suggestions(db, project_id, preview)}


@router.post("/projects/{project_id}/requirements/{requirement_id}/script-basis", status_code=201)
def attach_requirement_scripts(project_id: int, requirement_id: int, payload: ConfirmScriptBasis,
                               principal: CurrentPrincipal, db: Session = Depends(get_db)):
    permissions = PermissionService(db, principal)
    project = permissions.require_project_permission(project_id, "technical.edit")
    permissions.require_project_permission(project_id, "lineage.view")
    from app.services.requirement_script_basis import confirm_script_basis
    requirement = lock_requirement(db, project_id, requirement_id)
    if requirement.scope_json.get("document_ids"):
        if not ({"knowledge.search", "knowledge.manage"} & set(permissions.effective_project_permissions(project_id))):
            raise HTTPException(403, "无权将知识资料纳入脚本需求依据")
    revision = confirm_script_basis(db, requirement, payload, principal.user_id)
    record_audit(db, action="confirm_requirement_script_basis", resource_type="requirement",
        resource_id=requirement_id, actor_user_id=principal.user_id, institution_id=project.institution_id,
        project_id=project_id, after={"content_version": revision.content_version,
            "script_version_ids": payload.script_version_ids, "template_version_id": payload.template_version_id})
    result = revision_document(revision)
    db.commit()
    return result


@router.get("/projects/{project_id}/requirements/{requirement_id}/script-basis-impact")
def requirement_script_impact(project_id: int, requirement_id: int, principal: CurrentPrincipal,
                             content_version: int = Query(gt=0), db: Session = Depends(get_db)):
    PermissionService(db, principal).require_project_permission(project_id, "project.view")
    revision = load_revision(db, project_id, requirement_id, content_version)
    from app.services.requirement_script_basis import script_basis_changes
    changes = script_basis_changes(db, project_id, revision.content_json)
    return {"content_version": revision.content_version, "pending_review": bool(changes), "changes": changes}


@router.post("/projects/{project_id}/requirements/{requirement_id}/generation-runs", status_code=201)
def start_requirement_generation(project_id: int, requirement_id: int, payload: PrepareGenerationInput,
                                 principal: CurrentPrincipal, db: Session = Depends(get_db)):
    from app.models import RequirementGenerationItem
    from sqlalchemy.exc import IntegrityError
    from app.services.task_queue.factory import get_task_queue
    from app.services.requirement_generation_worker import requirement_generation_handler
    row, _ = prepare_input(db, project_id, requirement_id, payload, principal)
    existing = {(item.field_id, item.section) for item in db.scalars(select(RequirementGenerationItem).where(
        RequirementGenerationItem.input_id == row.id))}
    for field_id in row.input_json["field_ids"]:
        for section in row.input_json["sections"]:
            if (field_id, section) not in existing:
                try:
                    with db.begin_nested():
                        db.add(RequirementGenerationItem(input_id=row.id, field_id=field_id, section=section, status="pending"))
                        db.flush()
                except IntegrityError:
                    winner = db.scalar(select(RequirementGenerationItem.id).where(
                        RequirementGenerationItem.input_id == row.id, RequirementGenerationItem.field_id == field_id,
                        RequirementGenerationItem.section == section))
                    if winner is None:
                        raise
    db.flush()
    project = PermissionService(db, principal).require_project_permission(project_id, "project.view")
    input_id = row.id
    db.commit()
    job = get_task_queue().enqueue(db, job_type="requirement_generation", institution_id=project.institution_id,
        project_id=project_id, created_by=principal.user_id, idempotency_key=f"requirement-input-{input_id}",
        payload_summary={"input_id": input_id}, handler=requirement_generation_handler)
    persisted_input = db.get(type(row), input_id)
    persisted_input.job_id = job.id
    db.commit()
    return {"input_id": input_id, "job_id": job.id, "status": job.status}


@router.get("/projects/{project_id}/requirements/{requirement_id}/generation-runs")
def list_requirement_generation(project_id: int, requirement_id: int,
                                principal: CurrentPrincipal, db: Session = Depends(get_db)):
    from app.models import RequirementGenerationInput, RequirementGenerationItem
    PermissionService(db, principal).require_project_permission(project_id, "project.view")
    requirement = load_requirement(db, project_id, requirement_id)
    rows = list(db.scalars(select(RequirementGenerationInput).where(RequirementGenerationInput.project_id == project_id,
        RequirementGenerationInput.requirement_id == requirement_id).order_by(RequirementGenerationInput.id.desc()).limit(50)))
    summaries = []
    for row in rows:
        items = [{"id": item.id, "field_id": item.field_id, "section": item.section,
            "status": item.status, "reason_code": item.reason_code, "decision": item.decision,
            # 阻断/失败的原因必须随条目返回：只给状态码的话，用户看到"阻断"却不知道该补什么，
            # 只能来问研发（真实事故：K010002 的 filter_column_missing 只能靠查库才知道）。
            "failure_detail": (item.usage_json or {}).get("detail"),
            "adopted_content_version": item.adopted_content_version} for item in db.scalars(select(RequirementGenerationItem)
                .where(RequirementGenerationItem.input_id == row.id).order_by(RequirementGenerationItem.id))]
        states = [item["status"] for item in items]
        counts = {state: states.count(state) for state in ("pending", "running", "completed", "failed", "blocked")}
        status = "prepared" if not items else "running" if counts["running"] else "pending" if counts["pending"] else "completed" if counts["completed"] == len(items) else "partially_completed" if counts["completed"] else "blocked" if counts["blocked"] == len(items) else "failed"
        summaries.append({**input_summary(row), "status": status, "counts": counts, "total": len(items),
            "stale": row.input_json["content_version"] != requirement.content_version, "items": items})
    return summaries


def _generation_pricing(db) -> tuple[dict | None, object]:
    """读取显式配置的价格表与预算；未配置时返回 None（费用与预算一律 unknown）。"""

    from app.services.llm.prompt_runtime import get_prompt_runtime
    try:
        config = get_prompt_runtime(db, "requirement_field_candidate").config or {}
    except Exception:  # pragma: no cover - 配置缺失不应让对账接口 500
        return None, None
    prices = config.get("requirement_pricing")
    budget = config.get("requirement_generation_budget")
    return (prices if isinstance(prices, dict) else None), budget


@router.get("/projects/{project_id}/requirements/{requirement_id}/generation-inputs/{input_id}/usage")
def requirement_generation_usage(project_id: int, requirement_id: int, input_id: int,
                                 principal: CurrentPrincipal, db: Session = Depends(get_db)):
    """一次生成输入的用量与费用对账（P1-C）。

    只回可核对的数字：provider 回报的 token、每次尝试的时延与重试、以及
    按显式价格表算出的费用。缺价格或缺用量的部分标 unavailable/unknown，
    不会被当成 0 计入"未超预算"。
    """

    from app.models import RequirementGenerationInput, RequirementGenerationItem
    from app.services.requirement_generation_cost import summarize_ledger
    PermissionService(db, principal).require_project_permission(project_id, "project.view")
    requirement = load_requirement(db, project_id, requirement_id)
    row = db.scalar(select(RequirementGenerationInput).where(
        RequirementGenerationInput.id == input_id,
        RequirementGenerationInput.project_id == project_id,
        RequirementGenerationInput.requirement_id == requirement_id))
    if row is None:
        raise HTTPException(404, "生成输入不存在")
    items = [{"field_id": item.field_id, "section": item.section, "status": item.status,
              "usage": item.usage_json or {}} for item in db.scalars(
        select(RequirementGenerationItem)
        .where(RequirementGenerationItem.input_id == row.id)
        .order_by(RequirementGenerationItem.id))]
    prices, budget = _generation_pricing(db)
    ledger = summarize_ledger(items, prices=prices, budget=budget)
    return {"input_id": row.id, "requirement_id": requirement_id, "project_id": project_id,
            "created_at": row.created_at,
            "stale": row.input_json.get("content_version") != requirement.content_version,
            **ledger}


class AdoptRequirementCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_content_version: int = Field(gt=0)
    candidate_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    selected_fields: list[str] = Field(min_length=1, max_length=4)
    replace_manual_fields: list[str] = Field(default_factory=list, max_length=4)


class AdoptRequirementCandidateSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item_id: int = Field(gt=0)
    candidate_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    selected_fields: list[str] = Field(min_length=1, max_length=4)
    replace_manual_fields: list[str] = Field(default_factory=list, max_length=4)


class AdoptRequirementCandidateBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_content_version: int = Field(gt=0)
    selections: list[AdoptRequirementCandidateSelection] = Field(min_length=1, max_length=400)


class RejectRequirementCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidate_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    reason: str = Field(min_length=1, max_length=2000)


@router.get("/projects/{project_id}/requirements/{requirement_id}/generation-items/{item_id}")
def get_requirement_candidate(project_id: int, requirement_id: int, item_id: int,
                              principal: CurrentPrincipal, db: Session = Depends(get_db)):
    from app.services.requirement_candidates import candidate_detail
    return candidate_detail(db, project_id, requirement_id, item_id, principal)


@router.post("/projects/{project_id}/requirements/{requirement_id}/generation-items/{item_id}/adopt")
def adopt_requirement_candidate(project_id: int, requirement_id: int, item_id: int,
                                payload: AdoptRequirementCandidate,
                                principal: CurrentPrincipal, db: Session = Depends(get_db)):
    from app.services.requirement_candidates import adopt_candidate, load_candidate_item
    _, item = load_candidate_item(db, project_id, requirement_id, item_id)
    project = PermissionService(db, principal).require_project_permission(project_id,
        "business.edit" if item.section == "business" else "technical.edit")
    revision, idempotent = adopt_candidate(db, project_id, requirement_id, item_id,
        payload.expected_content_version, payload.candidate_hash, payload.selected_fields,
        payload.replace_manual_fields, principal.user_id)
    if not idempotent:
        record_audit(db, action="adopt_requirement_candidate", resource_type="requirement",
            resource_id=requirement_id, actor_user_id=principal.user_id, institution_id=project.institution_id,
            project_id=project_id, after={"item_id": item_id, "content_version": revision.content_version,
                "selected_fields": payload.selected_fields, "replaced_manual_fields": payload.replace_manual_fields})
    result = {"document": revision_document(revision), "idempotent": idempotent}
    db.commit()
    return result


@router.post("/projects/{project_id}/requirements/{requirement_id}/generation-candidates/adopt")
def adopt_requirement_candidate_batch(project_id: int, requirement_id: int,
                                      payload: AdoptRequirementCandidateBatch,
                                      principal: CurrentPrincipal, db: Session = Depends(get_db)):
    from app.services.requirement_candidates import adopt_candidates, load_candidate_item
    project = PermissionService(db, principal).require_project_permission(project_id, "project.view")
    for selection in payload.selections:
        _, item = load_candidate_item(db, project_id, requirement_id, selection.item_id)
        PermissionService(db, principal).require_project_permission(project_id,
            "business.edit" if item.section == "business" else "technical.edit")
    revision, idempotent = adopt_candidates(db, project_id, requirement_id,
        payload.expected_content_version, [selection.model_dump() for selection in payload.selections], principal.user_id)
    if not idempotent:
        record_audit(db, action="adopt_requirement_candidate_batch", resource_type="requirement",
            resource_id=requirement_id, actor_user_id=principal.user_id, institution_id=project.institution_id,
            project_id=project_id, after={"item_ids": [selection.item_id for selection in payload.selections],
                "content_version": revision.content_version, "selection_count": len(payload.selections)})
    result = {"document": revision_document(revision), "idempotent": idempotent}
    db.commit()
    return result


@router.post("/projects/{project_id}/requirements/{requirement_id}/generation-items/{item_id}/reject")
def reject_requirement_candidate(project_id: int, requirement_id: int, item_id: int,
                                 payload: RejectRequirementCandidate,
                                 principal: CurrentPrincipal, db: Session = Depends(get_db)):
    from app.services.requirement_candidates import reject_candidate, load_candidate_item
    _, item = load_candidate_item(db, project_id, requirement_id, item_id)
    project = PermissionService(db, principal).require_project_permission(project_id,
        "business.edit" if item.section == "business" else "technical.edit")
    item, idempotent = reject_candidate(db, project_id, requirement_id, item_id,
        payload.candidate_hash, payload.reason, principal.user_id)
    if not idempotent:
        record_audit(db, action="reject_requirement_candidate", resource_type="requirement",
            resource_id=requirement_id, actor_user_id=principal.user_id, institution_id=project.institution_id,
            project_id=project_id, after={"item_id": item_id, "reason": payload.reason})
    result = {"id": item.id, "decision": item.decision, "decision_reason": item.decision_reason,
        "idempotent": idempotent}
    db.commit()
    return result


class RetryRequirementGeneration(BaseModel):
    job_id: int = Field(gt=0)


@router.post("/projects/{project_id}/requirements/{requirement_id}/generation-runs/{input_id}/retry")
def retry_requirement_generation(project_id: int, requirement_id: int, input_id: int,
                                  payload: RetryRequirementGeneration,
                                  principal: CurrentPrincipal, db: Session = Depends(get_db)):
    from app.models import RequirementGenerationInput, RequirementGenerationItem, BackgroundJob
    from app.services.requirement_generation_worker import authorize_input
    from app.services.task_queue.factory import get_task_queue
    PermissionService(db, principal).require_project_permission(project_id, "project.view")
    load_requirement(db, project_id, requirement_id)
    row = db.scalar(select(RequirementGenerationInput).where(RequirementGenerationInput.id == input_id,
        RequirementGenerationInput.project_id == project_id, RequirementGenerationInput.requirement_id == requirement_id))
    if row is None:
        raise HTTPException(404, "生成输入不存在或不可见")
    authorize_input(db, row, principal)
    job = db.get(BackgroundJob, payload.job_id)
    if row.created_by != principal.user_id or job is None or job.created_by != principal.user_id or job.project_id != project_id or job.job_type != "requirement_generation" or job.payload_summary_json.get("input_id") != row.id:
        raise HTTPException(404, "生成任务不存在或不可见")
    # 单个候选项可能因合规闸门（模型引用了范围外规则）或模型波动被阻断，而任务本身正常结束。
    # 这类残留项允许重试，但任务级状态是 completed，队列的重试语义只接受失败类状态，
    # 因此先把任务重新标记为 failed，再交给队列完成重投递、重试计数与派发补偿。
    retryable_items = db.scalars(select(RequirementGenerationItem.id).where(
        RequirementGenerationItem.input_id == row.id,
        RequirementGenerationItem.status.in_(("failed", "blocked"))).limit(1)).all()
    if not retryable_items:
        raise HTTPException(409, "当前任务没有需要重试的失败或阻断项")
    if job.status not in {"failed", "partially_completed", "cancelled"}:
        job.status = "failed"
        db.commit()
        db.refresh(job)
    try:
        job = get_task_queue().retry(db, job)
    except ValueError:
        raise HTTPException(409, "当前任务不可重试，请核对执行状态和重试次数")
    return {"input_id": input_id, "job_id": job.id, "status": job.status}


@router.post("/projects/{project_id}/requirements/{requirement_id}/generation-inputs", status_code=201)
def prepare_generation(project_id: int, requirement_id: int, payload: PrepareGenerationInput,
                       principal: CurrentPrincipal, db: Session = Depends(get_db)):
    row, deduplicated = prepare_input(db, project_id, requirement_id, payload, principal)
    if not deduplicated:
        record_audit(db, action="prepare_requirement_generation", resource_type="requirement",
            resource_id=requirement_id, actor_user_id=principal.user_id, project_id=project_id,
            after={"input_id": row.id, "input_hash": row.input_hash})
    result = input_summary(row, deduplicated)
    db.commit()
    return result


@router.get("/projects/{project_id}/requirement-resources")
def requirement_resources(project_id: int, principal: CurrentPrincipal,
                          q: str = Query(default="", max_length=100),
                          db: Session = Depends(get_db)):
    permissions = PermissionService(db, principal)
    permissions.require_project_permission(project_id, "project.view")
    can_read_documents = bool(permissions.effective_project_permissions(project_id) & {"knowledge.search", "knowledge.manage"})
    result = {}
    for key, model, name, code in (
        ("document_ids", KnowledgeDocument, KnowledgeDocument.file_name, KnowledgeDocument.file_name),
        ("source_table_ids", SourceTable, SourceTable.table_name, SourceTable.table_code),
        ("mart_table_ids", MartTable, MartTable.table_name, MartTable.table_code),
    ):
        if model is KnowledgeDocument and not can_read_documents:
            result[key] = {"items": [], "truncated": False, "available": False}
            continue
        query = select(model.id, name.label("name"), code.label("code")).where(model.project_id == project_id)
        if model is KnowledgeDocument:
            query = query.where(KnowledgeDocument.document_status != "archived")
        if q.strip():
            query = query.where(or_(name.icontains(q.strip(), autoescape=True), code.icontains(q.strip(), autoescape=True)))
        rows = db.execute(query.order_by(model.id).limit(101)).mappings().all()
        result[key] = {"items": [dict(row) for row in rows[:100]], "truncated": len(rows) > 100, "available": True}
    return result


@router.get("/projects/{project_id}/requirements")
def list_requirements(project_id: int, principal: CurrentPrincipal, db: Session = Depends(get_db)):
    PermissionService(db, principal).require_project_permission(project_id, "project.view")
    return [requirement_dict(row) for row in db.scalars(select(Requirement).where(
        Requirement.project_id == project_id).order_by(Requirement.id.desc()).limit(200))]


@router.post("/projects/{project_id}/requirements", status_code=201)
def create_requirement(project_id: int, payload: ScopeInput, principal: CurrentPrincipal, db: Session = Depends(get_db)):
    project = PermissionService(db, principal).require_project_permission(project_id, "business.edit")
    validate_scope(db, project_id, payload)
    row = Requirement(project_id=project_id, name=payload.name.strip(), version=1,
        scope_json=payload.model_dump(mode="json", exclude={"name", "expected_version", "expected_content_version"}))
    db.add(row)
    db.flush()
    record_audit(db, action="create_requirement", resource_type="requirement", resource_id=row.id,
        actor_user_id=principal.user_id, institution_id=project.institution_id, project_id=project_id,
        after={"version": 1})
    db.commit()
    return requirement_dict(row)


@router.put("/projects/{project_id}/requirements/{requirement_id}")
def update_requirement(project_id: int, requirement_id: int, payload: ScopeInput,
                       principal: CurrentPrincipal, db: Session = Depends(get_db)):
    project = PermissionService(db, principal).require_project_permission(project_id, "business.edit")
    requirement = lock_requirement(db, project_id, requirement_id)
    previous = None
    if requirement.content_version:
        if payload.expected_content_version != requirement.content_version:
            raise HTTPException(409, "需求内容已变化，请重新加载后修订范围")
        previous = load_revision(db, project_id, requirement_id, requirement.content_version)
        if previous.status != "draft":
            raise HTTPException(409, "已锁定版本不能直接修改范围，请建立新修订")
    validate_scope(db, project_id, payload)
    if payload.expected_version is None:
        raise HTTPException(409, "请刷新需求版本后再保存")
    scope = payload.model_dump(mode="json", exclude={"name", "expected_version", "expected_content_version"})
    for key in ("script_requirement_batch_id", "import_batch_id"):
        if key in requirement.scope_json:
            scope[key] = requirement.scope_json[key]
    result = db.execute(update(Requirement).where(Requirement.id == requirement_id,
        Requirement.project_id == project_id, Requirement.version == payload.expected_version).values(
        name=payload.name.strip(), version=Requirement.version + 1,
        scope_json=scope))
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "需求已被修改，请重新加载后合并改动")
    if previous:
        from app.services.requirement_revisions import revise_scope
        db.refresh(requirement)
        revise_scope(db, requirement, previous, principal.user_id)
    record_audit(db, action="revise_requirement", resource_type="requirement", resource_id=requirement_id,
        actor_user_id=principal.user_id, institution_id=project.institution_id, project_id=project_id,
        after={"version": payload.expected_version + 1})
    db.commit()
    return requirement_dict(load_requirement(db, project_id, requirement_id))


@router.get("/projects/{project_id}/requirements/{requirement_id}/document")
def get_document(project_id: int, requirement_id: int, principal: CurrentPrincipal, db: Session = Depends(get_db)):
    PermissionService(db, principal).require_project_permission(project_id, "project.view")
    content = jsonable_encoder(document_content(db, load_requirement(db, project_id, requirement_id)))
    return {**content, "content_hash": content_digest(content)}


class InitializeContentInput(BaseModel):
    expected_version: int = Field(gt=0)


class FieldContentInput(BaseModel):
    expected_content_version: int = Field(gt=0)
    section: str
    changes: dict[str, str | None]


class ReviseContentInput(BaseModel):
    expected_content_version: int = Field(gt=0)
    reason: str = Field(min_length=1, max_length=2000)


@router.post("/projects/{project_id}/requirements/{requirement_id}/revisions/{content_version}/revise", status_code=201)
def revise_locked_content(project_id: int, requirement_id: int, content_version: int, payload: ReviseContentInput,
                          principal: CurrentPrincipal, db: Session = Depends(get_db)):
    from copy import deepcopy
    from app.services.requirement_revisions import append_revision
    project = PermissionService(db, principal).require_project_permission(project_id, "business.edit")
    requirement = lock_requirement(db, project_id, requirement_id)
    if not payload.reason.strip():
        raise HTTPException(422, "请填写修订原因")
    if requirement.content_version != content_version or payload.expected_content_version != content_version:
        raise HTTPException(409, "当前内容版本已变化，请重新加载")
    previous = load_revision(db, project_id, requirement_id, content_version)
    if previous.status not in {"confirmed", "rejected"}:
        raise HTTPException(409, "仅可从已确认或已退回版本建立修订，审核中内容不能解除保护")
    content = deepcopy(previous.content_json)
    content["revision_reason"] = payload.reason.strip()
    for record in content["fields"]:
        if record.get("business"):
            record["business"]["business_confirm_status"] = "draft"
        if record.get("lineage"):
            record["lineage"]["tech_confirm_status"] = "draft"
    revision = append_revision(db, requirement, content, content_version, principal.user_id)
    record_audit(db, action="revise_locked_requirement", resource_type="requirement", resource_id=requirement_id,
        actor_user_id=principal.user_id, institution_id=project.institution_id, project_id=project_id,
        after={"content_version": revision.content_version, "parent_version": content_version})
    result = revision_document(revision)
    db.commit()
    return result


@router.post("/projects/{project_id}/requirements/{requirement_id}/revisions", status_code=201)
def initialize_revision(project_id: int, requirement_id: int, payload: InitializeContentInput,
                        principal: CurrentPrincipal, db: Session = Depends(get_db)):
    project = PermissionService(db, principal).require_project_permission(project_id, "business.edit")
    requirement = lock_requirement(db, project_id, requirement_id)
    created = not requirement.content_version
    revision = initialize_content(db, requirement, payload.expected_version, principal.user_id,
        include_lineage="lineage.view" in PermissionService(db, principal).effective_project_permissions(project_id))
    if created:
        record_audit(db, action="initialize_requirement_content", resource_type="requirement", resource_id=requirement_id,
            actor_user_id=principal.user_id, institution_id=project.institution_id, project_id=project_id,
            after={"content_version": revision.content_version, "content_hash": revision.content_hash})
    result = revision_document(revision)
    db.commit()
    return result


@router.get("/projects/{project_id}/requirements/{requirement_id}/revisions")
def list_revisions(project_id: int, requirement_id: int, principal: CurrentPrincipal, db: Session = Depends(get_db)):
    PermissionService(db, principal).require_project_permission(project_id, "project.view")
    load_requirement(db, project_id, requirement_id)
    return [{"content_version": r.content_version, "scope_version": r.scope_version,
             "status": r.status, "created_at": r.created_at} for r in db.scalars(select(RequirementRevision).where(
        RequirementRevision.project_id == project_id, RequirementRevision.requirement_id == requirement_id
    ).order_by(RequirementRevision.content_version.desc()).limit(200))]


@router.get("/projects/{project_id}/requirements/{requirement_id}/revisions/{content_version}")
def get_revision(project_id: int, requirement_id: int, content_version: int,
                 principal: CurrentPrincipal, db: Session = Depends(get_db)):
    PermissionService(db, principal).require_project_permission(project_id, "project.view")
    return revision_document(load_revision(db, project_id, requirement_id, content_version))


@router.put("/projects/{project_id}/requirements/{requirement_id}/fields/{field_id}")
def update_field_content(project_id: int, requirement_id: int, field_id: int, payload: FieldContentInput,
                         principal: CurrentPrincipal, db: Session = Depends(get_db)):
    if payload.section not in {"business", "lineage"}:
        raise HTTPException(422, "请选择业务或技术口径")
    project = PermissionService(db, principal).require_project_permission(project_id,
        "business.edit" if payload.section == "business" else "technical.edit")
    requirement = lock_requirement(db, project_id, requirement_id)
    revision = edit_field(db, requirement, payload.expected_content_version, field_id,
                          payload.section, payload.changes, principal.user_id)
    record_audit(db, action="edit_requirement_field", resource_type="requirement", resource_id=requirement_id,
        actor_user_id=principal.user_id, institution_id=project.institution_id, project_id=project_id,
        after={"field_id": field_id, "section": payload.section, "content_version": revision.content_version})
    result = revision_document(revision)
    db.commit()
    return result


class ResolveGapInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_content_version: int = Field(gt=0)
    resolution_text: str = Field(min_length=1, max_length=2000)


@router.post("/projects/{project_id}/requirements/{requirement_id}/gaps/{gap_id}/resolve", status_code=201)
def resolve_requirement_gap(project_id: int, requirement_id: int, gap_id: str,
                            payload: ResolveGapInput, principal: CurrentPrincipal,
                            db: Session = Depends(get_db)):
    """人工填写解决依据关闭一个缺口（AI 候选缺口等），生成新内容版本。"""
    permissions = PermissionService(db, principal).effective_project_permissions(project_id)
    if not ({"business.edit", "technical.edit"} & permissions):
        raise HTTPException(403, "缺少编辑业务或技术口径的权限")
    project = PermissionService(db, principal).require_project_permission(project_id, "project.view")
    requirement = lock_requirement(db, project_id, requirement_id)
    revision = resolve_gap(db, requirement, payload.expected_content_version, gap_id,
                           payload.resolution_text, principal.user_id)
    record_audit(db, action="resolve_requirement_gap", resource_type="requirement",
                 resource_id=requirement_id, actor_user_id=principal.user_id,
                 institution_id=project.institution_id, project_id=project_id,
                 after={"gap_id": gap_id, "content_version": revision.content_version})
    result = revision_document(revision)
    db.commit()
    return result


@router.get("/projects/{project_id}/requirements/{requirement_id}/revisions/{content_version}/lineage")
def get_revision_lineage(project_id: int, requirement_id: int, content_version: int,
                        principal: CurrentPrincipal, db: Session = Depends(get_db)):
    PermissionService(db, principal).require_project_permission(project_id, "lineage.view")
    revision = load_revision(db, project_id, requirement_id, content_version)
    graph = revision.content_json.get("lineage_graph")
    if revision.content_json.get("script_basis"):
        from app.services.requirement_paths import frozen_path_graph
        graph = frozen_path_graph(revision.content_json)
    return {"content_version": content_version, "graph": graph,
            "assessment": "recorded" if graph else "unassessed"}


@router.post("/projects/{project_id}/requirements/{requirement_id}/revisions/{content_version}/refresh-lineage")
def refresh_requirement_lineage(project_id: int, requirement_id: int, content_version: int,
                                principal: CurrentPrincipal, db: Session = Depends(get_db)):
    """Refresh lineage graph from current assets and create new revision.

    Requires: lineage.view and technical.edit permissions.
    Preserves field content, manual ownership, evidence, and gaps.
    Only updates lineage_graph snapshot.
    """
    perms = PermissionService(db, principal)
    perms.require_project_permission(project_id, "lineage.view")
    perms.require_project_permission(project_id, "technical.edit")

    requirement = lock_requirement(db, project_id, requirement_id)
    new_revision = refresh_lineage(db, requirement, content_version, principal.user_id)
    record_audit(db, action="refresh_requirement_lineage", resource_type="requirement",
                 resource_id=requirement_id, actor_user_id=principal.user_id, project_id=project_id,
                 after={"content_version": new_revision.content_version,
                        "graph_updated": new_revision.content_json.get("lineage_graph") is not None})
    db.commit()

    return {
        "content_version": new_revision.content_version,
        "content_hash": new_revision.content_hash,
        "status": new_revision.status,
        "graph_updated": new_revision.content_json.get("lineage_graph") is not None,
        "assessment": new_revision.content_json.get("assessment", "clear")
    }


class FreezeDraftInput(BaseModel):
    expected_version: int = Field(gt=0)
    expected_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class SubmitRequirementReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_content_version: int = Field(gt=0)
    expected_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    assignments: dict[str, int] = Field(default_factory=dict)


@router.get("/projects/{project_id}/requirements/{requirement_id}/review-readiness")
def get_requirement_review_readiness(project_id: int, requirement_id: int,
                                     principal: CurrentPrincipal,
                                     content_version: int = Query(gt=0),
                                     db: Session = Depends(get_db)):
    PermissionService(db, principal).require_project_permission(project_id, "project.view")
    from app.services.requirement_review import review_readiness

    return review_readiness(db, project_id, requirement_id, content_version)


@router.post("/projects/{project_id}/requirements/{requirement_id}/review-submissions", status_code=201)
def submit_requirement_review(project_id: int, requirement_id: int,
                              payload: SubmitRequirementReviewInput,
                              principal: RealPrincipal,
                              db: Session = Depends(get_db)):
    project = PermissionService(db, principal).require_project_permission(project_id, "deliverable.manage")
    from app.services.requirement_review import submit_for_review, submission_summary

    row, created = submit_for_review(
        db,
        project_id=project_id,
        requirement_id=requirement_id,
        content_version=payload.expected_content_version,
        content_hash=payload.expected_content_hash,
        submitted_by=principal.user_id,
        assignments=payload.assignments,
    )
    if created:
        record_audit(
            db,
            action="submit_requirement_review",
            resource_type="requirement_review_submission",
            resource_id=row.id,
            actor_user_id=principal.user_id,
            institution_id=project.institution_id,
            project_id=project_id,
            after={"content_version": row.content_version, "content_hash": row.content_hash},
        )
    result = {**submission_summary(db, row), "deduplicated": not created}
    db.commit()
    return result


@router.get("/projects/{project_id}/requirements/{requirement_id}/review-submissions")
def list_requirement_reviews(project_id: int, requirement_id: int,
                             principal: CurrentPrincipal,
                             db: Session = Depends(get_db)):
    PermissionService(db, principal).require_project_permission(project_id, "deliverable.view")
    load_requirement(db, project_id, requirement_id)
    from app.services.requirement_review import load_submission, submission_summary

    rows = db.scalars(select(RequirementReviewSubmission).where(
        RequirementReviewSubmission.project_id == project_id,
        RequirementReviewSubmission.requirement_id == requirement_id,
    ).order_by(RequirementReviewSubmission.id.desc()).limit(200)).all()
    return [submission_summary(db, load_submission(db, project_id, requirement_id, row.id)) for row in rows]


@router.post("/projects/{project_id}/requirements/{requirement_id}/review-submissions/{submission_id}/finalize", status_code=201)
def finalize_requirement_delivery(project_id: int, requirement_id: int, submission_id: int,
                                  principal: RealPrincipal,
                                  db: Session = Depends(get_db)):
    project = PermissionService(db, principal).require_project_permission(project_id, "deliverable.review")
    from app.services.requirement_review import finalize_formal_delivery, formal_summary

    row, created = finalize_formal_delivery(
        db,
        project_id=project_id,
        requirement_id=requirement_id,
        submission_id=submission_id,
    )
    if created:
        record_audit(
            db,
            action="finalize_requirement_delivery",
            resource_type="requirement_formal_delivery",
            resource_id=row.id,
            actor_user_id=principal.user_id,
            institution_id=project.institution_id,
            project_id=project_id,
            after={"version_no": row.version_no, "content_version": row.content_version,
                   "content_hash": row.content_hash, "file_hash": row.file_hash},
        )
    result = {**formal_summary(row), "deduplicated": not created}
    db.commit()
    return result


@router.get("/projects/{project_id}/requirements/{requirement_id}/formal-deliveries")
def list_requirement_formal_deliveries(project_id: int, requirement_id: int,
                                       principal: CurrentPrincipal,
                                       db: Session = Depends(get_db)):
    PermissionService(db, principal).require_project_permission(project_id, "deliverable.view")
    load_requirement(db, project_id, requirement_id)
    from app.services.requirement_review import formal_summary, load_formal_delivery

    rows = db.scalars(select(RequirementFormalDelivery).where(
        RequirementFormalDelivery.project_id == project_id,
        RequirementFormalDelivery.requirement_id == requirement_id,
    ).order_by(RequirementFormalDelivery.version_no.desc()).limit(200)).all()
    return [formal_summary(load_formal_delivery(db, project_id, requirement_id, row.id)) for row in rows]


@router.get("/projects/{project_id}/requirements/{requirement_id}/formal-deliveries/{delivery_id}/export")
def export_requirement_formal_delivery(project_id: int, requirement_id: int, delivery_id: int,
                                       principal: CurrentPrincipal,
                                       db: Session = Depends(get_db), format: Literal["xlsx", "docx"] = "xlsx"):
    PermissionService(db, principal).require_project_permission(project_id, "deliverable.export")
    from app.services.requirement_review import formal_file, load_formal_delivery

    row = load_formal_delivery(db, project_id, requirement_id, delivery_id)
    content = row.content_json
    content_hash = content_digest(content)

    def produce() -> bytes:
        if format == "docx":
            from app.services.requirement_word import export_word

            return export_word(content)
        return formal_file(db, row)

    request = ArtifactRequest(
        project_id=project_id, requirement_id=requirement_id,
        source_kind="formal_delivery", source_id=delivery_id, format=format,
        file_name=f"requirement-formal-v{row.version_no}.{format}",
        content_hash=content_hash, renderer_version=LEGACY_RENDERERS[format],
        media_type=MEDIA_TYPES[format], snapshot_hash=content_hash,
    )
    try:
        record = ensure_artifact(db, request, produce, created_by=principal.user_id)
    except RenderArtifactError as failure:
        raise HTTPException(409, f"{failure.message}（错误代码：{failure.code}）") from failure
    payload = _stored_artifact_bytes(record)
    headers = _deprecated_export_headers(record)
    media_type = record.media_type
    # 产物记录必须落库：get_db 不自动提交，缺这一步会让"同一身份只渲一次"永远失效。
    db.commit()
    return Response(payload, media_type=media_type, headers=headers)


@router.post("/projects/{project_id}/requirements/{requirement_id}/snapshots", status_code=201)
def create_draft_snapshot(project_id: int, requirement_id: int, payload: FreezeDraftInput,
                          principal: CurrentPrincipal, db: Session = Depends(get_db)):
    project = PermissionService(db, principal).require_project_permission(project_id, "deliverable.manage")
    row, created = freeze_draft(db, project_id, requirement_id, payload.expected_version,
                               payload.expected_hash, principal.user_id)
    if created:
        record_audit(db, action="freeze_requirement_draft", resource_type="requirement_draft_snapshot",
            resource_id=row.id, actor_user_id=principal.user_id, institution_id=project.institution_id,
            project_id=project_id, after={"requirement_version": row.requirement_version,
                                        "content_hash": row.content_hash})
    db.commit()
    return {**snapshot_summary(row), "deduplicated": not created}


@router.get("/projects/{project_id}/requirements/{requirement_id}/snapshots")
def list_draft_snapshots(project_id: int, requirement_id: int, principal: CurrentPrincipal,
                        db: Session = Depends(get_db)):
    PermissionService(db, principal).require_project_permission(project_id, "deliverable.view")
    load_requirement(db, project_id, requirement_id)
    rows = list(db.scalars(select(RequirementDelivery).where(
        RequirementDelivery.project_id == project_id, RequirementDelivery.requirement_id == requirement_id
    ).order_by(RequirementDelivery.id.desc()).limit(200)))
    # is_latest 由服务端判定：界面要回答"当前内容是否已经冻结在最近那份快照里"，
    # 这必须来自同一份排序结果，否则界面可能把"较旧快照"当最新，给出错误的冻结状态。
    return [{**snapshot_summary(row), "is_latest": index == 0} for index, row in enumerate(rows)]


@router.get("/projects/{project_id}/requirements/{requirement_id}/script-basis-diff")
def requirement_script_basis_diff(
    project_id: int,
    requirement_id: int,
    principal: CurrentPrincipal,
    db: Session = Depends(get_db),
):
    """冻结的脚本依据与同一脚本最新版本，在目标字段层面差在哪。

    只回答"这次脚本更新触及了哪些目标字段"，不重算哈希、不改任何需求、也不给"是否需要重建"的结论。
    """
    PermissionService(db, principal).require_project_permission(project_id, "project.view")
    requirement = load_requirement(db, project_id, requirement_id)
    content = jsonable_encoder(document_content(db, requirement))
    versions = ((content.get("script_basis") or {}).get("versions") or [])
    basis = content.get("script_basis") or {}
    versions = basis.get("versions") or []
    bindings = (basis.get("confirmation") or {}).get("field_bindings") or {}
    return build_script_basis_diff(
        db,
        project_id,
        versions=versions,
        bound_codes=script_basis_bound_field_codes(db, project_id, bindings),
    )
    return {"requirement_id": requirement_id, **body}


@router.post("/projects/{project_id}/requirements/{requirement_id}/script-basis-decisions")
def record_requirement_script_basis_decision(
    project_id: int,
    requirement_id: int,
    payload: dict[str, Any],
    principal: CurrentPrincipal,
    db: Session = Depends(get_db),
):
    """登记"脚本依据落后了之后决定怎么办"。

    只登记决定，不代替动作：不重新冻结、不改正文、不关缺口。
    `defer`/`reject_change` 必须写原因——否则等于没复核。
    """
    PermissionService(db, principal).require_project_permission(project_id, "technical.edit")
    script_file_id = payload.get("script_file_id")
    latest_version_id = payload.get("latest_version_id")
    decision = payload.get("decision")
    if not isinstance(script_file_id, int) or not isinstance(latest_version_id, int):
        raise HTTPException(status_code=422, detail="script_file_id 与 latest_version_id 必须是整数")
    if decision not in SCRIPT_BASIS_DECISION_CHOICES:
        raise HTTPException(
            status_code=422,
            detail=f"处置决定只能是 {', '.join(SCRIPT_BASIS_DECISION_CHOICES)}",
        )
    try:
        row, created = record_script_basis_decision(
            db,
            project_id=project_id,
            requirement_id=requirement_id,
            script_file_id=script_file_id,
            frozen_version_id=int(payload.get("frozen_version_id") or 0),
            latest_version_id=latest_version_id,
            decision=str(decision),
            note=payload.get("note"),
            actor_id=principal.user_id,
        )
    except ScriptBasisDecisionError as error:
        raise HTTPException(status_code=422, detail=error.message) from error
    project_row = db.get(Project, project_id)
    record_audit(
        db,
        action="record_script_basis_decision",
        resource_type="requirement",
        resource_id=requirement_id,
        actor_user_id=principal.user_id,
        institution_id=getattr(project_row, "institution_id", None),
        project_id=project_id,
        after={
            "script_file_id": script_file_id,
            "frozen_version_id": row.frozen_version_id,
            "latest_version_id": latest_version_id,
            "decision": row.decision,
            "note": row.note,
            "created": created,
        },
    )
    db.commit()
    from app.services.requirement_script_basis_decision import serialize as serialize_decision

    return {"created": created, "decision": serialize_decision(row)}


@router.post("/projects/{project_id}/requirements/{requirement_id}/script-basis-regenerate", status_code=201)
def regenerate_from_script_basis(project_id: int, requirement_id: int, principal: CurrentPrincipal,
                                 db: Session = Depends(get_db),
                                 script_file_id: int = Form(..., ge=1),
                                 expected_version: int = Form(..., ge=1),
                                 expected_hash: str = Form(..., min_length=64, max_length=64),
                                 sections: str = Form("business,lineage")):
    """按新脚本版本重新生成这条需求的候选（"该重新生成"从结论变成动作）。

    只做三件事：确认脚本确实在本需求的冻结依据里、算出这次要重跑的绑定字段、
    按既有生成链路建输入与任务。**不采纳、不冻结、不切换脚本依据**——正文仍需人工采纳，
    脚本依据仍在确认脚本依据那一步显式更新（这是刻意的治理边界）。
    """
    from app.models import RequirementGenerationItem
    from app.services.requirement_scope import content_digest
    from app.services.task_queue.factory import get_task_queue
    from app.services.requirement_generation_worker import requirement_generation_handler

    permissions = PermissionService(db, principal)
    project = permissions.require_project_permission(project_id, "technical.edit")
    permissions.require_project_permission(project_id, "business.edit")
    requirement = load_requirement(db, project_id, requirement_id)
    if requirement.version != expected_version:
        raise HTTPException(409, f"需求范围版本已变化（请求 v{expected_version}，当前 v{requirement.version}）：请刷新后再重新生成。")
    content = jsonable_encoder(document_content(db, requirement))
    if content_digest(content) != expected_hash:
        raise HTTPException(409, "需求内容已发生变化（哈希与页面不一致）：请刷新后再重新生成，避免用旧内容建任务。")

    parsed_sections = [item.strip() for item in (sections or "").split(",") if item.strip()]
    if not parsed_sections or any(item not in ("business", "lineage") for item in parsed_sections):
        raise HTTPException(422, "重新生成的章节只能是 business（业务口径）或 lineage（技术溯源），用逗号分隔。")

    basis = content.get("script_basis") or {}
    versions = [item for item in (basis.get("versions") or [])
                if int(item.get("script_file_id") or 0) == script_file_id]
    if not versions:
        raise HTTPException(409, "指定脚本不在本需求的冻结依据里，无法重新生成。")
    bindings_raw = (basis.get("confirmation") or {}).get("field_bindings") or {}
    bindings = {str(code): int(value) for code, value in bindings_raw.items()}

    # 只有"冻结时真的绑定过、且仍在当前字段列表里"的字段才重跑：绑定表存的是目标字段 id，
    # 这里按字段记录反查列代码比对，避免把绑定在别的列上的字段也算进来。
    fields = content.get("fields") or []
    field_ids: list[int] = []
    for code, field_id in bindings.items():
        for record in fields:
            field = record.get("field") or {}
            if int(field.get("id") or 0) != field_id:
                continue
            if str(field.get("field_code") or "").upper() == code.upper():
                field_ids.append(field_id)
            break
    if not field_ids:
        raise HTTPException(409, "本需求在该脚本下没有可重新生成的绑定字段（绑定已失效或字段已移出范围）。")

    payload = PrepareGenerationInput(
        expected_content_version=int(requirement.content_version),
        field_ids=sorted(set(field_ids)),
        sections=parsed_sections,
        idempotency_key=f"script-basis-regen-{requirement_id}-{script_file_id}-{expected_hash[:8]}",
    )
    row, _ = prepare_input(db, project_id, requirement_id, payload, principal)
    existing = {(item.field_id, item.section) for item in db.scalars(select(RequirementGenerationItem).where(
        RequirementGenerationItem.input_id == row.id))}
    for field_id in row.input_json["field_ids"]:
        for section in row.input_json["sections"]:
            if (field_id, section) in existing:
                continue
            try:
                with db.begin_nested():
                    db.add(RequirementGenerationItem(input_id=row.id, field_id=field_id, section=section, status="pending"))
                    db.flush()
            except IntegrityError:
                winner = db.scalar(select(RequirementGenerationItem.id).where(
                    RequirementGenerationItem.input_id == row.id, RequirementGenerationItem.field_id == field_id,
                    RequirementGenerationItem.section == section))
                if winner is None:
                    raise
    db.flush()
    input_id = row.id
    db.commit()
    job = get_task_queue().enqueue(db, job_type="requirement_generation", institution_id=project.institution_id,
        project_id=project_id, created_by=principal.user_id,
        idempotency_key=f"requirement-input-{input_id}",
        payload_summary={"input_id": input_id}, handler=requirement_generation_handler)
    persisted_input = db.get(type(row), input_id)
    persisted_input.job_id = job.id
    record_audit(db, action="regenerate_requirement_from_script_basis", resource_type="requirement",
                 resource_id=requirement_id, actor_user_id=principal.user_id,
                 institution_id=project.institution_id, project_id=project_id,
                 after={"script_file_id": script_file_id, "input_id": input_id, "job_id": job.id,
                        "field_count": len(payload.field_ids), "sections": parsed_sections})
    db.commit()
    return {"requirement_id": requirement_id, "script_file_id": script_file_id, "input_id": input_id,
            "job_id": job.id, "status": job.status, "field_count": len(payload.field_ids),
            "sections": parsed_sections}


@router.get("/projects/{project_id}/script-basis-freshness")
def requirement_script_basis_freshness(project_id: int, principal: CurrentPrincipal, db: Session = Depends(get_db)):
    """跑批脚本更新后，哪些已建需求的脚本依据落后了。

    只看"同一脚本文件是否已有更高版本 / 解析状态是否变了"，不重算预览哈希
    （重算对只读看板太重；逐条复核请用 `…/script-basis-impact`）。
    """
    PermissionService(db, principal).require_project_permission(project_id, "project.view")
    return build_script_basis_freshness(db, project_id)


@router.get("/projects/{project_id}/delivery-audit")
def project_delivery_audit(
    project_id: int,
    limit: int = Query(200, ge=1, le=200),
    db: Session = Depends(get_db),
    principal: CurrentPrincipal = None,
) -> dict:
    """项目级交付审计：这个项目里哪些产物查过、结论是什么、哪些还没查。"""

    PermissionService(db, principal).require_project_permission(project_id, "project.view")
    return build_delivery_audit(db, project_id, limit=limit)


@router.get("/projects/{project_id}/requirements-worklist")
def requirements_field_worklist(
    project_id: int,
    limit: int = Query(3000, ge=1, le=3000),
    principal: CurrentPrincipal = None,
    db: Session = Depends(get_db),
) -> dict:
    """项目级待办派工清单：每条需求里还没做完的事按字段归并，只读、不写库。"""

    PermissionService(db, principal).require_project_permission(project_id, "project.view")
    return build_field_worklist(db, project_id, limit=limit)


@router.get("/projects/{project_id}/rejection-followup")
def requirements_rejection_followup(
    project_id: int,
    principal: CurrentPrincipal = None,
    db: Session = Depends(get_db),
) -> dict:
    """被否之后的跟随核对：判了「不通过」的产物，后来重新导出的那份内容变了没有。

    只读、不写库、不改判定：它回答的是"是否只是换了版式"，而不是"能不能复核通过"。
    """

    PermissionService(db, principal).require_project_permission(project_id, "project.view")
    return build_rejection_followup(db, project_id)


@router.get("/projects/{project_id}/requirements/{requirement_id}/field-coverage")
def requirement_field_coverage(
    project_id: int,
    requirement_id: int,
    sample: int = Query(200, ge=1, le=500),
    principal: CurrentPrincipal = None,
    db: Session = Depends(get_db),
) -> dict:
    """这条需求覆盖了监管表的哪些字段、没覆盖的是什么性质。

    只读、不写库、不补字段：补字段等于改需求范围，要走人工确认与重新生成。
    """

    PermissionService(db, principal).require_project_permission(project_id, "project.view")
    try:
        return build_field_coverage(db, project_id, requirement_id, sample=sample)
    except CoverageError as error:
        raise HTTPException(status_code=404, detail={"code": error.code, "message": error.message}) from error


@router.get("/projects/{project_id}/requirements-worklist/archive")
def requirements_field_worklist_archive(
    project_id: int,
    limit: int = Query(3000, ge=1, le=3000),
    principal: CurrentPrincipal = None,
    db: Session = Depends(get_db),
) -> Response:
    """把待办派工清单按监管表分装成 zip（一张表一个 CSV + manifest.json），只读、不写库。

    按表分装是因为派工是"按表交给一个人/一组人"；平铺 200+ 行让人自己切分，等于没派工。
    清单里不写生成时间，同一份清单两次导出字节完全相同。
    """

    PermissionService(db, principal).require_project_permission(project_id, "project.view")
    payload = build_field_worklist(db, project_id, limit=limit)
    try:
        archive_bytes, manifest = build_worklist_archive(payload)
    except WorklistArchiveError as exc:
        raise HTTPException(status_code=422, detail=exc.message) from exc
    digest = hashlib.sha256(archive_bytes).hexdigest()
    file_name = f"待办派工清单-{manifest['table_count']}表-{manifest['item_count']}条.zip"
    ascii_name = f"worklist-batch-{manifest['table_count']}-{manifest['item_count']}-{digest[:12]}.zip"
    return Response(
        archive_bytes,
        media_type="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(file_name)}",
            "X-Requirement-Worklist-Tables": str(manifest["table_count"]),
            "X-Requirement-Worklist-Items": str(manifest["item_count"]),
            "X-Requirement-Worklist-File-Sha256": digest,
        },
    )


@router.post("/projects/{project_id}/requirements-worklist/dispatch")
def record_field_dispatch_endpoint(
    project_id: int,
    payload: dict[str, Any] = Body(...),
    db: Session = Depends(get_db),
    principal: CurrentPrincipal = None,
) -> dict:
    """登记字段级派工与处置进展（谁在处理、到哪一步、留了什么话）。

    只登记事实：不关缺口、不改正文、不冻结。"已处置，待复核"也不代表验收通过——
    缺口是否关闭仍由工作台按内容重新评估。
    """

    service = PermissionService(db, principal)
    service.require_project_permission(project_id, "business.edit")
    service.require_project_permission(project_id, "technical.edit")
    requirement_id = payload.get("requirement_id")
    field_id = payload.get("field_id")
    if not _positive_int(requirement_id):
        raise HTTPException(status_code=422, detail="requirement_id 必须是正整数")
    if not _positive_int(field_id):
        raise HTTPException(status_code=422, detail="field_id 必须是正整数")
    try:
        row, created = record_dispatch(
            db,
            project_id=project_id,
            requirement_id=requirement_id,
            field_id=field_id,
            owner=payload.get("owner"),
            status=str(payload.get("status") or "in_progress"),
            note=payload.get("note"),
            created_by=getattr(principal, "user_id", None),
        )
    except DispatchError as exc:
        raise HTTPException(status_code=422, detail=exc.message) from exc
    project = db.get(Project, project_id)
    record_audit(
        db,
        action="record_field_dispatch",
        resource_type="requirement_field_dispatch",
        resource_id=row.id,
        actor_user_id=getattr(principal, "user_id", None),
        institution_id=project.institution_id if project else None,
        project_id=project_id,
        after={
            "requirement_id": requirement_id,
            "field_id": field_id,
            "owner": row.owner,
            "status": row.status,
            "note": row.note,
            "created": created,
        },
    )
    db.commit()
    item = serialize_dispatch(row)
    item.update({"requirement_id": requirement_id, "created": created})
    return item


@router.get("/projects/{project_id}/requirements-status")
def requirements_delivery_status(project_id: int, principal: CurrentPrincipal,
                                 db: Session = Depends(get_db)):
    # 项目级只读聚合：每条需求是否冻结在最近快照、有几个产物、还剩多少打开的字段级缺口。
    # 判据与工作台一致（content_hash），不用版本号推断；不写库、不触发任何渲染。
    PermissionService(db, principal).require_project_permission(project_id, "project.view")
    return build_delivery_status(db, project_id)


@router.get("/projects/{project_id}/template-coverage")
def template_column_coverage(project_id: int, principal: CurrentPrincipal,
                             db: Session = Depends(get_db)) -> dict:
    """标准模板列填充率（项目级）：分清"模板没给"与"平台没填"。只读聚合，不写库。"""
    PermissionService(db, principal).require_project_permission(project_id, "project.view")
    return build_template_coverage(db, project_id)


@router.get("/projects/{project_id}/template-coverage/gaps/{column_key}")
def template_column_coverage_gaps(
    project_id: int,
    column_key: str,
    principal: CurrentPrincipal,
    limit: int = Query(500, ge=1, le=MAX_GAP_ROWS),
    table_code: str | None = Query(None, max_length=64),
    db: Session = Depends(get_db),
) -> dict:
    """某一模板列缺数据的字段清单（可派工）：返回截断标记，不静默截断。

    只读。用途是把"2422 个字段数据格式为空"从统计变成可派工的单据，
    同时把缺口归属（模板没给 / 集市映射缺 / 脚本缺 / 需求待补）一起带出来，
    避免前端按列名猜责任方。

    `table_code` 是按监管表缩小范围（派工时通常只想派某一张表的几个字段）；
    过滤只影响本次返回与 CSV，`total` 仍是整列总数。
    """

    PermissionService(db, principal).require_project_permission(project_id, "project.view")
    try:
        return gaps_for_column(db, project_id, column_key, limit=limit, table_code=table_code)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/projects/{project_id}/table-coverage")
def requirements_table_coverage(project_id: int, principal: CurrentPrincipal,
                                db: Session = Depends(get_db)):
    """项目级监管表覆盖度：每张监管表有没有需求、脚本是否产出它、字段绑了多少集市映射。

    只读聚合。判据分开陈述：脚本没有写入目标 ≠ 需求没做——脚本被整段注释屏蔽的表
    （真实数据里 `T_3_5` 是这种情况）不该被算成"待办"，需要人工确认是否已停用。
    """

    PermissionService(db, principal).require_project_permission(project_id, "project.view")
    return build_table_coverage(db, project_id)


@router.get("/projects/{project_id}/requirements/{requirement_id}/snapshots/{snapshot_id}/content")
def read_draft_snapshot_content(project_id: int, requirement_id: int, snapshot_id: int,
                                principal: CurrentPrincipal, db: Session = Depends(get_db)):
    """读取冻结草稿快照的内容。

    为什么只读且返回完整 content：评审要能回答"上次冻结的那份里，这个字段的口径写的是什么"，
    也要能回答"自上次冻结以来改了什么"。快照本身就是审计对象，内容不随编辑变化，
    因此这里只做完整性校验（`load_frozen_draft` 会比对 `content_hash`），不改动任何数据。
    """

    PermissionService(db, principal).require_project_permission(project_id, "deliverable.view")
    row = load_frozen_draft(db, project_id, requirement_id, snapshot_id)
    return {**snapshot_summary(row), "content": row.content_json,
            "content_hash": content_digest(row.content_json)}


@router.get("/projects/{project_id}/requirements/{requirement_id}/gap-breakdown")
def requirement_gap_breakdown(project_id: int, requirement_id: int,
                              principal: CurrentPrincipal, db: Session = Depends(get_db)):
    """把看板上的"打开缺口 N 条"拆成按字段、按类别的可派工视图。

    只读。动机很具体：项目看板显示某需求"406 条缺口"，评审想知道"是哪几个字段、
    主要卡在哪一类问题"，否则只能进工作台逐条翻。口径与 `build_delivery_status`
    的 `open_gap_count` 完全一致（同一份 content、同一套关闭状态判定），避免两处数字打架。
    """

    PermissionService(db, principal).require_project_permission(project_id, "project.view")
    requirement = load_requirement(db, project_id, requirement_id)
    content = jsonable_encoder(document_content(db, requirement))
    return {
        "project_id": project_id,
        "requirement_id": requirement_id,
        "name": requirement.name,
        "requirement_version": requirement.version,
        **gap_breakdown(content),
    }


@router.get("/projects/{project_id}/requirements/{requirement_id}/snapshots/{snapshot_id}/export")
def export_draft_snapshot(project_id: int, requirement_id: int, snapshot_id: int,
                          principal: CurrentPrincipal, db: Session = Depends(get_db), format: Literal["xlsx", "docx"] = "xlsx"):
    PermissionService(db, principal).require_project_permission(project_id, "deliverable.export")
    row = load_frozen_draft(db, project_id, requirement_id, snapshot_id)
    content = row.content_json
    content_hash = content_digest(content)

    def produce() -> bytes:
        if format == "docx":
            from app.services.requirement_word import export_word

            return export_word(content)
        return export_document(content)

    request = ArtifactRequest(
        project_id=project_id, requirement_id=requirement_id,
        source_kind="draft_snapshot", source_id=snapshot_id, format=format,
        file_name=f"requirement-draft-snapshot-{row.id}.{format}",
        content_hash=content_hash, renderer_version=LEGACY_RENDERERS[format],
        media_type=MEDIA_TYPES[format], snapshot_hash=content_hash,
    )
    try:
        record = ensure_artifact(db, request, produce, created_by=principal.user_id)
    except RenderArtifactError as failure:
        raise HTTPException(409, f"{failure.message}（错误代码：{failure.code}）") from failure
    payload = _stored_artifact_bytes(record)
    headers = _deprecated_export_headers(record)
    media_type = record.media_type
    # 产物记录必须落库：get_db 不自动提交，缺这一步会让"同一身份只渲一次"永远失效。
    db.commit()
    return Response(payload, media_type=media_type, headers=headers)


@router.get("/projects/{project_id}/requirements/{requirement_id}/export")
def export_requirement(project_id: int, requirement_id: int, principal: CurrentPrincipal, db: Session = Depends(get_db)):
    PermissionService(db, principal).require_project_permission(project_id, "export")
    content = document_content(db, load_requirement(db, project_id, requirement_id))
    return Response(export_document(content), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="requirement-draft.xlsx"',
                 "Deprecation": "true", "X-Requirement-Deprecated": _EXPORT_REPLACEMENT})


def _frozen_content_for_template(db: Session, project_id: int, requirement_id: int,
                                 delivery_id: int | None, snapshot_id: int | None) -> tuple[dict, str]:
    """客户模板导出只接受已冻结内容；未冻结内容可能随时变化，不能当正式文档来源。"""

    if delivery_id is not None:
        from app.services.requirement_review import load_formal_delivery

        row = load_formal_delivery(db, project_id, requirement_id, delivery_id)
        return row.content_json, f"requirement-formal-v{row.version_no}"
    if snapshot_id is not None:
        row = load_frozen_draft(db, project_id, requirement_id, snapshot_id)
        return row.content_json, f"requirement-draft-snapshot-{row.id}"
    raise HTTPException(409,
        "客户模板导出只接受已冻结内容：请指定正式交付版本（delivery_id）或冻结草稿快照（snapshot_id）。"
        "未冻结的需求内容可能随时变化，不能作为正式文档来源。")


def _template_config(raw: str | None) -> dict[str, Any]:
    if not raw or not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except ValueError as failure:
        raise HTTPException(422, f"模板适配配置不是合法 JSON：{failure}") from failure
    if not isinstance(parsed, dict):
        raise HTTPException(422, "模板适配配置必须是 JSON 对象（锚点/命名单元格映射）。")
    return parsed


def _config_digest(payload: dict[str, Any]) -> str:
    import hashlib as _hashlib

    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return _hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _template_source(db: Session, project_id: int, *, template: UploadFile | None,
                     config: str | None, template_id: int | None) -> tuple[bytes, dict[str, Any]]:
    """解析客户模板来源：注册库（``template_id``）或随请求上传。

    注册过的模板带适配配置与配置摘要，随请求重复上传文件既浪费也不可追溯；因此
    允许只给 ``template_id``。同时给文件或给不同配置都视为冲突，直接 422。
    """

    if template_id is not None:
        from app.services.customer_template_store import (
            CustomerTemplateError, config_digest, get_template, template_bytes,
        )

        if template is not None:
            raise HTTPException(422, "已指定 template_id 时不要再上传模板文件；如需换模板请注册新版本。")
        row = get_template(db, project_id, template_id)
        if row is None:
            raise HTTPException(404, "模板不存在或不属于该项目")
        payload = dict(row.config_json or {})
        if config and config.strip() and config.strip() != "{}":
            supplied = _template_config(config)
            if config_digest(supplied) != row.config_digest:
                raise HTTPException(
                    422, "传入的适配配置与已注册模板不一致；请用注册时的配置，或注册新的模板版本。")
        try:
            return template_bytes(row), payload
        except CustomerTemplateError as failure:
            status = 404 if failure.code == "template_file_missing" else 422
            raise HTTPException(status, f"{failure.message}（错误代码：{failure.code}）") from failure

    if template is None:
        raise HTTPException(
            422, "客户模板导出需要 template_id（已注册模板）或直接上传模板文件。")
    payload = _template_config(config)
    raw = template.file.read()
    if len(raw) > 20 * 1024 * 1024:
        raise HTTPException(413, "模板文件超过 20MB 上限，请精简模板后重新上传。")
    return raw, payload


def _render_customer_template(db: Session, project_id: int, requirement_id: int, *,
                              template: UploadFile | None, format: str, config: str | None,
                              delivery_id: int | None, snapshot_id: int | None,
                              principal: CurrentPrincipal, audit_action: str,
                              template_id: int | None = None):
    """渲染（或复用已存产物）客户模板导出，返回渲染产物记录。

    正式文件只渲染一次：同一渲染身份（内容/模板/渲染器/配置/格式/冻结来源）
    第二次请求直接读已存文件，不再重新渲染，也不会覆盖历史产物。
    """

    PermissionService(db, principal).require_project_permission(project_id, "deliverable.export")
    content, base_name = _frozen_content_for_template(db, project_id, requirement_id, delivery_id, snapshot_id)
    raw, payload = _template_source(db, project_id, template=template, config=config,
                                    template_id=template_id)
    content_hash = content_digest(content)
    template_sha256 = hashlib.sha256(raw).hexdigest() if raw else ""
    source_kind = "formal_delivery" if delivery_id is not None else "draft_snapshot"
    source_id = int(delivery_id if delivery_id is not None else snapshot_id)
    request = ArtifactRequest(
        project_id=project_id, requirement_id=requirement_id,
        source_kind=source_kind, source_id=source_id, format=format,
        file_name=base_name, content_hash=content_hash,
        renderer_version=template_renderer_version,
        config_version=str(payload.get("config_version") or ""),
        config_digest=_config_digest(payload), template_sha256=template_sha256,
        media_type=MEDIA_TYPES.get(format, "application/octet-stream"),
    )
    identity = render_identity(request)
    existing = find_artifact(db, project_id, identity)
    if existing is not None and existing.status == "ready":
        return existing
    try:
        artifact = render_requirement_artifact(
            format=format,
            template_bytes=raw,
            frozen_content=content,
            config=payload,
            base_name=base_name,
            content_hash=content_hash,
        )
    except CustomerTemplateRenderError as failure:
        raise HTTPException(422, f"{failure.message}（错误代码：{failure.code}）") from failure
    request = ArtifactRequest(
        project_id=project_id, requirement_id=requirement_id,
        source_kind=source_kind, source_id=source_id, format=artifact.format,
        file_name=artifact.file_name, content_hash=content_hash,
        renderer_version=artifact.renderer_version, config_version=artifact.config_version,
        config_digest=_config_digest(payload), template_sha256=artifact.template_sha256,
        media_type=artifact.media_type, diagnostics=dict(artifact.diagnostics or {}),
        warnings=list(artifact.warnings or []), snapshot_hash=content_hash,
    )
    try:
        record = ensure_artifact(db, request, lambda: artifact.content, created_by=principal.user_id)
    except RenderArtifactError as failure:
        raise HTTPException(409, f"{failure.message}（错误代码：{failure.code}）") from failure
    record_audit(db, action=audit_action, resource_type="requirement_template_export",
                 resource_id=requirement_id, actor_user_id=principal.user_id,
                 project_id=project_id,
                 after={"format": record.format, "template_sha256": record.template_sha256,
                        "renderer_version": record.renderer_version,
                        "config_version": record.config_version,
                        "file_sha256": record.file_sha256, "file_name": record.file_name,
                        "content_hash": content_hash, "render_artifact_id": record.id})
    return record


def _artifact_headers(record) -> dict[str, str]:
    headers = {
        "Content-Disposition": f'attachment; filename="{record.file_name}"',
        "X-Requirement-Render-Artifact-Id": str(record.id),
        "X-Requirement-Rendered-File-Sha256": record.file_sha256,
        "X-Requirement-Template-Sha256": record.template_sha256,
        "X-Requirement-Renderer-Version": record.renderer_version,
        "X-Requirement-Render-Config-Version": record.config_version,
    }
    if record.snapshot_hash:
        headers["X-Requirement-Snapshot-Hash"] = record.snapshot_hash
    return headers


_EXPORT_REPLACEMENT = "POST /projects/{project_id}/requirements/{requirement_id}/exports"


def _deprecated_export_headers(record) -> dict[str, str]:
    """旧导出端点仍可用，但不再是推荐入口：统一入口支持模板选择与内置版式分流。"""

    headers = dict(_artifact_headers(record))
    headers["Deprecation"] = "true"
    headers["X-Requirement-Deprecated"] = _EXPORT_REPLACEMENT
    return headers


def _stored_artifact_bytes(record) -> bytes:
    try:
        return read_artifact_bytes(record)
    except RenderArtifactError as failure:
        status = 404 if failure.code == "artifact_missing" else 409
        raise HTTPException(status, f"{failure.message}（错误代码：{failure.code}）") from failure


def _builtin_export_bytes(db: Session, content: dict, format: str, delivery_row=None) -> bytes:
    """内置版式导出（未适配客户模板时的默认路径）。

    正式交付的 xlsx 直接返回当时冻结的正式文件，docx 现渲一次；两种结果都会进入
    渲染产物表，因此"统一入口"与"旧 GET 端点"拿到的是同一份字节。
    """

    if format == "docx":
        from app.services.requirement_word import export_word

        return export_word(content)
    if delivery_row is not None:
        from app.services.requirement_review import formal_file

        return formal_file(db, delivery_row)
    return export_document(content)


def _builtin_export_artifact(db: Session, *, project_id: int, requirement_id: int,
                             source_kind: str, source_id: int, format: str, layout: str,
                             created_by: int):
    """按冻结来源渲染内置版式产物（调用方负责审计与提交）。

    统一入口与"冻结并导出"必须走同一段渲染逻辑：两处各写一份必然在某次改动后分叉，
    产出的正式文件就会与另一条路径不一致。
    """

    delivery_id = source_id if source_kind == "formal_delivery" else None
    snapshot_id = source_id if source_kind == "draft_snapshot" else None
    content, base_name = _frozen_content_for_template(db, project_id, requirement_id, delivery_id, snapshot_id)
    content_hash = content_digest(content)
    delivery_row = None
    if delivery_id is not None:
        from app.services.requirement_review import load_formal_delivery

        delivery_row = load_formal_delivery(db, project_id, requirement_id, delivery_id)

    survey_layout = layout == "survey"
    request = ArtifactRequest(
        project_id=project_id, requirement_id=requirement_id,
        source_kind=source_kind, source_id=source_id, format=format,
        file_name=f"{base_name}-survey.{format}" if survey_layout else f"{base_name}.{format}",
        content_hash=content_hash,
        renderer_version=survey_renderer_version() if survey_layout else LEGACY_RENDERERS[format],
        media_type=MEDIA_TYPES[format],
        snapshot_hash=content_hash,
    )
    try:
        return ensure_artifact(
            db, request,
            (lambda: export_survey_document(content)) if survey_layout
            else (lambda: _builtin_export_bytes(db, content, format, delivery_row)),
            created_by=created_by,
        )
    except RenderArtifactError as failure:
        raise HTTPException(409, f"{failure.message}（错误代码：{failure.code}）") from failure


@router.post("/projects/{project_id}/requirements/{requirement_id}/exports")
def export_requirement_document(project_id: int, requirement_id: int,
                                principal: CurrentPrincipal, db: Session = Depends(get_db),
                                format: Literal["xlsx", "docx"] = Form("docx"),
                                source_kind: str = Form("draft_snapshot"),
                                source_id: int = Form(..., ge=1),
                                template: UploadFile | None = File(None),
                                config: str | None = Form(None),
                                template_id: int | None = Form(None, ge=1),
                                layout: str = Form("standard")):
    """统一导出入口：带客户模板走模板渲染，不带模板走内置版式，产物都落库。

    `layout="survey"` 时 xlsx 按客户示例的"一表通调研表式"版式生成（表级信息 + 每个数据项
    一个横向区块）；不同版式是不同的渲染身份，不会复用同一条产物记录。

    旧的两个 GET 导出端点保留（前端与既有客户端仍在用），但它们与这里是同一套渲染
    产物身份：同一冻结内容 + 同一模板得到同一个 `render_artifact_id`，不会渲染两遍。
    """

    if source_kind not in {"draft_snapshot", "formal_delivery"}:
        raise HTTPException(422, "冻结来源只能是 draft_snapshot（冻结草稿快照）或 formal_delivery（正式交付）。")
    if layout not in {"standard", "survey"}:
        raise HTTPException(422, "导出布局只能是 standard（平台内置版式）或 survey（一表通调研表式）。")
    if layout == "survey" and format != "xlsx":
        raise HTTPException(422, "一表通调研表式只支持 xlsx；需要 Word 请用 standard 布局。")
    delivery_id = source_id if source_kind == "formal_delivery" else None
    snapshot_id = source_id if source_kind == "draft_snapshot" else None

    if template is not None or template_id is not None:
        record = _render_customer_template(
            db, project_id, requirement_id, template=template, format=format, config=config,
            delivery_id=delivery_id, snapshot_id=snapshot_id, principal=principal,
            audit_action="export_requirement_with_customer_template", template_id=template_id,
        )
        payload = _stored_artifact_bytes(record)
        headers = _artifact_headers(record)
        media_type = record.media_type
        # 带客户模板的分支同样必须提交产物记录。
        db.commit()
        return Response(payload, media_type=media_type, headers=headers)

    if config and config.strip() and config.strip() != "{}":
        raise HTTPException(422, "提供模板适配配置时必须同时上传客户模板文件；未上传模板时不允许应用锚点/单元格映射。")

    PermissionService(db, principal).require_project_permission(project_id, "deliverable.export")
    record = _builtin_export_artifact(
        db, project_id=project_id, requirement_id=requirement_id,
        source_kind=source_kind, source_id=source_id, format=format, layout=layout,
        created_by=principal.user_id,
    )
    record_audit(db, action="export_requirement_document", resource_type="requirement_export",
                 resource_id=requirement_id, actor_user_id=principal.user_id,
                 project_id=project_id,
                 after={"format": record.format, "layout": layout,
                        "source_kind": record.source_kind,
                        "source_id": record.source_id, "file_sha256": record.file_sha256,
                        "renderer_version": record.renderer_version,
                        "render_artifact_id": record.id})
    payload = _stored_artifact_bytes(record)
    headers = _artifact_headers(record)
    media_type = record.media_type
    # 产物记录必须落库：get_db 不自动提交，缺这一步会让"同一身份只渲一次"永远失效。
    db.commit()
    return Response(payload, media_type=media_type, headers=headers)


@router.post("/projects/{project_id}/requirements/{requirement_id}/freeze-and-export")
def freeze_and_export(project_id: int, requirement_id: int,
                      principal: CurrentPrincipal, db: Session = Depends(get_db),
                      format: Literal["xlsx", "docx"] = Form("xlsx"),
                      layout: str = Form("survey"),
                      expected_version: int = Form(..., ge=1),
                      expected_hash: str = Form(..., min_length=64, max_length=64)) -> Response:
    """冻结当前内容并立即导出（一步完成，产物可复现）。

    真实问题：工作台"导出需求文档"此前直接导出**编辑态**内容，文件 hash 随之变动，
    评审拿到文件后无法复现，也无法证明"这就是当时确认过的那份"。这里把"冻结 + 导出"
    做成一次调用：先在乐观锁下冻结（同一内容重复调用复用同一快照），再按同一产物身份
    渲染；响应头返回快照号与产物号，任何人可用同一快照重新导出得到同一字节。
    """

    if layout not in {"standard", "survey"}:
        raise HTTPException(422, "导出布局只能是 standard（平台内置版式）或 survey（一表通调研表式）。")
    if layout == "survey" and format != "xlsx":
        raise HTTPException(422, "一表通调研表式只支持 xlsx；需要 Word 请用 standard 布局。")

    permissions = PermissionService(db, principal)
    project = permissions.require_project_permission(project_id, "deliverable.manage")
    permissions.require_project_permission(project_id, "deliverable.export")

    snapshot, created = freeze_draft(db, project_id, requirement_id, expected_version,
                                     expected_hash, principal.user_id)
    if created:
        record_audit(db, action="freeze_requirement_draft", resource_type="requirement_draft_snapshot",
                     resource_id=snapshot.id, actor_user_id=principal.user_id,
                     institution_id=project.institution_id, project_id=project_id,
                     after={"requirement_version": snapshot.requirement_version,
                            "content_hash": snapshot.content_hash, "via": "freeze-and-export"})
    record = _builtin_export_artifact(
        db, project_id=project_id, requirement_id=requirement_id,
        source_kind="draft_snapshot", source_id=snapshot.id,
        format=format, layout=layout, created_by=principal.user_id,
    )
    record_audit(db, action="export_requirement_document", resource_type="requirement_export",
                 resource_id=requirement_id, actor_user_id=principal.user_id, project_id=project_id,
                 after={"format": record.format, "layout": layout, "source_kind": record.source_kind,
                        "source_id": record.source_id, "file_sha256": record.file_sha256,
                        "renderer_version": record.renderer_version, "render_artifact_id": record.id,
                        "snapshot_created": created})
    payload = _stored_artifact_bytes(record)
    headers = _artifact_headers(record) | {
        "X-Requirement-Snapshot-Id": str(snapshot.id),
        "X-Requirement-Snapshot-Created": "true" if created else "false",
        "X-Requirement-Snapshot-Hash": snapshot.content_hash,
    }
    media_type = record.media_type
    # 冻结与产物必须在同一事务提交：否则可能留下"已冻结但没有文件"或反之。
    db.commit()
    return Response(payload, media_type=media_type, headers=headers)


_BATCH_EXPORT_LIMIT = 20


def _batch_selection(raw: str) -> list[dict]:
    """解析批量导出清单；任何一项不合法都整体拒绝，不做"能导几条算几条"。"""

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as failure:
        raise HTTPException(422, f"批量导出清单不是合法 JSON：{failure.msg}") from failure
    if not isinstance(parsed, list) or not parsed:
        raise HTTPException(422, "批量导出清单必须是非空数组。")
    if len(parsed) > _BATCH_EXPORT_LIMIT:
        raise HTTPException(422, f"一次最多导出 {_BATCH_EXPORT_LIMIT} 条需求，当前选择了 {len(parsed)} 条。")
    items: list[dict] = []
    seen: set[int] = set()
    for index, entry in enumerate(parsed, start=1):
        if not isinstance(entry, dict):
            raise HTTPException(422, f"批量导出清单第 {index} 项不是对象。")
        requirement_id = entry.get("requirement_id")
        expected_version = entry.get("expected_version")
        expected_hash = entry.get("expected_hash")
        if not isinstance(requirement_id, int) or isinstance(requirement_id, bool) or requirement_id < 1:
            raise HTTPException(422, f"批量导出清单第 {index} 项的 requirement_id 必须是正整数。")
        if requirement_id in seen:
            raise HTTPException(422, f"同一需求（#{requirement_id}）只能选择一次。")
        seen.add(requirement_id)
        if not isinstance(expected_version, int) or isinstance(expected_version, bool) or expected_version < 1:
            raise HTTPException(422, f"批量导出清单第 {index} 项的 expected_version 必须是正整数。")
        if not isinstance(expected_hash, str) or len(expected_hash) != 64:
            raise HTTPException(422, f"批量导出清单第 {index} 项的 expected_hash 必须是 64 位内容哈希。")
        items.append({"requirement_id": requirement_id, "expected_version": expected_version,
                      "expected_hash": expected_hash})
    return items


@router.post("/projects/{project_id}/requirements/exports-batch")
def export_requirements_batch(project_id: int, principal: CurrentPrincipal,
                              db: Session = Depends(get_db),
                              selection: str = Form(..., min_length=2),
                              format: Literal["xlsx", "docx"] = Form("xlsx"),
                              layout: str = Form("survey")) -> Response:
    """一次冻结并导出多条需求，打成一个带清单的 zip。

    真实问题：项目里十几条需求，评审要一次性拿到"这一批"文件，逐条点导出既慢又容易漏；
    而"能导几条算几条"最危险——拿到半批文件的人不知道少了谁。所以这里先做整体预检
    （每条需求都存在、版本与内容哈希都对得上），任一条不匹配就**一条都不冻结**，
    再逐条冻结+渲染，最后打成一个可复现的压缩包，并附 `manifest.json` 记录每份文件
    来自哪份快照、哪条产物。
    """

    if layout not in {"standard", "survey"}:
        raise HTTPException(422, "导出布局只能是 standard（平台内置版式）或 survey（一表通调研表式）。")
    if layout == "survey" and format != "xlsx":
        raise HTTPException(422, "一表通调研表式只支持 xlsx；需要 Word 请用 standard 布局。")
    items = _batch_selection(selection)

    permissions = PermissionService(db, principal)
    project = permissions.require_project_permission(project_id, "deliverable.manage")
    permissions.require_project_permission(project_id, "deliverable.export")

    preflight: list[tuple[dict, Requirement, str]] = []
    for item in items:
        requirement = load_requirement(db, project_id, item["requirement_id"])
        content = jsonable_encoder(document_content(db, requirement))
        current_hash = content_digest(content)
        if requirement.version != item["expected_version"]:
            raise HTTPException(
                409,
                f"「{requirement.name}」的需求范围版本已变化（清单为 v{item['expected_version']}，"
                f"当前为 v{requirement.version}）：请刷新后再批量导出，本次未冻结任何需求。",
            )
        if current_hash != item["expected_hash"]:
            raise HTTPException(
                409,
                f"「{requirement.name}」的内容已发生变化（清单哈希与当前内容不一致）："
                "请刷新后再批量导出，本次未冻结任何需求。",
            )
        preflight.append((item, requirement, current_hash))

    entries: list[dict] = []
    snapshot_created = 0
    for item, requirement, current_hash in preflight:
        snapshot, created = freeze_draft(db, project_id, requirement.id, item["expected_version"],
                                         item["expected_hash"], principal.user_id)
        if created:
            snapshot_created += 1
            record_audit(db, action="freeze_requirement_draft", resource_type="requirement_draft_snapshot",
                         resource_id=snapshot.id, actor_user_id=principal.user_id,
                         institution_id=project.institution_id, project_id=project_id,
                         after={"requirement_version": snapshot.requirement_version,
                                "content_hash": snapshot.content_hash, "via": "batch-export"})
        record = _builtin_export_artifact(
            db, project_id=project_id, requirement_id=requirement.id,
            source_kind="draft_snapshot", source_id=snapshot.id,
            format=format, layout=layout, created_by=principal.user_id,
        )
        payload = _stored_artifact_bytes(record)
        table_id = (requirement.scope_json or {}).get("target_table_id")
        table = db.get(TargetTable, table_id) if table_id else None
        entries.append({
            "requirement_id": requirement.id,
            "name": requirement.name,
            "target_table_code": getattr(table, "table_code", None),
            "snapshot_id": snapshot.id,
            "content_hash": snapshot.content_hash,
            "artifact_id": record.id,
            "file_name": record.file_name,
            "file_sha256": record.file_sha256,
            "file_size": record.file_size,
            "renderer_version": record.renderer_version,
            "format": record.format,
            "layout": layout,
            "payload": payload,
        })

    try:
        archive = build_archive(entries, project_id=project_id)
    except BatchArchiveError as failure:
        raise HTTPException(422, f"{failure.message}（错误代码：{failure.code}）") from failure
    archive_hash = hashlib.sha256(archive).hexdigest()
    file_name = f"requirements-batch-{len(entries)}-{archive_hash[:12]}.zip"
    record_audit(db, action="batch_export_requirements", resource_type="requirement_export",
                 resource_id=project_id, actor_user_id=principal.user_id,
                 institution_id=project.institution_id, project_id=project_id,
                 after={"format": format, "layout": layout, "item_count": len(entries),
                        "snapshots_created": snapshot_created, "archive_sha256": archive_hash,
                        "requirement_ids": [entry["requirement_id"] for entry in entries]})
    headers = {
        "Content-Disposition": f'attachment; filename="{file_name}"',
        "X-Requirement-Batch-Items": str(len(entries)),
        "X-Requirement-Batch-Snapshots-Created": str(snapshot_created),
        "X-Requirement-Batch-File-Sha256": archive_hash,
    }
    # 与单条冻结导出一样：冻结、产物、审计一起提交，避免"已冻结但压缩包没发出去"。
    db.commit()
    return Response(archive, media_type="application/zip", headers=headers)


@router.post("/projects/{project_id}/requirements/refreeze-batch")
def refreeze_requirements_batch(project_id: int, principal: CurrentPrincipal,
                                body: dict[str, Any] = Body(...),
                                db: Session = Depends(get_db)) -> dict[str, Any]:
    """把多条需求"只重新冻结"成快照，不导出文件。

    真实场景：模板表级口径更新后，十几条需求只是"快照落后于当前内容"（正文没改），
    用户要的是把快照对齐、让看板回到可导出状态，而不是再生成一批用不上的文件；
    逐条进导出面板重新冻结，既要点开每条，又会顺手多出一批文件。

    与批量导出共用同一条预检与冻结路径：任一条版本或内容哈希对不上就**一条都不冻结**，
    避免出现"冻结了一半、用户以为都对齐了"的状态。
    """

    raw = body.get("selection")
    if isinstance(raw, list):
        raw = json.dumps(raw, ensure_ascii=False)
    if not isinstance(raw, str):
        raise HTTPException(422, "批量重新冻结需要 selection：JSON 数组或数组字符串。")
    items = _batch_selection(raw)

    permissions = PermissionService(db, principal)
    project = permissions.require_project_permission(project_id, "deliverable.manage")

    preflight: list[tuple[Requirement, dict]] = []
    for item in items:
        requirement = load_requirement(db, project_id, item["requirement_id"])
        current_hash = content_digest(jsonable_encoder(document_content(db, requirement)))
        if requirement.version != item["expected_version"]:
            raise HTTPException(
                409,
                f"「{requirement.name}」的需求范围版本已变化（清单为 v{item['expected_version']}，"
                f"当前为 v{requirement.version}）：请刷新后再重新冻结，本次未冻结任何需求。",
            )
        if current_hash != item["expected_hash"]:
            raise HTTPException(
                409,
                f"「{requirement.name}」的内容已发生变化（清单哈希与当前内容不一致）："
                "请刷新后再重新冻结，本次未冻结任何需求。",
            )
        preflight.append((requirement, item))

    frozen: list[dict[str, Any]] = []
    created_count = 0
    for requirement, item in preflight:
        snapshot, created = freeze_draft(db, project_id, requirement.id, item["expected_version"],
                                        item["expected_hash"], principal.user_id)
        if created:
            created_count += 1
            record_audit(db, action="freeze_requirement_draft",
                         resource_type="requirement_draft_snapshot", resource_id=snapshot.id,
                         actor_user_id=principal.user_id, institution_id=project.institution_id,
                         project_id=project_id,
                         after={"requirement_version": snapshot.requirement_version,
                                "content_hash": snapshot.content_hash, "via": "batch-refreeze"})
        frozen.append({
            "requirement_id": requirement.id,
            "name": requirement.name,
            "snapshot_id": snapshot.id,
            "created": created,
            "content_hash": snapshot.content_hash,
        })

    record_audit(db, action="batch_refreeze_requirements", resource_type="requirement",
                 resource_id=project_id, actor_user_id=principal.user_id,
                 institution_id=project.institution_id, project_id=project_id,
                 after={"item_count": len(frozen), "snapshots_created": created_count,
                        "requirement_ids": [entry["requirement_id"] for entry in frozen]})
    # 冻结与审计同事务提交：要么全部快照落地，要么一条都没有。
    db.commit()
    return {"item_count": len(frozen), "snapshots_created": created_count, "items": frozen}


@router.get("/projects/{project_id}/requirements/{requirement_id}/render-artifacts")
def list_requirement_render_artifacts(project_id: int, requirement_id: int,
                                      principal: CurrentPrincipal, db: Session = Depends(get_db),
                                      source_kind: str | None = Query(default=None, max_length=40),
                                      source_id: int | None = Query(default=None, ge=1)) -> list[dict[str, Any]]:
    """列出已冻结的导出产物（谁、何时、用什么模板/版本渲染、文件 hash）。"""

    PermissionService(db, principal).require_project_permission(project_id, "deliverable.export")
    rows = list_artifacts(db, project_id, requirement_id, source_kind=source_kind, source_id=source_id)
    return [{"id": row.id, "format": row.format, "file_name": row.file_name,
             "file_size": row.file_size, "file_sha256": row.file_sha256,
             "content_hash": row.content_hash, "template_sha256": row.template_sha256,
             "renderer_version": row.renderer_version, "config_version": row.config_version,
             "source_kind": row.source_kind, "source_id": row.source_id,
             "status": row.status, "created_by": row.created_by,
             "created_at": row.created_at.isoformat() if row.created_at else None,
             "warnings": list(row.warnings_json or [])} for row in rows]


@router.get("/projects/{project_id}/requirements/{requirement_id}/render-artifacts/{artifact_id}/download")
def download_requirement_render_artifact(project_id: int, requirement_id: int, artifact_id: int,
                                         principal: CurrentPrincipal, db: Session = Depends(get_db)):
    """按产物记录下载已保存文件；文件被替换/丢失时报错，不重新渲染。"""

    PermissionService(db, principal).require_project_permission(project_id, "deliverable.export")
    try:
        record = get_artifact(db, project_id, requirement_id, artifact_id)
    except RenderArtifactError as failure:
        raise HTTPException(404, failure.message) from failure
    payload = _stored_artifact_bytes(record)
    return Response(payload, media_type=record.media_type, headers=_artifact_headers(record))


@router.get("/projects/{project_id}/requirements/{requirement_id}/render-artifacts/{artifact_id}/preview")
def preview_requirement_render_artifact(project_id: int, requirement_id: int, artifact_id: int,
                                        principal: CurrentPrincipal, db: Session = Depends(get_db)) -> dict[str, Any]:
    """按产物记录把已保存的产物解析成页面内容（xlsx 网格 / docx 章节；只读，不重新渲染）。

    评审者需要"在页面上看到导出的到底是不是监管模板的版式与内容"，而不是先下载
    再用 Excel 打开。这里读的是**已落库的产物字节**，与下载返回同一份文件；文件被
    替换/丢失时报错而不是重新渲染，保证"看到的"与"交付的"是同一份。
    """

    PermissionService(db, principal).require_project_permission(project_id, "project.view")
    try:
        record = get_artifact(db, project_id, requirement_id, artifact_id)
    except RenderArtifactError as failure:
        raise HTTPException(404, failure.message) from failure
    payload = _stored_artifact_bytes(record)
    try:
        preview = preview_artifact(payload, file_format=record.format)
    except ArtifactPreviewError as failure:
        raise HTTPException(422, failure.message) from failure
    preview["artifact"] = {
        "id": record.id, "format": record.format, "file_name": record.file_name,
        "file_size": record.file_size, "file_sha256": record.file_sha256,
        "template_sha256": record.template_sha256, "renderer_version": record.renderer_version,
        "config_version": record.config_version, "source_kind": record.source_kind,
        "source_id": record.source_id,
    }
    return preview


@router.get("/projects/{project_id}/requirements/{requirement_id}/render-artifacts/{artifact_id}/structure-check")
def check_requirement_render_artifact_structure(project_id: int, requirement_id: int, artifact_id: int,
                                                principal: CurrentPrincipal,
                                                db: Session = Depends(get_db)) -> dict[str, Any]:
    """对已保存的产物做"是否仍符合一表通模板结构"的只读自检。

    与 `/preview` 的区别：preview 给页面网格，这里给可判定结论（表级信息 6 行、
    分组成对、列名行 11+6N+9N、每字段一行、完整度与来源说明在尾部）。读的是同一份
    已落库字节，所以"自检通过"与"交付的文件"是同一样东西。
    """

    PermissionService(db, principal).require_project_permission(project_id, "project.view")
    try:
        record = get_artifact(db, project_id, requirement_id, artifact_id)
    except RenderArtifactError as failure:
        raise HTTPException(404, failure.message) from failure
    payload = _stored_artifact_bytes(record)
    try:
        # 按产物格式分派：xlsx 走一表通调研表式契约，docx 走内置版式契约。
        # 两者都不"假装通过"：不是对应版式时由各服务抛错，端点统一 422。
        if record.format == "xlsx":
            result = check_survey_structure(payload, renderer_version=record.renderer_version)
        elif record.format == "docx":
            result = check_docx_structure(payload, renderer_version=record.renderer_version)
        else:
            raise HTTPException(422, f"暂不支持对 {record.format} 产物做结构自检。")
    except (StructureCheckError, DocxStructureCheckError) as failure:
        raise HTTPException(422, failure.message) from failure
    result["artifact"] = {
        "id": record.id, "format": record.format, "file_name": record.file_name,
        "file_size": record.file_size, "file_sha256": record.file_sha256,
        "renderer_version": record.renderer_version, "config_version": record.config_version,
        "source_kind": record.source_kind, "source_id": record.source_id,
    }
    return result


@router.get("/projects/{project_id}/requirements/{requirement_id}/render-artifacts/{artifact_id}/template-fidelity")
def check_requirement_render_artifact_fidelity(project_id: int, requirement_id: int, artifact_id: int,
                                               principal: CurrentPrincipal,
                                               db: Session = Depends(get_db)) -> dict[str, Any]:
    """逐字段比对产物里的模板列与当前监管标准模板值（只读）。

    与 `/structure-check` 的区别：后者判"长得像不像"，这里判"模板列的值对不对"——
    监管原始口径、报表名称这类业务方给定的标准值必须与模板一致，被改过就要能查出来。
    """

    PermissionService(db, principal).require_project_permission(project_id, "project.view")
    try:
        result = check_template_fidelity(
            db, project_id=project_id, artifact_id=artifact_id, requirement_id=requirement_id
        )
    except FidelityError as failure:
        raise HTTPException(404 if failure.code == "artifact_missing" else 422, failure.message) from failure
    return result


@router.post("/projects/{project_id}/requirements/{requirement_id}/render-artifacts/{artifact_id}/delivery-checks")
def record_delivery_check(
    project_id: int,
    requirement_id: int,
    artifact_id: int,
    db: Session = Depends(get_db),
    principal: CurrentPrincipal = None,
) -> dict:
    """跑一次交付前检查并把结论留痕（每次新增一行，保留"先通过后失败"的转折）。"""

    PermissionService(db, principal).require_project_permission(project_id, "project.view")
    load_requirement(db, project_id, requirement_id)
    try:
        result = record_check(
            db,
            project_id=project_id,
            requirement_id=requirement_id,
            artifact_id=artifact_id,
            actor_id=principal.user_id,
        )
    except RenderArtifactError as exc:
        raise HTTPException(status_code=404, detail=str(exc.message)) from exc
    record_audit(
        db,
        action="record_delivery_check",
        resource_type="requirement_delivery_check",
        resource_id=result["record"]["id"],
        actor_user_id=principal.user_id,
        project_id=project_id,
        after={
            "artifact_id": artifact_id,
            "verdict": result["record"]["verdict"],
            "blocking_keys": result["record"]["blocking_keys"],
        },
    )
    db.commit()
    return result


@router.get("/projects/{project_id}/requirements/{requirement_id}/delivery-checks")
def list_delivery_checks(
    project_id: int,
    requirement_id: int,
    limit: int = Query(20, ge=1, le=100),
    artifact_id: int | None = Query(None, ge=1),
    db: Session = Depends(get_db),
    principal: CurrentPrincipal = None,
) -> dict:
    PermissionService(db, principal).require_project_permission(project_id, "project.view")
    load_requirement(db, project_id, requirement_id)
    items = list_checks(
        db,
        project_id=project_id,
        requirement_id=requirement_id,
        limit=limit,
        artifact_id=artifact_id,
    )
    return {
        "requirement_id": requirement_id,
        "artifact_id": artifact_id,
        "count": len(items),
        "items": items,
    }

@router.get("/projects/{project_id}/requirements/{requirement_id}/render-artifacts/{artifact_id}/delivery-checklist")
def requirement_render_artifact_delivery_checklist(project_id: int, requirement_id: int, artifact_id: int,
                                                   principal: CurrentPrincipal,
                                                   db: Session = Depends(get_db)) -> dict[str, Any]:
    """一份产物一次性回答"能不能交出去"：字节完整 / 身份可复现 / 结构合规 / 字段都在。

    与 `/structure-check` 的区别：后者只判结构；这里还要证明"文件没被换过、快照号能重新取回
    同一份字节、冻结内容里的字段编码确实都在文件里"，并把阻断项聚成 verdict。
    仍然只读：不重渲染、不修改产物、不关闭缺口。
    """

    PermissionService(db, principal).require_project_permission(project_id, "project.view")
    try:
        return check_delivery(db, project_id=project_id, requirement_id=requirement_id, artifact_id=artifact_id)
    except RenderArtifactError as failure:
        raise HTTPException(404, failure.message) from failure


@router.post("/projects/{project_id}/requirements/{requirement_id}/render-artifacts/{artifact_id}/acceptance-run")
def requirement_render_artifact_acceptance_run(project_id: int, requirement_id: int, artifact_id: int,
                                               principal: CurrentPrincipal,
                                               db: Session = Depends(get_db)) -> dict[str, Any]:
    """一键验收：字节完整 / 结构合规 / 模板列一致 / 检查单，一次给出结论并留痕。

    会写一条检查记录（`requirement_delivery_checks`），这样"这份文件交出去前查过、结论是什么"
    在审计里可回查；其余一律只读：不重渲染、不修改需求、不关闭缺口。
    """

    PermissionService(db, principal).require_project_permission(project_id, "project.view")
    try:
        payload = run_acceptance(
            db,
            project_id=project_id,
            requirement_id=requirement_id,
            artifact_id=artifact_id,
            actor_id=principal.user_id,
            record=True,
        )
    except RenderArtifactError as failure:
        raise HTTPException(404, failure.message) from failure
    except (AcceptanceError, StructureCheckError, DocxStructureCheckError, FidelityError) as failure:
        code = getattr(failure, "code", "acceptance_failed")
        message = getattr(failure, "message", str(failure))
        raise HTTPException(422, f"{message}（{code}）") from failure
    project = db.get(Project, project_id)
    record_audit(db, action="run_delivery_acceptance", resource_type="requirement_render_artifact",
                 resource_id=artifact_id, actor_user_id=principal.user_id,
                 institution_id=project.institution_id if project else None, project_id=project_id,
                 after={"verdict": payload["verdict"], "blocking_keys": payload["blocking_keys"],
                        "record_id": (payload.get("record") or {}).get("id")})
    db.commit()
    return payload


@router.post("/projects/{project_id}/requirements/{requirement_id}/render-artifacts/{artifact_id}/attestations")
def requirement_render_artifact_attestation_record(project_id: int, requirement_id: int, artifact_id: int,
                                                   payload: dict[str, Any] = Body(default=None),
                                                   principal: CurrentPrincipal = None,
                                                   db: Session = Depends(get_db)) -> dict[str, Any]:
    """人工核对登记：给"自动验收跑不了"的产物留一条人看过的事实。

    只给不可自动验收的产物用（内置版式 xlsx / 客户模板 Word）；能跑自动验收的走「一键验收」，
    两种结论不能并存。依据必填、追加写不改历史；登记不改变交付状态、不关闭缺口、不写检查记录。
    """

    PermissionService(db, principal).require_project_permission(project_id, "project.view")
    body = payload or {}
    try:
        row = record_attestation(
            db,
            project_id=project_id,
            requirement_id=requirement_id,
            artifact_id=artifact_id,
            conclusion=body.get("conclusion"),
            basis=body.get("basis"),
            actor_id=principal.user_id,
        )
    except AttestationError as failure:
        status = 404 if failure.code == "artifact_not_found" else 422
        raise HTTPException(status, f"{failure.message}（{failure.code}）") from failure
    project = db.get(Project, project_id)
    record_audit(db, action="record_artifact_attestation", resource_type="requirement_render_artifact",
                 resource_id=artifact_id, actor_user_id=principal.user_id,
                 institution_id=project.institution_id if project else None, project_id=project_id,
                 after={"conclusion": row.conclusion, "scope_code": row.scope_code,
                        "basis_chars": len(row.basis)})
    db.commit()
    db.refresh(row)
    attested_user = db.get(User, row.attested_by) if row.attested_by else None
    return {
        "attestation_version": ATTESTATION_VERSION,
        "attestation": serialize_attestation(row, {attested_user.id: attested_user} if attested_user else None),
        "note": "人工核对登记只说明有人看过并写明依据：不改变交付状态、不关闭缺口，也不替代机器检查。",
    }


@router.get("/projects/{project_id}/requirements/{requirement_id}/render-artifacts/{artifact_id}/attestations")
def requirement_render_artifact_attestations(project_id: int, requirement_id: int, artifact_id: int,
                                             principal: CurrentPrincipal,
                                             db: Session = Depends(get_db)) -> dict[str, Any]:
    """这份产物的人工核对记录（最新在前）。没有记录就返回空数组，不编占位。"""

    PermissionService(db, principal).require_project_permission(project_id, "project.view")
    rows = attestations_for_project(db, project_id, per_artifact=50).get(artifact_id, [])
    actor_ids = {row.attested_by for row in rows if row.attested_by}
    users = {user.id: user for user in db.scalars(select(User).where(User.id.in_(actor_ids)))} if actor_ids else {}
    return {
        "attestation_version": ATTESTATION_VERSION,
        "artifact_id": artifact_id,
        "items": [serialize_attestation(row, users) for row in rows],
    }


@router.get("/projects/{project_id}/export-stability")
def check_export_stability(project_id: int, principal: CurrentPrincipal,
                           db: Session = Depends(get_db),
                           limit: int = Query(20, ge=1, le=50),
                           requirement_id: int | None = Query(None, ge=1)):
    """交付稳定性核对：把已登记产物按同一冻结内容重放，比字节（只读）。"""

    PermissionService(db, principal).require_project_permission(project_id, "project.view")
    try:
        payload = build_stability(db, project_id, requirement_id=requirement_id, limit=limit)
    except StabilityError as failure:
        raise HTTPException(422, detail={"code": failure.code, "message": failure.message}) from failure
    return payload


@router.get("/projects/{project_id}/replay-manifest")
def requirement_replay_manifest(project_id: int, principal: CurrentPrincipal,
                                db: Session = Depends(get_db),
                                state: str | None = Query(None),
                                renderer: str | None = Query(None),
                                requirement_id: int | None = Query(None, ge=1),
                                keyword: str | None = Query(None, max_length=100),
                                limit: int = Query(100, ge=0, le=500)):
    """交付复核清单：按状态/渲染器/需求/关键字列出产物能不能用当前代码复核（只读）。"""

    PermissionService(db, principal).require_project_permission(project_id, "project.view")
    try:
        return build_replay_manifest(
            db,
            project_id,
            state=state,
            renderer=renderer,
            requirement_id=requirement_id,
            keyword=keyword,
            limit=limit,
        )
    except ValueError as failure:
        raise HTTPException(422, detail={"code": "manifest_filter_invalid", "message": str(failure)}) from failure


@router.post("/projects/{project_id}/requirements-acceptance/batch")
def requirement_acceptance_batch(
    project_id: int,
    payload: dict[str, Any] = Body(default=None),
    db: Session = Depends(get_db),
    principal: CurrentPrincipal = None,
) -> dict[str, Any]:
    """批量验收：把还没有检查记录的产物一次跑完，每个产物各写一条检查记录。

    默认只跑未检查过的产物（已查过的不重复刷记录）；单个失败不中断整批，原因逐条返回。
    """

    PermissionService(db, principal).require_project_permission(project_id, "project.view")
    body = payload or {}
    only_unchecked = body.get("only_unchecked", True)
    if not isinstance(only_unchecked, bool):
        raise HTTPException(status_code=422, detail="only_unchecked 必须是布尔值")
    limit = body.get("limit", 10)
    if not _positive_int(limit):
        raise HTTPException(status_code=422, detail="limit 必须是正整数")
    result = run_acceptance_batch(
        db,
        project_id=project_id,
        only_unchecked=only_unchecked,
        limit=limit,
        actor_id=principal.user_id,
    )
    project = db.get(Project, project_id)
    record_audit(db, action="run_delivery_acceptance_batch", resource_type="project",
                 resource_id=project_id, actor_user_id=principal.user_id,
                 institution_id=project.institution_id if project else None, project_id=project_id,
                 after={"attempted": result["summary"]["attempted"],
                        "passed": result["summary"]["passed"],
                        "failed": result["summary"]["failed"],
                        "errored": result["summary"]["errored"],
                        "unchecked_after": result["summary"]["unchecked_after"]})
    db.commit()
    return result


@router.post("/projects/{project_id}/requirements/{requirement_id}/template-exports/check")
def check_customer_template(project_id: int, requirement_id: int,
                            principal: CurrentPrincipal, db: Session = Depends(get_db),
                            template: UploadFile | None = File(None), format: str = Form("docx"),
                            config: str | None = Form(None),
                            delivery_id: int | None = Form(None),
                            snapshot_id: int | None = Form(None),
                            template_id: int | None = Form(None, ge=1)):
    """只渲染不返回文件：用于客户模板首次适配，核对锚点/映射与诊断信息。"""

    record = _render_customer_template(
        db, project_id, requirement_id, template=template, format=format, config=config,
        delivery_id=delivery_id, snapshot_id=snapshot_id, principal=principal,
        audit_action="check_requirement_template_export", template_id=template_id)
    # 预渲染同样是产物：落库后下载才能复用同一文件，而不是再渲一遍。
    db.commit()
    return {"artifact_id": record.id, "format": record.format, "file_name": record.file_name,
            "file_size": record.file_size, "file_sha256": record.file_sha256,
            "template_sha256": record.template_sha256,
            "renderer_version": record.renderer_version,
            "config_version": record.config_version,
            "warnings": list(record.warnings_json or []),
            "diagnostics": dict(record.diagnostics_json or {})}


@router.post("/projects/{project_id}/requirements/{requirement_id}/template-exports")
def export_with_customer_template(project_id: int, requirement_id: int,
                                  principal: CurrentPrincipal, db: Session = Depends(get_db),
                                  template: UploadFile | None = File(None), format: str = Form("docx"),
                                  config: str | None = Form(None),
                                  delivery_id: int | None = Form(None),
                                  snapshot_id: int | None = Form(None),
                                  template_id: int | None = Form(None, ge=1)):
    """按客户 DOCX/XLSX 模板渲染冻结内容并直接下载（同一身份复用已存文件）。"""

    record = _render_customer_template(
        db, project_id, requirement_id, template=template, format=format, config=config,
        delivery_id=delivery_id, snapshot_id=snapshot_id, principal=principal,
        audit_action="export_requirement_template", template_id=template_id)
    payload = _stored_artifact_bytes(record)
    headers = _artifact_headers(record)
    media_type = record.media_type
    # 产物记录必须落库：get_db 不自动提交，缺这一步会让"同一身份只渲一次"永远失效。
    db.commit()
    return Response(payload, media_type=media_type, headers=headers)

@router.post("/projects/{project_id}/requirements/{requirement_id}/runtime-fact-packs", status_code=201)
def import_runtime_fact_pack(project_id: int, requirement_id: int, payload: dict[str, Any],
                             principal: CurrentPrincipal, db: Session = Depends(get_db)):
    """导入授权环境产出的脱敏运行事实包（P2-A）。

    平台不执行客户跑批；这里只接收事实并冻结导入时的校验结论。同一份内容重复导入
    返回原记录（``created=False``），不会刷新历史结论。导入成功**不代表**业务结论
    已验证——``gaps`` 里仍然列出"运行事实未验证"的待确认事项。
    """

    from app.services.requirement_runtime_fact_store import (
        FactPackError,
        MAX_PACK_BYTES,
        gaps_for,
        serialize,
        store_fact_pack,
    )

    permissions = PermissionService(db, principal)
    project = permissions.require_project_permission(project_id, "technical.edit")
    requirement = load_requirement(db, project_id, requirement_id)
    raw = json.dumps(payload, ensure_ascii=False)
    if len(raw.encode("utf-8")) > MAX_PACK_BYTES:
        raise HTTPException(413, f"事实包超过 {MAX_PACK_BYTES // 1024} KB 上限，请只上传脱敏统计结果")
    try:
        row, created = store_fact_pack(
            db, project_id=project_id, requirement_id=requirement.id,
            pack=payload, created_by=principal.user_id,
        )
    except FactPackError as exc:
        raise HTTPException(422, exc.message) from exc
    if created:
        record_audit(db, action="import_requirement_runtime_fact_pack", resource_type="requirement",
            resource_id=requirement_id, actor_user_id=principal.user_id,
            institution_id=project.institution_id, project_id=project_id,
            after={"pack_id": row.id, "pack_sha256": row.pack_sha256, "level": row.level,
                   "status": row.status, "execution_batch": row.execution_batch,
                   "business_date": row.business_date})
    db.commit()
    return {"created": created, "pack": serialize(row), "gaps": gaps_for(row)}


@router.get("/projects/{project_id}/requirements/{requirement_id}/runtime-fact-packs")
def list_runtime_fact_packs(project_id: int, requirement_id: int, principal: CurrentPrincipal,
                            db: Session = Depends(get_db)):
    from app.services.requirement_runtime_fact_store import gaps_for, list_fact_packs, serialize

    PermissionService(db, principal).require_project_permission(project_id, "project.view")
    requirement = load_requirement(db, project_id, requirement_id)
    rows = list_fact_packs(db, project_id=project_id, requirement_id=requirement.id)
    items = []
    for row in rows:
        item = serialize(row)
        item["gaps"] = gaps_for(row)
        items.append(item)
    return {"requirement_id": requirement.id, "count": len(items), "items": items}
