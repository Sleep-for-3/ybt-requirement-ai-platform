"""Persist authoritative input separately from redacted background job summaries."""
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models import RequirementGenerationInput
from app.services.auth.permission_service import PermissionService
from app.services.mapping.generator_context import build_requirement_generation_input
from app.services.requirement_revisions import lock_requirement, load_revision
from app.services.requirement_scope import content_digest


class PrepareGenerationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_content_version: int = Field(gt=0)
    field_ids: list[int] = Field(min_length=1, max_length=200)
    sections: list[Literal["business", "lineage"]] = Field(min_length=1, max_length=2)
    idempotency_key: str = Field(min_length=8, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")


def prepare_input(db, project_id, requirement_id, payload, principal):
    permissions = PermissionService(db, principal)
    project = permissions.require_project_permission(project_id, "project.view")
    for section in payload.sections:
        permissions.require_project_permission(project_id, "business.edit" if section == "business" else "technical.edit")
    requirement = lock_requirement(db, project_id, requirement_id)
    revision = load_revision(db, project_id, requirement_id, payload.expected_content_version)
    if revision.content_json["requirement"].get("document_ids"):
        available = permissions.effective_project_permissions(project_id)
        if not ({"knowledge.search", "knowledge.manage"} & set(available)):
            raise HTTPException(403, "无权将知识资料纳入生成")
    request_hash = content_digest({"version": payload.expected_content_version,
        "field_ids": sorted(set(payload.field_ids)), "sections": sorted(set(payload.sections)), "operation": "generate"})
    existing = db.scalar(select(RequirementGenerationInput).where(
        RequirementGenerationInput.requirement_id == requirement_id,
        RequirementGenerationInput.project_id == project_id,
        RequirementGenerationInput.idempotency_key == payload.idempotency_key))
    if existing:
        if existing.request_hash != request_hash or existing.created_by != principal.user_id:
            raise HTTPException(409, "此提交标识已用于其他生成请求")
        if content_digest(existing.input_json) != existing.input_hash:
            raise HTTPException(409, "生成输入完整性检查失败")
        return existing, True
    if requirement.content_version != payload.expected_content_version or revision.status != "draft":
        raise HTTPException(409, "只能为当前草稿准备新的生成输入")
    content = build_requirement_generation_input(db, revision=revision, field_ids=payload.field_ids,
        sections=payload.sections, actor=principal, authorized_project=project)
    row = RequirementGenerationInput(project_id=project_id, requirement_id=requirement_id,
        revision_id=revision.id, idempotency_key=payload.idempotency_key, request_hash=request_hash,
        input_hash=content_digest(content), input_json=content, created_by=principal.user_id)
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
    except IntegrityError:
        winner = db.scalar(select(RequirementGenerationInput).where(
            RequirementGenerationInput.requirement_id == requirement_id,
            RequirementGenerationInput.project_id == project_id,
            RequirementGenerationInput.idempotency_key == payload.idempotency_key))
        if winner is None:
            raise
        if winner.request_hash != request_hash or winner.created_by != principal.user_id:
            raise HTTPException(409, "此提交标识已用于其他生成请求")
        if content_digest(winner.input_json) != winner.input_hash:
            raise HTTPException(409, "生成输入完整性检查失败")
        return winner, True
    return row, False


def input_summary(row, deduplicated=False):
    return {"id": row.id, "requirement_id": row.requirement_id,
        "content_version": row.input_json["content_version"], "input_hash": row.input_hash,
        "field_ids": row.input_json["field_ids"], "sections": row.input_json["sections"],
        "status": "prepared", "job_id": row.job_id, "deduplicated": deduplicated}
