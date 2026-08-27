from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import (
    BackgroundJob,
    BusinessSystem,
    DataSource,
    DeliverablePackage,
    MappingEvidenceReference,
    MartField,
    MartTable,
    MartToYbtMapping,
    PendingQuestion,
    ProductScenario,
    ScenarioBusinessMapping,
    ScenarioTechnicalLineage,
    SourceToMartMapping,
    TargetField,
    TargetTable,
)


class RequirementWorkspaceProjectionService:
    """Bounded-query read model for the requirement workspace.

    The projection deliberately excludes full AI/final text and quoted evidence.
    Those payloads are loaded only for the selected field or opened evidence panel.
    """

    def __init__(self, db: Session):
        self.db = db

    def projection(self, project_id: int, target_table_id: int | None, scenario_id: int | None) -> dict[str, Any]:
        tables = list(self.db.scalars(select(TargetTable).where(TargetTable.project_id == project_id).order_by(TargetTable.id)).all())
        scenarios = list(self.db.scalars(select(ProductScenario).where(ProductScenario.project_id == project_id, ProductScenario.enabled.is_(True)).order_by(ProductScenario.sort_order, ProductScenario.id)).all())
        selected_table = self._selected(tables, target_table_id, "目标表")
        selected_scenario = self._selected(scenarios, scenario_id, "场景")

        fields = list(self.db.scalars(select(TargetField).where(
            TargetField.project_id == project_id,
            TargetField.target_table_id == selected_table.id if selected_table else False,
        ).order_by(TargetField.id)).all()) if selected_table else []
        field_ids = [item.id for item in fields]

        business = self._by_field(ScenarioBusinessMapping, field_ids, selected_scenario)
        lineage = self._by_field(ScenarioTechnicalLineage, field_ids, selected_scenario)
        mart_mappings = self._many_by_field(MartToYbtMapping, field_ids)
        mart_field_ids = {item.mart_field_id for rows in mart_mappings.values() for item in rows if item.mart_field_id}
        source_mappings = self._source_mappings(project_id, mart_field_ids)
        evidence_counts = self._evidence_counts(project_id, business, lineage, mart_mappings, source_mappings)

        questions = list(self.db.scalars(select(PendingQuestion).where(
            PendingQuestion.project_id == project_id,
            PendingQuestion.target_table_id == selected_table.id if selected_table else False,
            or_(PendingQuestion.scenario_id.is_(None), PendingQuestion.scenario_id == selected_scenario.id) if selected_scenario else PendingQuestion.scenario_id.is_(None),
        ).order_by(PendingQuestion.id.desc()).limit(20)).all()) if selected_table else []
        deliverable = self.db.scalar(select(DeliverablePackage).where(
            DeliverablePackage.project_id == project_id,
            DeliverablePackage.target_table_id == selected_table.id if selected_table else False,
        ).order_by(DeliverablePackage.version_no.desc(), DeliverablePackage.id.desc()).limit(1)) if selected_table else None

        systems = list(self.db.scalars(select(BusinessSystem).where(BusinessSystem.project_id == project_id, BusinessSystem.enabled.is_(True)).order_by(BusinessSystem.id)).all())
        datasources = list(self.db.scalars(select(DataSource).where(DataSource.project_id == project_id, DataSource.enabled.is_(True)).order_by(DataSource.id)).all())
        mart_tables = list(self.db.scalars(select(MartTable).where(MartTable.project_id == project_id).order_by(MartTable.id)).all())
        mart_fields = list(self.db.scalars(select(MartField).where(MartField.project_id == project_id).order_by(MartField.id)).all())
        jobs = list(self.db.scalars(select(BackgroundJob).where(
            BackgroundJob.project_id == project_id,
            BackgroundJob.job_type.in_(("batch_ai_generation_business", "batch_ai_generation_technical")),
        ).order_by(BackgroundJob.id.desc()).limit(10)).all())

        records = []
        total_evidence = 0
        complete = 0
        for field in fields:
            business_item = business.get(field.id)
            lineage_item = lineage.get(field.id)
            mart_items = mart_mappings.get(field.id, [])
            count = evidence_counts.get(field.id, 0)
            total_evidence += count
            statuses = [business_item.business_confirm_status if business_item else "missing", lineage_item.tech_confirm_status if lineage_item else "missing", *[item.mapping_status for item in mart_items]]
            ready = bool(business_item and lineage_item and mart_items) and all(value in {"confirmed", "approved"} for value in statuses)
            complete += int(ready)
            records.append({
                "field": _field_summary(field),
                "business": _business_summary(business_item),
                "lineage": _lineage_summary(lineage_item),
                "mart_mappings": [_mart_mapping_summary(item) for item in mart_items],
                "source_mappings": {
                    str(item.mart_field_id): [_source_mapping_summary(row) for row in source_mappings.get(item.mart_field_id, [])]
                    for item in mart_items if item.mart_field_id
                },
                "evidence_count": count,
                "question_count": sum(1 for question in questions if question.target_field_id == field.id and question.question_status not in {"resolved", "closed"}),
                "readiness_status": "complete" if ready else "incomplete",
            })

        return {
            "project_id": project_id,
            "selected_target_table_id": selected_table.id if selected_table else None,
            "selected_scenario_id": selected_scenario.id if selected_scenario else None,
            "tables": [_row(item) for item in tables],
            "scenarios": [_row(item) for item in scenarios],
            "business_systems": [_row(item) for item in systems],
            "datasources": [_public_datasource(item) for item in datasources],
            "mart_tables": [_row(item) for item in mart_tables],
            "mart_fields": [_row(item) for item in mart_fields],
            "records": records,
            "question_summaries": [_question_summary(item) for item in questions],
            "deliverable_summary": _deliverable_summary(deliverable),
            "recent_jobs": [_job_summary(item) for item in jobs],
            "readiness_summary": {
                "field_count": len(fields),
                "complete_field_count": complete,
                "open_question_count": sum(1 for item in questions if item.question_status not in {"resolved", "closed"}),
                "evidence_count": total_evidence,
            },
            "performance_budget": {
                "projection_version": "requirement-workspace-v1",
                "initial_api_request_budget": 1,
                "bounded_sql_query_budget": 16,
                "large_content_deferred": True,
            },
        }

    def field_detail(self, project_id: int, field_id: int, scenario_id: int | None) -> dict[str, Any]:
        field = self.db.scalar(select(TargetField).where(TargetField.id == field_id, TargetField.project_id == project_id))
        if field is None:
            raise LookupError("Target field not found")
        scenario = self._scenario(project_id, scenario_id)
        business = self._one(ScenarioBusinessMapping, field_id, scenario)
        lineage = self._one(ScenarioTechnicalLineage, field_id, scenario)
        mart_mappings = list(self.db.scalars(select(MartToYbtMapping).where(MartToYbtMapping.project_id == project_id, MartToYbtMapping.target_field_id == field_id).order_by(MartToYbtMapping.id)).all())
        mart_field_ids = {item.mart_field_id for item in mart_mappings if item.mart_field_id}
        sources = self._source_mappings(project_id, mart_field_ids)
        return {
            "field": _row(field),
            "business": _row(business) if business else None,
            "lineage": _row(lineage) if lineage else None,
            "mart_mappings": [_row(item) for item in mart_mappings],
            "source_mappings": {str(key): [_row(item) for item in rows] for key, rows in sources.items()},
        }

    def field_evidence(self, project_id: int, field_id: int, scenario_id: int | None) -> list[dict[str, Any]]:
        detail = self.field_detail(project_id, field_id, scenario_id)
        pairs: set[tuple[str, int]] = set()
        if detail["business"]:
            pairs.add(("scenario_business", detail["business"]["id"]))
        if detail["lineage"]:
            pairs.add(("scenario_technical", detail["lineage"]["id"]))
        for item in detail["mart_mappings"]:
            pairs.add(("mart_to_ybt", item["id"]))
        for rows in detail["source_mappings"].values():
            for item in rows:
                pairs.add(("source_to_mart", item["id"]))
        if not pairs:
            return []
        mapping_types = {item[0] for item in pairs}
        mapping_ids = {item[1] for item in pairs}
        rows = self.db.scalars(select(MappingEvidenceReference).where(
            MappingEvidenceReference.project_id == project_id,
            MappingEvidenceReference.mapping_type.in_(mapping_types),
            MappingEvidenceReference.mapping_id.in_(mapping_ids),
        ).order_by(MappingEvidenceReference.id)).all()
        return [_row(item) for item in rows if (item.mapping_type, item.mapping_id) in pairs]

    def _selected(self, rows: list[Any], requested_id: int | None, label: str):
        if requested_id is None:
            return rows[0] if rows else None
        selected = next((item for item in rows if item.id == requested_id), None)
        if selected is None:
            raise LookupError(f"{label}不属于当前项目")
        return selected

    def _scenario(self, project_id: int, scenario_id: int | None):
        if scenario_id is None:
            return self.db.scalar(select(ProductScenario).where(ProductScenario.project_id == project_id, ProductScenario.enabled.is_(True)).order_by(ProductScenario.sort_order, ProductScenario.id).limit(1))
        scenario = self.db.scalar(select(ProductScenario).where(ProductScenario.id == scenario_id, ProductScenario.project_id == project_id))
        if scenario is None:
            raise LookupError("场景不属于当前项目")
        return scenario

    def _one(self, model, field_id: int, scenario):
        if scenario is None:
            return None
        return self.db.scalar(select(model).where(model.target_field_id == field_id, model.scenario_id == scenario.id))

    def _by_field(self, model, field_ids: list[int], scenario) -> dict[int, Any]:
        if not field_ids or scenario is None:
            return {}
        rows = self.db.scalars(select(model).where(model.target_field_id.in_(field_ids), model.scenario_id == scenario.id)).all()
        return {item.target_field_id: item for item in rows}

    def _many_by_field(self, model, field_ids: list[int]) -> dict[int, list[Any]]:
        output: dict[int, list[Any]] = defaultdict(list)
        if not field_ids:
            return output
        for item in self.db.scalars(select(model).where(model.target_field_id.in_(field_ids)).order_by(model.id)).all():
            output[item.target_field_id].append(item)
        return output

    def _source_mappings(self, project_id: int, mart_field_ids: set[int]) -> dict[int, list[SourceToMartMapping]]:
        output: dict[int, list[SourceToMartMapping]] = defaultdict(list)
        if not mart_field_ids:
            return output
        for item in self.db.scalars(select(SourceToMartMapping).where(
            SourceToMartMapping.project_id == project_id,
            SourceToMartMapping.mart_field_id.in_(mart_field_ids),
        ).order_by(SourceToMartMapping.id)).all():
            output[item.mart_field_id].append(item)
        return output

    def _evidence_counts(self, project_id, business, lineage, mart_mappings, source_mappings) -> dict[int, int]:
        fields_by_pair: dict[tuple[str, int], set[int]] = defaultdict(set)
        mart_fields_to_targets: dict[int, set[int]] = defaultdict(set)
        for field_id, item in business.items():
            fields_by_pair[("scenario_business", item.id)].add(field_id)
        for field_id, item in lineage.items():
            fields_by_pair[("scenario_technical", item.id)].add(field_id)
        for field_id, rows in mart_mappings.items():
            for item in rows:
                fields_by_pair[("mart_to_ybt", item.id)].add(field_id)
                if item.mart_field_id:
                    mart_fields_to_targets[item.mart_field_id].add(field_id)
        for mart_field_id, rows in source_mappings.items():
            for item in rows:
                fields_by_pair[("source_to_mart", item.id)].update(mart_fields_to_targets[mart_field_id])
        if not fields_by_pair:
            return {}
        mapping_types = {item[0] for item in fields_by_pair}
        mapping_ids = {item[1] for item in fields_by_pair}
        rows = self.db.execute(select(
            MappingEvidenceReference.mapping_type,
            MappingEvidenceReference.mapping_id,
            func.count(MappingEvidenceReference.id),
        ).where(
            MappingEvidenceReference.project_id == project_id,
            MappingEvidenceReference.mapping_type.in_(mapping_types),
            MappingEvidenceReference.mapping_id.in_(mapping_ids),
        ).group_by(MappingEvidenceReference.mapping_type, MappingEvidenceReference.mapping_id)).all()
        output: dict[int, int] = defaultdict(int)
        for mapping_type, mapping_id, count in rows:
            for field_id in fields_by_pair.get((mapping_type, mapping_id), set()):
                output[field_id] += int(count)
        return output


