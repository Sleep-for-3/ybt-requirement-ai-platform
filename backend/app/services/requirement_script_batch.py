"""Explicit, atomic multi-target creation using existing scopes and revisions."""
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models import Requirement, TargetField, TargetTable, TemplateVersion
from app.models.batch_import import ResourceImportBatch, ResourceImportItem
from app.models.requirement import RequirementScriptBatch
from app.services.requirement_scope import ScopeInput, content_digest, validate_scope
from app.services.requirement_revisions import initialize_content
from app.services.requirement_script_basis import ScriptSelection, ConfirmScriptBasis, script_preview, confirm_script_basis


class ReverseTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: ScopeInput
    template_version_id: int = Field(gt=0)
    target_key: str = Field(min_length=1, max_length=1000)
    field_bindings: dict[str, int] = Field(min_length=1, max_length=500)


class CreateScriptRequirements(ScriptSelection):
    idempotency_key: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    preview_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    import_batch_id: int | None = Field(default=None, gt=0)
    targets: list[ReverseTarget] = Field(min_length=1, max_length=30)


def import_script_versions(db, project_id, batch_id):
    batch = db.scalar(select(ResourceImportBatch).where(ResourceImportBatch.id == batch_id,
        ResourceImportBatch.project_id == project_id))
    if batch is None:
        raise HTTPException(404, "导入批次不存在或不可见")
    rows = list(db.scalars(select(ResourceImportItem).where(ResourceImportItem.batch_id == batch.id)))
    return {"batch_id": batch.id, "status": batch.status,
        "script_version_ids": sorted({r.result_json["script_version_id"] for r in rows
            if r.status == "completed" and r.result_json.get("script_version_id")}),
        "excluded_items": [{"id": r.id, "path": r.relative_path, "status": r.status} for r in rows
            if r.status != "completed" or not r.result_json.get("script_version_id")]}


def target_suggestions(db, project_id, preview):
    templates = list(db.scalars(select(TemplateVersion).where(TemplateVersion.project_id == project_id)))
    tables = list(db.scalars(select(TargetTable).where(TargetTable.project_id == project_id)))
    fields = list(db.scalars(select(TargetField).where(TargetField.project_id == project_id)))
    options = []
    for template in templates:
        codes = {str(s.get("table_code") or s.get("sheet_name")) for s in template.parsed_snapshot_json or []}
        for table in tables:
            if table.table_code not in codes:
                continue
            options.append({"target_table_id": table.id, "table_code": table.table_code,
                "table_name": table.table_name, "template_version_id": template.id,
                "template_version_no": template.version_no, "template_status": template.status,
                "fields": [{"id": f.id, "code": f.field_code, "name": f.field_name}
                    for f in fields if f.target_table_id == table.id]})
    return {"options": options, "suggestions": [{"target_key": t["key"],
        "matches": [{"target_table_id": o["target_table_id"], "template_version_id": o["template_version_id"]}
            for o in options if o["table_code"].casefold() == t["table_name"].casefold()]}
        for t in preview["targets"]]}


def create_script_requirements(db, project_id, payload, actor_id):
    digest = content_digest(payload.model_dump(mode="json"))
    existing = db.scalar(select(RequirementScriptBatch).where(RequirementScriptBatch.project_id == project_id,
        RequirementScriptBatch.idempotency_key == payload.idempotency_key))
    if existing:
        if existing.request_hash != digest:
            raise HTTPException(409, "请求标识已用于不同的建需内容")
        return {**existing.result_json, "deduplicated": True}
    if payload.import_batch_id:
        imported = import_script_versions(db, project_id, payload.import_batch_id)
        if not set(payload.script_version_ids) <= set(imported["script_version_ids"]):
            raise HTTPException(422, "所选脚本版本不属于该批次成功导入的脚本")
    if len({t.scope.target_table_id for t in payload.targets}) != len(payload.targets):
        raise HTTPException(422, "同一监管目标请合并为一个需求")
    if len({t.target_key for t in payload.targets}) != len(payload.targets):
        raise HTTPException(422, "同一物理写入目标不能重复确认")
    preview = script_preview(db, project_id, payload.script_version_ids)
    if preview["preview_hash"] != payload.preview_hash:
        raise HTTPException(409, "脚本或元数据已变化，请重新预览")
    for target in payload.targets:
        validate_scope(db, project_id, target.scope)
    batch = RequirementScriptBatch(project_id=project_id, created_by=actor_id,
        import_batch_id=payload.import_batch_id, idempotency_key=payload.idempotency_key,
        request_hash=digest, result_json={})
    # A failed target rolls back the entire batch, including its idempotency claim.
    try:
        with db.begin_nested():
            db.add(batch)
            db.flush()
            results = []
            for target in payload.targets:
                scope = target.scope.model_dump(mode="json", exclude={"name", "expected_version", "expected_content_version"})
                scope["script_requirement_batch_id"] = batch.id
                scope["import_batch_id"] = payload.import_batch_id
                requirement = Requirement(project_id=project_id, name=target.scope.name.strip(), version=1,
                    content_version=0, scope_json=scope)
                db.add(requirement)
                db.flush()
                initial = initialize_content(db, requirement, 1, actor_id)
                revision = confirm_script_basis(db, requirement, ConfirmScriptBasis(
                    script_version_ids=payload.script_version_ids, expected_content_version=initial.content_version,
                    preview_hash=payload.preview_hash, template_version_id=target.template_version_id,
                    target_key=target.target_key, field_bindings=target.field_bindings), actor_id)
                results.append({"requirement_id": requirement.id, "target_table_id": target.scope.target_table_id,
                    "scenario_id": target.scope.scenario_id, "content_version": revision.content_version,
                    "name": requirement.name})
            batch.result_json = {"batch_id": batch.id, "import_batch_id": payload.import_batch_id,
                "requirements": results, "script_version_ids": payload.script_version_ids}
            db.flush()
    except IntegrityError:
        winner = db.scalar(select(RequirementScriptBatch).where(RequirementScriptBatch.project_id == project_id,
            RequirementScriptBatch.idempotency_key == payload.idempotency_key))
        if winner and winner.request_hash == digest:
            return {**winner.result_json, "deduplicated": True}
        if winner:
            raise HTTPException(409, "请求标识已用于不同的建需内容")
        raise
    return {**batch.result_json, "deduplicated": False}
