import pytest
from sqlalchemy import func, select

from app.models import (CatalogColumn, CatalogTable, CatalogSchema, DataSource, TargetField, TargetTable,
    CandidateSourceRecommendation, ProjectMembership, User)
from test_ai_skill_control import control_env


def seeded(env):
    _, factory, login, scope, _ = env
    with factory() as db:
        datasource = DataSource(project_id=scope["project_id"], name="isolated", db_type="postgresql",
            host="NEVER_CONNECT", encrypted_password="SECRET_MUST_NOT_APPEAR", database_name="bank", enabled=True)
        target_table = TargetTable(project_id=scope["project_id"], table_code="RPT", table_name="监管表")
        db.add_all([datasource, target_table]); db.flush()
        schema = CatalogSchema(project_id=scope["project_id"], datasource_id=datasource.id, schema_name="public", enabled=True)
        target = TargetField(project_id=scope["project_id"], target_table_id=target_table.id, field_code="balance", field_name="余额")
        db.add_all([schema, target]); db.flush()
        table = CatalogTable(project_id=scope["project_id"], datasource_id=datasource.id, catalog_schema_id=schema.id,
            schema_name="public", table_name="account", enabled=True)
        db.add(table); db.flush()
        columns = [CatalogColumn(project_id=scope["project_id"], datasource_id=datasource.id, catalog_table_id=table.id,
            schema_name="public", table_name="account", column_name=name, column_comment=comment, enabled=True)
            for name, comment in (("balance", "账户余额"), ("id", "账户编号"))]
        db.add_all(columns); db.commit()
        result = {"project_id": scope["project_id"], "target_field_id": target.id, "top_k": 20}
        ids = {"datasource": datasource.id, "table": table.id, "schema": schema.id, "column": columns[0].id}
    login("manager")
    return result, ids


def proposal(query, result):
    return {"input": query, "context_hash": result["context_hash"], "ranking": [
        {"candidate_id": item["candidate_id"], "score": 0.5, "rationale": "固定回放重排，待人工核验"}
        for item in reversed(result["candidates"])]}


def test_read_only_candidate_recall_and_replay_never_adopt_or_expose_connections(control_env):
    query, _ = seeded(control_env)
    client, factory, _, _, _ = control_env
    response = client.post("/ai-skills/field-candidates", json=query)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["candidates"][0]["column_name"] == "balance"
    assert result["scanned_count"] == 2
    assert "SECRET_MUST_NOT_APPEAR" not in response.text and "NEVER_CONNECT" not in response.text
    replay = client.post("/ai-skills/field-candidates/validate-ranking", json=proposal(query, result))
    assert replay.status_code == 200, replay.text
    assert replay.json()["ranking_mode"] == "validated_proposal"
    assert replay.json()["requires_human_confirmation"] is True
    assert replay.json()["writes_mapping"] is False
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(CandidateSourceRecommendation)) == 0


@pytest.mark.parametrize("mutation", ["unknown", "duplicate", "missing"])
def test_reranker_cannot_change_the_candidate_allowlist(control_env, mutation):
    query, _ = seeded(control_env)
    client = control_env[0]
    payload = proposal(query, client.post("/ai-skills/field-candidates", json=query).json())
    if mutation == "unknown":
        payload["ranking"][0]["candidate_id"] = "catalog:999999"
    elif mutation == "duplicate":
        payload["ranking"][0] = dict(payload["ranking"][1])
    else:
        payload["ranking"].pop()
    response = client.post("/ai-skills/field-candidates/validate-ranking", json=payload)
    assert response.status_code == 422


@pytest.mark.parametrize("change", ["metadata", "disabled_datasource", "disabled_schema", "broken_scope", "permission"])
def test_replay_reauthorizes_and_reloads_metadata(control_env, change):
    query, ids = seeded(control_env)
    client, factory, _, scope, _ = control_env
    payload = proposal(query, client.post("/ai-skills/field-candidates", json=query).json())
    with factory() as db:
        if change == "metadata":
            db.get(CatalogColumn, ids["column"]).column_comment = "新口径"
        elif change == "disabled_datasource":
            db.get(DataSource, ids["datasource"]).enabled = False
        elif change == "disabled_schema":
            db.get(CatalogSchema, ids["schema"]).enabled = False
        elif change == "broken_scope":
            db.get(CatalogTable, ids["table"]).project_id += 1
        else:
            manager = db.scalar(select(User).where(User.username == "manager"))
            db.scalar(select(ProjectMembership).where(ProjectMembership.project_id == scope["project_id"],
                ProjectMembership.user_id == manager.id)).project_role = "viewer"
        db.commit()
    response = client.post("/ai-skills/field-candidates/validate-ranking", json=payload)
    assert response.status_code == (403 if change == "permission" else 409), response.text


def test_cross_project_target_and_oversized_recall_are_rejected(control_env, monkeypatch):
    query, _ = seeded(control_env)
    client, _, login, _, _ = control_env
    login("outsider")
    assert client.post("/ai-skills/field-candidates", json=query).status_code == 404
    login("legacy")
    assert client.post("/ai-skills/field-candidates", json=query).status_code == 401
    login("manager")
    from app.services.ai_skills import field_candidates
    monkeypatch.setattr(field_candidates, "MAX_SCANNED_COLUMNS", 1)
    response = client.post("/ai-skills/field-candidates", json=query)
    assert response.status_code == 409
    assert response.json()["detail"]["error_code"] == "candidate_scope_too_large"


@pytest.mark.parametrize("score", [True, "0.9", float("nan"), float("inf"), -0.1, 1.1])
def test_rank_scores_cannot_use_coercion_or_nonfinite_values(score):
    from pydantic import ValidationError
    from app.schemas.ai_skill_ranking import CandidateRank
    with pytest.raises(ValidationError):
        CandidateRank(candidate_id="catalog:1", score=score, rationale="回放")


def test_ranking_snapshot_is_bound_to_actor_and_exact_target_scope(control_env):
    query, _ = seeded(control_env)
    client, _, login, _, _ = control_env
    result = client.post("/ai-skills/field-candidates", json=query).json()
    assert client.post("/ai-skills/field-candidates", json={**query, "target_field_id": 999999}).status_code == 404
    login("bank_admin")
    response = client.post("/ai-skills/field-candidates/validate-ranking", json=proposal(query, result))
    assert response.status_code == 409, response.text
