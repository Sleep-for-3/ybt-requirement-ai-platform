"""VNext2 P1-B: composite business keys must not be silently treated as unique.

Banking reality: a product dimension is often keyed by ``PRODUCT_ID + TERM_NO``
(or a scheme/plan code).  Joining an installment/loan table to that dimension on
``PRODUCT_ID`` alone multiplies rows, which inflates regulatory amounts.  The
platform must keep the join cardinality *unknown* and raise a business review
item instead of claiming 1:1, and it must never append the missing key to the
join condition on its own.

These tests pin that contract on the existing structured join-plan path
(``RequirementSnapshotService`` field plans + gap recommendations).
"""

from __future__ import annotations

from app.models import (
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
from app.services.requirement_snapshot import RequirementSnapshotService

TERM_MARKER = "期限"


def _seed(db, *, product_join: str, product_key_columns: list[str]):
    """Seed EAST target field fed by a mart table that joins a product dimension."""

    project = Project(name="P1-B 复合业务键项目")
    db.add(project)
    db.flush()
    table = TargetTable(project_id=project.id, table_code="EAST_LOAN", table_name="EAST借据报送表")
    scenario = ProductScenario(project_id=project.id, scenario_code="MONTHLY", scenario_name="月度报送", enabled=True)
    db.add_all([table, scenario])
    db.flush()
    target = TargetField(
        project_id=project.id,
        target_table_id=table.id,
        field_code="PRODUCT_BALANCE",
        field_name="产品余额",
        regulatory_refined_definition="按产品与期限口径报送产品余额",
    )
    db.add(target)
    db.flush()

    mart_table = MartTable(
        project_id=project.id,
        table_code="MART_LOAN_PRODUCT",
        table_name="监管借据产品集市",
        table_comment="借据与产品口径",
        schema_name="MART",
        physical_table_name="MART_LOAN_PRODUCT",
    )
    db.add(mart_table)
    db.flush()
    mart_field = MartField(
        project_id=project.id,
        mart_table_id=mart_table.id,
        field_code="PRODUCT_BALANCE",
        field_name="产品余额",
        field_comment="集市产品余额",
        physical_column_name="PRODUCT_BALANCE",
    )
    db.add(mart_field)
    db.flush()
    # The mart side carries the product key columns as well, so the join tokens
    # resolve instead of failing with an unresolved qualifier.
    for column_name in ("PRODUCT_ID", "TERM_NO"):
        db.add(
            MartField(
                project_id=project.id,
                mart_table_id=mart_table.id,
                field_code=column_name,
                field_name=column_name,
                field_comment=column_name,
                physical_column_name=column_name,
            )
        )
    db.flush()

    # The product dimension itself: physical key is PRODUCT_ID + TERM_NO.
    datasource = DataSource(project_id=project.id, name="warehouse", db_type="sqlite")
    db.add(datasource)
    db.flush()
    schema = CatalogSchema(project_id=project.id, datasource_id=datasource.id, schema_name="SRC")
    db.add(schema)
    db.flush()
    catalog_table = CatalogTable(
        project_id=project.id,
        datasource_id=datasource.id,
        catalog_schema_id=schema.id,
        schema_name="SRC",
        table_name="DIM_PRODUCT",
        primary_key_columns_json=list(product_key_columns),
    )
    db.add(catalog_table)
    db.flush()
    for column_name in product_key_columns:
        db.add(
            CatalogColumn(
                project_id=project.id,
                datasource_id=datasource.id,
                catalog_table_id=catalog_table.id,
                schema_name="SRC",
                table_name="DIM_PRODUCT",
                column_name=column_name,
                is_primary_key=True,
            )
        )
    db.add(
        CatalogColumn(
            project_id=project.id,
            datasource_id=datasource.id,
            catalog_table_id=catalog_table.id,
            schema_name="SRC",
            table_name="DIM_PRODUCT",
            column_name="PRODUCT_NAME",
            is_primary_key=False,
        )
    )

    db.add(
        MartToYbtMapping(
            project_id=project.id,
            target_field_id=target.id,
            mart_field_id=mart_field.id,
            mapping_status="approved",
            join_condition="MART_LOAN_PRODUCT.PRODUCT_BALANCE = EAST_LOAN.PRODUCT_BALANCE",
            filter_condition="STAT_DATE = :report_date",
            final_content="从集市输出产品余额",
        )
    )
    source_mapping = SourceToMartMapping(
        project_id=project.id,
        mart_field_id=mart_field.id,
        mapping_status="approved",
        source_system_summary="核心系统",
        source_tables_summary="DIM_PRODUCT",
        source_fields_summary="PRODUCT_ID",
        join_condition=product_join,
        filter_condition="STAT_DATE = :report_date",
        final_content="产品维度入集市",
    )
    db.add(source_mapping)
    db.add(
        ScenarioBusinessMapping(
            project_id=project.id,
            target_field_id=target.id,
            scenario_id=scenario.id,
            business_definition="按产品口径报送余额",
            final_content="取借据关联产品后的余额",
            business_confirm_status="confirmed",
        )
    )
    db.add(
        ScenarioTechnicalLineage(
            project_id=project.id,
            target_field_id=target.id,
            scenario_id=scenario.id,
            source_system_name="核心系统",
            source_table_english_name="DIM_PRODUCT",
            source_field_english_name="PRODUCT_ID",
            processing_logic="借据关联产品维度后取余额",
            tech_confirm_status="confirmed",
            lineage_status="linked",
        )
    )
    db.commit()
    return project, table, scenario, source_mapping.id


def _snapshot(db, project, table, scenario):
    row, _ = RequirementSnapshotService(db).create(
        project_id=project.id,
        target_table_id=table.id,
        scenario_id=scenario.id,
        created_by=None,
    )
    db.commit()
    return row.content_snapshot_json


def _source_join_plan(content):
    return next(item for item in content["field_plans"][0]["join_plans"] if item["mapping_type"] == "source_to_mart")


def _gaps_for(content, mapping_id: int) -> list[dict]:
    return [
        gap
        for gap in content["field_plans"][0]["gap_recommendations"]
        if gap.get("mapping_id") == mapping_id
    ]


def _cardinality_gaps(content, mapping_id: int) -> list[str]:
    return [
        str(gap["problem_statement"])
        for gap in _gaps_for(content, mapping_id)
        if gap["gap_type"] == "missing_join_cardinality"
    ]


def test_single_product_id_join_against_composite_key_stays_unknown(db_session):
    project, table, scenario, source_mapping_id = _seed(
        db_session,
        product_join="DIM_PRODUCT.PRODUCT_ID = MART_LOAN_PRODUCT.PRODUCT_ID",
        product_key_columns=["PRODUCT_ID", "TERM_NO"],
    )

    content = _snapshot(db_session, project, table, scenario)
    plan = _source_join_plan(content)

    assert plan["structured"] is True
    assert plan["cardinality"] == "unknown"
    assert plan["cardinality_basis"] == "none"
    assert plan["review_required"] is True
    coverage = plan["key_coverage"]
    assert coverage["left"]["declared"] == ["PRODUCT_ID", "TERM_NO"]
    assert coverage["left"]["covered"] == ["PRODUCT_ID"]
    assert coverage["left"]["complete"] is False
    assert coverage["left"]["unique"] is False
    assert [item["declared"] for item in plan["partial_unique_keys"]] == [["PRODUCT_ID", "TERM_NO"]]

    composite = [
        gap
        for gap in _gaps_for(content, source_mapping_id)
        if gap["gap_type"] == "missing_join_cardinality" and "复合唯一键" in str(gap["problem_statement"])
    ]
    assert len(composite) == 1
    gaps = composite
    statement = gaps[0]["problem_statement"]
    assert "复合唯一键" in statement
    assert "PRODUCT_ID" in statement and "TERM_NO" in statement
    assert "不得视为一对一" in gaps[0]["recommended_change"]
    assert gaps[0]["confidence_level"] == "medium"
    assert "重复累计" in gaps[0]["estimated_impact"]
    # The platform must not silently rewrite the join to add the missing key.
    assert plan["left_keys"] == ["PRODUCT_ID"]
    assert "MART_LOAN_PRODUCT" not in plan["right_keys"]


def test_full_composite_key_join_confirms_cardinality(db_session):
    project, table, scenario, source_mapping_id = _seed(
        db_session,
        product_join=(
            "DIM_PRODUCT.PRODUCT_ID = MART_LOAN_PRODUCT.PRODUCT_ID "
            "AND DIM_PRODUCT.TERM_NO = MART_LOAN_PRODUCT.TERM_NO"
        ),
        product_key_columns=["PRODUCT_ID", "TERM_NO"],
    )

    content = _snapshot(db_session, project, table, scenario)
    plan = _source_join_plan(content)

    assert plan["structured"] is True
    assert plan["key_coverage"]["left"]["complete"] is True
    assert plan["key_coverage"]["left"]["unique"] is True
    assert plan["partial_unique_keys"] == []
    assert plan["cardinality"] in {"1:1", "1:N", "N:1"}
    assert not [text for text in _cardinality_gaps(content, source_mapping_id) if "复合唯一键" in text]
    # Both key columns are covered, so the composite-key complaint must be gone.
    assert not [text for text in _cardinality_gaps(content, source_mapping_id) if "复合唯一键" in text]


def test_single_column_key_behaviour_is_unchanged(db_session):
    project, table, scenario, source_mapping_id = _seed(
        db_session,
        product_join="DIM_PRODUCT.PRODUCT_ID = MART_LOAN_PRODUCT.PRODUCT_ID",
        product_key_columns=["PRODUCT_ID"],
    )

    content = _snapshot(db_session, project, table, scenario)
    plan = _source_join_plan(content)

    assert plan["key_coverage"]["left"]["declared"] == ["PRODUCT_ID"]
    assert plan["key_coverage"]["left"]["complete"] is True
    assert plan["partial_unique_keys"] == []
    assert plan["cardinality"] in {"1:1", "1:N", "N:1"}
    assert not [text for text in _cardinality_gaps(content, source_mapping_id) if "复合唯一键" in text]
