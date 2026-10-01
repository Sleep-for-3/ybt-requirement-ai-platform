from datetime import datetime, timezone

import pytest
from sqlalchemy import select, func

from app.models import (ProductScenario, CandidateSourceRecommendation, ScenarioTechnicalLineage,
    ColumnProfileTask, ColumnProfileSnapshot, CatalogColumn, ProjectMembership, User)
from test_ai_skill_control import control_env
from test_ai_skill_field_candidates import seeded


def setup(env):
    from app.api.source_recommendations import router
    query, ids = seeded(env)
    client, factory, _, scope, _ = env
    client.app.include_router(router)
    with factory() as db:
        scenario = ProductScenario(project_id=scope["project_id"], scenario_code="PREPARE", scenario_name="候选场景", enabled=True)
        db.add(scenario); db.commit()
        scenario_id = scenario.id
    recalled = client.post("/ai-skills/field-candidates", json=query).json()
    payload = {"input": query, "context_hash": recalled["context_hash"],
        "candidate_id": recalled["candidates"][0]["candidate_id"], "scenario_id": scenario_id}
    return payload, ids


def prepare(env, payload):
    response = env[0].post("/ai-skills/field-candidates/prepare", json=payload)
    assert response.status_code == 200, response.text
    return response.json()["recommendation"]


def profile(factory, row, *, status="completed", total=2):
    with factory() as db:
        task = ColumnProfileTask(project_id=row["project_id"], datasource_id=row["datasource_id"],
            catalog_column_id=row["catalog_column_id"], target_field_id=row["target_field_id"],
            scenario_id=row["scenario_id"], source_recommendation_id=row["id"], status=status,
            finished_at=datetime.now(timezone.utc))
        db.add(task); db.flush()
        db.add(ColumnProfileSnapshot(project_id=row["project_id"], datasource_id=row["datasource_id"],
            catalog_column_id=row["catalog_column_id"], profile_task_id=task.id, total_count=total))
        db.commit()


def test_prepare_idempotent_then_explicit_select_profile_adopt(control_env):
    payload, _ = setup(control_env)
    row = prepare(control_env, payload)
    assert not row["selected_flag"] and row["profile_status"] is None
    assert prepare(control_env, payload)["id"] == row["id"]
    with control_env[1]() as db:
        assert db.scalar(select(func.count()).select_from(ScenarioTechnicalLineage)) == 0
        assert db.scalar(select(func.count()).select_from(CandidateSourceRecommendation)) == 1
    route = f'/source-recommendations/{row["id"]}'
    assert control_env[0].post(route + "/adopt").status_code == 400
    selected = control_env[0].post(route + "/select")
    assert selected.status_code == 200, selected.text
    assert not selected.json()["lineage"]["source_field_english_name"]
    assert control_env[0].post(route + "/adopt").status_code == 400
    profile(control_env[1], row)
    adopted = control_env[0].post(route + "/adopt")
    assert adopted.status_code == 200, adopted.text
    assert adopted.json()["lineage"]["source_field_english_name"] == "balance"
    assert adopted.json()["lineage"]["tech_confirm_status"] == "draft"


@pytest.mark.parametrize("phase", ["prepare", "select", "adopt"])
def test_directory_mutation_invalidates_each_step(control_env, phase):
    payload, ids = setup(control_env)
    row = prepare(control_env, payload) if phase != "prepare" else None
    if phase == "adopt":
        control_env[0].post(f'/source-recommendations/{row["id"]}/select')
        profile(control_env[1], row)
    with control_env[1]() as db:
        db.get(CatalogColumn, ids["column"]).column_comment = "发生变化"
        db.commit()
    response = control_env[0].post("/ai-skills/field-candidates/prepare", json=payload) if phase == "prepare" else control_env[0].post(f'/source-recommendations/{row["id"]}/{phase}')
    assert response.status_code == 409, response.text


@pytest.mark.parametrize("status,total", [("failed", 2), ("running", 2), ("partially_completed", None)])
def test_incomplete_profile_cannot_be_adopted(control_env, status, total):
    payload, _ = setup(control_env)
    row = prepare(control_env, payload)
    route = f'/source-recommendations/{row["id"]}'
    control_env[0].post(route + "/select")
    profile(control_env[1], row, status=status, total=total)
    assert control_env[0].post(route + "/adopt").status_code == 400


@pytest.mark.parametrize("identity,status", [("outsider", 404), ("legacy", 401)])
def test_prepare_and_existing_write_routes_reauthorize(control_env, identity, status):
    payload, _ = setup(control_env)
    row = prepare(control_env, payload)
    control_env[2](identity)
    assert control_env[0].post("/ai-skills/field-candidates/prepare", json=payload).status_code == status
    assert control_env[0].post(f'/source-recommendations/{row["id"]}/select').status_code == status
    assert control_env[0].post(f'/source-recommendations/{row["id"]}/adopt').status_code == status


def test_outside_candidate_and_scenario_rejected(control_env):
    payload, _ = setup(control_env)
    assert control_env[0].post("/ai-skills/field-candidates/prepare", json={**payload, "candidate_id": "catalog:999999"}).status_code == 422
    assert control_env[0].post("/ai-skills/field-candidates/prepare", json={**payload, "scenario_id": 999999}).status_code == 404


def test_shared_guard_routes_technical_reader_search_and_profile_permissions(control_env):
    from fastapi import Depends
    from app.services.auth.resource_guard import guard_project_resource
    payload, ids = setup(control_env)
    client, factory, _, scope, _ = control_env
    dependencies = [Depends(guard_project_resource)]
    @client.app.get("/target-fields/{field_id}/scenario-business-mappings", dependencies=dependencies)
    def read_business(field_id: int): return {"read": True}
    @client.app.post("/catalog/columns/{column_id}/profile", dependencies=dependencies)
    def profile_permission(column_id: int): return {"allowed": True}
    @client.app.post("/projects/{project_id}/knowledge/planned-search", dependencies=dependencies)
    def planned_permission(project_id: int): return {"allowed": True}
    @client.app.post("/projects/{project_id}/knowledge/documents/upload", dependencies=dependencies)
    def manage_permission(project_id: int): return {"allowed": True}
    with factory() as db:
        manager = db.scalar(select(User).where(User.username == "manager"))
        membership = db.scalar(select(ProjectMembership).where(ProjectMembership.project_id == scope["project_id"],
            ProjectMembership.user_id == manager.id))
        membership.project_role = "technical_analyst"
        db.commit()
    assert client.get(f'/target-fields/{payload["input"]["target_field_id"]}/scenario-business-mappings').status_code == 200
    assert client.post(f'/catalog/columns/{ids["column"]}/profile').status_code == 200
    assert client.post(f'/projects/{scope["project_id"]}/knowledge/planned-search').status_code == 200
    assert client.post(f'/projects/{scope["project_id"]}/knowledge/documents/upload').status_code == 403
    with factory() as db:
        db.get(ProjectMembership, membership.id).project_role = "viewer"
        db.commit()
    assert client.post(f'/catalog/columns/{ids["column"]}/profile').status_code == 403
