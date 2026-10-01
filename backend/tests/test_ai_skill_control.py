from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.ai_skills import router, runs_router
from app.core.database import Base, get_db
from app.models import (AISkillDefinition, AISkillVersion, AISkillScopeBinding, AISkillReleaseEvent,
                        AuditLog, Institution, InstitutionMembership, ModelProfile, Project, ProjectMembership, User)
from app.services.auth.dependencies import Principal, get_current_principal

ROOT = "/ai-skills/lineage_edge_explanation"


@pytest.fixture
def control_env():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as db:
        institutions = [Institution(institution_code=code, institution_name=code,
                                    institution_type="platform_operator" if code == "platform" else "bank")
                        for code in ("platform", "a", "b")]
        users = [User(username=name, status="active") for name in ("platform", "manager", "bank_admin", "outsider")]
        db.add_all(institutions + users)
        db.flush()
        platform, bank, other_bank = institutions
        admin, manager, bank_admin, outsider = users
        db.add_all([InstitutionMembership(institution_id=platform.id, user_id=admin.id, role="institution_admin", status="active"),
                    InstitutionMembership(institution_id=bank.id, user_id=bank_admin.id, role="institution_admin", status="active")])
        projects = [Project(name="a", institution_id=bank.id), Project(name="b", institution_id=other_bank.id)]
        db.add_all(projects)
        model = ModelProfile(profile_name="mock", provider_type="mock", local_only=True, enabled=True)
        db.add(model)
        db.flush()
        db.add_all([ProjectMembership(project_id=projects[0].id, user_id=manager.id, project_role="project_manager", status="active"),
                    ProjectMembership(project_id=projects[1].id, user_id=outsider.id, project_role="project_manager", status="active")])
        db.commit()
        ids = {user.username: user.id for user in users}
        scope = {"scope_type": "project", "institution_id": bank.id, "project_id": projects[0].id}
        content = {"system_prompt": "只根据证据解释", "model_profile_id": model.id}
    app = FastAPI()
    app.include_router(router)
    app.include_router(runs_router)
    def session():
        with factory() as db:
            yield db
    app.dependency_overrides[get_db] = session
    def login(name):
        principal = Principal(ids[name], name, name) if name != "legacy" else Principal(None, "legacy", None, True)
        app.dependency_overrides[get_current_principal] = lambda: principal
    login("platform")
    with TestClient(app) as client:
        response = client.post("/ai-skills", json={"skill_key": "lineage_edge_explanation", "task_key": "lineage_edge_explanation", "display_name": "血缘解释"})
        assert response.status_code == 201, response.text
        yield client, factory, login, scope, content
    engine.dispose()


def draft(env):
    client, _, login, scope, content = env
    login("manager")
    response = client.post(ROOT + "/versions", json={"scope": scope, "content": content})
    assert response.status_code == 201, response.text
    return response.json()


def test_draft_edit_stale_conflict_and_audit(control_env):
    client, factory, _, _, content = control_env
    item = draft(control_env)
    path = ROOT + f'/versions/{item["version_no"]}'
    edit = {"expected_lock_version": 1, "content": dict(content, system_prompt="修改后的解释")}
    updated = client.patch(path, json=edit)
    assert updated.status_code == 200
    assert updated.json()["lock_version"] == 2
    assert client.patch(path, json=edit).status_code == 409
    assert client.get(path).json()["content_hash"] == updated.json()["content_hash"]
    with factory() as db:
        actions = db.scalars(select(AISkillReleaseEvent.action)).all()
        assert actions == ["created", "draft_created", "draft_edited"]
        assert len(db.scalars(select(AuditLog)).all()) == 3


def test_scope_authentication_and_cross_tenant_reads(control_env):
    client, _, login, scope, content = control_env
    item = draft(control_env)
    login("outsider")
    assert client.get(ROOT + f'/versions/{item["version_no"]}').status_code == 404
    assert client.get(ROOT + "/versions", params=scope).status_code == 404
    assert client.post(ROOT + "/versions", json={"scope": scope, "content": content}).status_code == 404
    login("manager")
    spoofed = dict(scope, institution_id=scope["institution_id"] + 1)
    assert client.post(ROOT + "/versions", json={"scope": spoofed, "content": content}).status_code == 404
    login("legacy")
    assert client.get("/ai-skills").status_code == 401
    assert client.post(ROOT + "/versions", json={"scope": scope, "content": content}).status_code == 401


