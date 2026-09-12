"""Phase F: structured field plans, join plans and gap recommendations."""

from __future__ import annotations

from app.models import (
    BusinessSystem,
    CatalogColumn,
    CatalogSchema,
    CatalogTable,
    DataSource,
    MartField,
    MartTable,
    MartToYbtMapping,
    ProductScenario,
    Project,
    ScenarioBusinessMapping,
    ScenarioTechnicalLineage,
    SourceField,
    SourceTable,
    SourceToMartMapping,
    TargetField,
    TargetTable,
)
from app.services import requirement_snapshot as snapshot_module
from app.services.requirement_snapshot import RequirementSnapshotService


def _seed(
    db,
    *,
    project_name: str = "Phase F 项目",
    join_condition: str | None = "REG_CUSTOMER.CUSTOMER_ID = EAST_CUSTOMER.CUSTOMER_ID",
    source_join_condition: str | None = "CUSTOMER.CUST_ID = REG_CUSTOMER.CUSTOMER_ID",
    source_tables_summary: str | None = "CUSTOMER",
    code_mapping_rule: str | None = None,
    filter_condition: str | None = "STAT_DATE = :report_date",
    with_source_mapping: bool = True,
    source_field_name: str = "CUST_ID",
    target_field_name: str = "客户统一标识",
    table_code: str = "EAST_CUSTOMER",
):
    """Build one project with a regulatory target field and its mappings."""

    project = Project(name=project_name)
    db.add(project)
    db.flush()
    table = TargetTable(project_id=project.id, table_code=table_code, table_name="EAST客户报送表")
    scenario = ProductScenario(project_id=project.id, scenario_code="MONTHLY", scenario_name="月度报送", enabled=True)
    db.add_all([table, scenario])
    db.flush()
    target = TargetField(
        project_id=project.id,
        target_table_id=table.id,
        field_code="CUSTOMER_ID",
        field_name=target_field_name,
        regulatory_refined_definition="监管客户唯一标识",
    )
    system = BusinessSystem(project_id=project.id, system_code="ECIF", system_name="客户信息系统")
    db.add_all([target, system])
    db.flush()
    source_table = SourceTable(
        project_id=project.id,
        business_system_id=system.id,
        table_code="SRC_CUSTOMER",
        table_name="客户源表",
        table_comment="客户主数据",
        schema_name="SRC",
        physical_table_name="CUSTOMER",
    )
    mart_table = MartTable(
        project_id=project.id,
        table_code="REG_CUSTOMER",
        table_name="监管客户集市表",
        table_comment="监管报送客户主题",
        schema_name="MART",
        physical_table_name="REG_CUSTOMER",
    )
    db.add_all([source_table, mart_table])
    db.flush()
    source_field = SourceField(
        project_id=project.id,
        source_table_id=source_table.id,
        field_code="CUST_ID",
        field_name="客户标识",
        field_comment="源系统客户标识",
        physical_column_name="CUST_ID",
    )
    mart_field = MartField(
        project_id=project.id,
        mart_table_id=mart_table.id,
        field_code="CUSTOMER_ID",
        field_name="客户统一标识",
        field_comment="监管集市客户统一标识",
        physical_column_name="CUSTOMER_ID",
    )
    db.add_all([source_field, mart_field])
    db.flush()
    db.add(MartToYbtMapping(
        project_id=project.id,
        target_field_id=target.id,
        mart_field_id=mart_field.id,
        mapping_status="approved",
        join_condition=join_condition,
        filter_condition=filter_condition,
        code_mapping_rule=code_mapping_rule,
        final_content="从监管集市输出客户统一标识",
    ))
    if with_source_mapping:
        db.add(SourceToMartMapping(
            project_id=project.id,
            mart_field_id=mart_field.id,
            mapping_status="approved",
            source_system_summary="客户信息系统",
            source_tables_summary=source_tables_summary,
            source_fields_summary=source_field_name,
            join_condition=source_join_condition,
            filter_condition=filter_condition,
            code_mapping_rule=code_mapping_rule,
            final_content="客户标识入监管集市",
        ))
    db.add(ScenarioBusinessMapping(
        project_id=project.id,
        target_field_id=target.id,
        scenario_id=scenario.id,
        business_definition="按客户统一标识报送",
        final_content="取客户主数据中的统一标识",
        business_confirm_status="confirmed",
    ))
    db.add(ScenarioTechnicalLineage(
        project_id=project.id,
        target_field_id=target.id,
        scenario_id=scenario.id,
        source_system_name="客户信息系统",
        source_table_english_name="CUSTOMER",
        source_field_english_name=source_field_name,
        processing_logic="直接取值",
        tech_confirm_status="confirmed",
        lineage_status="linked",
    ))
    db.commit()
    return project, table, scenario, target


def _snapshot(db, project, table, scenario):
    row, _ = RequirementSnapshotService(db).create(
        project_id=project.id,
        target_table_id=table.id,
        scenario_id=scenario.id,
        created_by=None,
    )
    db.commit()
    return row.content_snapshot_json


