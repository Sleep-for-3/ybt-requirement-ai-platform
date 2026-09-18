from copy import deepcopy

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models import CatalogTable, Institution, Project, User, ProjectMembership
from app.models.data_architecture import DataArchitectureRevision
from app.services import data_architecture as service
from app.api.data_architecture import read_project, write_project, ArchitectureWrite
from app.services.auth.dependencies import Principal


def projects(db):
    banks = [Institution(institution_code=f"isolated-{i}", institution_name=f"Bank {i}") for i in range(2)]
    db.add_all(banks); db.flush()
    rows = [Project(name=f"project-{i}", institution_id=bank.id) for i, bank in enumerate(banks)]
    db.add_all(rows); db.flush()
    return banks, rows


def test_two_banks_copy_independently_and_old_assets_remain_unclassified(db_session):
    db = db_session
    banks, rows = projects(db)
    for bank, definition in zip(banks, service.examples()):
        service.save_architecture(db, definition, 0, institution_id=bank.id)
    for project in rows:
        service.copy_institution_template(db, project)
    before = deepcopy(service.get_architecture(db, project_id=rows[0].id).definition_json)
    service.save_architecture(db, service.examples()[1], 1, institution_id=banks[0].id)
    assert service.get_architecture(db, project_id=rows[0].id).definition_json == before
    assert len(service.get_architecture(db, project_id=rows[1].id).definition_json["layers"]) == 6
    table = CatalogTable(project_id=rows[0].id, datasource_id=1, catalog_schema_id=1,
        schema_name="ods", table_name="DWD_IMPLICIT", database_name="bank_a")
    db.add(table); db.flush()
    assert service.table_classifications(db, rows[0].id)[0]["assignment"] == {"layer_key": None}
    assert service.table_classifications(db, rows[1].id) == []


def test_rename_disable_preserves_snapshot_and_rejects_stale_update(db_session):
    db = db_session
    _, rows = projects(db)
    project = rows[0]
    definition = service.examples()[0]
    architecture = service.save_architecture(db, definition, 0, project_id=project.id)
    table = CatalogTable(project_id=project.id, datasource_id=1, catalog_schema_id=1,
        schema_name="s", table_name="t")
    db.add(table); db.flush()
    binding = service.assign_table(db, project.id, table.id, {"layer_key": "layer_1"}, 1)
    original = db.get(DataArchitectureRevision, binding.architecture_revision_id)
    frozen_assignment = deepcopy(service.table_classifications(db, project.id)[0]["assignment"])
    changed = deepcopy(definition)
    changed["layers"][1]["name"] = "新贴源名称"
    service.save_architecture(db, changed, 1, project_id=project.id)
    assert original.definition_json["layers"][1]["name"] == "贴源层"
    assert binding.assignment_json["layer_name"] == "贴源层"
    assert service.table_classifications(db, project.id)[0]["assignment"]["layer_name"] == "新贴源名称"
    assert frozen_assignment["layer_name"] == "贴源层"
    changed["layers"].pop(1); changed["relations"] = []
    service.save_architecture(db, changed, 2, project_id=project.id)
    assert not architecture.definition_json["layers"][-1]["active"]
    assert service.table_classifications(db, project.id)[0]["assignment"]["layer_active"] is False
    assert frozen_assignment.get("layer_active", True) is True
    with pytest.raises(HTTPException) as error:
        service.assign_table(db, project.id, table.id, {"layer_key": "layer_1"}, 3)
    assert error.value.status_code == 422
    with pytest.raises(HTTPException) as error:
        service.save_architecture(db, definition, 1, project_id=project.id)
    assert error.value.status_code == 409
    assert len(list(db.scalars(select(DataArchitectureRevision)))) == 3
    with pytest.raises(HTTPException):
        service.assign_table(db, rows[1].id, table.id, {}, 1)


