from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from io import BytesIO
from zipfile import ZipFile
from openpyxl import load_workbook

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app
from app.models import (
    CatalogColumn, CatalogSchema, CatalogTable, DataSource, Institution, LineageNode,
    MartField, MartTable, MartToYbtMapping, ProductScenario, Project, ReviewTask,
    ScenarioTechnicalLineage, ScriptFile as ScriptFileModel, ScriptFileVersion,
    SourceToMartMapping, TargetField, TargetTable, User,
)
from app.services.lineage.resolver import resolve_lineage_node
from app.services.lineage.impact_analyzer import persist_change_impact
from app.services.governance.audit import redact_summary
from app.services.lineage.preprocessing import preprocess_sql
from app.services.lineage.sql_parser import parse_sql_lineage
from app.services.lineage.shell_parser import parse_shell_dependencies
from app.services.lineage.version_diff import compare_shell_versions, compare_sql_versions
from app.services.lineage.archive_ingestion import read_safe_script_archive
from app.services.lineage.git_repository import read_git_repository_scripts
from app.services.storage.local import LocalStorageService


def test_template_variables_are_preserved_and_instance_table_is_parseable() -> None:
    source = """
    insert into #{INSTANCE_GB}.MART_CUSTOMER (CERT_TYPE)
    select CERT_TYPE from ${SCHEMA}.ECIF_CUSTOMER where BIZ_DATE = :biz_date
    """

    result = preprocess_sql(source, variables={"INSTANCE_GB": "SAFE_SCHEMA"})

    assert "#{INSTANCE_GB}.MART_CUSTOMER" in result.original_sql
    assert "SAFE_SCHEMA.MART_CUSTOMER" in result.parse_sql
    assert "SAFE_SCHEMA.ECIF_CUSTOMER" in result.parse_sql
    assert ":biz_date" in result.normalized_sql
    assert {item.expression for item in result.variables} == {
        "#{INSTANCE_GB}",
        "${SCHEMA}",
        ":biz_date",
    }
    assert any("SCHEMA" in warning for warning in result.warnings)


def test_insert_select_produces_table_and_column_lineage() -> None:
    sql = """
    insert into MART.MART_CUSTOMER (CERT_TYPE, CUSTOMER_COUNT)
    select c.CERT_TYPE, count(c.CUSTOMER_ID)
    from ODS.ECIF_CUSTOMER c
    where c.ENABLED_FLAG = 'Y'
    group by c.CERT_TYPE
    """

    result = parse_sql_lineage(sql, dialect="sqlite")

    assert result.parse_status == "parsed"
    assert any(
        edge.source.logical_name == "ODS.ECIF_CUSTOMER"
        and edge.target.logical_name == "MART.MART_CUSTOMER"
        and edge.edge_type == "reads_from"
        for edge in result.edges
    )
    cert_edge = next(
        edge for edge in result.edges
        if edge.target.logical_name == "MART.MART_CUSTOMER.CERT_TYPE"
        and edge.edge_type == "derives_from"
    )
    assert cert_edge.source.logical_name == "ODS.ECIF_CUSTOMER.CERT_TYPE"
    assert "ENABLED_FLAG" in (cert_edge.filter_condition or "")
    count_edge = next(
        edge for edge in result.edges
        if edge.target.logical_name == "MART.MART_CUSTOMER.CUSTOMER_COUNT"
        and edge.edge_type == "aggregates"
    )
    assert count_edge.source.logical_name == "ODS.ECIF_CUSTOMER.CUSTOMER_ID"
    assert "COUNT" in count_edge.transformation_expression.upper()


