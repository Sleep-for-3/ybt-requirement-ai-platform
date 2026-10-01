import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.mapping_rules import router
from app.core.database import get_db
from app.models import WorkflowInstance
from app.services.auth.dependencies import get_current_principal
from app.services.llm.execution_metadata import stable_hash
from test_ai_skill_control import control_env
from test_double_layer_mapping import _seed_source_mapping, _seed_mart_to_ybt_mapping, _principal


@pytest.mark.parametrize("kind", ["source_to_mart", "mart_to_ybt"])
@pytest.mark.parametrize("state", ["allowed", "human", "approved", "review", "stale", "missing"])
def test_adoption_never_overwrites_human_or_reviewed_content(control_env, kind, state):
    _, factory, _, _, _ = control_env
    with factory() as db:
        fixture = _seed_source_mapping(db, kind + state)
        mapping = fixture["mapping"] if kind == "source_to_mart" else _seed_mart_to_ybt_mapping(db, fixture, "guard")
        mapping.ai_generated_content = "可核验候选"
        if state == "human": mapping.final_content = "人工编辑保持原样"
        if state == "approved": mapping.mapping_status = "approved"
        if state == "review":
            db.add(WorkflowInstance(project_id=mapping.project_id, workflow_key="double_layer_mapping_review",
                target_type=kind, target_id=mapping.id, status="in_progress", created_by=fixture["user"].id))
        db.commit()
        before = mapping.final_content
        app = FastAPI(); app.include_router(router)
        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_current_principal] = lambda: _principal(fixture)
        with TestClient(app) as client:
            payload = None if state == "missing" else {"expected_draft_hash": stable_hash("已过期候选" if state == "stale" else "可核验候选")}
            response = client.post(f'/{kind.replace("_", "-")}-mappings/{mapping.id}/adopt-ai-draft', json=payload)
            assert response.status_code == (200 if state == "allowed" else 409), response.text
            db.refresh(mapping)
            assert mapping.final_content == ("可核验候选" if state == "allowed" else before)
