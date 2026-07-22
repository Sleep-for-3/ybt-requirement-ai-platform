from __future__ import annotations

from sqlalchemy import select

from app.models import (
    CatalogColumn,
    DeliverableEvidenceItem,
    ImpactAnalysis,
    MappingEvidenceReference,
    MartToYbtMapping,
    PendingQuestion,
    ScenarioBusinessMapping,
    ScenarioTechnicalLineage,
    SourceToMartMapping,
    TargetField,
    TargetTable,
)


EVIDENCE_DIMENSIONS = (
    "regulatory_definition",
    "regulatory_qa",
    "historical_caliber",
    "source_system",
    "catalog_column",
    "column_profile",
    "sql_lineage",
    "business_confirmation",
    "technical_confirmation",
    "double_layer_mapping",
)


def field_readiness(db, target_field_id: int) -> dict:
    field = db.get(TargetField, target_field_id)
    if field is None:
        raise ValueError("Target field not found")
    project_id = field.project_id
    business = list(db.scalars(select(ScenarioBusinessMapping).where(
        ScenarioBusinessMapping.project_id == project_id,
        ScenarioBusinessMapping.target_field_id == field.id,
    )).all())
    technical = list(db.scalars(select(ScenarioTechnicalLineage).where(
        ScenarioTechnicalLineage.project_id == project_id,
        ScenarioTechnicalLineage.target_field_id == field.id,
    )).all())
    mart_to_ybt = list(db.scalars(select(MartToYbtMapping).where(
        MartToYbtMapping.project_id == project_id,
        MartToYbtMapping.target_field_id == field.id,
    )).all())
    mart_field_ids = [item.mart_field_id for item in mart_to_ybt if item.mart_field_id]
    source_to_mart = list(db.scalars(select(SourceToMartMapping).where(
        SourceToMartMapping.project_id == project_id,
        SourceToMartMapping.mart_field_id.in_(mart_field_ids),
    )).all()) if mart_field_ids else []
    questions = list(db.scalars(select(PendingQuestion).where(
        PendingQuestion.project_id == project_id,
        PendingQuestion.target_field_id == field.id,
        PendingQuestion.question_status.not_in(("closed", "accepted")),
    )).all())

    business_complete = bool(business) and all(item.final_content for item in business)
    business_confirmed = bool(business) and all(item.business_confirm_status == "confirmed" for item in business)
    technical_complete = bool(technical) and all(
        item.final_content
        and item.source_system_name
        and item.source_schema_name
        and item.source_table_english_name
        and item.source_field_english_name
        for item in technical
    )
    technical_confirmed = bool(technical) and all(item.tech_confirm_status == "confirmed" for item in technical)
    physical_sources_verified = bool(technical) and all(
        _physical_source_verified(db, project_id, item) for item in technical
    )
    mappings_present = bool(mart_to_ybt) and bool(source_to_mart)
    mappings_complete = mappings_present and all(item.final_content for item in mart_to_ybt + source_to_mart)
    mappings_approved = mappings_complete and all(item.mapping_status == "approved" for item in mart_to_ybt + source_to_mart)

    evidence = list(db.scalars(select(DeliverableEvidenceItem).where(
        DeliverableEvidenceItem.project_id == project_id,
        DeliverableEvidenceItem.target_field_id == field.id,
    )).all())
    types = {item.evidence_type for item in evidence}
    dimensions = {
        "regulatory_definition": bool(field.regulatory_description or field.regulatory_original_definition),
        "regulatory_qa": "regulatory_qa" in types,
        "historical_caliber": "historical_caliber" in types,
        "source_system": bool(technical and all(item.source_system_name for item in technical)),
        "catalog_column": physical_sources_verified,
        "column_profile": "column_profile" in types,
        "sql_lineage": bool(technical and any(item.lineage_status in {"linked", "verified"} for item in technical)),
        "business_confirmation": business_confirmed,
        "technical_confirmation": technical_confirmed,
        "double_layer_mapping": mappings_approved,
    }
    blockers: list[dict[str, str]] = []
    if not business:
        blockers.append(_reason("business_mapping_missing", "尚未配置场景业务口径"))
    elif not business_complete:
        blockers.append(_reason("business_content_missing", "场景业务口径尚未全部填写最终内容"))
    elif not business_confirmed:
        blockers.append(_reason("business_confirmation_pending", "场景业务口径尚未全部确认"))
    if not technical:
        blockers.append(_reason("technical_lineage_missing", "尚未配置场景技术溯源"))
    elif not technical_complete:
        blockers.append(_reason("technical_source_incomplete", "技术来源系统、schema、表、字段或最终内容不完整"))
    elif not technical_confirmed:
        blockers.append(_reason("technical_confirmation_pending", "场景技术来源尚未全部确认"))
    elif not physical_sources_verified:
        blockers.append(_reason("physical_source_unverified", "物理来源未通过当前项目数据目录或人工确认"))
    if not mappings_present:
        blockers.append(_reason("double_layer_mapping_missing", "双层加工口径尚未完成"))
    elif not mappings_complete:
        blockers.append(_reason("double_layer_content_missing", "双层加工口径最终内容不完整"))
    elif not mappings_approved:
        blockers.append(_reason("mapping_review_pending", "双层加工口径尚未全部审核通过"))
    if any(item.priority == "high" for item in questions):
        blockers.append(_reason("high_priority_question", "存在未关闭的高优先级问题"))
    if _has_unreviewed_high_impact(db, project_id, field.id):
        blockers.append(_reason("unreviewed_high_impact", "存在未审核的 critical/high 脚本变更影响"))

    hard_blocker_codes = {"high_priority_question", "unreviewed_high_impact"}
    if any(reason["code"] in hard_blocker_codes for reason in blockers):
        status = "blocked"
    elif not business:
        status = "not_started"
    elif not business_complete or not business_confirmed:
        status = "pending_business_confirmation"
    elif not technical_complete or not technical_confirmed or not physical_sources_verified:
        status = "pending_technical_confirmation"
    elif not mappings_approved:
        status = "pending_mapping_review"
    else:
        status = "approved"
    completeness = round(sum(dimensions.values()) / len(dimensions), 2)
    return {
        "target_field_id": field.id,
        "status": status,
        "business_mapping_count": len(business),
        "technical_lineage_count": len(technical),
        "business_confirmed_count": sum(item.business_confirm_status == "confirmed" for item in business),
        "technical_confirmed_count": sum(item.tech_confirm_status == "confirmed" for item in technical),
        "source_to_mart_status": _aggregate_status(source_to_mart),
        "mart_to_ybt_status": _aggregate_status(mart_to_ybt),
        "evidence_completeness": completeness,
        "evidence_dimensions": {
            key: "confirmed" if dimensions[key] else "unsupported" for key in EVIDENCE_DIMENSIONS
        },
        "open_question_count": len(questions),
        "blocking_reasons": blockers,
    }


