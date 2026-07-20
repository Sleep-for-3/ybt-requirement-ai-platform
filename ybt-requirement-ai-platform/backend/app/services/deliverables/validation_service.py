from sqlalchemy import select

from app.models import CatalogColumn, DeliverablePackage, MappingEvidenceReference, PendingQuestion, ScenarioBusinessMapping, ScenarioTechnicalLineage, TargetField
from app.services.deliverables.readiness_service import field_readiness


def validate_package(db, package_id: int) -> dict:
    package = db.get(DeliverablePackage, package_id)
    if package is None:
        raise ValueError("Deliverable package not found")
    fields = list(db.scalars(select(TargetField).where(TargetField.target_table_id == package.target_table_id).order_by(TargetField.id)).all())
    issues = []
    for order, field in enumerate(fields, 1):
        if not field.field_code: issues.append(_issue("error", field.id, "target_field_code", "字段代码为空"))
        if not field.field_name: issues.append(_issue("error", field.id, "target_field_name", "字段名称为空"))
        business = list(db.scalars(select(ScenarioBusinessMapping).where(ScenarioBusinessMapping.target_field_id == field.id)).all())
        technical = list(db.scalars(select(ScenarioTechnicalLineage).where(ScenarioTechnicalLineage.target_field_id == field.id)).all())
        if not business: issues.append(_issue("error", field.id, "business_mapping", "至少需要一个场景业务口径"))
        for item in business:
            if not item.final_content: issues.append(_issue("error", field.id, "business_content", "业务口径为空"))
            if item.business_confirm_status != "confirmed": issues.append(_issue("error", field.id, "business_confirmation", "业务口径未正式确认"))
        if not technical: issues.append(_issue("error", field.id, "technical_lineage", "缺少技术溯源"))
        for item in technical:
            if not all((item.source_system_name, item.source_table_english_name, item.source_field_english_name)):
                issues.append(_issue("error", field.id, "physical_source", "来源系统、表或字段不完整"))
            if item.tech_confirm_status != "confirmed": issues.append(_issue("error", field.id, "technical_confirmation", "技术溯源未正式确认"))
            if item.lineage_status == "stale": issues.append(_issue("warning", field.id, "stale_lineage", "技术溯源引用的脚本血缘已过期"))
            catalog_match = db.scalar(select(CatalogColumn.id).where(CatalogColumn.project_id == package.project_id, CatalogColumn.enabled.is_(True), CatalogColumn.schema_name == (item.source_schema_name or ""), CatalogColumn.table_name == (item.source_table_english_name or ""), CatalogColumn.column_name == (item.source_field_english_name or "")).limit(1))
            manual_confirmation = db.scalar(select(MappingEvidenceReference.id).where(MappingEvidenceReference.project_id == package.project_id, MappingEvidenceReference.mapping_type == "scenario_technical", MappingEvidenceReference.mapping_id == item.id, MappingEvidenceReference.evidence_type.in_(("catalog_column", "source_field", "manual_note"))).limit(1))
            if not catalog_match and not manual_confirmation: issues.append(_issue("error", field.id, "unverified_physical_source", "来源字段必须存在于启用的数据目录或具备人工确认记录"))
        readiness = field_readiness(db, field.id)
        if readiness["status"] == "blocked": issues.append(_issue("error", field.id, "readiness", ";".join(readiness["blocking_reasons"])))
    open_high = db.scalar(select(PendingQuestion.id).where(PendingQuestion.project_id == package.project_id, PendingQuestion.target_table_id == package.target_table_id, PendingQuestion.priority == "high", PendingQuestion.question_status.not_in(("closed", "accepted"))).limit(1))
    if open_high: issues.append(_issue("error", None, "high_priority_question", "存在未关闭的高优先级问题"))
    result = {"error_count": sum(item["severity"] == "error" for item in issues), "warning_count": sum(item["severity"] == "warning" for item in issues), "info_count": sum(item["severity"] == "info" for item in issues), "issues": issues}
    package.summary_json = {**(package.summary_json or {}), "validation": result}
    package.status = "validation_failed" if result["error_count"] else "generated" if package.generated_file_id else "draft"
    return result


def _issue(severity, field_id, code, message):
    return {"severity": severity, "target_field_id": field_id, "code": code, "message": message}