def test_api_permission_project_and_institution_boundary(db_session):
    db = db_session
    _, rows = projects(db)
    user = User(username="isolated-architecture-viewer")
    db.add(user); db.flush()
    db.add(ProjectMembership(project_id=rows[0].id, user_id=user.id, project_role="viewer")); db.flush()
    principal = Principal(user.id, user.username, None)
    assert read_project(rows[0].id, principal, db)["version"] == 0
    for action in [lambda: read_project(rows[1].id, principal, db),
                   lambda: write_project(rows[0].id, ArchitectureWrite(definition=service.examples()[0], expected_version=0), principal, db)]:
        with pytest.raises(HTTPException) as error:
            action()
        assert error.value.status_code in (403, 404)


@pytest.mark.parametrize("definition", [
    {"layers": []}, {"layers": [{"key": "a", "name": "A"}, {"key": "a", "name": "B"}]},
    {"layers": [{"key": 1, "name": "数字标识不合法"}]},
    {"layers": [{"key": "a", "name": "A"}], "relations": [{"from": "a", "to": "missing"}]},
])
def test_invalid_architecture_rejected(definition):
    with pytest.raises(HTTPException):
        service.validate_definition(definition)


def test_suggestions_do_not_apply_or_replace_confirmed_classification(db_session):
    db = db_session
    _, rows = projects(db)
    service.save_architecture(db, service.examples()[0], 0, project_id=rows[0].id)
    table = CatalogTable(project_id=rows[0].id, datasource_id=1, catalog_schema_id=1,
        database_name="a", schema_name="ods", table_name="T_ACCOUNT")
    db.add(table); db.flush()
    rules = [{"database_name": "a", "schema_name": "ods", "table_prefix": "T_", "layer_key": "layer_1"}]
    preview = service.suggest_classifications(db, rows[0].id, rules)
    assert preview[0]["suggested_layer_keys"] == ["layer_1"]
    assert preview[0]["requires_confirmation"]
    assert service.table_classifications(db, rows[0].id)[0]["assignment"]["layer_key"] is None
    assert not service.suggest_classifications(db, rows[0].id, [{**rules[0], "database_name": "b"}])
    service.assign_table(db, rows[0].id, table.id, {"layer_key": "layer_0"}, 1)
    assert not service.suggest_classifications(db, rows[0].id, rules)


def test_institution_routes_enforce_roles_without_project_guard():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.core.database import Base, get_db
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import StaticPool
    from app.models import InstitutionMembership
    from app.services.auth.dependencies import get_current_principal
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = Session(engine, expire_on_commit=False)
    banks, rows = projects(db)
    user = User(username="isolated-template-admin")
    db.add(user); db.flush()
    db.add(InstitutionMembership(institution_id=banks[0].id, user_id=user.id, role="institution_admin"))
    db.flush()
    principal = Principal(user.id, user.username, None)
    old = dict(app.dependency_overrides)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_principal] = lambda: principal
    try:
        client = TestClient(app)
        body = {"definition": service.examples()[0], "expected_version": 0}
        assert client.put(f"/api/institutions/{banks[0].id}/data-architecture", json=body).status_code == 200
        assert client.put(f"/api/institutions/{banks[1].id}/data-architecture", json=body).status_code == 404
        assert client.get(f"/api/institutions/{banks[1].id}/data-architecture").status_code == 404
        assert client.post(f"/api/projects/{rows[0].id}/data-architecture/copy-institution").status_code == 200
        assert client.post(f"/api/projects/{rows[0].id}/data-architecture/copy-institution").status_code == 409
        assert client.get(f"/api/projects/{rows[1].id}/data-architecture").status_code in (403, 404)
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(old)
        db.close()
        engine.dispose()


