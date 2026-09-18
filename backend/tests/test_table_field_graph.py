import pytest
from app.models import Project, TargetField, TargetTable, MartToYbtMapping
from app.services.lineage.table_graph import table_graph, search_assets
from app.services.lineage.path_resolver import LineagePathNotFound
from test_lineage_paths import _seed_assets


def test_table_graph_aggregates_fields_and_retains_real_edges(db_session):
    _, _, project, target, source, mart = _seed_assets(db_session)
    for index in range(7):
        field = TargetField(project_id=project.id, target_table_id=target.target_table_id,
            field_code=f"DEPENDENT_{index}", field_name=f"合成下游字段{index}")
        db_session.add(field)
        db_session.flush()
        db_session.add(MartToYbtMapping(project_id=project.id, target_field_id=field.id,
            mart_field_id=mart.id, mapping_status="approved", business_rule="直接映射（合成测试）"))
    db_session.flush()
    graph = table_graph(db_session, project.id, "target", target.target_table_id)
    assert len(graph["root_ids"]) == 8
    assert len(graph["tables"]) == 3
    assert len(graph["nodes"]) == 10
    target_card = next(t for t in graph["tables"] if t["id"] == f"target:{target.target_table_id}")
    assert len(target_card["fields"]) == 8
    assert len(graph["edges"]) == 9
    node_ids = {n["id"] for n in graph["nodes"]}
    assert all(e["source_node_id"] in node_ids and e["target_node_id"] in node_ids for e in graph["edges"])
    assert any(e["evidence_refs"] for e in graph["edges"])
    assert not graph["truncated"]


def test_search_accepts_names_and_field_codes_and_is_project_scoped(db_session):
    _, _, project, target, _, _ = _seed_assets(db_session)
    other = Project(name="不可见项目")
    db_session.add(other)
    db_session.flush()
    assert search_assets(db_session, project.id, "CUSTOMER_ID")["items"]
    assert search_assets(db_session, project.id, "客户报送")["items"][0]["id"] == target.target_table_id
    assert search_assets(db_session, other.id, "CUSTOMER_ID")["items"] == []
    with pytest.raises(LineagePathNotFound):
        table_graph(db_session, other.id, "target", target.target_table_id)


def test_graph_direction_and_limit_are_explicit(db_session):
    _, _, project, target, source, _ = _seed_assets(db_session)
    downstream = table_graph(db_session, project.id, "target", target.target_table_id, direction="downstream")
    assert len(downstream["nodes"]) == 1
    upstream = table_graph(db_session, project.id, "target", target.target_table_id, direction="upstream", depth=1)
    assert len(upstream["nodes"]) == 2
    assert upstream["truncated"]
    limited = table_graph(db_session, project.id, "target", target.target_table_id, max_nodes=2)
    assert len(limited["nodes"]) == 2
    assert limited["truncated"] and limited["omitted_frontier_count"] > 0


def test_isolated_fields_are_not_connected_by_similar_names(db_session):
    project = Project(name="孤立字段合成测试")
    db_session.add(project)
    db_session.flush()
    table = TargetTable(project_id=project.id, table_code="EMPTY", table_name="无关系表")
    db_session.add(table)
    db_session.flush()
    db_session.add_all([TargetField(project_id=project.id, target_table_id=table.id,
        field_code=f"NAME_{i}", field_name="同名字段") for i in range(8)])
    db_session.flush()
    graph = table_graph(db_session, project.id, "target", table.id)
    assert len(graph["nodes"]) == 8
    assert graph["edges"] == []
def test_bidirectional_paths_do_not_include_siblings():
    from app.services.lineage.table_graph import bounded_paths
    edges = [{"source_node_id": a, "target_node_id": b} for a, b in
             [("source", "root"), ("source", "sibling"), ("root", "target"), ("other", "target")]]
    selected, omitted = bounded_paths(["root"], edges, "both", 4, 100)
    assert selected == {"source", "root", "target"}
    assert not omitted


def test_path_limits_are_explicit_and_cycles_terminate():
    from app.services.lineage.table_graph import bounded_paths
    edges = [{"source_node_id": a, "target_node_id": b} for a, b in
             [("a", "b"), ("b", "c"), ("c", "a"), ("c", "d")]]
    selected, omitted = bounded_paths(["a"], edges, "downstream", 1, 100)
    assert selected == {"a", "b"}
    assert omitted == {"c"}
    selected, omitted = bounded_paths(["a"], edges, "both", 10, 3)
    assert selected == {"a", "b", "c"}
    assert omitted == {"d"}


def test_explicit_catalog_binding_projects_configured_layer_without_name_inference(db_session):
    from app.models import CatalogTable, CatalogColumn, CatalogImportBinding
    from app.services import data_architecture as architecture
    db = db_session
    _, _, project, target, source, _ = _seed_assets(db)
    architecture.save_architecture(db,architecture.examples()[1],0,project_id=project.id)
    physical = CatalogTable(project_id=project.id,datasource_id=1,catalog_schema_id=1,
        database_name="bank_a",schema_name="ods",table_name="ACCOUNT")
    db.add(physical);db.flush()
    db.add(CatalogColumn(project_id=project.id,datasource_id=1,catalog_table_id=physical.id,
        database_name="bank_a",schema_name="ods",table_name="ACCOUNT",column_name="id",data_type="INT"))
    db.add(CatalogImportBinding(project_id=project.id,catalog_table_id=physical.id,
        binding_type="source_field",source_table_id=source.source_table_id))
    db.flush()
    architecture.assign_table(db,project.id,physical.id,{"layer_key":"layer_1"},1)
    graph = table_graph(db,project.id,"target",target.target_table_id)
    card = next(t for t in graph["tables"] if t["id"]==f"source:{source.source_table_id}")
    assert card["layer"] == "ODS"
    assert card["physical_assignments"][0]["catalog_table_id"] == physical.id
    assert card["metadata_is_current"]
    found = search_assets(db,project.id)["items"]
    assert next(t for t in found if t["kind"]=="catalog")["physical_assignments"][0]["assignment"]["layer_name"] == "ODS"
    other = CatalogTable(project_id=project.id,datasource_id=2,catalog_schema_id=2,
        database_name="bank_b",schema_name="ods",table_name="ACCOUNT")
    db.add(other);db.flush()
    # Same schema/name does not acquire the first table's assignment.
    assert architecture.asset_classification_index(db,project.id)[("catalog",other.id)][0]["assignment"] == {"layer_key":None}
    db.add(CatalogImportBinding(project_id=project.id,catalog_table_id=other.id,
        binding_type="source_field",source_table_id=source.source_table_id));db.flush()
    graph = table_graph(db,project.id,"target",target.target_table_id)
    card = next(t for t in graph["tables"] if t["id"]==f"source:{source.source_table_id}")
    assert card["classification"] is None
    assert {x["database_name"] for x in card["physical_assignments"]} == {"bank_a","bank_b"}
    other_project = Project(name="other-bank");db.add(other_project);db.flush()
    assert architecture.asset_classification_index(db,other_project.id) == {}
