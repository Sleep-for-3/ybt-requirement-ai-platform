"""Skill control-plane endpoints. All access requires a real authenticated user."""
from typing import Literal

from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import AISkillDefinition, AISkillVersion, AISkillTestCase, AISkillTestRun, AISkillTestResult, AISkillScopeBinding, ModelProfile
from app.schemas.ai_skill import SkillScope
from app.schemas.ai_skill_ranking import FieldCandidateQuery, FieldRankProposal, FieldCandidatePrepare, FieldRerankRequest
from app.schemas.ai_skill_control import (SkillContent, SkillDefinitionCreate, SkillDiffRequest, SkillVersionAction,
    SkillVersionCreate, SkillVersionEdit, SkillTestCaseCreate, SkillTestRunCreate, SkillPublishRequest, SkillBindingRequest, SkillHumanReview)
from app.services.ai_skills import control, evaluation, releases
from app.services.auth.dependencies import RealPrincipal

router = APIRouter(prefix="/ai-skills", tags=["AI Skills"])
runs_router = APIRouter(prefix="/ai-skill-test-runs", tags=["AI Skill tests"])


def requested_scope(scope_type: Literal["platform", "institution", "project", "task"] = "platform",
                    institution_id: int | None = Query(None, gt=0), project_id: int | None = Query(None, gt=0),
                    invocation_key: str | None = None) -> SkillScope:
    try:
        return SkillScope(scope_type=scope_type, institution_id=institution_id,
                          project_id=project_id, invocation_key=invocation_key)
    except ValidationError:
        control.fail(422, "invalid_scope")


def version_response(item):
    return {"id": item.id, "definition_id": item.definition_id, "version_no": item.version_no,
            "status": item.status, "lock_version": item.lock_version,
            "scope": control.version_scope(item).model_dump(), "content": item.content_json,
            "created_by": item.created_by, "edited_by": item.edited_by,
            "content_hash": item.content_hash, "restored_from_version_id": item.restored_from_version_id}


def definition_response(item):
    return {"skill_key": item.skill_key, "task_key": item.task_key,
            "display_name": item.display_name, "description": item.description}


@router.get("")
def list_skills(principal: RealPrincipal, scope: SkillScope = Depends(requested_scope), db: Session = Depends(get_db)):
    control.authorize_scope(db, principal, scope)
    return [definition_response(item) for item in db.scalars(select(AISkillDefinition).order_by(AISkillDefinition.skill_key)).all()]


@router.post("", status_code=201)
def create_skill(payload: SkillDefinitionCreate, principal: RealPrincipal, db: Session = Depends(get_db)):
    item = control.create_definition(db, principal, payload)
    db.commit()
    return definition_response(item)


@router.get("/resolve")
def resolve(skill_key: str, principal: RealPrincipal, scope: SkillScope = Depends(requested_scope), db: Session = Depends(get_db)):
    from app.services.ai_skills.runtime import resolve_skill
    resolved = resolve_skill(db, principal, skill_key, scope)
    if resolved is None:
        return {"runtime_mode": "legacy", "skill_version_id": None}
    definition, version, binding = resolved
    return {"runtime_mode": "skill", "skill_key": definition.skill_key, "skill_version_id": version.id,
            "skill_version_no": version.version_no, "scope": binding.scope_key, "content_hash": version.content_hash}


@router.get("/capabilities")
def capabilities(principal: RealPrincipal, scope: SkillScope = Depends(requested_scope), db: Session = Depends(get_db)):
    control.authorize_scope(db, principal, scope)
    def allowed(target, **options):
        try:
            control.authorize_scope(db, principal, target, **options)
            return True
        except HTTPException as exc:
            if exc.status_code not in {403, 404, 409}:
                raise
            return False
    return {"actor_id": principal.user_id,
            "can_register": allowed(SkillScope(scope_type="platform"), write=True),
            "can_edit": allowed(scope, write=True),
            "can_publish": allowed(scope, write=True, publish=True)}


@router.get("/model-options")
def model_options(principal: RealPrincipal, scope: SkillScope = Depends(requested_scope), db: Session = Depends(get_db)):
    control.authorize_scope(db, principal, scope)
    return [{"id": item.id, "name": item.profile_name, "provider_type": item.provider_type, "model_name": item.model_name}
            for item in db.scalars(select(ModelProfile).where(ModelProfile.enabled.is_(True)).order_by(ModelProfile.id))]


