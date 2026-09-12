from app.models import (
    BusinessSystem,
    LineageNode,
    MartField,
    MartTable,
    Project,
    SourceField,
    SourceTable,
    TargetField,
    TargetTable,
)
from app.services.asset_display import AssetDisplayResolver


def test_target_field_uses_business_name_first_and_preserves_technical_name(db_session):
    project = Project(name="业务名称项目")
    db_session.add(project)
    db_session.flush()
    table = TargetTable(project_id=project.id, table_code="RPT_CUSTOMER", table_name="客户监管报表")
    db_session.add(table)
    db_session.flush()
    field = TargetField(
        project_id=project.id,
        target_table_id=table.id,
        field_code="CUST_ID",
        field_name="客户统一标识",
        regulatory_refined_definition="跨系统识别同一客户",
        field_type="VARCHAR",
    )
    db_session.add(field)
    db_session.commit()

    result = AssetDisplayResolver(db_session).resolve("target_field", field.id, project_id=project.id)
    assert result is not None
    assert result["display_name"] == "客户统一标识"
    assert result["display_name_source"] == "business_name"
    assert result["label_quality"] == "available"
    assert result["technical_name"] == "CUST_ID"
    assert result["qualified_technical_name"] == "RPT_CUSTOMER.CUST_ID"
    assert result["layer_name"] == "监管输出"


def test_source_field_includes_system_and_qualified_physical_name(db_session):
    project = Project(name="源系统名称项目")
    db_session.add(project)
    db_session.flush()
    system = BusinessSystem(project_id=project.id, system_code="CRM", system_name="客户信息系统")
    db_session.add(system)
    db_session.flush()
    table = SourceTable(
        project_id=project.id,
        business_system_id=system.id,
        table_code="ODS_CUSTOMER",
        table_name="客户源表",
        database_name="dw",
        schema_name="ods",
        physical_table_name="ods_customer",
    )
    field = SourceField(
        project_id=project.id,
        source_table_id=table.id,
        field_code="CUST_ID",
        field_name="客户标识",
        field_comment="客户主键",
        physical_column_name="cust_id",
    )
    db_session.add(table)
    db_session.flush()
    field.source_table_id = table.id
    db_session.add(field)
    db_session.commit()

    result = AssetDisplayResolver(db_session).resolve("source_field", field.id, project_id=project.id)
    assert result is not None
    assert result["display_name"] == "客户标识"
    assert result["comment"] == "客户主键"
    assert result["qualified_technical_name"] == "dw.ods.ods_customer.cust_id"
    assert result["system_name"] == "客户信息系统"
    assert result["layer_code"] == "SOURCE"


def test_lineage_node_prefers_linked_canonical_asset_and_falls_back_safely(db_session):
    project = Project(name="血缘节点显示项目")
    db_session.add(project)
    db_session.flush()
    table = MartTable(project_id=project.id, table_code="MART_CUSTOMER", table_name="监管集市客户")
    db_session.add(table)
    db_session.flush()
    field = MartField(project_id=project.id, mart_table_id=table.id, field_code="CUST_ID", field_name="集市客户标识", field_comment="监管集市客户主键")
    db_session.add(field)
    db_session.flush()
    linked = LineageNode(
        project_id=project.id,
        node_type="mart_field",
        logical_name="MART_CUSTOMER.CUST_ID",
        table_name="MART_CUSTOMER",
        column_name="CUST_ID",
        mart_field_id=field.id,
        unresolved_flag=False,
    )
    unresolved = LineageNode(
        project_id=project.id,
        node_type="unknown",
        logical_name="UNKNOWN_SCHEMA.UNKNOWN_FIELD",
        schema_name="unknown_schema",
        column_name="UNKNOWN_FIELD",
        metadata_json={"comment": "待人工确认字段"},
        unresolved_flag=True,
    )
    db_session.add_all([linked, unresolved])
    db_session.commit()

    resolver = AssetDisplayResolver(db_session)
    linked_result = resolver.describe_lineage_node(linked)
    fallback_result = resolver.describe_lineage_node(unresolved)
    assert linked_result["display_name"] == "集市客户标识"
    assert linked_result["canonical_entity_id"] == field.id
    assert linked_result["layer_code"] == "MART"
    assert fallback_result["display_name"] == "待人工确认字段"
    assert fallback_result["label_quality"] == "available"
    assert fallback_result["canonical_entity_id"] is None


def test_resolver_rejects_cross_project_lookup(db_session):
    first = Project(name="项目一")
    second = Project(name="项目二")
    db_session.add_all([first, second])
    db_session.flush()
    table = TargetTable(project_id=first.id, table_code="T1", table_name="项目一目标")
    db_session.add(table)
    db_session.commit()

    assert AssetDisplayResolver(db_session).resolve("target_table", table.id, project_id=second.id) is None
