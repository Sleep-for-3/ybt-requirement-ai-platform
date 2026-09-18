"""Detect current drift without editing historical requirements or deliveries."""
from copy import deepcopy

from fastapi import HTTPException
from sqlalchemy import select

from app.models import Requirement, RequirementRevision, ReviewTask, WorkflowInstance
from app.models.requirement import RequirementRecheck
from app.services.requirement_scope import content_digest
from app.services.requirement_revisions import load_revision, append_revision
from app.services.requirement_script_basis import script_basis_changes


def impact_summary(db, requirement):
    if not requirement.content_version:
        return None
    revision = load_revision(db, requirement.project_id, requirement.id, requirement.content_version)
    changes = script_basis_changes(db, requirement.project_id, revision.content_json)
    if not changes:
        return None
    digest = content_digest(changes)
    row = db.scalar(select(RequirementRecheck).where(RequirementRecheck.revision_id == revision.id,
        RequirementRecheck.change_hash == digest))
    scope = revision.content_json["requirement"]
    return {"requirement_id": requirement.id, "name": requirement.name,
        "content_version": revision.content_version, "content_hash": revision.content_hash,
        "target_table_id": scope["target_table_id"], "scenario_id": scope["scenario_id"],
        "field_ids": scope["field_ids"], "changes": changes, "change_hash": digest,
        "recheck_id": row.id if row else None, "pending_review": True}


def recheck_view(db, row):
    revision = db.get(RequirementRevision, row.revision_id)
    replacement = db.get(RequirementRevision, row.replacement_revision_id) if row.replacement_revision_id else None
    scope = revision.content_json["requirement"]
    tasks = list(db.scalars(select(ReviewTask).where(ReviewTask.project_id == row.project_id,
        ReviewTask.target_type == "requirement_recheck", ReviewTask.target_id == row.id).order_by(ReviewTask.id)))
    return {"id": row.id, "requirement_id": row.requirement_id, "name": scope["name"],
        "content_version": revision.content_version, "target_table_id": scope["target_table_id"],
        "scenario_id": scope["scenario_id"], "field_ids": scope["field_ids"],
        "changes": row.changes_json, "status": row.status, "resolution": row.resolution,
        "replacement_content_version": replacement.content_version if replacement else None,
        "tasks": [{"id": t.id, "status": t.status} for t in tasks]}


def create_recheck(db, requirement, version, change_hash, actor_id):
    if requirement.content_version != version:
        raise HTTPException(409, "需求内容已变化，请重新读取影响范围")
    impact = impact_summary(db, requirement)
    if impact is None or impact["change_hash"] != change_hash:
        raise HTTPException(409, "变化依据已更新，请重新核验")
    revision = load_revision(db, requirement.project_id, requirement.id, version)
    row = db.scalar(select(RequirementRecheck).where(RequirementRecheck.revision_id == revision.id,
        RequirementRecheck.change_hash == change_hash))
    if row is None:
        row = RequirementRecheck(project_id=requirement.project_id, requirement_id=requirement.id,
            revision_id=revision.id, created_by=actor_id, change_hash=change_hash,
            changes_json=deepcopy(impact["changes"]), status="pending")
        db.add(row); db.flush()
    from app.services.governance.workflow import start_workflow
    start_workflow(db, project_id=row.project_id, workflow_key="requirement_change_review",
        target_type="requirement_recheck", target_id=row.id, created_by=actor_id)
    return row


def new_recheck_revision(db, requirement, row, version, reason, actor_id):
    previous = load_revision(db, requirement.project_id, requirement.id, version)
    if requirement.content_version != version or row.status == "reviewed" or not reason.strip():
        raise HTTPException(409, "请从当前需求版本明确建立复核修订")
    if previous.status == "in_review":
        raise HTTPException(409, "审核中需求不能建立复核修订，请先完成或退回当前审核")
    content = deepcopy(previous.content_json)
    content["recheck_origin"] = {"recheck_id": row.id, "reason": reason.strip(), "actor_id": actor_id,
        "original_content_version": db.get(RequirementRevision, row.revision_id).content_version}
    content.pop("policy_comparisons", None)
    for record in content["fields"]:
        record.pop("confirmed_path", None)
        for key, status in (("business", "business_confirm_status"), ("lineage", "tech_confirm_status")):
            if record.get(key):
                record[key][status] = "draft"
    return append_revision(db, requirement, content, version, actor_id)


def replacement_revision(db, row):
    if not row.replacement_revision_id or not (row.resolution or "").strip():
        raise HTTPException(409, "请先关联已核验的新需求修订并填写处理依据")
    revision = db.get(RequirementRevision, row.replacement_revision_id)
    original = db.get(RequirementRevision, row.revision_id)
    requirement = db.get(Requirement, row.requirement_id)
    if (revision is None or revision.project_id != row.project_id or revision.requirement_id != row.requirement_id
            or revision.content_version <= original.content_version or requirement.content_version != revision.content_version):
        raise HTTPException(409, "关联修订不是该需求当前的新版本")
    load_revision(db, row.project_id, row.requirement_id, revision.content_version)
    from app.services.requirement_paths import path_issues
    from app.services.requirement_policy_comparison import comparison_issues, LEGACY_PENDING
    if (not revision.content_json.get("script_basis") or script_basis_changes(db, row.project_id, revision.content_json)
            or path_issues(revision.content_json) or comparison_issues(revision.content_json)):
        raise HTTPException(409, "新修订的依据、路径或制度对照仍需核验")
    if any(g != LEGACY_PENDING for g in revision.content_json["script_basis"].get("gaps", [])):
        raise HTTPException(409, "新修订仍包含脚本解析缺口，不能关闭复核")
    return revision


def review_recheck(db, row, actor_id, decision):
    if actor_id == row.created_by:
        raise HTTPException(409, "复核发起人不能审核自己的复核结论")
    if decision == "approved":
        return replacement_revision(db, row)
