from dataclasses import asdict, dataclass, field
from io import BytesIO
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    ProductScenario,
    Project,
    RegulatoryKnowledgeItem,
    ScenarioBusinessMapping,
    ScenarioTechnicalLineage,
    TargetField,
    TargetTable,
    TraceabilityTemplateDocument,
    TraceabilityTemplateParseResult,
)
from app.schemas import TraceabilityTemplateUploadResponse
from app.services.template_parser import TraceabilityExcelParser
from app.services.storage import get_storage_service


@dataclass
class TraceabilityApplySummary:
    template_id: int
    created_tables: int = 0
    created_fields: int = 0
    updated_fields: int = 0
    created_scenarios: int = 0
    updated_scenarios: int = 0
    created_business_mappings: int = 0
    updated_business_mappings: int = 0
    created_technical_lineages: int = 0
    updated_technical_lineages: int = 0
    created_knowledge_items: int = 0
    skipped_rows: int = 0
    warnings: list[str] = field(default_factory=list)


async def ingest_traceability_template(db: Session, project_id: int, upload: UploadFile) -> TraceabilityTemplateUploadResponse:
    if db.get(Project, project_id) is None:
        raise ValueError("Project not found")
    suffix = Path(upload.filename or "").suffix.lower()
    if suffix != ".xlsx":
        raise ValueError("业务口径及溯源表只支持 .xlsx 文件。")
    content = await upload.read()
    storage_path = get_storage_service().save(
        content, file_name=upload.filename or "traceability.xlsx", project_id=project_id,
    ).storage_key
    document = TraceabilityTemplateDocument(
        project_id=project_id, file_name=upload.filename or "traceability.xlsx", storage_path=storage_path,
        parse_status="pending", sheet_names_json=[], detected_scenarios_json=[], parse_summary_json={}, warnings_json=[],
    )
    db.add(document)
    db.flush()
    try:
        output = TraceabilityExcelParser().parse(BytesIO(content))
        document.parse_status = "success"
        document.sheet_names_json = output.sheet_names
        document.detected_scenarios_json = output.detected_scenarios
        document.parse_summary_json = {"sheet_count": output.sheet_count, "row_count": output.row_count}
        document.warnings_json = output.warnings
        for result in output.results:
            db.add(TraceabilityTemplateParseResult(
                project_id=project_id, template_document_id=document.id, sheet_name=result.sheet_name,
                header_start_row=result.header_start_row, header_end_row=result.header_end_row,
                fixed_columns_json=result.fixed_columns, scenario_groups_json=result.scenario_groups,
                parsed_rows_json=result.parsed_rows, warnings_json=result.warnings,
            ))
        db.commit()
        return TraceabilityTemplateUploadResponse(
            template_id=document.id, file_name=document.file_name, parse_status=document.parse_status,
            sheet_count=output.sheet_count, row_count=output.row_count,
            detected_scenarios=output.detected_scenarios, warnings=output.warnings,
        )
    except Exception as exc:
        document.parse_status = "failed"
        document.error_message = str(exc)
        db.commit()
        raise


def apply_traceability_template(db: Session, template_id: int) -> TraceabilityApplySummary:
    document = db.get(TraceabilityTemplateDocument, template_id)
    if document is None:
        raise ValueError("Traceability template not found")
    if document.parse_status != "success":
        raise ValueError("Traceability template has not parsed successfully")
    results = db.scalars(select(TraceabilityTemplateParseResult).where(
        TraceabilityTemplateParseResult.template_document_id == template_id
    ).order_by(TraceabilityTemplateParseResult.id)).all()
    summary = TraceabilityApplySummary(template_id=template_id)
    for result in results:
        table = _find_or_create_table(db, document.project_id, result, summary)
        for row in result.parsed_rows_json or []:
            fixed = row.get("fixed") or {}
            field_code = str(fixed.get("field_code") or "").strip()
            field_name = str(fixed.get("field_name") or fixed.get("report_field_name") or "").strip()
            if not field_code or not field_name:
                summary.skipped_rows += 1
                summary.warnings.append(f"{result.sheet_name} 第 {row.get('row_number', '?')} 行缺少数据项编码或名称，已跳过")
                continue
            target_field = db.scalar(select(TargetField).where(
                TargetField.project_id == document.project_id, TargetField.field_code == field_code
            ).order_by(TargetField.id))
            payload = _target_field_payload(document.project_id, table.id, fixed, field_code, field_name)
            if target_field is None:
                target_field = TargetField(**payload)
                db.add(target_field)
                db.flush()
                summary.created_fields += 1
            else:
                _apply(target_field, payload)
                summary.updated_fields += 1
            _fixed_knowledge(db, document, result, row, target_field, summary)
            for scenario_name, scenario_data in (row.get("scenarios") or {}).items():
                scenario = _upsert_scenario(db, document.project_id, scenario_name, scenario_data, summary)
                business_data = scenario_data.get("business") or {}
                technical_data = scenario_data.get("technical") or {}
                business = _upsert_business(db, target_field, scenario, business_data, summary) if business_data else None
                if business_data:
                    _scenario_knowledge(db, document, result, row, target_field, scenario, "business", business_data, summary)
                if technical_data:
                    _upsert_lineage(db, target_field, scenario, business, technical_data, summary)
                    _scenario_knowledge(db, document, result, row, target_field, scenario, "technical", technical_data, summary)
    db.commit()
    return summary