def _plan(content):
    return content["field_plans"][0]


def _gap_types(gaps) -> set[str]:
    return {str(gap["gap_type"]) for gap in gaps}


def test_join_plan_is_structured_when_both_sides_resolve(db_session):
    project, table, scenario, _target = _seed(db_session)

    plan = _plan(_snapshot(db_session, project, table, scenario))
    mart_join = next(item for item in plan["join_plans"] if item["mapping_type"] == "mart_to_ybt")

    assert mart_join["parse_status"] == "structured"
    assert mart_join["structured"] is True
    assert mart_join["fully_resolved"] is True
    assert mart_join["left_keys"] == ["CUSTOMER_ID"]
    assert mart_join["right_keys"] == ["CUSTOMER_ID"]
    assert mart_join["left_entity"]["display_name"] == "监管客户集市表"
    assert mart_join["right_entity"]["display_name"] == "EAST客户报送表"
    assert mart_join["key_pairs"][0]["left"]["display"]["display_name"] == "客户统一标识"
    assert mart_join["unresolved_references"] == []
    # No primary-key evidence exists for these tables, so cardinality stays
    # explicitly unknown instead of being guessed.
    assert mart_join["cardinality"] == "unknown"
    assert mart_join["review_required"] is True
    assert "missing_join_cardinality" in _gap_types(plan["gap_recommendations"])


def test_unknown_qualifier_is_never_resolved_by_a_global_column_match(db_session):
    project, table, scenario, _target = _seed(
        db_session,
        join_condition="CUSTOMER.CUST_ID = LEGACY_SYSTEM.CUST_ID",
        source_join_condition=None,
        with_source_mapping=False,
    )

    plan = _plan(_snapshot(db_session, project, table, scenario))
    mart_join = next(item for item in plan["join_plans"] if item["mapping_type"] == "mart_to_ybt")

    assert mart_join["structured"] is False
    assert mart_join["parse_status"] == "partial"
    assert "LEGACY_SYSTEM.CUST_ID" in mart_join["unresolved_references"]
    right = mart_join["key_pairs"][0]["right"]
    assert right["resolved"] is False
    assert right["unresolved_reason"] == "qualifier_not_found"
    assert "unresolved_join_key" in _gap_types(plan["gap_recommendations"])


def test_catalog_primary_key_produces_cardinality_and_no_cardinality_gap(db_session):
    project, table, scenario, _target = _seed(
        db_session,
        join_condition="REG_CUSTOMER.CUSTOMER_ID = SRC_CUSTOMER.CUST_ID",
        filter_condition=None,
    )
    datasource = DataSource(project_id=project.id, name="warehouse", db_type="sqlite")
    db_session.add(datasource)
    db_session.flush()
    schema = CatalogSchema(project_id=project.id, datasource_id=datasource.id, schema_name="SRC")
    db_session.add(schema)
    db_session.flush()
    for table_name, column_name in (
        ("SRC_CUSTOMER", "CUST_ID"),
        ("REG_CUSTOMER", "CUSTOMER_ID"),
        ("CUSTOMER", "CUST_ID"),
    ):
        catalog_table = CatalogTable(
            project_id=project.id,
            datasource_id=datasource.id,
            catalog_schema_id=schema.id,
            schema_name="SRC",
            table_name=table_name,
            primary_key_columns_json=[column_name],
        )
        db_session.add(catalog_table)
        db_session.flush()
        db_session.add(CatalogColumn(
            project_id=project.id,
            datasource_id=datasource.id,
            catalog_table_id=catalog_table.id,
            schema_name="SRC",
            table_name=table_name,
            column_name=column_name,
            is_primary_key=True,
            ordinal_position=1,
        ))
    db_session.commit()

    plan = _plan(_snapshot(db_session, project, table, scenario))
    mart_join = next(item for item in plan["join_plans"] if item["mapping_type"] == "mart_to_ybt")

    assert mart_join["structured"] is True
    # Both sides declare a primary key, so cardinality is a fact, not a guess.
    assert mart_join["cardinality"] == "1:1"
    assert mart_join["cardinality_basis"] == "both_sides_declared"
    assert "missing_join_cardinality" not in _gap_types(plan["gap_recommendations"])


def test_gaps_cover_dictionary_bridge_key_and_time(db_session):
    project, table, scenario, _target = _seed(
        db_session,
        join_condition=None,
        source_join_condition=None,
        source_tables_summary="CUSTOMER,DICT_CERT_TYPE",
        code_mapping_rule="1=身份证,2=护照",
        filter_condition=None,
    )

    plan = _plan(_snapshot(db_session, project, table, scenario))
    gaps = plan["gap_recommendations"]
    types = _gap_types(gaps)

    assert {"join_condition_missing", "missing_dictionary_table", "missing_bridge_table", "missing_time_field"} <= types
    for gap in gaps:
        assert gap["approval_status"] == "pending_review"
        assert gap["rationale"]
        assert gap["estimated_impact"]
        assert gap["source"] in {"requirement_snapshot", "lineage_path"}
        assert isinstance(gap["affected_assets"], list) and gap["affected_assets"]
        assert gap["dedupe_key"]
    dictionary = next(gap for gap in gaps if gap["gap_type"] == "missing_dictionary_table")
    assert "字典" in dictionary["recommended_change"]
    assert dictionary["alternative_options"]


