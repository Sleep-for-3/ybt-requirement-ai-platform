"""Contract tests for the bounded lineage graph API.

The audit found that ``direction``/``depth`` were echoed on the revision graph
branch without changing the result, and that ``view=business|technical``
returned the same business-first node projection.  These tests lock the fixed
contract: a real bounded traversal over one published revision and two
distinguishable presentation projections over the same facts.
"""

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
    MartField,
    MartTable,
    Project,
    ScriptFile,
    ScriptFileVersion,
    SourceField,
    SourceTable,
    StoredFile,
    TargetField,
    TargetTable,
    User,
)
from app.services.lineage.revisions import LineageRevisionService


def _seed_chain(db: Session, *, code: str) -> dict:
    institution = Institution(institution_code=f"GRAPH_{code}", institution_name=f"Graph Bank {code}")
    user = User(username=f"graph-user-{code}", status="active")
    db.add_all([institution, user])
    db.flush()
    project = Project(name=f"血缘图契约项目{code}", institution_id=institution.id)
    db.add(project)
    db.flush()

    target_table = TargetTable(project_id=project.id, table_code=f"EAST_{code}", table_name=f"EAST报送表{code}")
    mart_table = MartTable(
        project_id=project.id,
        table_code=f"REG_{code}",
        table_name=f"监管集市表{code}",
        schema_name="MART",
        physical_table_name=f"REG_{code}",
    )
    system = BusinessSystem(project_id=project.id, system_code=f"ECIF_{code}", system_name=f"客户信息系统{code}")
    db.add_all([target_table, mart_table, system])
    db.flush()
    source_table = SourceTable(
        project_id=project.id,
        business_system_id=system.id,
        table_code=f"CUSTOMER_{code}",
        table_name=f"客户基本信息表{code}",
        schema_name="SRC",
        physical_table_name=f"CUSTOMER_{code}",
    )
    db.add(source_table)
    db.flush()
    target_field = TargetField(
        project_id=project.id,
        target_table_id=target_table.id,
        field_code="CUSTOMER_ID",
        field_name="客户统一标识",
        regulatory_description="监管客户唯一标识",
    )
    mart_field = MartField(
        project_id=project.id,
        mart_table_id=mart_table.id,
        field_code="CUSTOMER_ID",
        field_name="客户统一标识",
        field_comment="监管集市客户统一标识",
        physical_column_name="CUSTOMER_ID",
    )
    source_field = SourceField(
        project_id=project.id,
        source_table_id=source_table.id,
        field_code="CUST_ID",
        field_name="客户统一标识",
        field_comment="源系统客户统一标识",
        physical_column_name="CUST_ID",
    )
    db.add_all([target_field, mart_field, source_field])
    db.flush()

    script = ScriptFile(
        project_id=project.id,
        relative_path="load.sql",
        file_name="load.sql",
        file_type="sql",
        current_version_no=1,
    )
    db.add(script)
    db.flush()
    stored = StoredFile(
        institution_id=institution.id,
        project_id=project.id,
        storage_key=f"projects/{project.id}/load.sql",
        original_file_name="load.sql",
        content_type="text/plain",
        byte_size=10,
        content_hash="a" * 64,
        classification="internal",
        created_by=user.id,
        enabled=True,
    )
    db.add(stored)
    db.flush()
    version = ScriptFileVersion(
        project_id=project.id,
        script_file_id=script.id,
        version_no=1,
        file_hash="b" * 64,
        normalized_hash="c" * 64,
        raw_content_storage_file_id=stored.id,
        parse_status="parsed",
    )
    db.add(version)
    db.flush()

    source_node = LineageNode(
        project_id=project.id,
        node_type="column",
        logical_name=f"SRC.CUSTOMER_{code}.CUST_ID",
        schema_name="SRC",
        table_name=f"CUSTOMER_{code}",
        column_name="CUST_ID",
        source_table_id=source_table.id,
        source_field_id=source_field.id,
        script_file_id=script.id,
        script_file_version_id=version.id,
        unresolved_flag=False,
    )
    mart_node = LineageNode(
        project_id=project.id,
        node_type="column",
        logical_name=f"MART.REG_{code}.CUSTOMER_ID",
        schema_name="MART",
        table_name=f"REG_{code}",
        column_name="CUSTOMER_ID",
        mart_table_id=mart_table.id,
        mart_field_id=mart_field.id,
        script_file_id=script.id,
        script_file_version_id=version.id,
        unresolved_flag=False,
    )
    target_node = LineageNode(
        project_id=project.id,
        node_type="column",
        logical_name=f"EAST.EAST_{code}.CUSTOMER_ID",
        schema_name="EAST",
        table_name=f"EAST_{code}",
        column_name="CUSTOMER_ID",
        target_table_id=target_table.id,
        target_field_id=target_field.id,
        script_file_id=script.id,
        script_file_version_id=version.id,
        unresolved_flag=False,
    )
    db.add_all([source_node, mart_node, target_node])
    db.flush()
    db.add_all([
        LineageEdge(
            project_id=project.id,
            script_file_version_id=version.id,
            source_node_id=source_node.id,
            target_node_id=mart_node.id,
            edge_type="derives_from",
            confidence_level="high",
            enabled=True,
        ),
        LineageEdge(
            project_id=project.id,
            script_file_version_id=version.id,
            source_node_id=mart_node.id,
            target_node_id=target_node.id,
            edge_type="derives_from",
            confidence_level="high",
            enabled=True,
        ),
    ])
    db.commit()
    revision = LineageRevisionService(db).build(project.id, created_by=user.id, publish=True)
    db.commit()
    return {
        "project_id": project.id,
        "target_table_id": target_table.id,
        "target_field_id": target_field.id,
        "source_field_id": source_field.id,
        "node_ids": {"source": source_node.id, "mart": mart_node.id, "target": target_node.id},
        "revision_id": revision.revision.id,
    }


