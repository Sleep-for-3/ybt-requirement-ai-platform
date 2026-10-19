"""The configuration-centre view of "this scope has not pinned this Skill yet".

The runtime never adopts a published version on its own, so the missing binding used to
surface only inside an agent run as ``skill_binding_missing``.  These cases pin the
read-only todo list that moves that question to the configuration centre, and — just as
importantly — that the list empties whenever a human really pins something.
"""
from test_ai_skill_control import control_env
from test_ai_skill_releases import ready, publish

ROUTE = "/ai-skills/binding-todos"


def _todos(client, scope):
    response = client.get(ROUTE, params=scope)
    assert response.status_code == 200, response.text
    return response.json()


def test_unpublished_skill_is_a_todo_that_publishing_clears(control_env):
    client, _, login, scope, _ = control_env
    login("manager")
    # Registered but never published: the operator is told why there is nothing to pin.
    todo = _todos(client, scope)[0]
    assert todo["skill_key"] == "lineage_edge_explanation"
    assert todo["reason"] == "no_published_version"
    assert todo["latest_published"] is None
    assert todo["available"] is False
    assert todo["code"] == "bind_skill_version"
    assert todo["scope"] == {**scope, "invocation_key": None}
    assert todo["api"] == "/ai-skills/lineage_edge_explanation/binding-options"
    assert todo["bind_api"] == "/ai-skills/lineage_edge_explanation/bindings"

    ready(control_env)
    # A ready-but-unpublished version still cannot be adopted, so the todo stays.
    assert _todos(client, scope)[0]["reason"] == "no_published_version"

    assert publish(control_env).status_code == 200
    # Publishing pins the version to its own scope, so the project's own todo disappears.
    assert _todos(client, scope) == []


def test_todo_points_at_the_newest_available_published_version(control_env):
    client, _, login, scope, _ = control_env
    ready(control_env)
    assert publish(control_env).status_code == 200
    # The task scope is a narrower scope than the project one: the project's pin does not
    # cover it, so the task scope is offered the compatible published version to adopt.
    task_scope = dict(scope, scope_type="task", invocation_key="lineage_graph")
    todo = _todos(client, task_scope)[0]
    assert todo["reason"] == "no_binding"
    assert todo["available"] is True
    assert todo["latest_published"]["version_no"] == 1
    assert todo["latest_published"]["scope_type"] == "project"
    assert todo["scope"]["scope_type"] == "task"


def test_platform_scope_has_no_todos(control_env):
    client, _, login, _scope, _ = control_env
    login("platform")
    assert _todos(client, {"scope_type": "platform"}) == []


def test_todos_require_scope_access(control_env):
    client, _, login, scope, _ = control_env
    login("outsider")
    assert client.get(ROUTE, params=scope).status_code == 404
    login("legacy")
    assert client.get(ROUTE, params=scope).status_code == 401
    # A project manager is not a platform administrator and may not list platform todos.
    login("manager")
    assert client.get(ROUTE, params={"scope_type": "platform"}).status_code == 403
