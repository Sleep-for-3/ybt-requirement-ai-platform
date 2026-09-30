import pytest

from test_ai_skill_control import control_env, draft


@pytest.mark.parametrize("name,register,publish", [
    ("manager", False, False), ("bank_admin", False, True), ("platform", True, True)])
def test_capabilities_match_scope_permissions(control_env, name, register, publish):
    client, _, login, scope, _ = control_env
    login(name)
    response = client.get("/ai-skills/capabilities", params=scope)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["can_register"] is register
    assert data["can_publish"] is publish
    assert data["can_edit"] is True
    assert data["actor_id"] > 0


def test_capabilities_deny_foreign_and_legacy_and_expose_author_for_independent_ui(control_env):
    client, _, login, scope, _ = control_env
    item = draft(control_env)
    manager = client.get("/ai-skills/capabilities", params=scope).json()
    assert item["created_by"] == manager["actor_id"]
    for name, status in (("outsider", 404), ("legacy", 401)):
        login(name)
        assert client.get("/ai-skills/capabilities", params=scope).status_code == status
