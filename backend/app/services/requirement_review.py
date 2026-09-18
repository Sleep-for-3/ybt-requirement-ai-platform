"""Governed review and immutable formal delivery for requirement revisions."""

from copy import deepcopy
from datetime import UTC, datetime
import hashlib

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Project,
    Requirement,
    RequirementFormalDelivery,
    RequirementReviewSubmission,
    RequirementRevision,
    ReviewDecision,
    ReviewTask,
    StoredFile,
    User,
    WorkflowInstance,
)
from app.services.requirement_gaps import field_gaps
from app.services.requirement_revisions import load_revision, lock_requirement
from app.services.requirement_scope import content_digest, export_document
from app.services.storage import get_storage_service


def _submission_hash(
    project_id: int,
    requirement_id: int,
    revision: RequirementRevision,
    submitted_by: int,
) -> str:
    value = (
        f"{project_id}:{requirement_id}:{revision.id}:{revision.content_version}:"
        f"{revision.content_hash}:{submitted_by}"
    )
    return hashlib.sha256(value.encode()).hexdigest()


def _unresolved(content: dict) -> list[dict]:
    issues: dict[str, dict] = {}
    resolved = {"resolved", "closed"}
    for gap in content.get("gaps", []):
        if gap.get("status") not in resolved or not gap.get("resolution_basis"):
            issues[str(gap.get("id") or len(issues))] = {
                "code": str(gap.get("id") or "recorded_gap"),
                "field_id": gap.get("field_id"),
                "message": str(gap.get("message") or "存在未解决缺口"),
            }
    for record in content.get("fields", []):
        for gap in field_gaps(record):
            issues.setdefault(gap["id"], {
                "code": gap["id"],
                "field_id": gap.get("field_id"),
                "message": gap["message"],
            })
    from app.services.requirement_policy_comparison import comparison_issues
    for issue in comparison_issues(content):
        issues.setdefault(issue["code"], issue)
    from app.services.requirement_paths import path_issues
    for issue in path_issues(content):
        issues.setdefault(issue["code"], issue)
    graph = content.get("lineage_graph")
    if not content.get("script_basis") and (not graph or not graph.get("edges")):
        issues.setdefault("scope:lineage_graph", {
            "code": "scope:lineage_graph",
            "field_id": None,
            "message": "缺少本需求版本已固定的字段血缘关系",
        })
    return list(issues.values())


def review_readiness(
    db: Session,
    project_id: int,
    requirement_id: int,
    content_version: int,
) -> dict:
    requirement = lock_requirement(db, project_id, requirement_id)
    revision = load_revision(db, project_id, requirement_id, content_version)
    reasons = _unresolved(revision.content_json)
    from app.services.requirement_script_basis import script_basis_changes
    reasons.extend({**change, "field_id": None} for change in script_basis_changes(db, project_id, revision.content_json))
    if requirement.content_version != content_version:
        reasons.insert(0, {
            "code": "stale_revision",
            "field_id": None,
            "message": "该内容版本已不是当前需求版本",
        })
    if requirement.version != revision.scope_version:
        reasons.insert(0, {
            "code": "stale_scope",
            "field_id": None,
            "message": "需求范围已变化，需先建立对应内容修订",
        })
    if not revision.content_json.get("fields"):
        reasons.insert(0, {
            "code": "empty_scope",
            "field_id": None,
            "message": "当前需求没有可审核字段",
        })
    unique = list({(item["code"], item.get("field_id")): item for item in reasons}.values())
    return {
        "eligible": not unique,
        "content_version": revision.content_version,
        "content_hash": revision.content_hash,
        "revision_status": revision.status,
        "blocking_count": len(unique),
        "reasons": unique,
    }


def load_submission(
    db: Session,
    project_id: int,
    requirement_id: int,
    submission_id: int,
) -> RequirementReviewSubmission:
    row = db.scalar(select(RequirementReviewSubmission).where(
        RequirementReviewSubmission.id == submission_id,
        RequirementReviewSubmission.project_id == project_id,
        RequirementReviewSubmission.requirement_id == requirement_id,
    ))
    if row is None:
        raise HTTPException(404, "送审记录不存在或不可见")
    revision = load_revision(db, project_id, requirement_id, row.content_version)
    expected = _submission_hash(project_id, requirement_id, revision, row.submitted_by)
    if (
        revision.id != row.revision_id
        or revision.content_hash != row.content_hash
        or expected != row.submission_hash
    ):
        raise HTTPException(409, "送审记录完整性检查失败")
    return row