def test_manual_sql_upload_is_version_idempotent_and_queryable(tmp_path: Path, monkeypatch) -> None:
    import app.api.lineage as lineage_api

    storage = LocalStorageService(tmp_path / "storage")
    monkeypatch.setattr(lineage_api, "get_storage_service", lambda: storage)
    sql = b"insert into MART.TARGET (CERT_TYPE) select CERT_TYPE from ODS.CUSTOMER"

    with _client() as client:
        project = client.post("/api/projects", json={"name": "lineage", "institution_id": 1}).json()
        first = client.post(
            f"/api/projects/{project['id']}/scripts/upload",
            data={"relative_path": "sql/load_customer.sql", "dialect": "sqlite"},
            files={"file": ("load_customer.sql", sql, "text/plain")},
        )
        assert first.status_code == 200, first.text
        second = client.post(
            f"/api/projects/{project['id']}/scripts/upload",
            data={"relative_path": "sql/load_customer.sql", "dialect": "sqlite"},
            files={"file": ("load_customer.sql", sql, "text/plain")},
        )
        assert second.status_code == 200, second.text
        assert second.json()["script_file_id"] == first.json()["script_file_id"]
        assert second.json()["version_id"] == first.json()["version_id"]
        assert second.json()["deduplicated"] is True

        graph = client.get(f"/api/projects/{project['id']}/lineage/graph?direction=both&depth=3")
        assert graph.status_code == 200, graph.text
        assert {node["logical_name"] for node in graph.json()["nodes"]} >= {
            "ODS.CUSTOMER.CERT_TYPE",
            "MART.TARGET.CERT_TYPE",
        }
        assert storage.read(first.json()["storage_key"]) == sql


def test_shell_parser_detects_scripts_sql_clients_and_arguments_without_execution() -> None:
    source = """
    SQL_FILE=sql/load_customer.sql
    sh ybt_04_loadData_HYF.sh HYF_TABLE YBT
    source common/env.sh
    psql -f ${SQL_FILE}
    mysql reporting < sql/check_customer.sql
    """

    result = parse_shell_dependencies(source)

    assert [(item.dependency_type, item.target_path) for item in result.dependencies] == [
        ("calls_script", "ybt_04_loadData_HYF.sh"),
        ("sources_script", "common/env.sh"),
        ("executes_sql", "sql/load_customer.sql"),
        ("executes_sql", "sql/check_customer.sql"),
    ]
    assert result.dependencies[0].arguments == ("HYF_TABLE", "YBT")
    assert all(item.source_line_start == item.source_line_end for item in result.dependencies)


def test_uploaded_shell_dependency_resolves_to_uploaded_sql(tmp_path: Path, monkeypatch) -> None:
    import app.api.lineage as lineage_api

    monkeypatch.setattr(lineage_api, "get_storage_service", lambda: LocalStorageService(tmp_path / "storage"))
    with _client() as client:
        project = client.post("/api/projects", json={"name": "shell lineage", "institution_id": 1}).json()
        sql = client.post(
            f"/api/projects/{project['id']}/scripts/upload",
            data={"relative_path": "sql/load.sql", "dialect": "sqlite"},
            files={"file": ("load.sql", b"insert into T.B select C from S.A", "text/plain")},
        ).json()
        shell = client.post(
            f"/api/projects/{project['id']}/scripts/upload",
            data={"relative_path": "run.sh"},
            files={"file": ("run.sh", b"psql -f sql/load.sql\n", "text/plain")},
        )
        assert shell.status_code == 200, shell.text
        detail = client.get(f"/api/scripts/{shell.json()['script_file_id']}")
        assert detail.status_code == 200, detail.text
        dependency = detail.json()["dependencies"][0]
        assert dependency["dependency_type"] == "executes_sql"
        assert dependency["child_script_file_id"] == sql["script_file_id"]
        assert dependency["source_line_start"] == 1


def test_cte_column_lineage_resolves_to_physical_source() -> None:
    result = parse_sql_lineage("""
        insert into MART.CUSTOMER_SUMMARY (CERT_TYPE)
        with scoped as (
            select c.CERT_TYPE from ODS.ECIF_CUSTOMER c where c.STATUS = 'A'
        )
        select scoped.CERT_TYPE from scoped
    """, dialect="sqlite")

    column_edges = [edge for edge in result.edges if edge.target.logical_name.endswith(".CERT_TYPE")]
    assert any(edge.source.logical_name == "ODS.ECIF_CUSTOMER.CERT_TYPE" for edge in column_edges)
    assert all(edge.source.logical_name != "scoped.CERT_TYPE" for edge in column_edges)