@contextmanager
def _stack(*codes: str) -> Iterator[tuple[TestClient, dict[str, dict]]]:
    """Seed the API's own database and yield a client plus the seeded ids.

    The API dependency override must share one StaticPool connection with the
    seed session; otherwise the request thread opens a second empty
    ``sqlite://`` database and every project looks missing.
    """

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False)
    with factory() as seed:
        seed.add(Institution(institution_code="GRAPH_API", institution_name="Graph API Bank"))
        seed.commit()
        seeded = {code: _seed_chain(seed, code=code) for code in codes}

    def override() -> Iterator[Session]:
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override
    try:
        with TestClient(app) as client:
            yield client, seeded
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)


def _graph(client: TestClient, project_id: int, revision_id: int, query: str) -> tuple[int, dict]:
    response = client.get(f"/api/projects/{project_id}/lineage/graph?revision_id={revision_id}&{query}")
    return response.status_code, response.json() if response.headers.get("content-type", "").startswith("application/json") else {}


def test_bounded_traversal_respects_direction_and_depth():
    with _stack("DEPTH") as (client, seeded_by_code):
        seeded = seeded_by_code["DEPTH"]
        status, shallow = _graph(
            client, seeded["project_id"], seeded["revision_id"],
            f"root_type=target_field&root_id={seeded['target_field_id']}&direction=upstream&depth=1",
        )
        assert status == 200, shallow
        assert shallow["traversal"]["mode"] == "bounded_traversal"
        assert shallow["traversal"]["direction_applied"] is True
        assert shallow["traversal"]["depth_applied"] is True
        assert shallow["traversal"]["depth_reached"] == 1
        assert {node["id"] for node in shallow["nodes"]} == {seeded["node_ids"]["target"], seeded["node_ids"]["mart"]}
        # The requested depth cut a longer chain, so the response must say so.
        assert shallow["traversal"]["truncation_reason"] == "depth_limit"
        assert shallow["truncated"] is True

        status, deep = _graph(
            client, seeded["project_id"], seeded["revision_id"],
            f"root_type=target_field&root_id={seeded['target_field_id']}&direction=upstream&depth=3",
        )
        assert status == 200, deep
        assert {node["id"] for node in deep["nodes"]} == set(seeded["node_ids"].values())
        assert deep["traversal"]["depth_reached"] >= 2
        assert len(deep["nodes"]) > len(shallow["nodes"])


def test_downstream_direction_from_source_reaches_target():
    with _stack("DIR") as (client, seeded_by_code):
        seeded = seeded_by_code["DIR"]
        status, payload = _graph(
            client, seeded["project_id"], seeded["revision_id"],
            f"root_type=source_field&root_id={seeded['source_field_id']}&direction=downstream&depth=3",
        )
        assert status == 200, payload
        assert {node["id"] for node in payload["nodes"]} == set(seeded["node_ids"].values())

        status, upstream_only = _graph(
            client, seeded["project_id"], seeded["revision_id"],
            f"root_type=source_field&root_id={seeded['source_field_id']}&direction=upstream&depth=3",
        )
        assert status == 200, upstream_only
        assert {node["id"] for node in upstream_only["nodes"]} == {seeded["node_ids"]["source"]}