def submission_summary(db: Session, row: RequirementReviewSubmission) -> dict:
    workflow = db.scalar(select(WorkflowInstance).where(
        WorkflowInstance.project_id == row.project_id,
        WorkflowInstance.workflow_key == "requirement_document_review",
        WorkflowInstance.target_type == "requirement_review_submission",
        WorkflowInstance.target_id == row.id,
    ).order_by(WorkflowInstance.id.desc()))
    tasks = []
    if workflow is not None:
        tasks = [{
            "id": task.id,
            "step_key": task.step_key,
            "status": task.status,
            "assignee_role": task.assignee_role,
            "assignee_user_id": task.assignee_user_id,
        } for task in db.scalars(select(ReviewTask).where(
            ReviewTask.workflow_instance_id == workflow.id,
        ).order_by(ReviewTask.id))]
    return {
        "id": row.id,
        "content_version": row.content_version,
        "content_hash": row.content_hash,
        "status": row.status,
        "submitted_by": row.submitted_by,
        "submitted_at": row.submitted_at,
        "reviewed_by": row.reviewed_by,
        "reviewed_at": row.reviewed_at,
        "workflow": None if workflow is None else {
            "id": workflow.id,
            "status": workflow.status,
            "current_step": workflow.current_step,
        },
        "tasks": tasks,
    }


def submit_for_review(
    db: Session,
    *,
    project_id: int,
    requirement_id: int,
    content_version: int,
    content_hash: str,
    submitted_by: int,
    assignments: dict[str, int] | None = None,
) -> tuple[RequirementReviewSubmission, bool]:
    requirement = lock_requirement(db, project_id, requirement_id)
    revision = load_revision(db, project_id, requirement_id, content_version)
    if requirement.content_version != content_version or revision.content_hash != content_hash:
        raise HTTPException(409, "需求内容已变化，请重新加载后送审")
    existing = db.scalar(select(RequirementReviewSubmission).where(
        RequirementReviewSubmission.revision_id == revision.id,
    ))
    if existing is not None:
        return load_submission(db, project_id, requirement_id, existing.id), False
    if revision.status != "draft":
        raise HTTPException(409, "仅草稿内容可提交审核")
    readiness = review_readiness(db, project_id, requirement_id, content_version)
    if not readiness["eligible"]:
        raise HTTPException(409, f"存在 {readiness['blocking_count']} 项阻断条件，请先处理后再送审")
    now = datetime.now(UTC)
    row = RequirementReviewSubmission(
        project_id=project_id,
        requirement_id=requirement_id,
        revision_id=revision.id,
        content_version=revision.content_version,
        content_hash=revision.content_hash,
        submission_hash=_submission_hash(project_id, requirement_id, revision, submitted_by),
        status="pending_review",
        submitted_by=submitted_by,
        submitted_at=now,
    )
    db.add(row)
    revision.status = "in_review"
    db.flush()
    from app.services.governance.workflow import start_workflow

    start_workflow(
        db,
        project_id=project_id,
        workflow_key="requirement_document_review",
        target_type="requirement_review_submission",
        target_id=row.id,
        created_by=submitted_by,
        assignments=assignments,
    )
    db.refresh(row)
    return row, True


def _content_authors(revision: RequirementRevision, step_key: str) -> set[int]:
    ownership = revision.content_json.get("manual_ownership", {})
    prefixes = {
        "business_review": ("business.",),
        "technical_review": ("lineage.",),
        "final_review": ("business.", "lineage."),
    }.get(step_key, ())
    authors: set[int] = set()
    for field_ownership in ownership.values():
        for path, owner in field_ownership.items():
            if prefixes and not path.startswith(prefixes):
                continue
            actor_id = owner.get("actor_id") if isinstance(owner, dict) else None
            if isinstance(actor_id, int):
                authors.add(actor_id)
    if step_key == "final_review" or not authors:
        if revision.created_by is not None:
            authors.add(revision.created_by)
    return authors


