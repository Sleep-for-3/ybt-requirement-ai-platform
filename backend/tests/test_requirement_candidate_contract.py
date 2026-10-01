from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.services.requirement_candidate_contract import RequirementCandidate, check_candidate_compliance, project_candidate_context


def frozen_context():
    return {
        "physical_sources": [{"kind": "source", "table_id": 10, "field_id": 11}],
        "evidence": [
            {"unit_id": 20, "source_category": "regulatory_formal"},
            {"unit_id": 21, "source_category": "technical_document"},
        ],
        "script_basis": {"rules": [{"rule_id": "fixed-rule-1"}]},
    }


def candidate():
    return {
        "final_content": "仅供人工核验的候选",
        "physical_references": [{"kind": "source", "table_id": 10, "field_id": 11}],
        "evidence_unit_ids": [20],
        "script_rule_ids": ["fixed-rule-1"],
        "policy_comparisons": [{"unit_id": 20, "rule_ids": ["fixed-rule-1"],
            "status": "conflict", "explanation": "实际规则与条款存在差异", "difference": "过滤条件缺失"}],
    }


def test_worker_uses_shared_contract_without_mutating_frozen_context():
    from app.services import requirement_generation_worker as worker
    assert worker.RequirementCandidate is RequirementCandidate
    assert worker.check_candidate_compliance is check_candidate_compliance
    context = frozen_context()
    original = deepcopy(context)
    parsed = RequirementCandidate.model_validate(candidate()).model_dump()
    assert check_candidate_compliance(context, parsed) == []
    assert context == original
    assert "adopted" not in parsed and "confirmed_by" not in parsed


@pytest.mark.parametrize("replacement", [
    {"physical_references": [{"kind": "mart", "table_id": 10, "field_id": 11}]},
    {"physical_references": [{"kind": "source", "table_id": 99, "field_id": 11}]},
    {"physical_references": [{"kind": "source", "table_id": 10, "field_id": 99}]},
    {"evidence_unit_ids": [999]},
    {"script_rule_ids": ["unknown-rule"]},
    {"policy_comparisons": [{"unit_id": 21, "rule_ids": ["fixed-rule-1"], "status": "matched", "explanation": "技术文档不能替代制度"}]},
    {"policy_comparisons": [{"unit_id": 20, "rule_ids": ["unknown-rule"], "status": "pending", "explanation": "待确认"}]},
    {"policy_comparisons": [{"unit_id": 20, "rule_ids": ["fixed-rule-1"], "status": "conflict", "explanation": "差异为空", "difference": "  "}]},
])
def test_candidate_references_remain_within_each_frozen_evidence_class(replacement):
    parsed = RequirementCandidate.model_validate({**candidate(), **replacement}).model_dump()
    assert check_candidate_compliance(frozen_context(), parsed)


@pytest.mark.parametrize("invalid", [True, "20", 20.0, 0, -1])
def test_reference_ids_are_positive_integers_without_coercion(invalid):
    for replacement in (
        {"evidence_unit_ids": [invalid]},
        {"physical_references": [{"kind": "source", "table_id": 10, "field_id": invalid}]},
        {"policy_comparisons": [{"unit_id": invalid, "rule_ids": ["fixed-rule-1"], "status": "matched", "explanation": "候选"}]},
    ):
        with pytest.raises(ValidationError):
            RequirementCandidate.model_validate({**candidate(), **replacement})


@pytest.mark.parametrize("key", ["adopted", "confirmed_by", "human_confirmation_status"])
def test_model_cannot_assert_human_decision(key):
    with pytest.raises(ValidationError):
        RequirementCandidate.model_validate({**candidate(), key: True})


def test_projection_selects_one_target_and_retains_all_evidence_without_mutation():
    frozen = {**frozen_context(), "field_ids": [1, 2], "sections": ["business", "lineage"],
        "fields": [{"target": {"id": 1}, "authored": {"business": {"final_content": "人工正文"}}},
                   {"target": {"id": 2}, "authored": {}}]}
    original = deepcopy(frozen)
    projected = project_candidate_context(frozen, 1, "business")
    assert projected["fields"] == [original["fields"][0]]
    assert projected["evidence"] == original["evidence"]
    assert projected["script_basis"] == original["script_basis"]
    projected["fields"][0]["authored"]["business"]["final_content"] = "候选正文"
    projected["evidence"].clear()
    assert frozen == original


@pytest.mark.parametrize("field_id,section,fields", [
    (2, "business", [{"target": {"id": 1}}]),
    (True, "business", [{"target": {"id": 1}}]),
    (1, "lineage", [{"target": {"id": 1}}]),
    (1, "unknown", [{"target": {"id": 1}}]),
    (1, "business", []),
    (1, "business", [{"target": {"id": 1}}, {"target": {"id": 1}}]),
])
def test_out_of_scope_or_ambiguous_queue_items_never_start_a_model(monkeypatch, field_id, section, fields):
    from types import SimpleNamespace
    from fastapi import HTTPException
    from app.services import requirement_generation_worker as worker
    monkeypatch.setattr(worker, "get_prompt_runtime", lambda *args: pytest.fail("Invalid item reached model preparation"))
    frozen = {"field_ids": [1], "sections": ["business"], "fields": fields}
    with pytest.raises(HTTPException) as error:
        worker.generate_candidate(None, SimpleNamespace(input_json=frozen),
            SimpleNamespace(field_id=field_id, section=section), None)
    assert error.value.status_code == 409