def _row(item) -> dict[str, Any]:
    return {column.key: getattr(item, column.key) for column in item.__table__.columns}


def _preview(*values: str | None) -> str | None:
    value = next((str(item).strip() for item in values if item and str(item).strip()), None)
    return value[:320] if value else None


def _field_summary(item: TargetField) -> dict[str, Any]:
    return {
        "id": item.id, "project_id": item.project_id, "target_table_id": item.target_table_id,
        "field_code": item.field_code, "field_name": item.field_name, "field_type": item.field_type,
        "required_flag": item.required_flag,
        "definition_preview": _preview(item.regulatory_refined_definition, item.regulatory_description, item.field_definition),
    }


def _business_summary(item: ScenarioBusinessMapping | None) -> dict[str, Any] | None:
    if item is None:
        return None
    return {"id": item.id, "status": item.business_confirm_status, "confidence_level": item.confidence_level, "has_ai_draft": bool(item.ai_generated_content), "has_final": bool(item.final_content), "content_preview": _preview(item.final_content, item.ai_generated_content, item.business_definition), "locked": item.business_confirm_status in {"confirmed", "approved", "submitted", "under_review"}}


def _lineage_summary(item: ScenarioTechnicalLineage | None) -> dict[str, Any] | None:
    if item is None:
        return None
    return {"id": item.id, "status": item.tech_confirm_status, "confidence_level": item.confidence_level, "has_ai_draft": bool(item.ai_generated_content), "has_final": bool(item.final_content), "content_preview": _preview(item.final_content, item.ai_generated_content, item.processing_logic), "source_system_name": item.source_system_name, "source_database_name": item.source_database_name, "source_schema_name": item.source_schema_name, "source_table_name": item.source_table_english_name or item.source_table_chinese_name, "source_field_name": item.source_field_english_name or item.source_field_chinese_name, "lineage_status": item.lineage_status, "locked": item.tech_confirm_status in {"confirmed", "approved", "submitted", "under_review"}}


