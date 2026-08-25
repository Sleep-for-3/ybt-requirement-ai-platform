from datetime import date

from app.models import SemanticBinding, SemanticConcept
from backend.tests.test_semantic_layer import (
    _post,
    _projects,
    _required_binding_entities,
    _semantic_client,
)


def test_semantic_catalog_traces_canonical_effective_definition_and_confirmed_assets() -> None:
    with _semantic_client() as (client, sessions):
        project_id, _ = _projects(sessions)
        target_field_id = _required_binding_entities(sessions, project_id)["target_field"]
        concept = _post(
            client,
            f"/api/projects/{project_id}/semantic-concepts",
            {
                "concept_type": "business_term",
                "concept_code": "CUST_NO",
                "concept_name": "客户统一编号",
                "definition": "由正式版本提供的客户统一编号定义",
                "business_domain": "客户",
                "owner_department": "数据治理部",
            },
        )
        confirmed = client.post(
            f"/api/projects/{project_id}/semantic-concepts/{concept['id']}/status",
            json={"status": "confirmed"},
        )
        assert confirmed.status_code == 200, confirmed.text

        with sessions() as db:
            db.get(SemanticConcept, concept["id"]).definition = "不得作为目录正式定义"
            db.add_all(
                [
                    SemanticBinding(
                        project_id=project_id,
                        institution_id=db.get(SemanticConcept, concept["id"]).institution_id,
                        semantic_concept_id=concept["id"],
                        entity_type="target_field",
                        entity_id=target_field_id,
                        binding_type="describes",
                        status="confirmed",
                    ),
                    SemanticBinding(
                        project_id=project_id,
                        institution_id=db.get(SemanticConcept, concept["id"]).institution_id,
                        semantic_concept_id=concept["id"],
                        entity_type="target_field",
                        entity_id=target_field_id + 10_000,
                        binding_type="candidate",
                        status="ai_suggested",
                    ),
                    SemanticConcept(
                        project_id=project_id,
                        institution_id=db.get(SemanticConcept, concept["id"]).institution_id,
                        concept_type="business_term",
                        concept_code="REJECTED",
                        concept_name="已拒绝口径",
                        status="rejected",
                    ),
                ]
            )
            db.commit()

        response = client.get(
            f"/api/projects/{project_id}/semantic-catalog",
            params={"as_of": date.today().isoformat()},
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["total"] == 1
        assert payload["page"] == 1
        assert payload["page_size"] == 50
        assert payload["mode"] == "candidate"
        assert payload["items"] == [
            {
                **payload["items"][0],
                "id": concept["id"],
                "project_id": project_id,
                "concept_code": "CUST_NO",
                "concept_name": "客户统一编号",
                "business_domain": "客户",
                "owner_department": "数据治理部",
                "related_asset_count": 1,
            }
        ]
        assert (
            payload["items"][0]["effective_version"]["definition"]
            == "由正式版本提供的客户统一编号定义"
        )
        assert "不得作为目录正式定义" not in response.text
        assert "REJECTED" not in response.text