def validate_review_decision(
    db: Session,
    submission_id: int,
    step_key: str,
    actor_id: int,
    decision: str,
) -> RequirementReviewSubmission:
    row = db.get(RequirementReviewSubmission, submission_id)
    if row is None:
        raise HTTPException(404, "需求送审记录不存在")
    row = load_submission(db, row.project_id, row.requirement_id, row.id)
    revision = load_revision(db, row.project_id, row.requirement_id, row.content_version)
    if row.status != "pending_review" or revision.status != "in_review":
        raise HTTPException(409, "需求内容已不处于审核中")
    if decision == "approved":
        readiness = review_readiness(db, row.project_id, row.requirement_id, row.content_version)
        if not readiness["eligible"]:
            raise HTTPException(409, "审核内容已失效或仍有阻断缺口")
        authors = _content_authors(revision, step_key)
        if actor_id in authors or (step_key == "final_review" and actor_id == row.submitted_by):
            raise HTTPException(409, "内容维护人或送审人不能审核自己负责的内容")
    return row


def complete_review(
    db: Session,
    submission_id: int,
    actor_id: int,
) -> None:
    row = db.get(RequirementReviewSubmission, submission_id)
    if row is None:
        raise HTTPException(404, "需求送审记录不存在")
    revision = load_revision(db, row.project_id, row.requirement_id, row.content_version)
    row.status = "approved"
    row.reviewed_by = actor_id
    row.reviewed_at = datetime.now(UTC)
    revision.status = "confirmed"


def return_review(db: Session, submission_id: int, decision: str) -> None:
    row = db.get(RequirementReviewSubmission, submission_id)
    if row is None:
        raise HTTPException(404, "需求送审记录不存在")
    revision = load_revision(db, row.project_id, row.requirement_id, row.content_version)
    row.status = "returned" if decision == "returned" else "rejected"
    revision.status = "rejected"


def _review_record(db: Session, workflow_id: int) -> list[dict]:
    rows = db.execute(select(ReviewDecision, ReviewTask.step_key, User.username)
        .join(ReviewTask, ReviewTask.id == ReviewDecision.review_task_id)
        .join(User, User.id == ReviewDecision.decided_by)
        .where(ReviewTask.workflow_instance_id == workflow_id)
        .order_by(ReviewDecision.id)).all()
    return [{
        "step": step,
        "decision": decision.decision,
        "comment": decision.comment,
        "reviewer": username,
        "decided_at": decision.decided_at.isoformat(),
    } for decision, step, username in rows]


