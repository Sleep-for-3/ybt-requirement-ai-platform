from pathlib import Path

from sqlalchemy import create_engine, text

from app.models import DataSource, Project, SqlExecutionLog
from app.services.db.safe_sql_executor import SafeSqlExecutor


def test_safe_sql_executor_rejects_unsafe_sql_and_logs(db_session):
    project, datasource = _make_datasource(db_session, ":memory:")
    executor = SafeSqlExecutor(db_session)

    result = executor.execute(datasource=datasource, sql="delete from ecif_customer", project_id=project.id)

    assert result.status == "rejected"
    assert "Only SELECT" in result.reject_reason
    log = db_session.query(SqlExecutionLog).one()
    assert log.status == "rejected"


def test_safe_sql_executor_rejects_select_star(db_session):
    project, datasource = _make_datasource(db_session, ":memory:")
    executor = SafeSqlExecutor(db_session)

    result = executor.execute(datasource=datasource, sql="select * from ecif_customer", project_id=project.id)

    assert result.status == "rejected"
    assert "SELECT *" in result.reject_reason


def test_safe_sql_executor_forces_limit_and_removes_sensitive_columns(db_session, tmp_path: Path):
    db_file = tmp_path / "source.db"
    engine = create_engine(f"sqlite:///{db_file}")
    with engine.begin() as connection:
        connection.execute(text("create table ecif_customer (cert_type text, customer_name text, cnt integer)"))
        connection.execute(text("insert into ecif_customer values ('01', '张三', 2), ('02', '李四', 1)"))
    project, datasource = _make_datasource(db_session, str(db_file))
    executor = SafeSqlExecutor(db_session, default_limit=100, max_limit=1000)

    result = executor.execute(
        datasource=datasource,
        sql="select cert_type, customer_name, cnt from ecif_customer",
        project_id=project.id,
        max_rows=100,
    )

    assert result.status == "success"
    assert "LIMIT 100" in result.sanitized_sql.upper()
    assert result.columns == ["cert_type", "cnt"]
    assert "customer_name" not in result.rows[0]


def _make_datasource(db_session, database_name: str):
    project = Project(name="安全 SQL 项目")
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
