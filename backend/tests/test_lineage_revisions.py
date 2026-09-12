from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app
from app.models import (
    Institution,
    ImpactAnalysis,
    LineageEdge,
    LineageNode,
    Project,
    ScriptChangeSet,
    ScriptFile,
    ScriptFileVersion,
    StoredFile,
    User,
)
from app.services.lineage.revisions import LineageRevisionService
from app.services.storage.local import LocalStorageService


def _seed_version(db_session, project: Project, script: ScriptFile, version_no: int, *, file_hash: str, normalized_hash: str, parse_status: str = "parsed", created_by: int):
    stored = StoredFile(
        institution_id=project.institution_id,
        project_id=project.id,
        storage_key=f"projects/{project.id}/{version_no}.sql",
        original_file_name="load.sql",
        content_type="text/plain",
        byte_size=10,
        content_hash=file_hash,
        classification="internal",
        created_by=created_by,
        enabled=True,
    )
    db_session.add(stored)
    db_session.flush()
    version = ScriptFileVersion(
        project_id=project.id,
        script_file_id=script.id,
        version_no=version_no,
        file_hash=file_hash,
        normalized_hash=normalized_hash,
        raw_content_storage_file_id=stored.id,
        parse_status=parse_status,
    )
    db_session.add(version)
    db_session.flush()
    return version


def _seed_graph(db_session, project: Project, script: ScriptFile, version: ScriptFileVersion, *, join_condition: str | None = None, filter_condition: str | None = None, column: str = "A"):
    source = LineageNode(
        project_id=project.id,
        node_type="column",
        logical_name=f"ODS.S.{column}",
        schema_name="ODS",
        table_name="S",
        column_name=column,
        script_file_id=script.id,
        script_file_version_id=version.id,
        unresolved_flag=True,
    )
    target = LineageNode(
        project_id=project.id,
        node_type="column",
        logical_name=f"MART.T.{column}",
        schema_name="MART",
        table_name="T",
        column_name=column,
        script_file_id=script.id,
        script_file_version_id=version.id,
        unresolved_flag=True,
    )
    db_session.add_all([source, target])
    db_session.flush()
    edge = LineageEdge(
        project_id=project.id,
        script_file_version_id=version.id,
        source_node_id=source.id,
        target_node_id=target.id,
        edge_type="derives_from",
        join_condition=join_condition,
        filter_condition=filter_condition,
        confidence_level="high",
        enabled=True,
    )
    db_session.add(edge)
    db_session.flush()
    return source, target, edge


def test_revision_build_is_immutable_and_idempotent(db_session):
    institution = Institution(institution_code="REV1", institution_name="Revision Bank")
    user = User(username="revision-user-1", status="active")
    db_session.add_all([institution, user])
    db_session.flush()
    project = Project(name="revision project", institution_id=institution.id)
    db_session.add(project)
    db_session.flush()
    script = ScriptFile(project_id=project.id, relative_path="load.sql", file_name="load.sql", file_type="sql", current_version_no=1)
    db_session.add(script)
    db_session.flush()
    version = _seed_version(db_session, project, script, 1, file_hash="a" * 64, normalized_hash="b" * 64, created_by=user.id)
    _seed_graph(db_session, project, script, version, filter_condition="status = 'A'")
    db_session.commit()

    service = LineageRevisionService(db_session)
    first = service.build(project.id, publish=True)
    db_session.commit()
    assert first.revision.status == "published"
    assert first.revision.node_count == 2
    assert first.revision.edge_count == 1

    replay = service.build(project.id, publish=True)
    assert replay.idempotent is True
    assert replay.revision.id == first.revision.id

    # Mutating the parser fact later must not mutate the serialized revision.
    node = db_session.query(LineageNode).filter_by(script_file_version_id=version.id).first()
    node.logical_name = "ODS.S.CHANGED"
    db_session.flush()
    historical_nodes, _ = service.members(first.revision)
    assert any(item["logical_name"] == "ODS.S.A" for item in historical_nodes)


