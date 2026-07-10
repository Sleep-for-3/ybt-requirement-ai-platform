from pathlib import Path

from sqlalchemy import create_engine, text

from app.models import DataSource, EvidenceReference, Project, SqlExecutionLog
from app.services.natural_language_task_service import create_natural_language_task, run_natural_language_task
from app.services.task_parser.natural_language_task_parser import NaturalLanguageTaskParser


def test_natural_language_parser_identifies_datasource_table_and_field(db_session):
    project, datasource = _make_datasource(db_session)

    parsed = NaturalLanguageTaskParser(db_session).parse(
        project_id=project.id,
        raw_text="使用 ecif_query 查询 ecif_customer 表 cert_type 字段的空值率和枚举分布",
    )

    assert parsed.status == "parsed"
    assert parsed.datasource_id == datasource.id
    assert parsed.extracted_table_name == "ecif_customer"
    assert parsed.extracted_field_name == "cert_type"


def test_natural_language_parser_returns_available_datasources_when_missing(db_session):
    project, _datasource = _make_datasource(db_session)

    parsed = NaturalLanguageTaskParser(db_session).parse(project_id=project.id, raw_text="查询客户表")

    assert parsed.status == "need_clarification"
    assert parsed.available_datasources == ["ecif_query"]


def test_natural_language_task_run_saves_sql_logs_and_result_summary(db_session, tmp_path: Path):
    db_file = tmp_path / "ecif.db"
    engine = create_engine(f"sqlite:///{db_file}")
    with engine.begin() as connection:
        connection.execute(text("create table ecif_customer (cert_type text)"))
        connection.execute(text("insert into ecif_customer values ('01'), ('01'), ('02'), (null)"))
    project, _datasource = _make_datasource(db_session, str(db_file))

    task = create_natural_language_task(
        db_session,
        project_id=project.id,
        raw_text="使用 ecif_query 查询 ecif_customer 表 cert_type 字段的空值率和枚举分布",
    )
    result = run_natural_language_task(db_session, task.id)

    assert result.status == "completed"
    assert result.result_summary_json["null_profile"]["total_count"] == 4
    assert result.result_summary_json["null_profile"]["null_count"] == 1
    assert result.result_summary_json["distinct_profile"]["distinct_count"] == 2
    assert db_session.query(SqlExecutionLog).count() >= 3


def test_supported_evidence_types_include_new_sources():
    supported = {
        "template_document",
        "template_parse_result",
        "natural_language_task",
        "sql_execution_log",
        "db_query_result",
        "datasource",
    }

    assert supported.issubset(EvidenceReference.supported_types())


def _make_datasource(db_session, database_name: str = ":memory:"):
    project = Project(name="自然语言项目")
    db_session.add(project)
    db_session.flush()
    datasource = DataSource(
        project_id=project.id,
        name="ecif_query",
        display_name="ECIF",
        db_type="sqlite",
        database_name=database_name,
        readonly_flag=True,
        enabled=True,
    )
    db_session.add(datasource)
    db_session.commit()
    return project, datasource