def test_comment_and_format_only_change_is_non_semantic() -> None:
    old = "insert into T.B (C) select C from S.A"
    new = """-- explain the load
        insert  into T.B (C)
        select C
        from S.A
    """

    result = compare_sql_versions(old, new, dialect="sqlite")

    assert result.semantic_changed is False
    assert [item.change_category for item in result.items] == ["non_semantic"]
    assert result.severity == "low"


def test_source_removal_and_filter_change_are_classified_by_risk() -> None:
    old = """
        insert into MART.T (A, B)
        select s.A, s.B from ODS.S s where s.STATUS = 'A'
    """
    new = """
        insert into MART.T (A)
        select s.A from ODS.S s where s.STATUS = 'B'
    """

    result = compare_sql_versions(old, new, dialect="sqlite")

    categories = {item.change_category for item in result.items}
    assert "source_column_removed" in categories
    assert "filter_changed" in categories
    assert result.severity == "critical"


def test_catalog_resolution_auto_binds_only_a_unique_candidate(db_session: Session) -> None:
    project = Project(name="resolve")
    db_session.add(project); db_session.flush()
    datasource = DataSource(project_id=project.id, name="warehouse", db_type="sqlite")
    db_session.add(datasource); db_session.flush()
    schema = CatalogSchema(project_id=project.id, datasource_id=datasource.id, schema_name="ODS")
    db_session.add(schema); db_session.flush()
    table = CatalogTable(project_id=project.id, datasource_id=datasource.id, catalog_schema_id=schema.id, schema_name="ODS", table_name="CUSTOMER")
    db_session.add(table); db_session.flush()
    column = CatalogColumn(project_id=project.id, datasource_id=datasource.id, catalog_table_id=table.id, schema_name="ODS", table_name="CUSTOMER", column_name="CERT_TYPE", ordinal_position=1)
    unique_node = LineageNode(project_id=project.id, node_type="column", logical_name="ODS.CUSTOMER.CERT_TYPE", schema_name="ODS", table_name="CUSTOMER", column_name="CERT_TYPE")
    db_session.add_all([column, unique_node]); db_session.flush()

    unique = resolve_lineage_node(db_session, unique_node)
    assert unique_node.catalog_column_id == column.id
    assert unique_node.unresolved_flag is False
    assert unique.candidates == ()

    other_schema = CatalogSchema(project_id=project.id, datasource_id=datasource.id, schema_name="DWD")
    db_session.add(other_schema); db_session.flush()
    other_table = CatalogTable(project_id=project.id, datasource_id=datasource.id, catalog_schema_id=other_schema.id, schema_name="DWD", table_name="CUSTOMER")
    db_session.add(other_table); db_session.flush()
    other_column = CatalogColumn(project_id=project.id, datasource_id=datasource.id, catalog_table_id=other_table.id, schema_name="DWD", table_name="CUSTOMER", column_name="CERT_TYPE", ordinal_position=1)
    ambiguous_node = LineageNode(project_id=project.id, node_type="column", logical_name="CUSTOMER.CERT_TYPE", table_name="CUSTOMER", column_name="CERT_TYPE")
    db_session.add_all([other_column, ambiguous_node]); db_session.flush()

    ambiguous = resolve_lineage_node(db_session, ambiguous_node)
    assert ambiguous_node.catalog_column_id is None
    assert ambiguous_node.unresolved_flag is True
    assert len(ambiguous.candidates) == 2