def test_revision_diff_classifies_filter_join_and_script_changes(db_session):
    institution = Institution(institution_code="REV2", institution_name="Revision Diff Bank")
    user = User(username="revision-user-2", status="active")
    db_session.add_all([institution, user])
    db_session.flush()
    project = Project(name="revision diff", institution_id=institution.id)
    db_session.add(project)
    db_session.flush()
    script = ScriptFile(project_id=project.id, relative_path="load.sql", file_name="load.sql", file_type="sql", current_version_no=1)
    db_session.add(script)
    db_session.flush()
    first_version = _seed_version(db_session, project, script, 1, file_hash="c" * 64, normalized_hash="d" * 64, created_by=user.id)
    _seed_graph(db_session, project, script, first_version, join_condition="s.id = d.id", filter_condition="status = 'A'")
    db_session.commit()
    service = LineageRevisionService(db_session)
    first = service.build(project.id, publish=True)
    db_session.commit()

    script.current_version_no = 2
    second_version = _seed_version(db_session, project, script, 2, file_hash="e" * 64, normalized_hash="f" * 64, created_by=user.id)
    _seed_graph(db_session, project, script, second_version, join_condition="s.customer_id = d.customer_id", filter_condition="status = 'B'")
    db_session.commit()
    second = service.build(project.id)
    db_session.commit()

    diff = service.diff(second.revision, first.revision)
    categories = {item["change_category"] for item in diff["items"]}
    assert "join_changed" in categories
    assert "filter_changed" in categories
    assert diff["semantic_changed"] is True
    assert diff["severity"] == "critical" or diff["severity"] == "high"

    readiness = service.publication_readiness(second.revision)
    assert readiness["review_required"] is True
    assert readiness["ready"] is False
    assert any("缺少影响分析" in item for item in readiness["blockers"])
    with pytest.raises(ValueError, match="not publishable"):
        service.publish(second.revision, commit=False)

    change_set = ScriptChangeSet(
        project_id=project.id,
        script_file_id=script.id,
        from_version_id=first_version.id,
        to_version_id=second_version.id,
        change_type="modified",
        status="completed",
        summary_json={},
        created_by=user.id,
    )
    db_session.add(change_set)
    db_session.flush()
    impact = ImpactAnalysis(
        institution_id=institution.id,
        project_id=project.id,
        change_set_id=change_set.id,
        status="completed",
        severity="high",
    )
    db_session.add(impact)
    db_session.flush()
    pending = service.publication_readiness(second.revision)
    assert pending["pending_impact_ids"] == [impact.id]
    impact.status = "reviewed"
    db_session.flush()
    assert service.publication_readiness(second.revision)["ready"] is True
    service.publish(second.revision, commit=False)
    assert second.revision.status == "published"


def test_column_rename_is_reported_once_instead_of_add_and_remove(db_session):
    institution = Institution(institution_code="REV_RENAME", institution_name="Rename Bank")
    user = User(username="revision-user-rename", status="active")
    db_session.add_all([institution, user])
    db_session.flush()
    project = Project(name="rename project", institution_id=institution.id)
    db_session.add(project)
    db_session.flush()
    script = ScriptFile(project_id=project.id, relative_path="load.sql", file_name="load.sql", file_type="sql", current_version_no=1)
    db_session.add(script)
    db_session.flush()
    first_version = _seed_version(db_session, project, script, 1, file_hash="1" * 64, normalized_hash="2" * 64, created_by=user.id)
    _seed_graph(db_session, project, script, first_version, column="CUSTOMER_CODE")
    db_session.commit()
    service = LineageRevisionService(db_session)
    first = service.build(project.id, publish=True)
    db_session.commit()

    script.current_version_no = 2
    second_version = _seed_version(db_session, project, script, 2, file_hash="3" * 64, normalized_hash="4" * 64, created_by=user.id)
    _seed_graph(db_session, project, script, second_version, column="CUSTOMER_ID")
    db_session.commit()
    second = service.build(project.id)
    db_session.commit()

    diff = service.diff(second.revision, first.revision)
    categories = [item["change_category"] for item in diff["items"]]
    renamed = [item for item in diff["items"] if item["change_category"] == "field_renamed"]
    # One rename of one column touches a source node and a target node, so it
    # must stay exactly two reviewable items and never look like a drop plus an
    # unrelated addition.
    assert len(renamed) == 2
    assert "node_removed" not in categories
    assert "node_added" not in categories
    assert {item["old_value"]["column_name"] for item in renamed} == {"CUSTOMER_CODE"}
    assert {item["new_value"]["column_name"] for item in renamed} == {"CUSTOMER_ID"}
    assert all(item["severity"] == "high" for item in renamed)
    assert all(item["match_confidence"] >= 0.65 for item in renamed)


