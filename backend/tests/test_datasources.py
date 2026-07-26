import pytest

from app.core.crypto import decrypt_secret
from app.models import DataSource, Project
from app.schemas import DataSourceCreate, DataSourceRead
from app.services.datasource_service import create_datasource, validate_datasource_name


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
