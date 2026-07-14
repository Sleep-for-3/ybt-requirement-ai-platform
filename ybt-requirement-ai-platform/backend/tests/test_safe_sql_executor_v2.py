from pathlib import Path

import pytest
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


def test_safe_sql_executor_rejects_writable_cte(db_session):
    project, datasource = _make_datasource(db_session, ":memory:")
    executor = SafeSqlExecutor(db_session)

    result = executor.execute(
        datasource=datasource,
        sql="with deleted as (delete from ecif_customer returning cert_type) select cert_type from deleted",
        project_id=project.id,
    )

    assert result.status == "rejected"
    assert "DDL/DML" in result.reject_reason
    assert db_session.query(SqlExecutionLog).one().status == "rejected"


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


@pytest.mark.parametrize(
    ("db_type", "expected_timeout_sql", "expected_reset_sql"),
    [
        ("postgresql", "SET LOCAL statement_timeout = 7000", None),
        ("mysql", "SET SESSION MAX_EXECUTION_TIME = 7000", "SET SESSION MAX_EXECUTION_TIME = 0"),
    ],
)
def test_safe_sql_executor_applies_dialect_statement_timeout(
    db_session,
    monkeypatch,
    db_type: str,
    expected_timeout_sql: str,
    expected_reset_sql: str | None,
):
    executed_driver_sql: list[str] = []

    class FakeResult:
        def mappings(self):
            return self

        def all(self):
            return [{"answer": 1}]

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def exec_driver_sql(self, sql: str):
            executed_driver_sql.append(sql)

        def execute(self, statement):
            return FakeResult()

    class FakeEngine:
        def connect(self):
            return FakeConnection()

        def dispose(self):
            pass

    monkeypatch.setattr("app.services.db.safe_sql_executor.create_engine", lambda *args, **kwargs: FakeEngine())
    project, datasource = _make_datasource(db_session, "warehouse", db_type=db_type)

    result = SafeSqlExecutor(db_session, timeout_seconds=7).execute(
        datasource=datasource,
        sql="select 1 as answer",
        project_id=project.id,
    )

    assert result.status == "success"
    assert expected_timeout_sql in executed_driver_sql
    if expected_reset_sql:
        assert expected_reset_sql in executed_driver_sql


def test_safe_sql_executor_installs_and_clears_sqlite_progress_timeout(db_session, monkeypatch):
    progress_handlers: list[tuple[object, int]] = []

    class FakeDriverConnection:
        def set_progress_handler(self, callback, instruction_count: int):
            progress_handlers.append((callback, instruction_count))

    class FakeResult:
        def mappings(self):
            return self

        def all(self):
            return [{"answer": 1}]

    class FakeConnection:
        connection = type("ConnectionProxy", (), {"driver_connection": FakeDriverConnection()})()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, statement):
            return FakeResult()

    class FakeEngine:
        def connect(self):
            return FakeConnection()

        def dispose(self):
            pass

    monkeypatch.setattr("app.services.db.safe_sql_executor.create_engine", lambda *args, **kwargs: FakeEngine())
    project, datasource = _make_datasource(db_session, ":memory:")

    result = SafeSqlExecutor(db_session, timeout_seconds=3).execute(
        datasource=datasource,
        sql="select 1 as answer",
        project_id=project.id,
    )

    assert result.status == "success"
    assert callable(progress_handlers[0][0])
    assert progress_handlers[0][1] > 0
    assert progress_handlers[-1] == (None, 0)


def test_safe_sql_executor_interrupts_a_long_running_sqlite_query(db_session, tmp_path: Path):
    db_file = tmp_path / "timeout.db"
    create_engine(f"sqlite:///{db_file}").dispose()
    project, datasource = _make_datasource(db_session, str(db_file))

    result = SafeSqlExecutor(db_session, timeout_seconds=0.001).execute(
        datasource=datasource,
        sql=(
            "with recursive counter as ("
            "select 1 as value union all select value + 1 as value from counter where value < 100000000"
            ") select sum(value) as total from counter"
        ),
        project_id=project.id,
    )

    assert result.status == "failed"
    assert "interrupted" in (result.error_message or "").lower()
    assert result.execution_time_ms < 2000


def _make_datasource(db_session, database_name: str, db_type: str = "sqlite"):
    project = Project(name="安全 SQL 项目")
    db_session.add(project)
    db_session.flush()
    datasource = DataSource(
        project_id=project.id,
        name="ecif_query",
        display_name="ECIF",
        db_type=db_type,
        database_name=database_name,
        readonly_flag=True,
        enabled=True,
    )
    db_session.add(datasource)
    db_session.commit()
    return project, datasource
