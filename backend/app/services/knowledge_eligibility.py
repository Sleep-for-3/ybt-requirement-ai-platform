"""Shared governed knowledge selection for retrieval and requirement evidence.

Preserves the existing legacy-active compatibility rule. Current versions use
knowledge governance activation; historical retrieval is explicitly opt-in.
"""
from datetime import datetime, timezone

from sqlalchemy import and_, func, or_, select
from app.models import KnowledgeDocument, KnowledgeDocumentVersion, KnowledgeUnit


def _as_utc(moment):
    """Normalise naive SQLite datetimes before comparing activation windows."""
    if moment is None:
        return None
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def governed_unit_predicates(project_id, *, historical=False, historical_as_of=None, reference_time=None):
    visibility = or_(
        and_(
            KnowledgeUnit.knowledge_scope.in_(("project", "institution")),
            KnowledgeUnit.project_id == project_id,
        ),
        and_(
            KnowledgeUnit.knowledge_scope == "global",
            or_(
                KnowledgeUnit.project_id == project_id,
                KnowledgeUnit.confidentiality_level != "restricted",
            ),
        ),
    )
    lifecycle_predicate = (
        KnowledgeDocumentVersion.lifecycle_status.in_(("active", "superseded"))
        if historical else or_(
            and_(KnowledgeDocumentVersion.lifecycle_status == "active",
                 KnowledgeDocument.current_version_id == KnowledgeDocumentVersion.id),
            and_(KnowledgeDocument.current_version_id.is_(None),
                 KnowledgeDocument.current_version_no == KnowledgeDocumentVersion.version_no,
                 KnowledgeDocument.document_status.in_(("indexed", "partially_indexed", "parsed", "parsed_with_warnings", "active"))),
        )
    )
    reference_time = reference_time or historical_as_of or func.now()
    eligible_versions = select(KnowledgeDocumentVersion.id).join(
        KnowledgeDocument, KnowledgeDocument.id == KnowledgeDocumentVersion.document_id
    ).where(
        lifecycle_predicate,
        KnowledgeDocument.document_status != "archived",
        or_(KnowledgeDocumentVersion.effective_at.is_(None), KnowledgeDocumentVersion.effective_at <= reference_time),
        or_(KnowledgeDocumentVersion.expires_at.is_(None), KnowledgeDocumentVersion.expires_at > reference_time),
        KnowledgeDocumentVersion.lifecycle_status != "withdrawn",
    )
    predicates = [visibility, KnowledgeUnit.document_version_id.in_(eligible_versions)]
    if not historical: predicates.insert(0, KnowledgeUnit.enabled.is_(True))
    return predicates


def governed_document_visible(document, version, project_id, institution, historical=False, reference_time=None):
    legacy_active = (document.current_version_id is None and document.current_version_no == version.version_no
                     and document.document_status in {"indexed", "partially_indexed", "parsed", "parsed_with_warnings", "active"})
    if not historical and not legacy_active and (document.current_version_id != version.id or version.lifecycle_status != "active"):
        return False
    if version.lifecycle_status == "withdrawn" or (version.lifecycle_status == "superseded" and not historical):
        return False
    if document.applicable_project_ids_json and project_id not in document.applicable_project_ids_json:
        return False
    if document.applicable_institution_names_json and institution not in document.applicable_institution_names_json:
        return False
    # Vector candidates are stored as unit ids and re-read from the database, so
    # the activation window must be checked here as well: the keyword branch only
    # filters through guarded SQL predicates. Use the caller's request time so both
    # branches agree on the effective/expiry boundary within one request.
    moment = _as_utc(reference_time) or datetime.now(timezone.utc)
    effective_at = _as_utc(version.effective_at)
    expires_at = _as_utc(version.expires_at)
    if effective_at is not None and effective_at > moment:
        return False
    if expires_at is not None and expires_at <= moment:
        return False
    return True


def selected_requirement_units(db, project_id, document_ids, scenario_id=None, limit=501, field_codes=None):
    """Explicit selection only; no search, vector service or implicit documents."""
    from app.models import Project
    project = db.get(Project, project_id)
    if project is None:
        return []
    query = select(KnowledgeUnit, KnowledgeDocument, KnowledgeDocumentVersion).join(
        KnowledgeDocument, KnowledgeDocument.id == KnowledgeUnit.document_id
    ).join(KnowledgeDocumentVersion, KnowledgeDocumentVersion.id == KnowledgeUnit.document_version_id).where(
        *governed_unit_predicates(project_id),
        KnowledgeUnit.project_id == project_id,
        KnowledgeDocument.project_id == project_id,
        KnowledgeDocumentVersion.document_id == KnowledgeUnit.document_id,
        KnowledgeDocumentVersion.project_id == project_id,
        KnowledgeUnit.document_id.in_(document_ids),
    )
    if scenario_id:
        query = query.where(or_(KnowledgeUnit.scenario_id.is_(None), KnowledgeUnit.scenario_id == scenario_id))
    # 字段级证据：选了 18 个字段就只送这 18 个字段的制度片段。之前的实现把选定资料里的
    # 全部单元都送进模型，语料一补齐就撑爆 128KB 输入预算（真实报错：请求 410135 字节）。
    # 没有字段代码的单元是通用条款，仍然保留；过滤结果写进 projection 审计可查。
    if field_codes:
        codes = sorted({str(code) for code in field_codes if code})
        query = query.where(
            or_(
                KnowledgeUnit.target_field_code.is_(None),
                KnowledgeUnit.target_field_code == "",
                KnowledgeUnit.target_field_code.in_(codes),
            )
        )
    # Apply JSON applicability before the evidence budget: hidden clauses must
    # neither enter the model nor consume its visible evidence limit.
    result = []
    for unit, document, version in db.execute(query.order_by(KnowledgeUnit.document_id, KnowledgeUnit.id)):
        if governed_document_visible(document, version, project_id, project.bank_name):
            result.append((unit, document, version))
            if len(result) >= limit:
                break
    return result


def validate_frozen_requirement_evidence(db, project_id, snapshot):
    """Recheck activation/expiry/scope and identity without replacing frozen text."""
    from fastapi import HTTPException
    evidence = snapshot.get("evidence", [])
    if not evidence:
        return
    rows = selected_requirement_units(db, project_id, snapshot["allowed"]["document_ids"],
        snapshot.get("requirement", {}).get("scenario_id"), field_codes=snapshot.get("field_codes"))
    current = {unit.id: unit for unit, _, _ in rows}
    for saved in evidence:
        unit = current.get(saved["unit_id"])
        if (unit is None or unit.document_id != saved["document_id"]
                or unit.document_version_id != saved["document_version_id"]
                or unit.content_hash != saved["content_hash"] or unit.content != saved["content"]):
            raise HTTPException(409, "固定制度依据已失效或变化，请显式建立新修订")


def requirement_evidence(db, project_id, document_ids, scenario_id=None, limit=501, field_codes=None):
    from app.services.knowledge_evidence import unit_locator
    return [{"unit_id": unit.id, "document_id": unit.document_id,
        "document_version_id": unit.document_version_id, "content_hash": unit.content_hash,
        "content": unit.content, "title": unit.title, "confidentiality_level": unit.confidentiality_level,
        "source_category": document.source_category, "regulatory_version": version.regulatory_version,
        "lifecycle_status": version.lifecycle_status, "locator": unit_locator(unit)}
        for unit, document, version in selected_requirement_units(
            db, project_id, document_ids, scenario_id, limit, field_codes=field_codes)]
