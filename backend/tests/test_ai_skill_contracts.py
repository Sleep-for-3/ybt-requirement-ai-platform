"""Golden input and negative boundary cases; no database or model requests."""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.schemas.ai_skill import (
    SkillClaim, SkillInputEnvelope, SkillRunIdentity, SkillScope, validate_claim_references,
)


@pytest.fixture
def envelope_data():
    scope = {"scope_type": "project", "institution_id": 2, "project_id": 17}
    return {
        "skill_key": "lineage_edge_explanation",
        "task_key": "lineage_edge_explanation",
        "scope": dict(scope),
        "subject_ref": "script:301:edge:88",
        "facts": [{
            "id": "script:301:stmt9:expression",
            "kind": "expression", "value": "COALESCE(loan_amt, 0)",
            "source": {"source_type": "script_version", "source_id": "301",
                       "source_version": "301", "locator": "stmt9:expression", "scope": dict(scope)},
            "confidentiality": "internal",
        }],
        "policy_evidence": [{
            "id": "knowledge:77:clause18.2", "kind": "policy_clause", "value": "余额不得为空",
            "source": {"source_type": "knowledge_clause", "source_id": "18.2",
                       "source_version": "77", "locator": "clause18.2", "scope": dict(scope)},
            "confidentiality": "internal",
        }],
    }


def test_golden_envelope_and_supported_claim(envelope_data):
    envelope = SkillInputEnvelope.model_validate(envelope_data)
    restored = SkillInputEnvelope.model_validate_json(envelope.model_dump_json())
    assert restored == envelope
    assert restored.context_hash() == envelope.context_hash()
    claim = SkillClaim(claim_type="policy_requirement", text="非空要求需确认零值处理",
                       fact_ids=[envelope.facts[0].id], policy_clause_ids=[envelope.policy_evidence[0].id])
    validate_claim_references(claim, envelope)


@pytest.mark.parametrize("scope", [
    {"scope_type": "platform", "project_id": 17},
    {"scope_type": "institution", "institution_id": 2, "project_id": 17},
    {"scope_type": "project", "project_id": 17},
    {"scope_type": "task", "institution_id": 2, "project_id": 17},
    {"scope_type": "project", "institution_id": True, "project_id": 17},
])
def test_invalid_scope_is_rejected(scope):
    with pytest.raises(ValidationError):
        SkillScope.model_validate(scope)


@pytest.mark.parametrize("field,value", [("institution_id", 3), ("project_id", 18)])
def test_cross_tenant_evidence_is_rejected(envelope_data, field, value):
    envelope_data["facts"][0]["source"]["scope"] = dict(envelope_data["scope"], **{field: value})
    with pytest.raises(ValidationError, match="cross-"):
        SkillInputEnvelope.model_validate(envelope_data)


def test_duplicate_ids_cannot_hide_policy_as_fact(envelope_data):
    envelope_data["policy_evidence"][0]["id"] = envelope_data["facts"][0]["id"]
    with pytest.raises(ValidationError, match="duplicate"):
        SkillInputEnvelope.model_validate(envelope_data)


@pytest.mark.parametrize("mutation", ["missing_version", "unknown_classification", "unsafe_option", "fake_policy"])
def test_missing_provenance_and_uncontrolled_options_are_rejected(envelope_data, mutation):
    if mutation == "missing_version":
        del envelope_data["facts"][0]["source"]["source_version"]
    elif mutation == "unknown_classification":
        envelope_data["facts"][0]["confidentiality"] = "unclassified"
    elif mutation == "unsafe_option":
        envelope_data["disable_citation_validation"] = True
    else:
        envelope_data["policy_evidence"][0]["source"]["source_type"] = "script_version"
    with pytest.raises(ValidationError):
        SkillInputEnvelope.model_validate(envelope_data)