@router.post("/field-candidates")
def field_candidates(payload: FieldCandidateQuery, principal: RealPrincipal, db: Session = Depends(get_db)):
    from app.services.ai_skills.field_candidates import recall_fields
    return recall_fields(db, principal, payload)


@router.post("/field-candidates/validate-ranking")
def validate_field_ranking(payload: FieldRankProposal, principal: RealPrincipal, db: Session = Depends(get_db)):
    from app.services.ai_skills.field_candidates import validate_rank_proposal
    return validate_rank_proposal(db, principal, payload)


@router.post("/field-candidates/model-rerank")
async def model_rerank_field_candidates(payload: FieldRerankRequest, principal: RealPrincipal, db: Session = Depends(get_db)):
    """Explicit user action only; never selects, probes, adopts or writes a mapping."""

    from app.services.ai_skills.field_rerank import rerank_fields
    result = await rerank_fields(db, principal, payload)
    db.commit()
    return result


@router.post("/field-candidates/prepare")
def prepare_field_candidate(payload: FieldCandidatePrepare, principal: RealPrincipal, db: Session = Depends(get_db)):
    from app.services.ai_skills.candidate_preparation import prepare_candidate
    from app.schemas.api import CandidateSourceRecommendationRead
    item = prepare_candidate(db, principal, payload)
    db.commit(); db.refresh(item)
    return {"recommendation": CandidateSourceRecommendationRead.model_validate(item), "writes_mapping": False}


@router.get("/{skill_key}")
def skill_detail(skill_key: str, principal: RealPrincipal, scope: SkillScope = Depends(requested_scope), db: Session = Depends(get_db)):
    control.authorize_scope(db, principal, scope)
    return definition_response(control.definition_for(db, skill_key))


@router.get("/{skill_key}/versions")
def versions(skill_key: str, principal: RealPrincipal, scope: SkillScope = Depends(requested_scope), db: Session = Depends(get_db)):
    control.authorize_scope(db, principal, scope)
    definition = control.definition_for(db, skill_key)
    items = db.scalars(select(AISkillVersion).where(AISkillVersion.definition_id == definition.id,
                       AISkillVersion.scope_key == control.scope_key(scope)).order_by(AISkillVersion.version_no.desc())).all()
    return [version_response(item) for item in items]


@router.post("/{skill_key}/versions", status_code=201)
def create_version(skill_key: str, payload: SkillVersionCreate, principal: RealPrincipal, db: Session = Depends(get_db)):
    item = control.create_version(db, principal, skill_key, payload)
    db.commit()
    return version_response(item)


@router.get("/{skill_key}/versions/{version}")
def get_version(skill_key: str, version: int, principal: RealPrincipal, db: Session = Depends(get_db)):
    return version_response(control.version_for(db, principal, skill_key, version))


@router.patch("/{skill_key}/versions/{version}")
def edit_version(skill_key: str, version: int, payload: SkillVersionEdit, principal: RealPrincipal, db: Session = Depends(get_db)):
    item = control.edit_version(db, principal, skill_key, version, payload)
    db.commit()
    return version_response(item)


@router.post("/{skill_key}/versions/{version}/validate")
def validate_version(skill_key: str, version: int, principal: RealPrincipal, test_project_id: int | None = Query(None, gt=0), db: Session = Depends(get_db)):
    item = control.version_for(db, principal, skill_key, version)
    control.validate_content(db, SkillContent.model_validate(item.content_json))
    evidence = []
    gate = "test_project_required"
    if test_project_id is not None:
        scope = evaluation.test_scope(db, principal, test_project_id)
        if item.scope_type == "task":
            scope = scope.model_copy(update={"scope_type": "task", "invocation_key": item.invocation_key})
        if not evaluation.compatible_owner(item, scope):
            control.fail(404, "resource_not_found")
        try:
            evidence = evaluation.release_evidence(db, item, test_project_id)
            gate = "tests_passed"
        except HTTPException as exc:
            if exc.status_code != 409:
                raise
            gate = exc.detail["error_code"]
    return {"valid": True, "content_hash": item.content_hash, "release_ready": bool(evidence) and item.status == "pending_approval",
            "gate": gate, "test_run_ids": evidence, "independent_approval_required": True}


@router.post("/{skill_key}/versions/{version}/diff")
def diff_version(skill_key: str, version: int, payload: SkillDiffRequest, principal: RealPrincipal, db: Session = Depends(get_db)):
    left = control.version_for(db, principal, skill_key, version)
    right = control.version_for(db, principal, skill_key, payload.other_version)
    keys = sorted(set(left.content_json) | set(right.content_json))
    return {"from_version": version, "to_version": payload.other_version,
            "changes": [{"field": key, "before": left.content_json.get(key), "after": right.content_json.get(key)}
                        for key in keys if left.content_json.get(key) != right.content_json.get(key)]}