def finalize_formal_delivery(
    db: Session,
    *,
    project_id: int,
    requirement_id: int,
    submission_id: int,
) -> tuple[RequirementFormalDelivery, bool]:
    requirement = lock_requirement(db, project_id, requirement_id)
    submission = load_submission(db, project_id, requirement_id, submission_id)
    existing = db.scalar(select(RequirementFormalDelivery).where(
        RequirementFormalDelivery.review_submission_id == submission.id,
    ))
    if existing is not None:
        return load_formal_delivery(db, project_id, requirement_id, existing.id), False
    workflow = db.scalar(select(WorkflowInstance).where(
        WorkflowInstance.project_id == project_id,
        WorkflowInstance.workflow_key == "requirement_document_review",
        WorkflowInstance.target_type == "requirement_review_submission",
        WorkflowInstance.target_id == submission.id,
    ).order_by(WorkflowInstance.id.desc()))
    if workflow is None or workflow.status != "approved" or submission.status != "approved":
        raise HTTPException(409, "需求审核尚未通过，不能形成正式交付")
    revision = load_revision(db, project_id, requirement_id, submission.content_version)
    if revision.status != "confirmed" or revision.content_hash != submission.content_hash:
        raise HTTPException(409, "已审核内容状态或哈希不一致")
    from app.services.requirement_script_basis import script_basis_changes
    from app.services.requirement_policy_comparison import comparison_issues
    from app.services.requirement_paths import path_issues
    if (script_basis_changes(db, project_id, revision.content_json) or comparison_issues(revision.content_json)
            or path_issues(revision.content_json)):
        raise HTTPException(409, "脚本需求依据已变化，须复核并建立新修订后交付")
    version_no = (db.scalar(select(func.max(RequirementFormalDelivery.version_no)).where(
        RequirementFormalDelivery.requirement_id == requirement.id,
    )) or 0) + 1
    approved_at = submission.reviewed_at or workflow.completed_at or datetime.now(UTC)
    snapshot = deepcopy(jsonable_encoder(revision.content_json))
    snapshot["formal_delivery"] = {
        "version_no": version_no,
        "content_version": revision.content_version,
        "content_hash": revision.content_hash,
        "workflow_instance_id": workflow.id,
        "review_submission_id": submission.id,
        "approved_by": submission.reviewed_by,
        "approved_at": approved_at.isoformat(),
        "review_record": _review_record(db, workflow.id),
    }
    snapshot_hash = content_digest(snapshot)
    file_name = f"requirement-{requirement.id}-formal-v{version_no}.xlsx"
    content = export_document(snapshot)
    saved = get_storage_service().save(content, file_name=file_name, project_id=project_id)
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "项目不存在或不可见")
    stored = db.scalar(select(StoredFile).where(StoredFile.storage_key == saved.storage_key))
    if stored is None:
        stored = StoredFile(
            institution_id=project.institution_id or 0,
            project_id=project_id,
            storage_key=saved.storage_key,
            original_file_name=file_name,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            byte_size=saved.byte_size,
            content_hash=saved.content_hash,
            classification=project.confidentiality_level,
            created_by=submission.reviewed_by or submission.submitted_by,
            enabled=True,
        )
        db.add(stored)
        db.flush()
    row = RequirementFormalDelivery(
        project_id=project_id,
        requirement_id=requirement_id,
        revision_id=revision.id,
        review_submission_id=submission.id,
        workflow_instance_id=workflow.id,
        version_no=version_no,
        content_version=revision.content_version,
        content_hash=revision.content_hash,
        snapshot_hash=snapshot_hash,
        stored_file_id=stored.id,
        file_hash=saved.content_hash,
        content_json=snapshot,
        approved_by=submission.reviewed_by or submission.submitted_by,
        approved_at=approved_at,
        created_at=datetime.now(UTC),
    )
    db.add(row)
    db.flush()
    return row, True


def load_formal_delivery(
    db: Session,
    project_id: int,
    requirement_id: int,
    delivery_id: int,
) -> RequirementFormalDelivery:
    row = db.scalar(select(RequirementFormalDelivery).where(
        RequirementFormalDelivery.id == delivery_id,
        RequirementFormalDelivery.project_id == project_id,
        RequirementFormalDelivery.requirement_id == requirement_id,
    ))
    if row is None:
        raise HTTPException(404, "正式交付版本不存在或不可见")
    if content_digest(row.content_json) != row.snapshot_hash:
        raise HTTPException(409, "正式交付快照完整性检查失败")
    base = deepcopy(row.content_json)
    base.pop("formal_delivery", None)
    if content_digest(base) != row.content_hash:
        raise HTTPException(409, "正式交付内容哈希不一致")
    stored = db.get(StoredFile, row.stored_file_id)
    if stored is None or stored.project_id != project_id or not stored.enabled:
        raise HTTPException(409, "正式交付文件不可用")
    content = get_storage_service().read(stored.storage_key)
    if hashlib.sha256(content).hexdigest() != row.file_hash or stored.content_hash != row.file_hash:
        raise HTTPException(409, "正式交付文件完整性检查失败")
    return row


def formal_summary(row: RequirementFormalDelivery) -> dict:
    return {
        "id": row.id,
        "version_no": row.version_no,
        "content_version": row.content_version,
        "content_hash": row.content_hash,
        "file_hash": row.file_hash,
        "approved_by": row.approved_by,
        "approved_at": row.approved_at,
        "created_at": row.created_at,
        "status": "formal",
    }


def formal_file(db: Session, row: RequirementFormalDelivery) -> bytes:
    checked = load_formal_delivery(db, row.project_id, row.requirement_id, row.id)
    stored = db.get(StoredFile, checked.stored_file_id)
    return get_storage_service().read(stored.storage_key)
