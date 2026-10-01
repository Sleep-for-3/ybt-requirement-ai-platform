"""Small reproducible boundary corpus; not a real-model quality benchmark."""
import json
from pathlib import Path

import pytest

from app.models import TargetField
from app.schemas.ai_skill import SkillInputEnvelope, validate_claim_references, validate_policy_comparison
from app.services.ai_skills.runtime import GroundedOutput
from test_ai_skill_control import control_env
from test_ai_skill_field_candidates import seeded

CORPUS = json.loads((Path(__file__).parent / "fixtures" / "ai_skill_a6_golden.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", CORPUS["field_recall"], ids=lambda case: case["id"])
def test_fixed_recall_queries(control_env, case):
    query, _ = seeded(control_env)
    client, factory, _, _, _ = control_env
    with factory() as db:
        target = db.get(TargetField, query["target_field_id"])
        target.field_code = case["field_code"]
        target.field_name = case["field_name"]
        db.commit()
    result = client.post("/ai-skills/field-candidates", json={**query, "query": case["query"]})
    assert result.status_code == 200, result.text
    assert result.json()["candidates"][0]["column_name"] == case["expected_first"]
    assert result.json()["writes_mapping"] is False


@pytest.mark.parametrize("case", CORPUS["grounded_answers"], ids=lambda case: case["id"])
def test_fixed_answer_replay(case):
    scope = {"scope_type": "project", "institution_id": 1, "project_id": 1}
    def evidence(identifier, kind, source_type, value):
        return {"id": identifier, "kind": kind, "value": value, "confidentiality": "internal",
                "source": {"source_type": source_type, "source_id": "1", "source_version": "1",
                           "locator": "synthetic:1", "scope": scope}}
    envelope = SkillInputEnvelope.model_validate({"skill_key": "lineage_edge_explanation",
        "task_key": "lineage_edge_explanation", "scope": scope, "subject_ref": "synthetic:edge:1",
        "facts": [evidence("script:1", "expression", "script_version", "previous_balance")],
        "policy_evidence": [evidence("policy:1", "policy_clause", "knowledge_clause", "期末余额")]
                           if case["has_policy"] else []})
    def validate():
        output = GroundedOutput.model_validate(case["output"])
        for claim in output.claims:
            validate_claim_references(claim, envelope)
        for comparison in output.policy_comparisons:
            validate_policy_comparison(comparison, envelope)
    if case["accepted"]:
        validate()
    else:
        with pytest.raises(ValueError):
            validate()