@router.post("/{skill_key}/versions/{version}/restore", status_code=201)
def restore_version(skill_key: str, version: int, principal: RealPrincipal, db: Session = Depends(get_db)):
    item = control.restore_version(db, principal, skill_key, version)
    db.commit()
    return version_response(item)


@router.post("/{skill_key}/versions/{version}/submit")
def submit(skill_key: str, version: int, payload: SkillPublishRequest, principal: RealPrincipal, db: Session = Depends(get_db)):
    item = releases.submit(db, principal, skill_key, version, payload)
    db.commit()
    return version_response(item)


@router.post("/{skill_key}/versions/{version}/publish")
def publish(skill_key: str, version: int, payload: SkillPublishRequest, principal: RealPrincipal, db: Session = Depends(get_db)):
    item = releases.publish(db, principal, skill_key, version, payload)
    db.commit()
    return version_response(item)


@router.post("/{skill_key}/versions/{version}/return-to-draft")
def return_to_draft(skill_key: str, version: int, payload: SkillVersionAction, principal: RealPrincipal, db: Session = Depends(get_db)):
    item = releases.reset_draft(db, principal, skill_key, version, payload.expected_lock_version)
    db.commit()
    return version_response(item)


@router.post("/{skill_key}/versions/{version}/deprecate")
def deprecate(skill_key: str, version: int, payload: SkillVersionAction, principal: RealPrincipal, db: Session = Depends(get_db)):
    item = releases.deprecate(db, principal, skill_key, version, payload.expected_lock_version)
    db.commit()
    return version_response(item)


@router.post("/{skill_key}/bindings")
def bind(skill_key: str, payload: SkillBindingRequest, principal: RealPrincipal, db: Session = Depends(get_db)):
    item = releases.adopt(db, principal, skill_key, payload)
    db.commit()
    return {"id": item.id, "version_id": item.version_id, "scope_key": item.scope_key,
            "lock_version": item.lock_version, "inherited_from_scope": item.inherited_from_scope}


@router.get("/{skill_key}/binding-options")
def binding_options(skill_key: str, principal: RealPrincipal, scope: SkillScope = Depends(requested_scope), db: Session = Depends(get_db)):
    """Only compatible published metadata; parent prompts and drafts stay private."""
    control.authorize_scope(db, principal, scope)
    definition = control.definition_for(db, skill_key)
    versions = db.scalars(select(AISkillVersion).where(
        AISkillVersion.definition_id == definition.id, AISkillVersion.status == "published",
        AISkillVersion.published_at.is_not(None),
        (AISkillVersion.institution_id.is_(None)) | (AISkillVersion.institution_id == scope.institution_id),
        (AISkillVersion.project_id.is_(None)) | (AISkillVersion.project_id == scope.project_id),
        (AISkillVersion.invocation_key.is_(None)) | (AISkillVersion.invocation_key == scope.invocation_key),
    ).order_by(AISkillVersion.version_no.desc())).all()
    options = []
    for item in versions:
        if not evaluation.compatible_owner(item, scope):
            continue
        try:
            available = item.release_dependency_hash == evaluation.dependencies(db, item)
        except HTTPException as exc:
            if exc.status_code != 422:
                raise
            available = False
        options.append({"id": item.id, "version_no": item.version_no, "scope_type": item.scope_type,
                        "content_hash": item.content_hash, "available": available})
    return options


@router.get("/{skill_key}/bindings")
def get_binding(skill_key: str, principal: RealPrincipal, scope: SkillScope = Depends(requested_scope), db: Session = Depends(get_db)):
    control.authorize_scope(db, principal, scope)
    definition = control.definition_for(db, skill_key)
    item = db.scalar(select(AISkillScopeBinding).where(AISkillScopeBinding.definition_id == definition.id,
                     AISkillScopeBinding.scope_key == control.scope_key(scope)))
    return None if item is None else {"version_id": item.version_id, "lock_version": item.lock_version}


@router.post("/{skill_key}/test-cases", status_code=201)
def create_case(skill_key: str, payload: SkillTestCaseCreate, principal: RealPrincipal, db: Session = Depends(get_db)):
    item = evaluation.create_case(db, principal, skill_key, payload)
    db.commit()
    return {"id": item.id, "name": item.name, "content_hash": item.content_hash}