def summary_dict(summary: TraceabilityApplySummary) -> dict:
    return asdict(summary)


def _find_or_create_table(db: Session, project_id: int, result: TraceabilityTemplateParseResult, summary: TraceabilityApplySummary) -> TargetTable:
    existing_field = next((row.get("fixed", {}).get("field_code") for row in (result.parsed_rows_json or []) if row.get("fixed", {}).get("field_code")), None)
    if existing_field:
        field = db.scalar(select(TargetField).where(TargetField.project_id == project_id, TargetField.field_code == existing_field))
        if field:
            return db.get(TargetTable, field.target_table_id)
    table_code = f"TRACEABILITY_{result.id}"
    table = db.scalar(select(TargetTable).where(TargetTable.project_id == project_id, TargetTable.table_code == table_code))
    if table is None:
        first = next(iter(result.parsed_rows_json or []), {}).get("fixed", {})
        table = TargetTable(project_id=project_id, table_code=table_code, table_name=first.get("report_name") or result.sheet_name,
                            description=f"由历史口径文件 {result.sheet_name} 导入")
        db.add(table)
        db.flush()
        summary.created_tables += 1
    return table


def _target_field_payload(project_id: int, table_id: int, fixed: dict, code: str, name: str) -> dict:
    return {
        "project_id": project_id, "target_table_id": table_id, "field_code": code, "field_name": name,
        "field_type": fixed.get("data_format") or None, "data_category": fixed.get("data_category") or None,
        "data_format": fixed.get("data_format") or None,
        "field_definition": fixed.get("internal_definition") or fixed.get("regulatory_refined_definition") or fixed.get("regulatory_original_definition") or None,
        "regulatory_description": fixed.get("regulatory_refined_definition") or fixed.get("regulatory_original_definition") or None,
        "regulatory_original_definition": fixed.get("regulatory_original_definition") or None,
        "regulatory_refined_definition": fixed.get("regulatory_refined_definition") or None,
        "report_name": fixed.get("report_name") or None, "report_field_name": fixed.get("report_field_name") or None,
        "east_definition": fixed.get("east_definition") or None, "internal_definition": fixed.get("internal_definition") or None,
        "remarks": fixed.get("remarks") or None,
    }


def _upsert_scenario(db: Session, project_id: int, name: str, data: dict, summary: TraceabilityApplySummary) -> ProductScenario:
    code = data.get("scenario_code") or name
    scenario = db.scalar(select(ProductScenario).where(ProductScenario.project_id == project_id, ProductScenario.scenario_code == code))
    if scenario is None:
        scenario = ProductScenario(project_id=project_id, scenario_code=code, scenario_name=name, scenario_type="product")
        db.add(scenario)
        db.flush()
        summary.created_scenarios += 1
    else:
        scenario.scenario_name = name
        summary.updated_scenarios += 1
    return scenario


def _upsert_business(db: Session, field: TargetField, scenario: ProductScenario, data: dict, summary: TraceabilityApplySummary) -> ScenarioBusinessMapping:
    mapping = db.scalar(select(ScenarioBusinessMapping).where(
        ScenarioBusinessMapping.target_field_id == field.id, ScenarioBusinessMapping.scenario_id == scenario.id
    ))
    payload = {key: value for key, value in data.items() if hasattr(ScenarioBusinessMapping, key)}
    if mapping is None:
        mapping = ScenarioBusinessMapping(project_id=field.project_id, target_field_id=field.id, scenario_id=scenario.id, **payload)
        db.add(mapping)
        db.flush()
        summary.created_business_mappings += 1
    else:
        _apply(mapping, payload)
        summary.updated_business_mappings += 1
    return mapping