def test_unrelated_column_similarity_below_threshold_stays_add_and_remove(db_session):
    institution = Institution(institution_code="REV_DROP", institution_name="Drop Bank")
    user = User(username="revision-user-drop", status="active")
    db_session.add_all([institution, user])
    db_session.flush()
    project = Project(name="drop project", institution_id=institution.id)
    db_session.add(project)
    db_session.flush()
    script = ScriptFile(project_id=project.id, relative_path="load.sql", file_name="load.sql", file_type="sql", current_version_no=1)
    db_session.add(script)
    db_session.flush()
    first_version = _seed_version(db_session, project, script, 1, file_hash="5" * 64, normalized_hash="6" * 64, created_by=user.id)
    _seed_graph(db_session, project, script, first_version, column="A")
    db_session.commit()
    service = LineageRevisionService(db_session)
    first = service.build(project.id, publish=True)
    db_session.commit()

    script.current_version_no = 2
    second_version = _seed_version(db_session, project, script, 2, file_hash="7" * 64, normalized_hash="8" * 64, created_by=user.id)
    _seed_graph(db_session, project, script, second_version, column="UNRELATED_COLUMN")
    db_session.commit()
    second = service.build(project.id)
    db_session.commit()

    diff = service.diff(second.revision, first.revision)
    categories = {item["change_category"] for item in diff["items"]}
    assert "field_renamed" not in categories
    assert "node_removed" in categories
    assert "node_added" in categories


def test_parse_warning_revision_is_not_publishable(db_session):
    institution = Institution(institution_code="REV3", institution_name="Failed Revision Bank")
    user = User(username="revision-user-3", status="active")
    db_session.add_all([institution, user])
    db_session.flush()
    project = Project(name="failed revision", institution_id=institution.id)
    db_session.add(project)
    db_session.flush()
    script = ScriptFile(project_id=project.id, relative_path="broken.sql", file_name="broken.sql", file_type="sql", current_version_no=1)
    db_session.add(script)
    db_session.flush()
    _seed_version(db_session, project, script, 1, file_hash="1" * 64, normalized_hash="2" * 64, parse_status="failed", created_by=user.id)
    db_session.commit()
    service = LineageRevisionService(db_session)
    result = service.build(project.id, publish=True)
    assert result.revision.status == "needs_review"
    with pytest.raises(ValueError, match="not publishable"):
        service.publish(result.revision)
    assert result.revision.status == "needs_review"


def test_revision_build_rejects_direct_terminal_status(db_session):
    institution = Institution(institution_code="REV4", institution_name="Status Guard Bank")
    db_session.add(institution)
    db_session.flush()
    project = Project(name="status guard", institution_id=institution.id)
    db_session.add(project)
    db_session.flush()

    with pytest.raises(ValueError, match="Invalid lineage revision status"):
        LineageRevisionService(db_session).build(project.id, status="published")


def test_revision_api_lists_reads_diffs_and_graphs(monkeypatch, tmp_path: Path):
    import app.api.lineage as lineage_api

    monkeypatch.setattr(lineage_api, "get_storage_service", lambda: LocalStorageService(tmp_path / "storage"))
    with _client() as client:
        project = client.post("/api/projects", json={"name": "revision api", "institution_id": 1}).json()
        first = client.post(
            f"/api/projects/{project['id']}/scripts/upload",
            data={"relative_path": "load.sql", "dialect": "sqlite"},
            files={"file": ("load.sql", b"insert into MART.T (A) select A from ODS.S", "text/plain")},
        )
        assert first.status_code == 200, first.text
        first_revision_id = first.json()["lineage_revision_id"]
        assert first_revision_id
        revisions = client.get(f"/api/projects/{project['id']}/lineage/revisions")
        assert revisions.status_code == 200, revisions.text
        assert revisions.json()[0]["id"] == first_revision_id

        detail = client.get(f"/api/lineage/revisions/{first_revision_id}")
        assert detail.status_code == 200, detail.text
        assert detail.json()["node_count"] >= 2
        graph = client.get(f"/api/projects/{project['id']}/lineage/graph?revision_id={first_revision_id}")
        assert graph.status_code == 200, graph.text
        assert graph.json()["revision_id"] == first_revision_id
        assert all("display" in node for node in graph.json()["nodes"])

        second = client.post(
            f"/api/projects/{project['id']}/scripts/upload",
            data={"relative_path": "load.sql", "dialect": "sqlite"},
            files={"file": ("load.sql", b"insert into MART.T (A) select A from ODS.S where STATUS = 'B'", "text/plain")},
        )
        assert second.status_code == 200, second.text
        second_revision_id = second.json()["lineage_revision_id"]
        assert second_revision_id != first_revision_id
        diff = client.get(f"/api/lineage/revisions/{second_revision_id}/diff?compare_to={first_revision_id}")
        assert diff.status_code == 200, diff.text
        assert "filter_changed" in {item["change_category"] for item in diff.json()["items"]}


@contextmanager
def _client() -> Iterator[TestClient]:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False)
    with factory() as seed:
        seed.add(Institution(institution_code="REV_API", institution_name="Revision API Bank"))
        seed.commit()

    def override() -> Iterator[Session]:
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