@pytest.mark.parametrize("template", ["{facts.__class__}", "{facts[0]}", "{unknown}", "{facts!r}", "{facts:>10}", "{facts"])
def test_template_cannot_access_attributes_or_unknown_variables(control_env, template):
    client, _, login, scope, content = control_env
    login("manager")
    result = client.post(ROOT + "/versions", json={"scope": scope, "content": dict(content, user_prompt_template=template)})
    assert result.status_code == 422


def test_publish_closed_and_client_cannot_supply_safety_bypass(control_env):
    client, factory, login, scope, content = control_env
    item = draft(control_env)
    login("bank_admin")
    result = client.post(ROOT + f'/versions/{item["version_no"]}/publish', json={"expected_lock_version": 1, "test_project_id": scope["project_id"]})
    assert result.status_code == 409
    assert result.json()["detail"]["error_code"] == "test_cases_required"
    for field, value in [("allow_tools", True), ("require_fact_references", False), ("tests_passed", True)]:
        assert client.post(ROOT + "/versions", json={"scope": scope, "content": dict(content, **{field: value})}).status_code == 422
    with factory() as db:
        assert db.scalars(select(AISkillScopeBinding)).all() == []
        assert db.get(AISkillVersion, item["id"]).status == "draft"


def test_restore_creates_new_draft_and_published_content_stays_immutable(control_env):
    client, factory, _, _, content = control_env
    item = draft(control_env)
    with factory() as db:
        source = db.get(AISkillVersion, item["id"])
        source.status = "published"
        source.published_at = datetime.now(timezone.utc)
        db.commit()
    path = ROOT + f'/versions/{item["version_no"]}'
    assert client.patch(path, json={"expected_lock_version": 1, "content": content}).status_code == 409
    restored = client.post(path + "/restore")
    assert restored.status_code == 201, restored.text
    assert restored.json()["status"] == "draft"
    assert restored.json()["version_no"] == 2
    assert restored.json()["restored_from_version_id"] == item["id"]
    assert restored.json()["content_hash"] == item["content_hash"]
    assert client.get(path).json()["status"] == "published"


def test_database_rejects_duplicate_platform_bindings_and_wrong_definition(control_env):
    _, factory, _, _, _ = control_env
    item = draft(control_env)
    with factory() as db:
        version = db.get(AISkillVersion, item["id"])
        binding = dict(definition_id=version.definition_id, version_id=version.id, scope_type="platform",
                       scope_key="platform", updated_by=version.created_by)
        db.add(AISkillScopeBinding(**binding))
        db.commit()
        db.add(AISkillScopeBinding(**binding))
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()
        other = AISkillDefinition(skill_key="other", task_key="policy_comparison", display_name="other", created_by=version.created_by)
        db.add(other)
        db.commit()
        db.add(AISkillScopeBinding(**dict(binding, definition_id=other.id)))
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()


def test_suspended_project_blocks_even_platform_admin_writes(control_env):
    client, factory, login, scope, content = control_env
    with factory() as db:
        db.get(Project, scope["project_id"]).project_status = "suspended"
        db.commit()
    login("platform")
    assert client.post(ROOT + "/versions", json={"scope": scope, "content": content}).status_code == 409


def test_configuration_support_reads_are_scoped_and_do_not_expose_credentials(control_env):
    client, _, login, scope, content = control_env
    login("manager")
    models = client.get("/ai-skills/model-options", params=scope)
    assert models.status_code == 200
    assert models.json()[0]["id"] == content["model_profile_id"]
    assert set(models.json()[0]) == {"id", "name", "provider_type", "model_name"}
    assert client.get(ROOT + "/bindings", params=scope).json() is None
    assert client.get(ROOT + "/test-runs", params={"project_id": scope["project_id"]}).json() == []
    login("outsider")
    assert client.get("/ai-skills/model-options", params=scope).status_code == 404
    assert client.get(ROOT + "/bindings", params=scope).status_code == 404
    assert client.get(ROOT + "/test-runs", params={"project_id": scope["project_id"]}).status_code == 404