def _mart_mapping_summary(item: MartToYbtMapping) -> dict[str, Any]:
    return {"id": item.id, "mart_field_id": item.mart_field_id, "status": item.mapping_status, "confidence_level": item.confidence_level, "content_preview": _preview(item.final_content, item.ai_generated_content, item.business_rule), "lineage_status": item.lineage_status}


def _source_mapping_summary(item: SourceToMartMapping) -> dict[str, Any]:
    return {"id": item.id, "mart_field_id": item.mart_field_id, "status": item.mapping_status, "confidence_level": item.confidence_level, "source_system_summary": _preview(item.source_system_summary), "content_preview": _preview(item.final_content, item.ai_generated_content, item.business_rule), "lineage_status": item.lineage_status}


def _question_summary(item: PendingQuestion) -> dict[str, Any]:
    return {"id": item.id, "project_id": item.project_id, "target_table_id": item.target_table_id, "target_field_id": item.target_field_id, "scenario_id": item.scenario_id, "question_type": item.question_type, "question_text": _preview(item.question_text) or "", "question_status": item.question_status, "priority": item.priority, "assigned_role": item.assigned_role, "assigned_user_id": item.assigned_user_id, "source_type": item.source_type, "source_id": item.source_id, "resolution_text": _preview(item.resolution_text)}