@router.get("/{skill_key}/test-cases")
def list_cases(skill_key: str, project_id: int, principal: RealPrincipal, db: Session = Depends(get_db)):
    evaluation.test_scope(db, principal, project_id)
    definition = control.definition_for(db, skill_key)
    return [{"id": case.id, "name": case.name, "content_hash": case.content_hash} for case in evaluation.cases_for(db, definition.id, project_id)]


@router.post("/{skill_key}/feedback/{feedback_id}/test-case")
def feedback_case(skill_key: str, feedback_id: int, payload: SkillTestCaseCreate, principal: RealPrincipal, db: Session = Depends(get_db)):
    item = evaluation.feedback_case(db, principal, skill_key, feedback_id, payload)
    db.commit()
    return {"id": item.id, "source_feedback_id": item.source_feedback_id, "content_hash": item.content_hash}


def run_response(run):
    return {"id": run.id, "version_id": run.version_id, "project_id": run.project_id, "mode": run.mode,
            "created_by": run.created_by,
            "status": run.status, "metrics": run.metrics_json, "content_hash": run.content_hash,
            "dependency_hash": run.dependency_hash, "case_snapshot": run.case_snapshot_json}


@router.post("/{skill_key}/test-runs", status_code=201)
async def run_tests(skill_key: str, payload: SkillTestRunCreate, principal: RealPrincipal, db: Session = Depends(get_db)):
    run = await evaluation.run_tests(db, principal, skill_key, payload)
    db.commit()
    return run_response(run)


@router.get("/{skill_key}/test-runs")
def list_runs(skill_key: str, project_id: int, principal: RealPrincipal, db: Session = Depends(get_db)):
    evaluation.test_scope(db, principal, project_id)
    definition = control.definition_for(db, skill_key)
    return [run_response(run) for run in db.scalars(select(AISkillTestRun).join(AISkillVersion)
        .where(AISkillVersion.definition_id == definition.id, AISkillTestRun.project_id == project_id)
        .order_by(AISkillTestRun.id.desc()).limit(50))]


def authorized_run(db, principal, run_id):
    control.require_user(db, principal)
    run = db.get(AISkillTestRun, run_id)
    if run is None:
        control.fail(404, "resource_not_found")
    evaluation.test_scope(db, principal, run.project_id)
    return run


@runs_router.get("/{run_id}")
def get_run(run_id: int, principal: RealPrincipal, db: Session = Depends(get_db)):
    return run_response(authorized_run(db, principal, run_id))


@runs_router.get("/{run_id}/results")
def results(run_id: int, principal: RealPrincipal, db: Session = Depends(get_db)):
    authorized_run(db, principal, run_id)
    return [{"case_id": item.case_id, "passed": item.passed, "assertions": item.assertions_json,
             "output": item.output_json, "error_code": item.error_code} for item in db.scalars(
                 select(AISkillTestResult).where(AISkillTestResult.run_id == run_id).order_by(AISkillTestResult.id)).all()]


@runs_router.post("/{run_id}/human-review")
def human_review(run_id: int, payload: SkillHumanReview, principal: RealPrincipal, db: Session = Depends(get_db)):
    run = authorized_run(db, principal, run_id)
    scope = evaluation.test_scope(db, principal, run.project_id)
    control.authorize_scope(db, principal, scope, write=True, publish=True)
    if run.mode != "human_review" or run.status != "pending_review" or principal.user_id == run.created_by:
        control.fail(409, "independent_review_required")
    changed = db.execute(update(AISkillTestRun).where(AISkillTestRun.id == run_id,
        AISkillTestRun.status == "pending_review", AISkillTestRun.mode == "human_review").values(
            status="passed" if payload.passed else "failed",
            metrics_json={**run.metrics_json, "reviewer_id": principal.user_id, "review_comment": payload.comment,
                          "passed": run.metrics_json["total"] if payload.passed else 0}))
    if changed.rowcount != 1:
        control.fail(409, "review_conflict")
    db.refresh(run)
    for result in db.scalars(select(AISkillTestResult).where(AISkillTestResult.run_id == run_id)):
        result.passed = payload.passed
    version = db.get(AISkillVersion, run.version_id)
    control.event(db, principal, version.definition_id, version, "human_review_completed",
                  {"run_id": run_id, "passed": payload.passed}, scope=scope)
    db.commit()
    return run_response(run)
