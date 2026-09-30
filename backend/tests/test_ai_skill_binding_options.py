from app.models import ModelProfile
from test_ai_skill_control import control_env, ROOT
from test_ai_skill_releases import ready, publish


def test_binding_options_show_only_published_metadata_and_recheck_dependencies(control_env):
    client, factory, login, scope, content = control_env
    ready(control_env)
    route = ROOT + "/binding-options"
    assert client.get(route, params=scope).json() == []
    assert publish(control_env).status_code == 200
    option = client.get(route, params=scope).json()[0]
    assert option["version_no"] == 1 and option["available"]
    assert set(option) == {"id", "version_no", "scope_type", "content_hash", "available"}
    login("outsider")
    assert client.get(route, params=scope).status_code == 404
    login("legacy")
    assert client.get(route, params=scope).status_code == 401
    login("manager")
    with factory() as db:
        db.get(ModelProfile, content["model_profile_id"]).enabled = False
        db.commit()
    assert client.get(route, params=scope).json()[0]["available"] is False


def test_parent_option_is_explicitly_adopted_and_does_not_expose_foreign_scope(control_env):
    client, _, login, scope, content = control_env
    parent = {"scope_type": "institution", "institution_id": scope["institution_id"]}
    login("platform")
    version = client.post(ROOT + "/versions", json={"scope": parent, "content": content}).json()
    from test_ai_skill_runtime import envelope
    assert client.post(ROOT + "/test-cases", json={"name": "parent", "input": envelope(scope).model_dump(mode="json")}).status_code == 201
    for mode, lock in (("deterministic", 1), ("mock_model", 2)):
        assert client.post(ROOT + "/test-runs", json={"version": version["version_no"], "project_id": scope["project_id"], "mode": mode, "expected_lock_version": lock}).status_code == 201
    assert client.post(ROOT + "/versions/1/submit", json={"expected_lock_version": 3, "test_project_id": scope["project_id"]}).status_code == 200
    assert publish(control_env).status_code == 200
    login("manager")
    options = client.get(ROOT + "/binding-options", params=scope).json()
    assert len(options) == 1 and options[0]["scope_type"] == "institution"
    assert client.get(ROOT + "/bindings", params=scope).json() is None
    # Existing institution-role checks conceal inaccessible institutions as 404.
    assert client.post(ROOT + "/bindings", json={"scope": scope, "version": 1}).status_code == 404
    login("bank_admin")
    adopted = client.post(ROOT + "/bindings", json={"scope": scope, "version": 1})
    assert adopted.status_code == 200
    assert adopted.json()["inherited_from_scope"]
    assert client.post(ROOT + "/bindings", json={"scope": scope, "version": 1}).status_code == 409
    login("outsider")
    foreign = {"scope_type": "project", "institution_id": scope["institution_id"] + 1, "project_id": scope["project_id"] + 1}
    assert client.get(ROOT + "/binding-options", params=foreign).json() == []