def test_second_script_version_creates_change_set_and_impact(tmp_path: Path, monkeypatch) -> None:
    import app.api.lineage as lineage_api

    monkeypatch.setattr(lineage_api, "get_storage_service", lambda: LocalStorageService(tmp_path / "storage"))
    with _client() as client:
        project = client.post("/api/projects", json={"name": "impact", "institution_id": 1}).json()
        first = b"insert into MART.T (A, B) select A, B from ODS.S where STATUS = 'A'"
        second = b"insert into MART.T (A) select A from ODS.S where STATUS = 'B'"
        for content in (first, second):
            response = client.post(
                f"/api/projects/{project['id']}/scripts/upload",
                data={"relative_path": "load.sql", "dialect": "sqlite"},
                files={"file": ("load.sql", content, "text/plain")},
            )
            assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["version_no"] == 2
        assert payload["change_set_id"]
        assert payload["impact_id"]
        assert "source_column_removed" in payload["change_categories"]
        assert payload["impact_severity"] == "critical"

        change = client.get(f"/api/lineage/changes/{payload['change_set_id']}")
        assert change.status_code == 200, change.text
        assert change.json()["impact"]["severity"] == "critical"


def test_zip_reader_blocks_zip_slip_and_reads_only_safe_scripts() -> None:
    safe = BytesIO()
    with ZipFile(safe, "w") as archive:
        archive.writestr("sql/load.sql", "select A from T")
        archive.writestr("run.sh", "psql -f sql/load.sql")
    files = read_safe_script_archive(safe.getvalue())
    assert [item.relative_path for item in files] == ["sql/load.sql", "run.sh"]

    malicious = BytesIO()
    with ZipFile(malicious, "w") as archive:
        archive.writestr("../../escape.sql", "select 1")
    try:
        read_safe_script_archive(malicious.getvalue())
    except ValueError as exc:
        assert "unsafe path" in str(exc).lower()
    else:
        raise AssertionError("Zip Slip payload was accepted")


def test_zip_upload_runs_as_idempotent_retryable_background_job(tmp_path: Path, monkeypatch) -> None:
    import app.api.lineage as lineage_api
    import app.services.lineage.jobs as lineage_jobs

    storage = LocalStorageService(tmp_path / "storage")
    monkeypatch.setattr(lineage_api, "get_storage_service", lambda: storage)
    monkeypatch.setattr(lineage_jobs, "get_storage_service", lambda: storage)
    stream = BytesIO()
    with ZipFile(stream, "w") as archive:
        archive.writestr("load.sql", "insert into T.B(A) select A from S.C")
        archive.writestr("run.sh", "psql -f load.sql")
    with _client() as client:
        project = client.post("/api/projects", json={"name": "archive", "institution_id": 1}).json()
        responses = [client.post(
            f"/api/projects/{project['id']}/scripts/upload-zip",
            data={"dialect": "sqlite"}, files={"file": ("scripts.zip", stream.getvalue(), "application/zip")},
        ) for _ in range(2)]
        assert all(item.status_code == 200 for item in responses)
        first, repeated = (item.json() for item in responses)
        assert first["status"] == "completed"
        assert first["job_id"] == repeated["job_id"]
        assert len(first["items"]) == 2
        assert len(client.get(f"/api/projects/{project['id']}/scripts").json()) == 2


def test_git_reader_does_not_execute_checkout_hooks(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repository, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repository, check=True)
    subprocess.run(["git", "config", "user.name", "Lineage Test"], cwd=repository, check=True)
    (repository / "load.sql").write_text("select A from T", encoding="utf-8")
    hooks = repository / ".git" / "hooks"
    marker = tmp_path / "hook-ran"
    hook = hooks / "post-checkout"
    hook.write_text(f"#!/bin/sh\nprintf ran > '{marker.as_posix()}'\n", encoding="utf-8")
    hook.chmod(0o755)
    subprocess.run(["git", "add", "load.sql"], cwd=repository, check=True)
    subprocess.run(["git", "commit", "-m", "safe fixture"], cwd=repository, check=True, capture_output=True)

    result = read_git_repository_scripts(str(repository), branch="main")

    assert result.files[0].relative_path == "load.sql"
    assert result.files[0].content == b"select A from T"
    assert not marker.exists()