def table_readiness(db, target_table_id: int) -> dict:
    table = db.get(TargetTable, target_table_id)
    if table is None:
        raise ValueError("Target table not found")
    fields = list(db.scalars(select(TargetField).where(
        TargetField.project_id == table.project_id,
        TargetField.target_table_id == table.id,
    ).order_by(TargetField.id)).all())
    items = [field_readiness(db, field.id) for field in fields]
    status_counts = {
        status: sum(item["status"] == status for item in items)
        for status in (
            "not_started",
            "pending_business_confirmation",
            "pending_technical_confirmation",
            "pending_mapping_review",
            "blocked",
            "approved",
        )
    }
    return {
        "target_table_id": target_table_id,
        "field_count": len(items),
        "approved_count": status_counts["approved"],
        "blocked_count": status_counts["blocked"],
        "status_counts": status_counts,
        "items": items,
    }


def _physical_source_verified(db, project_id: int, lineage: ScenarioTechnicalLineage) -> bool:
    catalog_match = db.scalar(select(CatalogColumn.id).where(
        CatalogColumn.project_id == project_id,
        CatalogColumn.enabled.is_(True),
        CatalogColumn.schema_name == (lineage.source_schema_name or ""),
        CatalogColumn.table_name == (lineage.source_table_english_name or ""),
        CatalogColumn.column_name == (lineage.source_field_english_name or ""),
    ).limit(1))
    if catalog_match is not None:
        return True
    return db.scalar(select(MappingEvidenceReference.id).where(
        MappingEvidenceReference.project_id == project_id,
        MappingEvidenceReference.mapping_type == "scenario_technical",
        MappingEvidenceReference.mapping_id == lineage.id,
        MappingEvidenceReference.evidence_type.in_(("catalog_column", "source_field", "manual_note")),
    ).limit(1)) is not None


def _has_unreviewed_high_impact(db, project_id: int, target_field_id: int) -> bool:
    impacts = db.scalars(select(ImpactAnalysis).where(
        ImpactAnalysis.project_id == project_id,
        ImpactAnalysis.severity.in_(("critical", "high")),
        ImpactAnalysis.status != "reviewed",
    )).all()
    return any(target_field_id in (impact.affected_target_field_ids_json or []) for impact in impacts)


def _aggregate_status(rows) -> str:
    if not rows:
        return "missing"
    if all(row.mapping_status == "approved" for row in rows):
        return "approved"
    return "draft"


def _reason(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}
