"""制度版本对比：固定两个版本，逐条输出差异与双侧出处。

只读服务：不修改知识库，不生成任务；供接口与后续 /agent 版本对比入口复用。
"""

from __future__ import annotations

import difflib
from typing import Any

from sqlalchemy import select

from app.models import KnowledgeDocument, KnowledgeDocumentVersion, KnowledgeUnit
from app.services.auth.permission_service import PermissionService


def _citation(unit: KnowledgeUnit, document: KnowledgeDocument, version: KnowledgeDocumentVersion) -> dict[str, Any]:
    locator = {
        "block_id": f"knowledge-unit-{unit.id}",
        "sheet_name": unit.source_sheet_name,
        "cell_range": unit.source_cell_range,
        "page_no": unit.source_page_no,
        "heading": unit.source_heading,
    }
    return {
        "citation_id": f"knowledge-unit-{unit.id}",
        "citation_type": "knowledge_document",
        "project_id": document.project_id,
        "document_id": document.id,
        "document_version_id": version.id,
        "knowledge_unit_id": unit.id,
        "label": unit.title or unit.source_file_name,
        "source_file_name": unit.source_file_name,
        "source_sheet_name": unit.source_sheet_name,
        "source_cell_range": unit.source_cell_range,
        "source_page_no": unit.source_page_no,
        "source_heading": unit.source_heading,
        "quoted_content": (unit.content or "")[:1500],
        "locator": {key: value for key, value in locator.items() if value is not None},
    }


def _unit_key(unit: KnowledgeUnit) -> str:
    if unit.source_sheet_name or unit.source_cell_range:
        return f"{unit.source_sheet_name or ''}!{unit.source_cell_range or ''}"
    if unit.source_heading:
        return f"heading:{unit.source_heading}"
    return f"unit:{unit.id}"


def compare_versions(db, principal, project_id: int, document_id: int,
                     base_version_id: int, target_version_id: int) -> dict[str, Any]:
    PermissionService(db, principal).require_project_permission(project_id, "knowledge.search")
    document = db.get(KnowledgeDocument, document_id)
    if document is None or document.project_id != project_id:
        raise ValueError("document_not_found")
    versions = {
        version.id: version
        for version in db.scalars(select(KnowledgeDocumentVersion).where(
            KnowledgeDocumentVersion.document_id == document_id,
            KnowledgeDocumentVersion.project_id == project_id,
        )).all()
    }
    base_version = versions.get(base_version_id)
    target_version = versions.get(target_version_id)
    if base_version is None or target_version is None:
        raise ValueError("version_not_found")

    def load(version_id: int) -> dict[str, KnowledgeUnit]:
        units = db.scalars(select(KnowledgeUnit).where(
            KnowledgeUnit.document_id == document_id,
            KnowledgeUnit.document_version_id == version_id,
            KnowledgeUnit.project_id == project_id,
        ).order_by(KnowledgeUnit.id)).all()
        return {_unit_key(unit): unit for unit in units}

    base_units = load(base_version_id)
    target_units = load(target_version_id)
    items: list[dict[str, Any]] = []
    for key in sorted(set(base_units) | set(target_units)):
        base_unit = base_units.get(key)
        target_unit = target_units.get(key)
        if base_unit is None:
            items.append({"key": key, "change_type": "added",
                          "target": _citation(target_unit, document, target_version)})
            continue
        if target_unit is None:
            items.append({"key": key, "change_type": "removed",
                          "base": _citation(base_unit, document, base_version)})
            continue
        base_text = (base_unit.content or "").strip()
        target_text = (target_unit.content or "").strip()
        if base_text == target_text:
            continue
        diff = [line for line in difflib.unified_diff(
            base_text.splitlines(), target_text.splitlines(), lineterm="", n=1,
        )][2:]
        items.append({
            "key": key,
            "change_type": "changed",
            "base": _citation(base_unit, document, base_version),
            "target": _citation(target_unit, document, target_version),
            "diff": diff[:40],
        })

    counts = {"added": 0, "removed": 0, "changed": 0}
    for item in items:
        counts[item["change_type"]] += 1
    return {
        "document_id": document_id,
        "file_name": document.file_name,
        "base_version": {"id": base_version.id, "version_no": base_version.version_no},
        "target_version": {"id": target_version.id, "version_no": target_version.version_no},
        "counts": counts,
        "items": items,
        "unchanged_count": len(set(base_units) & set(target_units)) - counts["changed"],
    }
