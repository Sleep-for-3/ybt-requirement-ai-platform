from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from app.models import KnowledgeDocumentVersion
from app.services.requirement_policy_comparison import comparison_issues
from app.services.requirement_revisions import load_revision
from app.services.requirement_review import _unresolved
from test_requirement_script_basis import seed
from test_requirement_resources import add_document
from test_requirement_generation_input import add_unit
from test_requirement_snapshot_api import snapshot_api, snapshot_db


def setup_comparison(sample, category="regulatory_formal"):
    client, db, project, field, req, membership = sample
    doc = add_document(db, project.id, "隔离监管制度")
    doc.source_category = category
    unit = add_unit(db, project.id, doc, "余额应按期末余额报送，不能乘以二。")
    version = db.get(KnowledgeDocumentVersion, unit.document_version_id)
    doc.current_version_id = version.id
    version.lifecycle_status = "active"
    req.scope_json = {**req.scope_json, "document_ids": [doc.id]}
    db.flush()
    base, service, script, payload, _ = seed(client, db, project, req, field)
    response = client.post(base + "/script-basis", json=payload)
    assert response.status_code == 201, response.text
    view = client.get(base + "/policy-comparison?content_version=2")
    assert view.status_code == 200, view.text
    return base, unit, version, view.json(), payload


def decision(view, unit_id, status="conflict"):
    return {"expected_content_version": 2, "basis_hash": view["basis_hash"], "decisions": [{
        "unit_id": unit_id, "rule_ids": [r["rule_id"] for r in view["rules"]], "status": status,
        "rationale": "逐条核对期末口径与表达式", "difference": "脚本将余额乘以二，与制度原值要求不一致"}]}


def test_conflict_is_versioned_and_cannot_become_review_ready(snapshot_api):
    client, db, project, field, req, _ = snapshot_api
    base, unit, _, view, _ = setup_comparison(snapshot_api)
    before = deepcopy(load_revision(db, project.id, req.id, 2).content_json)
    response = client.post(base + "/policy-comparison", json=decision(view, unit.id))
    assert response.status_code == 201, response.text
    content = load_revision(db, project.id, req.id, 3).content_json
    confirmed = content["policy_comparisons"]["decisions"][str(unit.id)]
    assert confirmed["status"] == "conflict" and confirmed["confirmed_by"] and confirmed["confirmed_at"]
    assert confirmed["difference"]
    assert any("存在差异" in g["message"] for g in comparison_issues(content))
    assert load_revision(db, project.id, req.id, 2).content_json == before
    # Even if someone removed the rendered gap list, review recomputes the block.
    content = deepcopy(content); content["gaps"] = []
    assert any(g["code"].startswith("scope:policy:") for g in _unresolved(content))


def test_match_clears_only_comparison_gaps_and_keeps_old_mapping_requirements(snapshot_api):
    client, db, project, _, req, _ = snapshot_api
    base, unit, _, view, _ = setup_comparison(snapshot_api)
    before = deepcopy(load_revision(db, project.id, req.id, 2).content_json)
    payload = decision(view, unit.id, "matched")
    payload["decisions"][0]["rationale"] = "隔离流程测试中的人工判断，非真实制度结论"
    result = client.post(base + "/policy-comparison", json=payload)
    assert result.status_code == 201, result.text
    content = load_revision(db, project.id, req.id, 3).content_json
    assert comparison_issues(content) == []
    other_gaps = {g["id"] for g in before["gaps"] if not g["id"].startswith("scope:policy:")}
    assert other_gaps <= {g["id"] for g in content["gaps"]}
    assert _unresolved(content)  # Matching clauses is not approval of Mapping/lineage.
    assert client.post(base + "/policy-comparison", json=payload).status_code == 409


@pytest.mark.parametrize("invalid", ["unit", "rule", "no_rules", "no_rationale", "no_difference", "duplicate"])
def test_invalid_or_out_of_scope_comparisons_rejected(snapshot_api, invalid):
    client, _, _, _, _, _ = snapshot_api
    base, unit, _, view, _ = setup_comparison(snapshot_api)
    payload = decision(view, unit.id)
    row = payload["decisions"][0]
    if invalid == "unit": row["unit_id"] = 99999
    elif invalid == "rule": row["rule_ids"] = ["script-edge-99999"]
    elif invalid == "no_rules": row["rule_ids"] = []
    elif invalid == "no_rationale": row["rationale"] = " "
    elif invalid == "no_difference": row["difference"] = " "
    else: payload["decisions"].append(deepcopy(row))
    assert client.post(base + "/policy-comparison", json=payload).status_code == 422