def _upsert_lineage(db: Session, field: TargetField, scenario: ProductScenario, business: ScenarioBusinessMapping | None,
                    data: dict, summary: TraceabilityApplySummary) -> ScenarioTechnicalLineage:
    lineage = db.scalar(select(ScenarioTechnicalLineage).where(
        ScenarioTechnicalLineage.target_field_id == field.id, ScenarioTechnicalLineage.scenario_id == scenario.id
    ))
    payload = {key: value for key, value in data.items() if hasattr(ScenarioTechnicalLineage, key)}
    if payload.get("processing_logic_type") not in {
        "direct", "default_value", "code_mapping", "concatenate", "calculate", "conditional",
        "manual_supplement", "external_data", "pending_confirmation",
    }:
        payload["processing_logic_type"] = "pending_confirmation"
    if lineage is None:
        lineage = ScenarioTechnicalLineage(project_id=field.project_id, target_field_id=field.id, scenario_id=scenario.id,
                                           business_mapping_id=business.id if business else None, **payload)
        db.add(lineage)
        db.flush()
        summary.created_technical_lineages += 1
    else:
        _apply(lineage, payload)
        if business:
            lineage.business_mapping_id = business.id
        summary.updated_technical_lineages += 1
    return lineage


def _fixed_knowledge(db: Session, document: TraceabilityTemplateDocument, result: TraceabilityTemplateParseResult,
                     row: dict, field: TargetField, summary: TraceabilityApplySummary) -> None:
    fixed = row.get("fixed") or {}
    sources = row.get("sources") or {}
    entries = [
        ("field_explanation", fixed.get("regulatory_original_definition"), "regulatory_original_definition"),
        ("field_explanation", fixed.get("regulatory_refined_definition"), "regulatory_refined_definition"),
        ("east_mapping", fixed.get("east_definition"), "east_definition"),
        ("field_explanation", fixed.get("internal_definition"), "internal_definition"),
        ("manual_note", fixed.get("remarks"), "remarks"),
    ]
    for knowledge_type, text, source_key in entries:
        if text:
            _add_knowledge(db, document, result, field, None, knowledge_type, text, sources.get(f"fixed.{source_key}"), summary)


def _scenario_knowledge(db: Session, document: TraceabilityTemplateDocument, result: TraceabilityTemplateParseResult,
                        row: dict, field: TargetField, scenario: ProductScenario, layer: str, data: dict,
                        summary: TraceabilityApplySummary) -> None:
    sources = row.get("sources") or {}
    for key, value in data.items():
        if value in (None, "", False):
            continue
        text = f"{key}: {value}"
        location = sources.get(f"scenarios.{scenario.scenario_name}.{layer}.{key}")
        _add_knowledge(db, document, result, field, scenario, "historical_mapping", text, location, summary)


def _add_knowledge(db: Session, document: TraceabilityTemplateDocument, result: TraceabilityTemplateParseResult,
                   field: TargetField, scenario: ProductScenario | None, knowledge_type: str, text: str,
                   location: str | None, summary: TraceabilityApplySummary) -> None:
    location = location or f"{result.sheet_name}!A{result.header_end_row + 1}"
    exists = db.scalar(select(RegulatoryKnowledgeItem.id).where(
        RegulatoryKnowledgeItem.project_id == document.project_id,
        RegulatoryKnowledgeItem.source_document_name == document.file_name,
        RegulatoryKnowledgeItem.source_sheet_name == result.sheet_name,
        RegulatoryKnowledgeItem.source_cell_range == location,
        RegulatoryKnowledgeItem.knowledge_type == knowledge_type,
        RegulatoryKnowledgeItem.scenario_id == (scenario.id if scenario else None),
    ))
    if exists:
        return
    db.add(RegulatoryKnowledgeItem(
        project_id=document.project_id, knowledge_type=knowledge_type, target_table_code=field.target_table.table_code if field.target_table else None,
        target_field_code=field.field_code, target_field_name=field.field_name, scenario_id=scenario.id if scenario else None,
        business_explanation=str(text), source_document_name=document.file_name, source_sheet_name=result.sheet_name,
        source_cell_range=location, tags_json=["historical_excel", "traceability"],
    ))
    summary.created_knowledge_items += 1


def _apply(model: object, values: dict) -> None:
    for key, value in values.items():
        setattr(model, key, value)
