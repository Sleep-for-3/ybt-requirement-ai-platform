"""一次性补丁：在 document_content 里读时补全场景分组（只加新键，不改历史内容）。"""
from pathlib import Path

TARGET = Path("app/services/requirement_scope.py")

ENRICH = '''
#: 场景分组在冻结内容里的键：导出文档按场景分列时只认这一份读时补全的事实。
_SCENARIO_GROUP_KEY = "scenario_groups"

_SCENARIO_BUSINESS_FIELDS = (
    "business_definition",
    "final_content",
    "ai_generated_content",
    "source_system_screenshot_required",
    "source_system_change_required",
    "external_data_required",
    "manual_supplement_required",
    "business_owner",
    "business_confirm_status",
    "business_confirm_at",
    "remarks",
    "confidence_level",
    "open_questions",
    "created_by",
)

_SCENARIO_LINEAGE_FIELDS = (
    "business_mapping_id",
    "source_system_name",
    "source_database_name",
    "source_schema_name",
    "source_table_english_name",
    "source_table_chinese_name",
    "source_field_english_name",
    "source_field_chinese_name",
    "processing_logic",
    "processing_logic_type",
    "tech_owner",
    "tech_confirm_status",
    "tech_confirm_at",
    "remarks",
    "ai_generated_content",
    "final_content",
    "confidence_level",
    "open_questions",
    "created_by",
    "lineage_status",
)


def _scenario_payload(row, keys):
    payload = {
        "id": row.id,
        "scenario_id": row.scenario_id,
        "target_field_id": row.target_field_id,
    }
    for key in keys:
        payload[key] = getattr(row, key, None)
    return payload


def _with_scenario_groups(db, content):
    """把场景级业务口径与技术血缘补进冻结内容——只加新键，不覆盖任何已有键。

    导出文档的客户版式是"按场景重复列组"（业务口径 6 列 + 溯源 9 列），而需求正文里
    只有字段级的 business / mart_mappings。场景行存在时按 scenario 汇总成
    ``content["scenario_groups"]``，随冻结内容一起存盘；重放与产物身份因此有据可依。

    没有任何场景行时不加这个键：历史内容及其 content_hash 完全不受影响。
    顺序按 scenario.sort_order、scenario.id 固定，保证同一份数据每次得到同一份内容。
    """

    if content.get(_SCENARIO_GROUP_KEY):
        return content
    requirement = content.get("requirement") or {}
    project_id = requirement.get("project_id")
    field_ids = [
        int((record.get("field") or {})["id"])
        for record in content.get("fields") or []
        if (record.get("field") or {}).get("id") is not None
    ]
    if not project_id or not field_ids:
        return content
    business_rows = list(
        db.scalars(
            select(ScenarioBusinessMapping)
            .where(
                ScenarioBusinessMapping.project_id == project_id,
                ScenarioBusinessMapping.target_field_id.in_(field_ids),
            )
            .order_by(ScenarioBusinessMapping.id)
        )
    )
    lineage_rows = list(
        db.scalars(
            select(ScenarioTechnicalLineage)
            .where(
                ScenarioTechnicalLineage.project_id == project_id,
                ScenarioTechnicalLineage.target_field_id.in_(field_ids),
            )
            .order_by(ScenarioTechnicalLineage.id)
        )
    )
    if not business_rows and not lineage_rows:
        return content
    scenario_ids = sorted({row.scenario_id for row in business_rows + lineage_rows})
    scenarios = list(
        db.scalars(
            select(ProductScenario)
            .where(
                ProductScenario.project_id == project_id,
                ProductScenario.id.in_(scenario_ids),
            )
            .order_by(ProductScenario.sort_order, ProductScenario.id)
        )
    )
    groups = []
    for scenario in scenarios:
        groups.append(
            {
                "scenario_id": scenario.id,
                "scenario_code": scenario.scenario_code,
                "scenario_name": scenario.scenario_name,
                "sort_order": scenario.sort_order,
                "business": [
                    _scenario_payload(row, _SCENARIO_BUSINESS_FIELDS)
                    for row in business_rows
                    if row.scenario_id == scenario.id
                ],
                "technical": [
                    _scenario_payload(row, _SCENARIO_LINEAGE_FIELDS)
                    for row in lineage_rows
                    if row.scenario_id == scenario.id
                ],
            }
        )
    if not groups:
        return content
    content[_SCENARIO_GROUP_KEY] = groups
    return content


'''

OLD_DOCUMENT = '''def document_content(db, row):
    if row.content_version:
        from app.services.requirement_revisions import revision_document, load_revision
        return _with_table_meta(db, revision_document(load_revision(db, row.project_id, row.id, row.content_version)))
    return _with_table_meta(db, live_document_content(db, row))
'''

NEW_DOCUMENT = '''def document_content(db, row):
    if row.content_version:
        from app.services.requirement_revisions import revision_document, load_revision
        content = revision_document(load_revision(db, row.project_id, row.id, row.content_version))
    else:
        content = live_document_content(db, row)
    return _with_scenario_groups(db, _with_table_meta(db, content))
'''


def main() -> None:
    raw = TARGET.read_bytes().decode("utf-8")
    text = raw.replace("\r\n", "\n")
    if OLD_DOCUMENT not in text:
        raise SystemExit("anchor for document_content not found")
    text = text.replace(OLD_DOCUMENT, NEW_DOCUMENT)
    anchor = "\ndef document_content(db, row):"
    if anchor not in text:
        raise SystemExit("anchor for insertion not found")
    text = text.replace(anchor, ENRICH + anchor, 1)
    TARGET.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))
    print("patched", TARGET)


if __name__ == "__main__":
    main()