def test_lineage_export_is_a_real_workbook_with_required_sheets(tmp_path: Path, monkeypatch) -> None:
    import app.api.lineage as lineage_api

    monkeypatch.setattr(lineage_api, "get_storage_service", lambda: LocalStorageService(tmp_path / "storage"))
    with _client() as client:
        project = client.post("/api/projects", json={"name": "export", "institution_id": 1}).json()
        client.post(
            f"/api/projects/{project['id']}/scripts/upload",
            data={"relative_path": "load.sql", "dialect": "sqlite"},
            files={"file": ("load.sql", b"insert into MART.T (A) select A from ODS.S", "text/plain")},
        )
        response = client.get(f"/api/projects/{project['id']}/export/lineage-workbook")
        assert response.status_code == 200, response.text
        workbook = load_workbook(BytesIO(response.content))
        assert workbook.sheetnames == [
            "血缘总览", "字段级血缘", "表级血缘", "脚本清单", "脚本依赖", "加工逻辑",
            "未解析节点", "版本变更", "影响分析", "待确认问题", "审核记录",
        ]
        assert workbook["字段级血缘"].freeze_panes == "A2"
        assert workbook["字段级血缘"].auto_filter.ref


def test_case_coalesce_and_window_expressions_keep_all_source_columns() -> None:
    result = parse_sql_lineage("""
        insert into MART.T (CODE_NAME, BEST_PHONE, RN)
        select case when s.CODE='1' then 'A' else 'B' end,
               coalesce(s.MOBILE, s.PHONE),
               row_number() over (partition by s.CUSTOMER_ID order by s.UPDATED_AT desc)
        from ODS.S s
    """, dialect="sqlite")
    by_target: dict[str, list] = {}
    for edge in result.edges:
        by_target.setdefault(edge.target.logical_name, []).append(edge)
    assert {item.source.column_name for item in by_target["MART.T.CODE_NAME"]} == {"CODE"}
    assert all(item.edge_type == "maps_code" for item in by_target["MART.T.CODE_NAME"])
    assert {item.source.column_name for item in by_target["MART.T.BEST_PHONE"]} == {"MOBILE", "PHONE"}
    assert {item.source.column_name for item in by_target["MART.T.RN"]} == {"CUSTOMER_ID", "UPDATED_AT"}


def test_union_lineage_keeps_sources_from_both_branches() -> None:
    result = parse_sql_lineage("insert into MART.T (A) select A from ODS.S1 union all select A from ODS.S2", dialect="sqlite")
    sources = {edge.source.logical_name for edge in result.edges if edge.target.logical_name == "MART.T.A"}
    assert sources == {"ODS.S1.A", "ODS.S2.A"}


def test_merge_update_and_insert_produce_column_lineage() -> None:
    result = parse_sql_lineage("""
        merge into MART.T t using ODS.S s on t.ID=s.ID
        when matched then update set t.A=s.A
        when not matched then insert (ID,A) values (s.ID,s.A)
    """, dialect="postgres")
    pairs = {(edge.source.logical_name, edge.target.logical_name) for edge in result.edges}
    assert ("ODS.S.A", "MART.T.A") in pairs
    assert ("ODS.S.ID", "MART.T.ID") in pairs
    assert all(edge.join_condition and "ID" in edge.join_condition for edge in result.edges)


def test_update_from_produces_source_to_target_column_lineage() -> None:
    result = parse_sql_lineage("update MART.T t set A=s.A from ODS.S s where t.ID=s.ID", dialect="postgres")
    assert any(edge.source.logical_name == "ODS.S.A" and edge.target.logical_name == "MART.T.A" for edge in result.edges)