def test_direction_without_root_is_rejected_instead_of_echoed():
    with _stack("NOROOT") as (client, seeded_by_code):
        seeded = seeded_by_code["NOROOT"]
        status, payload = _graph(
            client, seeded["project_id"], seeded["revision_id"], "direction=upstream&depth=2"
        )
        assert status == 400, payload
        assert "root_type" in payload["detail"]


def test_snapshot_mode_does_not_claim_direction_was_applied():
    with _stack("SNAP") as (client, seeded_by_code):
        seeded = seeded_by_code["SNAP"]
        status, payload = _graph(client, seeded["project_id"], seeded["revision_id"], "")
        assert status == 200, payload
        assert payload["traversal"]["mode"] == "revision_snapshot"
        assert payload["traversal"]["direction_applied"] is False
        assert payload["traversal"]["depth_applied"] is False
        assert payload["traversal"]["returned_node_count"] == len(payload["nodes"])


def test_business_and_technical_views_project_the_same_facts_differently():
    with _stack("VIEW") as (client, seeded_by_code):
        seeded = seeded_by_code["VIEW"]
        root_query = f"root_type=target_field&root_id={seeded['target_field_id']}&direction=upstream&depth=3"
        status, business = _graph(client, seeded["project_id"], seeded["revision_id"], f"{root_query}&view=business")
        assert status == 200, business
        status, technical = _graph(client, seeded["project_id"], seeded["revision_id"], f"{root_query}&view=technical")
        assert status == 200, technical

        assert {node["id"] for node in business["nodes"]} == {node["id"] for node in technical["nodes"]}
        business_target = next(node for node in business["nodes"] if node["id"] == seeded["node_ids"]["target"])
        technical_target = next(node for node in technical["nodes"] if node["id"] == seeded["node_ids"]["target"])
        assert business_target["display"]["display_name"] == "客户统一标识"
        assert business_target["projection"]["primary_source"] != "technical_identifier"
        assert technical_target["display"]["display_name"] == technical_target["display"]["technical_identifier"]
        assert technical_target["projection"]["primary_source"] == "technical_identifier"
        assert technical_target["display"]["business_display_name"] == "客户统一标识"
        assert technical_target["projection"]["secondary"] == "客户统一标识"
        assert business_target["projection"]["primary"] != technical_target["projection"]["primary"]


def test_cross_project_root_is_not_visible():
    with _stack("ISO1", "ISO2") as (client, seeded_by_code):
        first = seeded_by_code["ISO1"]
        second = seeded_by_code["ISO2"]
        status, payload = _graph(
            client, first["project_id"], first["revision_id"],
            f"root_type=target_field&root_id={second['target_field_id']}&direction=upstream&depth=3",
        )
        assert status == 404, payload


def test_node_budget_reports_truncation_reason():
    with _stack("BUDGET") as (client, seeded_by_code):
        seeded = seeded_by_code["BUDGET"]
        status, payload = _graph(
            client, seeded["project_id"], seeded["revision_id"],
            f"root_type=target_field&root_id={seeded['target_field_id']}&direction=upstream&depth=3&limit=2",
        )
        assert status == 200, payload
        assert payload["truncated"] is True
        assert payload["traversal"]["truncation_reason"] == "node_budget"
        assert payload["traversal"]["returned_node_count"] <= 2
        assert payload["traversal"]["node_budget"] == 2


def test_path_api_applies_the_requested_view():
    with _stack("PATHVIEW") as (client, seeded_by_code):
        seeded = seeded_by_code["PATHVIEW"]
        base = f"root_type=target_field&root_id={seeded['target_field_id']}&direction=upstream&depth=3"
        business = client.get(f"/api/projects/{seeded['project_id']}/lineage/path?{base}&view=business").json()
        technical = client.get(f"/api/projects/{seeded['project_id']}/lineage/path?{base}&view=technical").json()
        assert business["view"] == "business"
        assert technical["view"] == "technical"
        business_root = business["nodes"][0]
        technical_root = technical["nodes"][0]
        assert business_root["display"]["display_name"] == "客户统一标识"
        assert technical_root["display"]["display_name"] == technical_root["display"]["technical_identifier"]
        assert business_root["projection"]["primary"] != technical_root["projection"]["primary"]
