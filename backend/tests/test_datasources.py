import pytest

from app.core.crypto import decrypt_secret
from app.models import DataSource, Project
from app.schemas import DataSourceCreate, DataSourceRead
from app.services.datasource_service import create_datasource, validate_datasource_name
from app.services.connectors.diagnostics import classify_connection_error, diagnose_payload
from app.services.connectors.registry import connector_registry


@pytest.mark.parametrize("name", ["ecif_query", "loan_query", "mart_query", "ybt_mart"])
def test_datasource_name_accepts_valid_values(name):
    validate_datasource_name(name)


@pytest.mark.parametrize("name", ["ECIF查询", "ecif-query", "123ecif", "ecif query", "ab"])
def test_datasource_name_rejects_invalid_values(name):
    with pytest.raises(ValueError):
        validate_datasource_name(name)


def test_datasource_name_must_be_unique_within_project(db_session):
    project = Project(name="数据源项目")
    db_session.add(project)
    db_session.commit()
    payload = DataSourceCreate(name="ecif_query", display_name="ECIF", db_type="sqlite", database_name=":memory:", password="secret")
    create_datasource(db_session, project.id, payload)

    with pytest.raises(ValueError):
        create_datasource(db_session, project.id, payload)


def test_datasource_password_is_encrypted_and_read_schema_redacts_it(db_session):
    project = Project(name="密码项目")
    db_session.add(project)
    db_session.commit()

    datasource = create_datasource(
        db_session,
        project.id,
        DataSourceCreate(name="ecif_query", display_name="ECIF", db_type="sqlite", database_name=":memory:", password="secret"),
    )

    stored = db_session.get(DataSource, datasource.id)
    assert stored.encrypted_password != "secret"
    assert decrypt_secret(stored.encrypted_password) == "secret"
    read_payload = DataSourceRead.model_validate(stored).model_dump()
    assert "encrypted_password" not in read_payload
    assert "password" not in read_payload
    assert read_payload["password_configured"] is True


def test_datasource_rejects_credentials_inside_connection_params(db_session):
    project = Project(name="连接参数安全项目")
    db_session.add(project)
    db_session.commit()

    with pytest.raises(ValueError, match="凭据"):
        create_datasource(
            db_session,
            project.id,
            DataSourceCreate(
                name="warehouse_query",
                db_type="postgresql",
                connection_params_json={"sqlalchemy_url": "postgresql://reader:plain-secret@localhost/warehouse"},
            ),
        )


def test_datasource_read_redacts_connection_url_and_secret_parameters(db_session):
    project = Project(name="历史连接参数脱敏项目")
    db_session.add(project)
    db_session.flush()
    datasource = DataSource(
        project_id=project.id,
        name="legacy_query",
        db_type="postgresql",
        connection_params_json={
            "sqlalchemy_url": "postgresql://reader:legacy-secret@localhost/warehouse",
            "driver": "psycopg",
            "connect_args": {"sslmode": "require", "password": "nested-secret"},
        },
    )
    db_session.add(datasource)
    db_session.commit()

    read_payload = DataSourceRead.model_validate(datasource).model_dump()

    assert read_payload["connection_params_json"] == {
        "driver": "psycopg",
        "connect_args": {"sslmode": "require"},
    }
    assert "secret" not in str(read_payload).lower()


def test_connector_registry_exposes_capabilities_without_claiming_gbase_compatibility() -> None:
    connectors = {item["engine_type"]: item for item in connector_registry()}
    assert set(connectors) >= {"sqlite", "postgresql", "mysql_compatible", "oracle", "sqlserver", "db2", "gbase"}
    assert connectors["sqlite"]["status"] == "available"
    assert connectors["postgresql"]["default_port"] == 5432
    assert connectors["oracle"]["service_name_mode"] == "service_name_or_sid"
    assert connectors["gbase"]["status"] == "extension_only"
    assert connectors["gbase"]["metadata_discovery"] is False


def test_sqlite_connection_diagnostic_returns_real_version_and_schema(tmp_path) -> None:
    database = tmp_path / "diagnostic.db"
    database.touch()
    result = diagnose_payload(1, DataSourceCreate(
        name="diagnostic_db", db_type="sqlite", database_name=str(database), readonly_flag=True,
    ))
    assert result["status"] == "success"
    assert result["database_version"]
    assert result["schemas"] == ["main"]
    assert {step["code"] for step in result["steps"]} >= {"driver", "network", "authentication", "readonly", "version", "metadata"}


def test_connection_diagnostic_separates_metadata_permission_failure(tmp_path, monkeypatch) -> None:
    database = tmp_path / "diagnostic.db"
    database.touch()

    class DeniedInspector:
        def get_schema_names(self):
            raise RuntimeError("permission denied while reading information schema")

    monkeypatch.setattr("app.services.connectors.diagnostics.inspect", lambda _engine: DeniedInspector())
    result = diagnose_payload(1, DataSourceCreate(
        name="metadata_denied", db_type="sqlite", database_name=str(database), readonly_flag=True,
    ))
    assert result["status"] == "failed"
    assert result["error_code"] == "metadata_permission_missing"
    assert "Catalog/Schema" in result["message"]


@pytest.mark.parametrize("message,code", [
    ("password authentication failed for user", "auth_failed"),
    ("could not translate host name", "dns_failure"),
    ("connection refused", "network_unreachable"),
    ("certificate verify failed", "tls_failed"),
    ("database does not exist", "database_not_found"),
])
def test_connection_errors_are_classified_without_returning_driver_diagnostics(message, code) -> None:
    assert classify_connection_error(RuntimeError(message))[0] == code