def _deliverable_summary(item: DeliverablePackage | None) -> dict[str, Any] | None:
    return {"id": item.id, "target_table_id": item.target_table_id, "status": item.status, "version_no": item.version_no} if item else None


def _job_summary(item: BackgroundJob) -> dict[str, Any]:
    result = item.result_summary_json if isinstance(item.result_summary_json, dict) else {}
    safe_result = {
        key: result[key]
        for key in ("processed", "succeeded", "failed", "total", "table_count", "column_count")
        if key in result
    }
    return {"id": item.id, "project_id": item.project_id, "job_type": item.job_type, "status": item.status, "progress": item.progress, "current_step": item.current_step, "result_summary_json": safe_result, "started_at": item.started_at, "finished_at": item.finished_at, "created_at": item.created_at, "updated_at": item.updated_at}


def _public_datasource(item: DataSource) -> dict[str, Any]:
    return {"id": item.id, "project_id": item.project_id, "name": item.name, "display_name": item.display_name, "db_type": item.db_type, "connection_params_json": {}, "password_configured": item.password_configured, "readonly_flag": item.readonly_flag, "enabled": item.enabled, "last_test_status": item.last_test_status, "last_database_version": item.last_database_version, "last_discovered_schemas_json": item.last_discovered_schemas_json}
