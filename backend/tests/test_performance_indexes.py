from app.core.database import Base


def test_workspace_queries_have_targeted_composite_indexes() -> None:
    expected = {
        "target_fields": {("project_id", "target_table_id")},
        "product_scenarios": {("project_id", "enabled", "sort_order")},
        "scenario_business_mappings": {("target_field_id", "scenario_id")},
        "scenario_technical_lineages": {("target_field_id", "scenario_id")},
        "source_to_mart_mappings": {("project_id", "mart_field_id")},
        "pending_questions": {("project_id", "target_table_id", "scenario_id")},
        "background_jobs": {("project_id", "job_type", "id")},
        "mapping_evidence_references": {("project_id", "mapping_type", "mapping_id")},
    }
    for table_name, required in expected.items():
        actual = {tuple(column.name for column in index.columns) for index in Base.metadata.tables[table_name].indexes}
        assert required <= actual, table_name


def test_existing_indexes_are_reused_instead_of_duplicated() -> None:
    expected_existing = {
        "mart_to_ybt_mappings": ("target_field_id",),
        "background_jobs": ("project_id", "status"),
    }
    for table_name, required in expected_existing.items():
        actual = {tuple(column.name for column in index.columns) for index in Base.metadata.tables[table_name].indexes}
        assert required in actual