def test_technical_material_is_not_promoted_to_policy(snapshot_api):
    client, _, _, _, _, _ = snapshot_api
    base, unit, _, view, _ = setup_comparison(snapshot_api, "technical_evidence")
    assert not view["units"] and view["excluded_unit_count"] == 1
    assert any("缺少有效制度依据" in g["message"] for g in view["issues"])
    assert client.post(base + "/policy-comparison", json=decision(view, unit.id, "matched")).status_code == 422


def test_expired_policy_permission_and_locked_revision_block_confirmation(snapshot_api):
    client, db, project, _, req, membership = snapshot_api
    base, unit, version, view, _ = setup_comparison(snapshot_api)
    payload = decision(view, unit.id)
    membership.project_role = "viewer"; db.flush()
    assert client.post(base + "/policy-comparison", json=payload).status_code == 403
    membership.project_role = "project_manager"
    version.expires_at = datetime.now(timezone.utc) - timedelta(days=1); db.flush()
    assert client.post(base + "/policy-comparison", json=payload).status_code == 409
    version.expires_at = None
    load_revision(db, project.id, req.id, 2).status = "confirmed"; db.flush()
    assert client.post(base + "/policy-comparison", json=payload).status_code == 409


def test_scope_edit_preserves_manual_comparison_and_new_basis_invalidates_it(snapshot_api):
    client, db, project, _, req, _ = snapshot_api
    base, unit, _, view, basis_payload = setup_comparison(snapshot_api)
    assert client.post(base + "/policy-comparison", json=decision(view, unit.id)).status_code == 201
    saved = deepcopy(load_revision(db, project.id, req.id, 3).content_json["policy_comparisons"])
    response = client.put(base, json={**req.scope_json, "name": req.name, "background": "新增背景说明",
        "expected_version": 1, "expected_content_version": 3})
    assert response.status_code == 200, response.text
    assert load_revision(db, project.id, req.id, 4).content_json["policy_comparisons"] == saved
    # Explicitly removing the policy range and reconfirming yields a new basis;
    # previous confirmations remain only in historical revisions.
    assert client.put(base, json={**req.scope_json, "name": req.name, "document_ids": [],
        "expected_version": 2, "expected_content_version": 4}).status_code == 200
    response = client.post(base + "/script-basis", json={**basis_payload, "expected_content_version": 5})
    assert response.status_code == 201, response.text
    latest = load_revision(db, project.id, req.id, 6).content_json
    assert not latest.get("policy_comparisons") and comparison_issues(latest)
    assert load_revision(db, project.id, req.id, 3).content_json["policy_comparisons"] == saved


def test_model_comparison_is_separate_and_regeneration_keeps_human_conflict(snapshot_api, monkeypatch):
    from app.services.task_queue.inline import InlineTaskQueue
    client, db, project, field, req, _ = snapshot_api
    base, unit, _, view, _ = setup_comparison(snapshot_api)
    assert client.post(base + "/policy-comparison", json=decision(view, unit.id)).status_code == 201
    saved = deepcopy(load_revision(db, project.id, req.id, 3).content_json)
    async def fake_model(*args, **kwargs):
        return {"final_content": "合成模型解释", "script_rule_ids": [view["rules"][0]["rule_id"]],
            "policy_comparisons": [{"unit_id": unit.id, "rule_ids": [view["rules"][0]["rule_id"]],
                "status": "matched", "explanation": "仅供验证的模型判断，不覆盖人工冲突结论", "difference": ""}]}
    monkeypatch.setattr("app.services.requirement_generation_worker.execute_runtime_chat", fake_model)
    monkeypatch.setattr("app.services.task_queue.factory.get_task_queue", lambda: InlineTaskQueue())
    response = client.post(base + "/generation-runs", json={"expected_content_version": 3,
        "field_ids": [field.id], "sections": ["lineage"], "idempotency_key": "policy-mock-run"})
    assert response.status_code == 201, response.text
    result = client.get(base + "/policy-comparison?content_version=3").json()
    assert result["ai_suggestions"][0]["comparisons"][0]["status"] == "matched"
    assert result["decisions"][str(unit.id)]["status"] == "conflict"
    assert load_revision(db, project.id, req.id, 3).content_json == saved
    # A historical content view must not acquire candidates generated later.
    assert client.get(base + "/policy-comparison?content_version=2").json()["ai_suggestions"] == []


def test_missing_implementation_and_partial_rule_coverage_remain_blocking(snapshot_api):
    client, db, project, _, req, _ = snapshot_api
    base, unit, _, view, _ = setup_comparison(snapshot_api)
    payload = decision(view, unit.id, "missing_implementation")
    payload["decisions"][0]["rule_ids"] = []
    assert client.post(base + "/policy-comparison", json=payload).status_code == 201
    issues = comparison_issues(load_revision(db, project.id, req.id, 3).content_json)
    assert any("缺少脚本实现" in i["message"] for i in issues)
    assert sum(i["code"].startswith("scope:policy:rule:") for i in issues) == len(view["rules"])
