from sqlalchemy import select

from app.core.settings import get_settings
from app.models import CatalogColumn, DeliverableEvidenceItem, DeliverablePackage, MappingEvidenceReference, MartToYbtMapping, PendingQuestion, Project, ScenarioBusinessMapping, ScenarioTechnicalLineage, SourceToMartMapping, TargetField
from app.services.deliverables.readiness_service import field_readiness


def validate_package(db, package_id: int, *, update_status: bool = True) -> dict:
    package = db.get(DeliverablePackage, package_id)
    if package is None:
        raise ValueError("Deliverable package not found")
    fields = list(db.scalars(select(TargetField).where(TargetField.project_id == package.project_id, TargetField.target_table_id == package.target_table_id).order_by(TargetField.id)).all())
    issues = []
    project = db.get(Project, package.project_id)
    governed = get_settings().auth_mode == "required" or bool(project and project.governance_workflow_enabled)
    for order, field in enumerate(fields, 1):
        if not field.field_code: issues.append(_issue("error", field.id, "target_field_code", "字段代码为空"))
        if not field.field_name: issues.append(_issue("error", field.id, "target_field_name", "字段名称为空"))
        business = list(db.scalars(select(ScenarioBusinessMapping).where(ScenarioBusinessMapping.project_id == package.project_id, ScenarioBusinessMapping.target_field_id == field.id)).all())
        technical = list(db.scalars(select(ScenarioTechnicalLineage).where(ScenarioTechnicalLineage.project_id == package.project_id, ScenarioTechnicalLineage.target_field_id == field.id)).all())
        if not business: issues.append(_issue("error", field.id, "business_mapping", "至少需要一个场景业务口径"))
        for item in business:
            if not item.final_content: issues.append(_issue("error", field.id, "business_content", "业务口径为空"))
            if item.business_confirm_status != "confirmed": issues.append(_issue("error", field.id, "business_confirmation", "业务口径未正式确认"))
        if not technical: issues.append(_issue("error", field.id, "technical_lineage", "缺少技术溯源"))
        for item in technical:
            if not all((item.source_system_name, item.source_schema_name, item.source_table_english_name, item.source_field_english_name)):
                issues.append(_issue("error", field.id, "physical_source", "来源系统、schema、表或字段不完整"))
            if item.tech_confirm_status != "confirmed": issues.append(_issue("error", field.id, "technical_confirmation", "技术溯源未正式确认"))
            if item.lineage_status == "stale": issues.append(_issue("warning", field.id, "stale_lineage", "技术溯源引用的脚本血缘已过期"))
            catalog_match = db.scalar(select(CatalogColumn.id).where(CatalogColumn.project_id == package.project_id, CatalogColumn.enabled.is_(True), CatalogColumn.schema_name == (item.source_schema_name or ""), CatalogColumn.table_name == (item.source_table_english_name or ""), CatalogColumn.column_name == (item.source_field_english_name or "")).limit(1))
            manual_confirmation = db.scalar(select(MappingEvidenceReference.id).where(MappingEvidenceReference.project_id == package.project_id, MappingEvidenceReference.mapping_type == "scenario_technical", MappingEvidenceReference.mapping_id == item.id, MappingEvidenceReference.evidence_type.in_(("catalog_column", "source_field", "manual_note"))).limit(1))
            if not catalog_match and not manual_confirmation: issues.append(_issue("error", field.id, "unverified_physical_source", "来源字段必须存在于启用的数据目录或具备人工确认记录"))
        mart_mappings = list(db.scalars(select(MartToYbtMapping).where(MartToYbtMapping.project_id == package.project_id, MartToYbtMapping.target_field_id == field.id)).all())
        if not mart_mappings:
            issues.append(_issue("error", field.id, "mart_to_ybt_mapping", "缺少监管集市到一表通口径"))
        for mart_mapping in mart_mappings:
            if not mart_mapping.final_content: issues.append(_issue("error", field.id, "mart_to_ybt_content", "监管集市到一表通口径为空"))
            if governed and mart_mapping.mapping_status != "approved": issues.append(_issue("error", field.id, "mart_to_ybt_review", "监管集市到一表通口径尚未通过治理审核"))
            source_mappings = list(db.scalars(select(SourceToMartMapping).where(SourceToMartMapping.project_id == package.project_id, SourceToMartMapping.mart_field_id == mart_mapping.mart_field_id)).all()) if mart_mapping.mart_field_id else []
            if not source_mappings: issues.append(_issue("error", field.id, "source_to_mart_mapping", "缺少业务系统到监管集市口径"))
            for source_mapping in source_mappings:
                if not source_mapping.final_content: issues.append(_issue("error", field.id, "source_to_mart_content", "业务系统到监管集市口径为空"))
                if governed and source_mapping.mapping_status != "approved": issues.append(_issue("error", field.id, "source_to_mart_review", "业务系统到监管集市口径尚未通过治理审核"))
        readiness = field_readiness(db, field.id)
        for reason in readiness["blocking_reasons"]:
            if reason["code"] in {"high_priority_question", "unreviewed_high_impact"}:
                issues.append(_issue("error", field.id, reason["code"], reason["message"]))
    for citation in db.scalars(select(DeliverableEvidenceItem).where(DeliverableEvidenceItem.project_id == package.project_id, DeliverableEvidenceItem.deliverable_package_id == package.id)).all():
        reference = db.scalar(select(MappingEvidenceReference.id).where(
            MappingEvidenceReference.project_id == package.project_id,
            MappingEvidenceReference.mapping_type == citation.mapping_type,
            MappingEvidenceReference.mapping_id == citation.mapping_id,
            MappingEvidenceReference.evidence_type == citation.evidence_type,
            MappingEvidenceReference.evidence_id == citation.evidence_id,
        ).limit(1))
        if reference is None: issues.append(_issue("error", citation.target_field_id, "invalid_citation", "证据引用不存在或不属于当前项目"))
    open_high = db.scalar(select(PendingQuestion.id).where(PendingQuestion.project_id == package.project_id, PendingQuestion.target_table_id == package.target_table_id, PendingQuestion.priority == "high", PendingQuestion.question_status.not_in(("closed", "accepted"))).limit(1))
    if open_high: issues.append(_issue("error", None, "high_priority_question", "存在未关闭的高优先级问题"))
    render_validation = (package.summary_json or {}).get("render_validation") or {}
    for render_issue in render_validation.get("issues", []):
        if render_issue.get("severity") == "error":
            issues.append({**render_issue, "target_field_id": render_issue.get("target_field_id")})
    result = {"error_count": sum(item["severity"] == "error" for item in issues), "warning_count": sum(item["severity"] == "warning" for item in issues), "info_count": sum(item["severity"] == "info" for item in issues), "issues": issues}
    package.summary_json = {**(package.summary_json or {}), "validation": result}
    if update_status:
        package.status = "validation_failed" if result["error_count"] else "generated" if package.generated_file_id else "draft"
    return result


def _issue(severity, field_id, code, message):
    return {"severity": severity, "target_field_id": field_id, "code": code, "message": message}