@pytest.mark.parametrize("change", ["scope", "version", "value", "budget"])
def test_context_hash_changes_with_material_inputs(envelope_data, change):
    original = SkillInputEnvelope.model_validate(envelope_data).context_hash()
    changed = deepcopy(envelope_data)
    if change == "scope":
        changed["scope"]["project_id"] = 18
        for evidence in [*changed["facts"], *changed["policy_evidence"]]:
            evidence["source"]["scope"]["project_id"] = 18
    elif change == "version":
        changed["facts"][0]["source"]["source_version"] = "302"
    elif change == "value":
        changed["facts"][0]["value"] = "loan_amt"
    else:
        changed["max_input_bytes"] = 1000
    assert SkillInputEnvelope.model_validate(changed).context_hash() != original


def test_script_reference_cannot_support_policy_requirement(envelope_data):
    envelope = SkillInputEnvelope.model_validate(envelope_data)
    claim = SkillClaim(claim_type="policy_requirement", text="不得为空",
                       policy_clause_ids=[envelope.facts[0].id])
    with pytest.raises(ValueError, match="unknown policy"):
        validate_claim_references(claim, envelope)


@pytest.mark.parametrize("payload", [
    {"claim_type": "inference", "text": "无来源推断"},
    {"claim_type": "policy_requirement", "text": "假制度", "fact_ids": ["f1"]},
    {"claim_type": "policy_requirement", "text": "自动确认", "policy_clause_ids": ["p1"], "requires_human_confirmation": False},
])
def test_unsupported_claims_are_rejected(payload):
    with pytest.raises(ValidationError):
        SkillClaim.model_validate(payload)


def test_legacy_run_cannot_claim_a_published_skill():
    data = {"runtime_mode": "legacy", "execution_kind": "mock_model", "context_hash": "a" * 64}
    assert SkillRunIdentity.model_validate(data).skill_version_id is None
    with pytest.raises(ValidationError):
        SkillRunIdentity.model_validate(dict(data, skill_version_id=7))
    with pytest.raises(ValidationError):
        SkillRunIdentity.model_validate(dict(data, runtime_mode="skill"))
    assert SkillRunIdentity.model_validate(dict(data, runtime_mode="skill", skill_key="lineage_edge_explanation",
                                               skill_version_id=7, skill_version_no=2, input_contract_version="1.0"))


@pytest.mark.parametrize("origin", [
    {"scope_type": "platform"},
    {"scope_type": "institution", "institution_id": 2},
])
def test_structurally_compatible_shared_evidence(envelope_data, origin):
    # Real Provider authorization and clause effectiveness remain required.
    envelope_data["policy_evidence"][0]["source"]["scope"] = origin
    assert SkillInputEnvelope.model_validate(envelope_data)


def test_task_evidence_cannot_leak_to_another_callsite(envelope_data):
    task_scope = dict(envelope_data["scope"], scope_type="task", invocation_key="lineage_graph")
    envelope_data["scope"] = task_scope
    envelope_data["facts"][0]["source"]["scope"] = dict(task_scope)
    assert SkillInputEnvelope.model_validate(envelope_data)
    envelope_data["facts"][0]["source"]["scope"]["invocation_key"] = "mapping_editor"
    with pytest.raises(ValidationError, match="cross-task"):
        SkillInputEnvelope.model_validate(envelope_data)


def test_missing_basis_is_a_gap_not_an_unsupported_claim(envelope_data):
    envelope_data["policy_evidence"] = []
    envelope_data["gaps"] = [{"code": "missing_basis", "message": "没有有效制度条款"}]
    envelope = SkillInputEnvelope.model_validate(envelope_data)
    assert envelope.gaps[0].code == "missing_basis"
    with pytest.raises(ValueError, match="unknown fact"):
        validate_claim_references(SkillClaim(claim_type="observed_fact", text="不存在的事实", fact_ids=["unknown"]), envelope)


def test_skill_key_fits_legacy_snapshot_column(envelope_data):
    envelope_data["skill_key"] = "s" * 91
    assert len("ai_skill:" + SkillInputEnvelope.model_validate(envelope_data).skill_key) == 100
    envelope_data["skill_key"] += "s"
    with pytest.raises(ValidationError):
        SkillInputEnvelope.model_validate(envelope_data)
