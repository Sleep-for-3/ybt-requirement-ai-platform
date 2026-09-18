"""Editable, versioned requirement scopes; existing review APIs remain authoritative."""
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ConfigDict, Field
from app.core.database import get_db
from app.models import (
    KnowledgeDocument,
    MartTable,
    Requirement,
    RequirementDelivery,
    RequirementFormalDelivery,
    RequirementReviewSubmission,
    RequirementRevision,
    SourceTable,
)
from app.services.requirement_revisions import lock_requirement, load_revision, revision_document, initialize_content, edit_field, refresh_lineage
from app.services.auth.dependencies import CurrentPrincipal, RealPrincipal
from app.services.auth.permission_service import PermissionService
from app.services.governance.audit import record_audit
from app.services.requirement_scope import ScopeInput, validate_scope, requirement_dict, load_requirement, document_content, export_document
from app.services.requirement_scope import content_digest
from app.services.requirement_delivery import freeze_draft, load_frozen_draft, snapshot_summary

router = APIRouter(tags=["requirements"])

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
    return recheck_view(db, row)


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
            "adopted_content_version": item.adopted_content_version} for item in db.scalars(select(RequirementGenerationItem)
                .where(RequirementGenerationItem.input_id == row.id).order_by(RequirementGenerationItem.id))]
        states = [item["status"] for item in items]
        counts = {state: states.count(state) for state in ("pending", "running", "completed", "failed", "blocked")}
        status = "prepared" if not items else "running" if counts["running"] else "pending" if counts["pending"] else "completed" if counts["completed"] == len(items) else "partially_completed" if counts["completed"] else "blocked" if counts["blocked"] == len(items) else "failed"
        summaries.append({**input_summary(row), "status": status, "counts": counts, "total": len(items),
            "stale": row.input_json["content_version"] != requirement.content_version, "items": items})
    return summaries


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
    from app.models import RequirementGenerationInput, BackgroundJob
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
    record_audit(db, "requirement_lineage_refresh", requirement.project_id, principal.user_id,
                 f"需求 {requirement_id} 刷新血缘快照至内容版本 {new_revision.content_version}")
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
    if format == "docx":
        from app.services.requirement_word import export_word
        return Response(export_word(row.content_json),
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": f'attachment; filename="requirement-formal-v{row.version_no}.docx"',
                "X-Requirement-Snapshot-Hash": content_digest(row.content_json)})
    return Response(
        formal_file(db, row),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="requirement-formal-v{row.version_no}.xlsx"',
            "X-Requirement-Snapshot-Hash": content_digest(row.content_json)},
    )


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
    return [snapshot_summary(row) for row in db.scalars(select(RequirementDelivery).where(
        RequirementDelivery.project_id == project_id, RequirementDelivery.requirement_id == requirement_id
    ).order_by(RequirementDelivery.id.desc()).limit(200))]


@router.get("/projects/{project_id}/requirements/{requirement_id}/snapshots/{snapshot_id}/export")
def export_draft_snapshot(project_id: int, requirement_id: int, snapshot_id: int,
                          principal: CurrentPrincipal, db: Session = Depends(get_db), format: Literal["xlsx", "docx"] = "xlsx"):
    PermissionService(db, principal).require_project_permission(project_id, "deliverable.export")
    row = load_frozen_draft(db, project_id, requirement_id, snapshot_id)
    if format == "docx":
        from app.services.requirement_word import export_word
        return Response(export_word(row.content_json),
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": f'attachment; filename="requirement-draft-snapshot-{row.id}.docx"',
                "X-Requirement-Snapshot-Hash": content_digest(row.content_json)})
    return Response(export_document(row.content_json),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="requirement-draft-snapshot-{row.id}.xlsx"',
            "X-Requirement-Snapshot-Hash": content_digest(row.content_json)})


@router.get("/projects/{project_id}/requirements/{requirement_id}/export")
def export_requirement(project_id: int, requirement_id: int, principal: CurrentPrincipal, db: Session = Depends(get_db)):
    PermissionService(db, principal).require_project_permission(project_id, "export")
    content = document_content(db, load_requirement(db, project_id, requirement_id))
    return Response(export_document(content), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="requirement-draft.xlsx"'})
