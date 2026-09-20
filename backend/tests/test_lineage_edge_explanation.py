"""Contract tests for grounded, project-scoped lineage edge explanations."""

from __future__ import annotations

from test_lineage_graph_contract import _stack

from app.services.lineage.explanation import LineageEdgeExplanationOutput, _relation_label, _sanitize_output


def test_write_edge_types_use_business_language() -> None:
    assert _relation_label({"edge_type": "insert"}) == "插入写入"
    assert _relation_label({"edge_type": "update"}) == "更新写入"
    assert _relation_label({"edge_type": "merge"}) == "合并写入"


def _first_edge(client, seeded: dict) -> dict:
    response = client.get(
        f"/api/projects/{seeded['project_id']}/lineage/table-graph"
        f"?kind=target&table_id={seeded['target_table_id']}&revision_id={seeded['revision_id']}"
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["edges"]
    return payload["edges"][0]


def test_mock_explanation_keeps_script_facts_and_marks_missing_regulation():
    with _stack("AIEXP") as (client, seeded_by_code):
        seeded = seeded_by_code["AIEXP"]
        edge = _first_edge(client, seeded)
        response = client.post(
            f"/api/projects/{seeded['project_id']}/lineage/edge-explanations",
            json={"edge_id": edge["id"], "revision_id": seeded["revision_id"]},
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["status"] == "ready"
        assert payload["model"]["provider"] == "mock"
        assert payload["deterministic"]["summary"]
        assert payload["ai"]["regulatory_status"] == "missing_basis"
        assert payload["ai"]["unsupported_claim_count"] == 0
        assert payload["ai"]["plain_language_steps"]
        assert any(item["id"] == "script_version" for item in payload["facts"])
        assert any(item["id"] == "transformation" for item in payload["facts"]) is False
        assert payload["disclaimer"]


def test_unknown_model_fact_references_are_rejected():
    output = LineageEdgeExplanationOutput.model_validate({
        "business_summary": "客户标识从来源字段进入目标字段。",
        "plain_language_steps": [
            {"text": "有效结论", "fact_ids": ["source_entity"]},
            {"text": "伪造依据", "fact_ids": ["invented_fact"]},
        ],
        "regulatory_interpretation": "脚本现状只是实现事实。",
        "regulatory_status": "grounded",
        "risks": [{"text": "没有制度依据", "fact_ids": ["target_entity"]}],
        "open_questions": ["请确认业务口径。"],
        "confidence_level": "high",
    })
    result = _sanitize_output(output.model_dump(), {"source_entity", "target_entity"}, [])
    assert result["regulatory_status"] == "missing_basis"
    assert result["unsupported_claim_count"] == 1
    assert result["confidence_level"] == "low"
    assert [item["text"] for item in result["plain_language_steps"]] == ["有效结论"]


def test_edge_explanation_is_scoped_to_the_selected_project_revision():
    with _stack("AIONE", "AITWO") as (client, seeded_by_code):
        first = seeded_by_code["AIONE"]
        second = seeded_by_code["AITWO"]
        foreign_edge = _first_edge(client, second)
        response = client.post(
            f"/api/projects/{first['project_id']}/lineage/edge-explanations",
            json={"edge_id": foreign_edge["id"], "revision_id": first["revision_id"]},
        )
        assert response.status_code == 404
        response = client.post(
            f"/api/projects/{first['project_id']}/lineage/edge-explanations",
            json={"edge_id": foreign_edge["id"], "revision_id": second["revision_id"]},
        )
        assert response.status_code == 404


def test_model_failure_degrades_without_losing_deterministic_facts(monkeypatch):
    with _stack("AIFAIL") as (client, seeded_by_code):
        seeded = seeded_by_code["AIFAIL"]
        edge = _first_edge(client, seeded)
        import app.services.lineage.explanation as service

        async def fail(*args, **kwargs):
            raise RuntimeError("synthetic provider outage")

        monkeypatch.setattr(service, "execute_runtime_chat", fail)
        response = client.post(
            f"/api/projects/{seeded['project_id']}/lineage/edge-explanations",
            json={"edge_id": edge["id"], "revision_id": seeded["revision_id"]},
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["status"] == "degraded"
        assert payload["ai"] is None
        assert payload["facts"]
        assert payload["deterministic"]["summary"]
