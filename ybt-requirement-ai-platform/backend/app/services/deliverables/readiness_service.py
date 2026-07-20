from sqlalchemy import func, select

from app.models import (
    DeliverableEvidenceItem, MartToYbtMapping, PendingQuestion, ScenarioBusinessMapping,
    ScenarioTechnicalLineage, SourceToMartMapping, TargetField,
)

EVIDENCE_DIMENSIONS = ("regulatory_definition", "regulatory_qa", "historical_caliber", "source_system", "catalog_column", "column_profile", "sql_lineage", "business_confirmation", "technical_confirmation", "double_layer_mapping")


def field_readiness(db, target_field_id: int) -> dict:
    field = db.get(TargetField, target_field_id)
    if field is None:
        raise ValueError("Target field not found")
    business = list(db.scalars(select(ScenarioBusinessMapping).where(ScenarioBusinessMapping.target_field_id == field.id)).all())
    technical = list(db.scalars(select(ScenarioTechnicalLineage).where(ScenarioTechnicalLineage.target_field_id == field.id)).all())
    business_confirmed = sum(item.business_confirm_status == "confirmed" for item in business)
    technical_confirmed = sum(item.tech_confirm_status == "confirmed" for item in technical)
    source_to_mart = list(db.scalars(select(SourceToMartMapping).where(SourceToMartMapping.project_id == field.project_id)).all())
    mart_to_ybt = list(db.scalars(select(MartToYbtMapping).where(MartToYbtMapping.target_field_id == field.id)).all())
    questions = list(db.scalars(select(PendingQuestion).where(PendingQuestion.target_field_id == field.id, PendingQuestion.question_status.not_in(("closed", "accepted")))).all())
    dimensions = {
        "regulatory_definition": bool(field.regulatory_description or field.regulatory_original_definition),
        "regulatory_qa": False,
        "historical_caliber": False,
        "source_system": bool(technical and all(item.source_system_name for item in technical)),
        "catalog_column": bool(technical and all(item.source_table_english_name and item.source_field_english_name for item in technical)),
        "column_profile": False,
        "sql_lineage": bool(technical and any(item.lineage_status in {"linked", "verified"} for item in technical)),
        "business_confirmation": bool(business and business_confirmed == len(business)),
        "technical_confirmation": bool(technical and technical_confirmed == len(technical)),
        "double_layer_mapping": bool(source_to_mart and mart_to_ybt and all(item.mapping_status == "approved" for item in source_to_mart + mart_to_ybt)),
    }
    evidence = list(db.scalars(select(DeliverableEvidenceItem).where(DeliverableEvidenceItem.target_field_id == field.id)).all())
    types = {item.evidence_type for item in evidence}
    dimensions["regulatory_qa"] = "regulatory_qa" in types
    dimensions["historical_caliber"] = "historical_caliber" in types
    dimensions["column_profile"] = "column_profile" in types
    completeness = round(sum(dimensions.values()) / len(dimensions), 2)
    blockers = []
    if not business: blockers.append("尚未配置场景业务口径")
    elif business_confirmed < len(business): blockers.append("场景业务口径尚未全部确认")
    if not technical: blockers.append("尚未配置场景技术溯源")
    elif technical_confirmed < len(technical): blockers.append("场景技术来源尚未全部确认")
    if not source_to_mart or not mart_to_ybt: blockers.append("双层加工口径尚未完成")
    if any(item.priority == "high" for item in questions): blockers.append("存在未关闭的高优先级问题")
    status = "blocked" if any(item.priority == "high" for item in questions) else "approved" if not blockers else "pending_technical_confirmation" if business_confirmed == len(business) and business else "pending_business_confirmation"
    return {"target_field_id": field.id, "status": status, "business_mapping_count": len(business), "technical_lineage_count": len(technical), "business_confirmed_count": business_confirmed, "technical_confirmed_count": technical_confirmed, "source_to_mart_status": _aggregate_status(source_to_mart), "mart_to_ybt_status": _aggregate_status(mart_to_ybt), "evidence_completeness": completeness, "evidence_dimensions": {key: "confirmed" if dimensions[key] else "unsupported" for key in EVIDENCE_DIMENSIONS}, "open_question_count": len(questions), "blocking_reasons": blockers}


def table_readiness(db, target_table_id: int) -> dict:
    fields = list(db.scalars(select(TargetField).where(TargetField.target_table_id == target_table_id).order_by(TargetField.id)).all())
    items = [field_readiness(db, field.id) for field in fields]
    return {"target_table_id": target_table_id, "field_count": len(items), "approved_count": sum(item["status"] == "approved" for item in items), "blocked_count": sum(item["status"] == "blocked" for item in items), "items": items}


def _aggregate_status(rows) -> str:
    if not rows: return "missing"
    if all(row.mapping_status == "approved" for row in rows): return "approved"
    return "draft"