def test_critical_impact_marks_mappings_stale_without_overwriting_final_content(db_session: Session) -> None:
    user = User(username="impact-owner", status="active")
    project = Project(name="impact governance")
    db_session.add_all([user, project]); db_session.flush()
    target_table = TargetTable(project_id=project.id, table_code="YBT_T", table_name="YBT")
    mart_table = MartTable(project_id=project.id, table_code="MART_T", table_name="Mart")
    scenario = ProductScenario(project_id=project.id, scenario_code="DEFAULT", scenario_name="默认")
    db_session.add_all([target_table, mart_table, scenario]); db_session.flush()
    target = TargetField(project_id=project.id, target_table_id=target_table.id, field_code="A", field_name="A")
    mart = MartField(project_id=project.id, mart_table_id=mart_table.id, field_code="A", field_name="A")
    db_session.add_all([target, mart]); db_session.flush()
    technical = ScenarioTechnicalLineage(project_id=project.id, target_field_id=target.id, scenario_id=scenario.id, final_content="人工技术口径")
    source_mapping = SourceToMartMapping(project_id=project.id, mart_field_id=mart.id, final_content="人工入集市口径")
    ybt_mapping = MartToYbtMapping(project_id=project.id, target_field_id=target.id, mart_field_id=mart.id, final_content="人工上报口径")
    script = ScriptFileModel(project_id=project.id, relative_path="load.sql", file_name="load.sql", file_type="sql", current_version_no=2)
    db_session.add_all([technical, source_mapping, ybt_mapping, script]); db_session.flush()
    old = ScriptFileVersion(project_id=project.id, script_file_id=script.id, version_no=1, file_hash="a"*64, normalized_hash="b"*64, raw_content_storage_file_id=1, parse_status="parsed", created_by=user.id)
    new = ScriptFileVersion(project_id=project.id, script_file_id=script.id, version_no=2, file_hash="c"*64, normalized_hash="d"*64, raw_content_storage_file_id=2, parse_status="parsed", created_by=user.id)
    db_session.add_all([old, new]); db_session.flush()
    db_session.add_all([
        LineageNode(project_id=project.id, node_type="column", logical_name="MART_T.A", table_name="MART_T", column_name="A", mart_field_id=mart.id, script_file_id=script.id, script_file_version_id=old.id, unresolved_flag=False),
        LineageNode(project_id=project.id, node_type="column", logical_name="YBT_T.A", table_name="YBT_T", column_name="A", target_field_id=target.id, script_file_id=script.id, script_file_version_id=new.id, unresolved_flag=False),
    ]); db_session.flush()

    diff = compare_sql_versions("insert into MART_T(A,B) select A,B from ODS_S", "insert into MART_T(A) select A from ODS_S", dialect="sqlite")
    _change, impact = persist_change_impact(db_session, script_file=script, from_version=old, to_version=new, diff=diff, created_by=user.id)

    assert impact.severity == "critical"
    assert technical.lineage_status == source_mapping.lineage_status == ybt_mapping.lineage_status == "stale"
    assert (technical.final_content, source_mapping.final_content, ybt_mapping.final_content) == ("人工技术口径", "人工入集市口径", "人工上报口径")
    assert db_session.query(ReviewTask).count() == 3


def test_task_payload_redaction_preserves_safe_storage_keys_but_not_sensitive_text() -> None:
    digest = "807914e0d8a5e97b79d85f8497a6c34c6dd856577473afb1234567890abcdef"
    storage_key = f"projects/1/{digest[:2]}/{digest}.xlsx"
    result = redact_summary({"storage_key": storage_key, "note": "账号 6222020202020202", "password": "never-store"})
    assert result["storage_key"] == storage_key
    assert "6222020202020202" not in result["note"]
    assert "password" not in result


def test_shell_call_change_is_a_high_risk_dependency_change() -> None:
    result = compare_shell_versions("sh load_a.sh TABLE_A", "sh load_b.sh TABLE_B")
    assert result.semantic_changed is True
    assert [item.change_category for item in result.items] == ["script_dependency_changed"]
    assert result.severity == "high"


@contextmanager
def _client() -> Iterator[TestClient]:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False)
    with factory() as seed:
        seed.add(Institution(institution_code="TEST_BANK", institution_name="测试银行"))
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
import subprocess