def test_incremental_migration_preserves_existing_catalog():
    import importlib.util
    from pathlib import Path
    from sqlalchemy import create_engine, inspect
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from app.core.database import Base
    from app.models import DataSource, CatalogSchema
    from sqlalchemy.orm import Session
    engine = create_engine("sqlite://")
    new_names = {"data_architectures", "data_architecture_revisions", "catalog_classifications"}
    Base.metadata.create_all(engine, tables=[table for table in Base.metadata.sorted_tables if table.name not in new_names])
    with Session(engine) as db:
        project = Project(name="migration legacy")
        db.add(project); db.flush()
        source = DataSource(project_id=project.id, name="offline", db_type="sqlite")
        db.add(source); db.flush()
        schema = CatalogSchema(project_id=project.id, datasource_id=source.id, schema_name="legacy")
        db.add(schema); db.flush()
        table = CatalogTable(project_id=project.id, datasource_id=source.id, catalog_schema_id=schema.id,
            schema_name="legacy", table_name="OLD", table_comment="人工确认注释")
        db.add(table); db.commit()
        identity = table.id
        project_id = project.id
    path = Path(__file__).resolve().parents[1] / "alembic/versions/202609170034_data_architecture.py"
    spec = importlib.util.spec_from_file_location("architecture_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with engine.begin() as connection:
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        assert new_names <= set(inspect(connection).get_table_names())
    with Session(engine) as db:
        assert db.get(CatalogTable, identity).table_comment == "人工确认注释"
        assert service.table_classifications(db, project_id)[0]["assignment"] == {"layer_key": None}
    engine.dispose()


def test_classification_options_and_three_independent_assignments(db_session):
    from app.models import BusinessSystem, TargetTable, TemplateDocument, TemplateVersion
    from app.api.data_architecture import classification_options
    db = db_session
    _, rows = projects(db)
    project, other = rows
    service.save_architecture(db, service.examples()[0], 0, project_id=project.id)
    system = BusinessSystem(project_id=project.id, system_code="CORE", system_name="核心")
    foreign = BusinessSystem(project_id=other.id, system_code="OTHER", system_name="另一银行")
    target = TargetTable(project_id=project.id, table_code="REPORT", table_name="监管余额表")
    document = TemplateDocument(project_id=project.id, template_code="REG", display_name="监管模板",
        file_name="test.xlsx", file_type="xlsx", storage_path="not-read")
    db.add_all([system, foreign, target, document]); db.flush()
    template = TemplateVersion(project_id=project.id, template_document_id=document.id, version_no=1,
        template_code="REG", file_name="test.xlsx", file_type="xlsx", storage_path="not-read",
        file_hash="synthetic", parsed_snapshot_json=[{"table_code":"REPORT"}])
    table = CatalogTable(project_id=project.id, datasource_id=1, catalog_schema_id=1,
        database_name="bank", schema_name="reg", table_name="BALANCE")
    user = User(username="isolated-classification-admin")
    db.add_all([template,table,user]); db.flush()
    membership = ProjectMembership(project_id=project.id,user_id=user.id,project_role="project_manager")
    db.add(membership); db.flush()
    principal = Principal(user.id,user.username,None)
    options = classification_options(project.id,principal,db)
    assert [s["id"] for s in options["business_systems"]] == [system.id]
    assert options["templates"][0]["target_ids"] == [target.id]
    assignment = {"layer_key":"layer_2","business_system_id":system.id,
        "target_table_id":target.id,"template_version_id":template.id}
    binding = service.assign_table(db,project.id,table.id,assignment,1)
    service.assign_table(db,project.id,table.id,{**assignment,"layer_key":None},1)
    assert binding.assignment_json["business_system_id"] == system.id
    assert binding.assignment_json["template_version_id"] == template.id
    assert binding.assignment_json["business_system_name"] == "核心"
    assert binding.assignment_json["target_table_code"] == "REPORT"
    assert binding.assignment_json["template_version_no"] == 1
    frozen = deepcopy(binding.assignment_json)
    system.system_name = "核心新名称"; db.flush()
    assert binding.assignment_json == frozen
    with pytest.raises(HTTPException) as error:
        service.assign_table(db,project.id,table.id,{**assignment,"business_system_id":foreign.id},1)
    assert error.value.status_code == 404
    with pytest.raises(HTTPException):
        service.assign_table(db,project.id,table.id,{**assignment,"template_version_id":None},1)
    with pytest.raises(HTTPException):
        classification_options(other.id,principal,db)
    membership.project_role="viewer";db.flush()
    with pytest.raises(HTTPException) as error:
        classification_options(project.id,principal,db)
    assert error.value.status_code == 403
