"""Frozen requirement drafts; never a substitute for final delivery review."""
import json

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select

from app.models import Requirement, RequirementDelivery
from app.services.requirement_scope import content_digest, document_content


def freeze_draft(db, project_id, requirement_id, expected_version, expected_hash, actor_id):
    requirement = db.scalar(select(Requirement).where(
        Requirement.project_id == project_id, Requirement.id == requirement_id
    ).with_for_update().execution_options(populate_existing=True))
    if requirement is None:
        raise HTTPException(404, "需求不存在或不可见")
    if requirement.version != expected_version:
        raise HTTPException(409, "需求范围已修改，请重新预览后保存快照")
    content = jsonable_encoder(document_content(db, requirement))
    digest = content_digest(content)
    if digest != expected_hash:
        raise HTTPException(409, "字段口径或依据已变化，请重新预览后保存快照")
    existing = db.scalar(select(RequirementDelivery).where(
        RequirementDelivery.project_id == project_id,
        RequirementDelivery.requirement_id == requirement_id,
        RequirementDelivery.requirement_version == expected_version,
        RequirementDelivery.content_hash == digest,
    ))
    if existing:
        return existing, False
    # JSON round-trip detaches all mutable objects from the live projection.
    row = RequirementDelivery(project_id=project_id, requirement_id=requirement_id,
        requirement_version=expected_version, content_hash=digest,
        content_json=json.loads(json.dumps(content, ensure_ascii=False)), created_by=actor_id)
    db.add(row)
    db.flush()
    return row, True


def load_frozen_draft(db, project_id, requirement_id, snapshot_id):
    row = db.scalar(select(RequirementDelivery).where(
        RequirementDelivery.id == snapshot_id,
        RequirementDelivery.project_id == project_id,
        RequirementDelivery.requirement_id == requirement_id,
    ))
    if row is None:
        raise HTTPException(404, "需求快照不存在或不可见")
    if content_digest(row.content_json) != row.content_hash:
        raise HTTPException(409, "快照完整性校验失败，暂不能导出")
    return row


def snapshot_summary(row):
    return {"id": row.id, "requirement_id": row.requirement_id,
        "requirement_version": row.requirement_version, "content_hash": row.content_hash,
        "created_at": row.created_at, "status": "frozen_draft"}
