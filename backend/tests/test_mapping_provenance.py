from sqlalchemy import select

from app.api.mapping_evidence import router
from app.models import AuditLog, ProductScenario, ScenarioBusinessMapping
from app.services.llm.execution_metadata import stable_hash
from test_ai_skill_control import control_env
from test_ai_skill_field_candidates import seeded


def test_provenance_requires_exact_target_project_and_safe_metadata(control_env):
    query, _ = seeded(control_env)
    client, factory, login, scope, _ = control_env
    client.app.include_router(router)
    with factory() as db:
        scenario = ProductScenario(project_id=scope["project_id"], scenario_code="synthetic", scenario_name="Synthetic")
        db.add(scenario); db.flush()
        row = ScenarioBusinessMapping(project_id=scope["project_id"], target_field_id=query["target_field_id"],
            scenario_id=scenario.id, ai_generated_content="synthetic draft")
        db.add(row); db.flush()
        mapping_id = row.id
        event = AuditLog(project_id=scope["project_id"], action="generate_business_draft", result="success",
            resource_type="scenario_business_mapping", resource_id=str(mapping_id), after_summary_json={
                "draft_hash": stable_hash("synthetic draft"), "execution_metadata": {
                    "execution_kind": "mock_model", "provider_type": "mock", "model_name": "mock-llm",
                    "system_prompt": "SECRET_PROMPT", "regression_input": "SECRET_INPUT", "config": {"api_key": "SECRET"}}})
        db.add(event); db.commit()
    path = f"/mappings/scenario_business/{mapping_id}/generation-provenance"
    result = client.get(path)
    assert result.status_code == 200 and result.json()["status"] == "current_text"
    assert "SECRET" not in result.text
    assert result.json()["execution_metadata"]["runtime_mode"] == "legacy"
    login("outsider")
    assert client.get(path).status_code == 404
    login("manager")
    with factory() as db:
        event = db.scalar(select(AuditLog).where(AuditLog.action == "generate_business_draft"))
        event.project_id += 1
        db.commit()
    assert client.get(path).json()["status"] == "unavailable"
    assert client.get(f"/mappings/unknown/{mapping_id}/generation-provenance").status_code == 404


def test_unlinked_skill_audit_cannot_invent_model_provenance(control_env):
    query, _ = seeded(control_env)
    client, factory, _, scope, _ = control_env
    client.app.include_router(router)
    with factory() as db:
        scenario = ProductScenario(project_id=scope["project_id"], scenario_code="synthetic", scenario_name="Synthetic")
        db.add(scenario); db.flush()
        row = ScenarioBusinessMapping(project_id=scope["project_id"], target_field_id=query["target_field_id"],
            scenario_id=scenario.id, ai_generated_content="draft")
        db.add(row); db.flush()
        mapping_id = row.id
        db.add(AuditLog(project_id=scope["project_id"], action="generate_business_draft", result="success",
            resource_type="scenario_business_mapping", resource_id=str(mapping_id), after_summary_json={
                "draft_hash": stable_hash("draft"), "execution_metadata": {
                    "runtime_mode": "skill", "run_id": 999999, "skill_version_id": 999999}}))
        db.commit()
    result = client.get(f"/mappings/scenario_business/{mapping_id}/generation-provenance")
    assert result.status_code == 200
    assert result.json() == {"status": "unavailable", "execution_metadata": None}
