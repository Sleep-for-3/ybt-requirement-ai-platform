from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app
from app.models import (
    BusinessSystem,
    Institution,
    LineageEdge,
    LineageNode,
    MappingEvidenceReference,
    MartField,
    MartTable,
    MartToYbtMapping,
    Project,
    ScriptFile,
    ScriptFileVersion,
    SourceField,
    SourceTable,
    SourceToMartMapping,
    StoredFile,
    TargetField,
    TargetTable,
    User,
)
from app.schemas.lineage import LineagePathResponse
from app.services.lineage.path_resolver import LineagePathNotFound, LineagePathResolver
from app.services.lineage.revisions import LineageRevisionService


def _seed_assets(db_session):
    institution = Institution(institution_code="PATH", institution_name="Path Bank")
    user = User(username="path-user", status="active")
    db_session.add_all([institution, user])
    db_session.flush()
    project = Project(name="端到端路径项目", institution_id=institution.id)
    db_session.add(project)
    db_session.flush()

    target_table = TargetTable(project_id=project.id, table_code="EAST_CUSTOMER", table_name="EAST客户报送表")
    db_session.add(target_table)
    db_session.flush()
    target_field = TargetField(
        project_id=project.id,
        target_table_id=target_table.id,
        field_code="CUSTOMER_ID",
        field_name="客户统一标识",
        regulatory_description="监管客户唯一标识",
    )
    system = BusinessSystem(project_id=project.id, system_code="ECIF", system_name="客户信息系统")
    db_session.add_all([target_field, system])
    db_session.flush()
    source_table = SourceTable(
        project_id=project.id,
        business_system_id=system.id,
        table_code="CUSTOMER",
        table_name="客户基本信息表",
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
    db_session.add_all([source_table, mart_table])
    db_session.flush()
    source_field = SourceField(
        project_id=project.id,
        source_table_id=source_table.id,
        field_code="CUST_ID",
        field_name="客户统一标识",
        field_comment="源系统客户统一标识",
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
    db_session.add_all([source_field, mart_field])
    db_session.flush()

    source_mapping = SourceToMartMapping(
        project_id=project.id,
        mart_field_id=mart_field.id,
        mapping_name="客户标识入监管集市",
        mapping_status="approved",
        source_system_summary="客户信息系统",
        source_tables_summary="CUSTOMER",
        source_fields_summary="CUST_ID",
        business_rule="按客户主键直接映射",
        join_condition="SRC.CUSTOMER.CUST_ID = ODS.CUSTOMER.CUST_ID",
        filter_condition="SRC.CUSTOMER.IS_DELETED = 0",
        code_mapping_rule="TRIM(CUST_ID)",
        quality_check_rule="CUSTOMER_ID IS NOT NULL",
        confidence_level="high",
    )
    target_mapping = MartToYbtMapping(
        project_id=project.id,
        target_field_id=target_field.id,
        mart_field_id=mart_field.id,
        mapping_name="监管集市到EAST",
        mapping_status="approved",
        business_rule="从监管客户集市输出客户统一标识",
        filter_condition="STAT_DATE = :report_date",
        validation_rule="长度不超过64位",
        confidence_level="high",
    )
    db_session.add_all([source_mapping, target_mapping])
    db_session.flush()
    db_session.add(MappingEvidenceReference(
        project_id=project.id,
        mapping_type="source_to_mart",
        mapping_id=source_mapping.id,
        evidence_type="source_field",
        evidence_id=source_field.id,
        source_name="ECIF.SRC.CUSTOMER.CUST_ID",
        location_text="数据字典/客户表/CUST_ID",
        evidence_summary="已确认来源字段",
    ))
    db_session.flush()
    return institution, user, project, target_field, source_field, mart_field


def _seed_script_graph(
    db_session,
    *,
    institution,
    user,
    project,
    target_field,
    source_field,
    mart_field,
    version_no: int,
    filter_condition: str,
):
    script = db_session.query(ScriptFile).filter_by(project_id=project.id, relative_path="etl/customer.sql").one_or_none()
    if script is None:
        script = ScriptFile(
            institution_id=institution.id,
            project_id=project.id,
            relative_path="etl/customer.sql",
            file_name="customer.sql",
            file_type="sql",
            current_version_no=version_no,
        )
        db_session.add(script)
        db_session.flush()
    else:
        script.current_version_no = version_no
    stored = StoredFile(
        institution_id=institution.id,
        project_id=project.id,
        storage_key=f"projects/{project.id}/{version_no}.sql",
        original_file_name="customer.sql",
        content_type="text/plain",
        byte_size=100,
        content_hash=f"{version_no}" * 64,
        classification="internal",
        created_by=user.id,
        enabled=True,
    )
    db_session.add(stored)
    db_session.flush()
    version = ScriptFileVersion(
        project_id=project.id,
        script_file_id=script.id,
        version_no=version_no,
        file_hash=f"{version_no}" * 64,
        normalized_hash=f"{version_no + 2}" * 64,
        raw_content_storage_file_id=stored.id,
        parse_status="parsed",
        dialect="sqlite",
        created_by=user.id,
    )
    db_session.add(version)
    db_session.flush()

    nodes = [
        LineageNode(
            institution_id=institution.id,
            project_id=project.id,
            node_type="column",
            logical_name="ECIF.SRC.CUSTOMER.CUST_ID",
            schema_name="SRC",
            table_name="CUSTOMER",
            column_name="CUST_ID",
            source_field_id=source_field.id,
            script_file_id=script.id,
            script_file_version_id=version.id,
            unresolved_flag=False,
        ),
        LineageNode(
            institution_id=institution.id,
            project_id=project.id,
            node_type="column",
            logical_name="ODS.CUSTOMER.CUSTOMER_ID",
            schema_name="ODS",
            table_name="CUSTOMER",
            column_name="CUSTOMER_ID",
            script_file_id=script.id,
            script_file_version_id=version.id,
            unresolved_flag=False,
            metadata_json={"layer_code": "ODS", "business_name": "ODS客户统一标识"},
        ),
        LineageNode(
            institution_id=institution.id,
            project_id=project.id,
            node_type="column",
            logical_name="DWD.CUSTOMER_DETAIL.CUSTOMER_ID",
            schema_name="DWD",
            table_name="CUSTOMER_DETAIL",
            column_name="CUSTOMER_ID",
            script_file_id=script.id,
            script_file_version_id=version.id,
            unresolved_flag=False,
            metadata_json={"layer_code": "DWD", "business_name": "客户明细统一标识"},
        ),
        LineageNode(
            institution_id=institution.id,
            project_id=project.id,
            node_type="column",
            logical_name="MART.REG_CUSTOMER.CUSTOMER_ID",
            schema_name="MART",
            table_name="REG_CUSTOMER",
            column_name="CUSTOMER_ID",
            mart_field_id=mart_field.id,
            script_file_id=script.id,
            script_file_version_id=version.id,
            unresolved_flag=False,
        ),
        LineageNode(
            institution_id=institution.id,
            project_id=project.id,
            node_type="column",
            logical_name="EAST.EAST_CUSTOMER.CUSTOMER_ID",
            schema_name="EAST",
            table_name="EAST_CUSTOMER",
            column_name="CUSTOMER_ID",
            target_field_id=target_field.id,
            script_file_id=script.id,
            script_file_version_id=version.id,
            unresolved_flag=False,
        ),
    ]
    db_session.add_all(nodes)
    db_session.flush()
    edge_specs = [
        (nodes[0], nodes[1], "projection", None, None),
        (nodes[1], nodes[2], "join", "ODS.CUSTOMER.CUSTOMER_ID = ODS.ACCOUNT.CUSTOMER_ID", filter_condition),
        (nodes[2], nodes[3], "expression", None, None),
        (nodes[3], nodes[4], "projection", None, "STAT_DATE = :report_date"),
    ]
    for index, (source, target, edge_type, join_condition, edge_filter) in enumerate(edge_specs, start=1):
        db_session.add(LineageEdge(
            institution_id=institution.id,
            project_id=project.id,
            script_file_version_id=version.id,
            source_node_id=source.id,
            target_node_id=target.id,
            edge_type=edge_type,
            transformation_type="direct" if edge_type == "projection" else edge_type,
            transformation_expression="TRIM(CUSTOMER_ID)" if edge_type == "expression" else None,
            join_condition=join_condition,
            filter_condition=edge_filter,
            source_line_start=index * 10,
            source_line_end=index * 10 + 2,
            confidence_level="high",
            evidence_json={"parser": "sqlglot"},
            enabled=True,
        ))
    db_session.flush()
    return script, version


def test_versioned_end_to_end_path_contains_layers_rules_and_script_evidence(db_session):
    institution, user, project, target_field, source_field, mart_field = _seed_assets(db_session)
    _seed_script_graph(
        db_session,
        institution=institution,
        user=user,
        project=project,
        target_field=target_field,
        source_field=source_field,
        mart_field=mart_field,
        version_no=1,
        filter_condition="ODS.CUSTOMER.STATUS = 'ACTIVE'",
    )
    db_session.commit()
    revision = LineageRevisionService(db_session).build(project.id, created_by=user.id, publish=True).revision
    db_session.commit()

    payload = LineagePathResolver(db_session).resolve(
        project.id,
        root_entity_type="target_field",
        root_entity_id=target_field.id,
        direction="upstream",
        depth=10,
    )
    validated = LineagePathResponse.model_validate(payload)
    assert validated.revision_id == revision.id
    assert validated.root["display"]["display_name"] == "客户统一标识"
    assert {item.layer_code for item in validated.nodes} >= {"SOURCE", "ODS", "DWD", "MART", "TARGET"}
    assert any(item.complete for item in validated.paths)
    assert any(item.join_condition == "ODS.CUSTOMER.CUSTOMER_ID = ODS.ACCOUNT.CUSTOMER_ID" for item in validated.edges)
    assert any(item.join_condition == "SRC.CUSTOMER.CUST_ID = ODS.CUSTOMER.CUST_ID" for item in validated.edges)
    assert any(item.filter_condition == "ODS.CUSTOMER.STATUS = 'ACTIVE'" for item in validated.edges)
    assert any(
        evidence.get("relative_path") == "etl/customer.sql"
        for edge in validated.edges
        for evidence in edge.evidence_refs
    )
    assert any(item.source_line_start == 20 for item in validated.edges)
    assert all("display_name" in item.display for item in validated.nodes)


def test_explicit_revision_keeps_historical_path_separate_from_latest_published(db_session):
    institution, user, project, target_field, source_field, mart_field = _seed_assets(db_session)
    _seed_script_graph(
        db_session,
        institution=institution,
        user=user,
        project=project,
        target_field=target_field,
        source_field=source_field,
        mart_field=mart_field,
        version_no=1,
        filter_condition="STATUS = 'A'",
    )
    db_session.commit()
    first = LineageRevisionService(db_session).build(project.id, created_by=user.id, publish=True).revision
    db_session.commit()
    _seed_script_graph(
        db_session,
        institution=institution,
        user=user,
        project=project,
        target_field=target_field,
        source_field=source_field,
        mart_field=mart_field,
        version_no=2,
        filter_condition="STATUS = 'B'",
    )
    db_session.commit()
    second = LineageRevisionService(db_session).build(project.id, created_by=user.id).revision
    db_session.commit()

    default_path = LineagePathResolver(db_session).resolve(
        project.id,
        root_entity_type="target_field",
        root_entity_id=target_field.id,
    )
    draft_path = LineagePathResolver(db_session).resolve(
        project.id,
        root_entity_type="target_field",
        root_entity_id=target_field.id,
        lineage_revision_id=second.id,
    )
    assert default_path["revision_id"] == first.id
    assert draft_path["revision_id"] == second.id
    assert "STATUS = 'A'" in {edge["filter_condition"] for edge in default_path["edges"]}
    assert "STATUS = 'B'" in {edge["filter_condition"] for edge in draft_path["edges"]}


def test_missing_canonical_source_binding_returns_auditable_gap(db_session):
    institution = Institution(institution_code="PATH_GAP", institution_name="Gap Bank")
    db_session.add(institution)
    db_session.flush()
    project = Project(name="gap", institution_id=institution.id)
    db_session.add(project)
    db_session.flush()
    target_table = TargetTable(project_id=project.id, table_code="T", table_name="目标表")
    mart_table = MartTable(project_id=project.id, table_code="M", table_name="集市表")
    db_session.add_all([target_table, mart_table])
    db_session.flush()
    target = TargetField(project_id=project.id, target_table_id=target_table.id, field_code="F", field_name="目标字段")
    mart = MartField(project_id=project.id, mart_table_id=mart_table.id, field_code="F", field_name="集市字段")
    db_session.add_all([target, mart])
    db_session.flush()
    db_session.add_all([
        MartToYbtMapping(
            project_id=project.id,
            target_field_id=target.id,
            mart_field_id=mart.id,
            mapping_status="approved",
            confidence_level="high",
        ),
        SourceToMartMapping(
            project_id=project.id,
            mart_field_id=mart.id,
            mapping_status="approved",
            source_tables_summary="ONLY_A_STRING_TABLE",
            source_fields_summary="ONLY_A_STRING_FIELD",
            confidence_level="high",
        ),
    ])
    db_session.commit()

    payload = LineagePathResolver(db_session).resolve(
        project.id,
        root_entity_type="target_field",
        root_entity_id=target.id,
        include_unresolved=True,
    )
    assert payload["revision_id"] is None
    assert any(item["unresolved_flag"] for item in payload["nodes"])
    assert any(item["gap_type"] == "missing_asset_binding" for item in payload["gap_recommendations"])
    assert any(item["gap_type"] == "missing_lineage_revision" for item in payload["gap_recommendations"])
    assert all(item["complete"] is False for item in payload["paths"])


def test_cross_project_root_and_revision_are_hidden(db_session):
    _, _, project, target_field, _, _ = _seed_assets(db_session)
    other = Project(name="other")
    db_session.add(other)
    db_session.commit()
    resolver = LineagePathResolver(db_session)

    try:
        resolver.resolve(other.id, root_entity_type="target_field", root_entity_id=target_field.id)
    except LineagePathNotFound:
        pass
    else:
        raise AssertionError("cross-project root must not be visible")


def test_lineage_path_api_validates_scope_and_serializes_contract():
    with _api_client() as (client, factory):
        with factory() as db_session:
            institution, user, project, target_field, source_field, mart_field = _seed_assets(db_session)
            _seed_script_graph(
                db_session,
                institution=institution,
                user=user,
                project=project,
                target_field=target_field,
                source_field=source_field,
                mart_field=mart_field,
                version_no=1,
                filter_condition="STATUS = 'ACTIVE'",
            )
            db_session.commit()
            revision = LineageRevisionService(db_session).build(project.id, created_by=user.id, publish=True).revision
            db_session.commit()
            project_id = project.id
            target_field_id = target_field.id
            revision_id = revision.id
            other = Project(name="API other")
            db_session.add(other)
            db_session.commit()
            other_project_id = other.id

        response = client.get(
            f"/api/projects/{project_id}/lineage/path",
            params={
                "root_type": "target_field",
                "root_id": target_field_id,
                "revision_id": revision_id,
                "direction": "upstream",
                "depth": 10,
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["revision_id"] == revision_id
        assert response.json()["paths"]
        hidden = client.get(
            f"/api/projects/{other_project_id}/lineage/path",
            params={"root_type": "target_field", "root_id": target_field_id},
        )
        assert hidden.status_code == 404


@contextmanager
def _api_client() -> Iterator[tuple[TestClient, sessionmaker]]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False)

    def override() -> Iterator[Session]:
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override
    try:
        with TestClient(app) as client:
            yield client, factory
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