def test_missing_source_field_is_reported_with_explicit_gap(db_session):
    project, table, scenario, _target = _seed(db_session, source_field_name="NOT_REGISTERED_COL")

    plan = _plan(_snapshot(db_session, project, table, scenario))
    types = _gap_types(plan["gap_recommendations"])

    assert "source_field_not_in_catalog" in types
    gap = next(item for item in plan["gap_recommendations"] if item["gap_type"] == "source_field_not_in_catalog")
    assert gap["confidence_level"] == "low"
    assert "新增字段" in gap["recommended_change"]


def test_path_gaps_and_complete_paths_are_projected_with_business_names(db_session):
    project, table, scenario, _target = _seed(db_session)

    content = _snapshot(db_session, project, table, scenario)
    plan = _plan(content)

    assert plan["plan_version"] == "requirement-field-plan-v1"
    assert plan["path_resolution"]["resolved"] is True
    assert plan["source_paths"], "resolver should return at least one upstream path"
    hops = plan["source_paths"][0]["hops"]
    assert hops
    assert all(hop["display_name"] for hop in hops)
    assert plan["source_paths"][0]["transformations"]

    path_gaps = [gap for gap in plan["gap_recommendations"] if gap["source"] == "lineage_path"]
    assert path_gaps, "no published lineage revision must surface as a path gap"
    assert "missing_lineage_revision" in {gap["gap_type"] for gap in path_gaps}
    for gap in path_gaps:
        assert gap["affected_assets"]
        assert gap["affected_assets"][0]["display_name"]
        assert gap["approval_status"] == "pending_review"


def test_plan_summary_uses_null_ratio_when_no_join_plan_exists(db_session):
    project = Project(name="无条件项目")
    db_session.add(project)
    db_session.flush()
    table = TargetTable(project_id=project.id, table_code="EMPTY_TABLE", table_name="空目标表")
    scenario = ProductScenario(project_id=project.id, scenario_code="EMPTY", scenario_name="空场景", enabled=True)
    db_session.add_all([table, scenario])
    db_session.flush()
    db_session.add(TargetField(
        project_id=project.id,
        target_table_id=table.id,
        field_code="NO_SOURCE",
        field_name="无来源字段",
    ))
    db_session.commit()

    content = _snapshot(db_session, project, table, scenario)
    summary = content["plan_summary"]

    assert summary["field_plan_count"] == 1
    assert summary["join_plan_count"] == 0
    assert summary["structured_join_ratio"] is None
    assert summary["fields_with_gaps"] == 1
    assert summary["path_resolution"]["truncated"] is False


def test_snapshot_does_not_leak_other_project_assets(db_session):
    first = _seed(db_session, project_name="项目甲")
    second = _seed(db_session, project_name="项目乙", table_code="OTHER_TARGET")

    content = _snapshot(db_session, first[0], first[1], first[2])
    other_content = _snapshot(db_session, second[0], second[1], second[2])

    assert content["scope"]["project_id"] == first[0].id
    assert other_content["scope"]["project_id"] == second[0].id
    target_field_assets = {
        asset["id"]
        for plan in content["field_plans"]
        for gap in plan["gap_recommendations"]
        for asset in gap["affected_assets"]
        if asset.get("entity_type") == "target_field"
    }
    assert target_field_assets == {first[3].id}
    assert second[3].id not in target_field_assets


def test_path_resolution_budget_is_reported_when_truncated(db_session, monkeypatch):
    project = Project(name="预算项目")
    db_session.add(project)
    db_session.flush()
    table = TargetTable(project_id=project.id, table_code="BUDGET_TABLE", table_name="预算目标表")
    scenario = ProductScenario(project_id=project.id, scenario_code="BUDGET", scenario_name="预算场景", enabled=True)
    db_session.add_all([table, scenario])
    db_session.flush()
    for index in range(3):
        db_session.add(TargetField(
            project_id=project.id,
            target_table_id=table.id,
            field_code=f"FIELD_{index}",
            field_name=f"字段{index}",
        ))
    db_session.commit()
    monkeypatch.setattr(snapshot_module, "MAX_PATH_FIELDS", 1)

    content = _snapshot(db_session, project, table, scenario)

    assert content["plan_summary"]["path_resolution"]["truncated"] is True
    assert content["plan_summary"]["path_resolution"]["resolved_fields"] == 1
    assert any("端到端路径" in warning for warning in content["warnings"])
    assert any(plan["path_resolution"]["reason"] == "outside_path_budget" for plan in content["field_plans"][1:])
