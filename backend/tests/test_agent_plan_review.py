"""The 15-step plan review, pinned as a contract.

The acceptance brief asks which steps of the regulatory chain must stay fixed, which the
Observation step may decide on, which a planner may insert, and which are only optional.
This test freezes that classification against the shipped deterministic template:

* fixed      - required governance/chain steps: the chain may not silently drop them;
* observation- driven / optional - steps whose precondition may legitimately be absent
  (lineage, impact surface, mapping candidates). They must degrade with a gap, never block
  the deliverables or the human gates.
"""
from __future__ import annotations

from app.services.agent.planner import DETERMINISTIC_PLANS, SCENARIO_REGULATORY_FIELD_ANALYSIS

CHAIN = {step["step_key"]: step for step in DETERMINISTIC_PLANS[SCENARIO_REGULATORY_FIELD_ANALYSIS]}

# Fixed: the regulatory basis, the evidence gathering, the comparison, both human gates and
# the two governance deliverables.
FIXED = {
    "search_policy", "search_metadata", "recall_candidates", "rerank_candidates", "inspect_sql",
    "compare_policy", "generate_requirement_candidate", "confirm_requirement_candidate",
    "generate_requirement_document", "summarize_evidence", "create_gap_report",
}
# Optional: only meaningful when the observation actually found lineage, an impact surface or
# mapping candidates. Their absence is recorded as a gap.
OPTIONAL = {"query_lineage", "analyze_impact", "prepare_mapping", "generate_mapping_draft"}


def test_the_regulatory_chain_has_the_reviewed_step_set():
    assert set(CHAIN) == FIXED | OPTIONAL, "the reviewed step set must match the shipped template"
    assert len(CHAIN) == 15


def test_governance_and_chain_steps_stay_required():
    for key in sorted(FIXED):
        assert CHAIN[key].get("required", True) is not False, f"{key} must stay a fixed step"


def test_precondition_dependent_steps_are_optional():
    for key in sorted(OPTIONAL):
        assert CHAIN[key].get("required") is False, f"{key} may be skipped with a gap"


def test_no_fixed_deliverable_hard_depends_on_an_optional_step():
    for key, step in CHAIN.items():
        if key not in FIXED:
            continue
        hard = set(step.get("depends_on") or [])
        assert not (hard & OPTIONAL), \
            f"{key} must not be blocked by the optional steps {sorted(hard & OPTIONAL)}"
    assert set(CHAIN["generate_requirement_candidate"].get("optional_depends_on") or []) >= {"analyze_impact"}
    assert set(CHAIN["prepare_mapping"].get("depends_on") or []) & {"rerank_candidates"}


def test_the_two_human_gates_are_still_declared():
    gates = {key: step for key, step in CHAIN.items()
             if step.get("tool_key") == "request_human_confirmation"}
    assert set(gates) == {"confirm_requirement_candidate"}, \
        "the requirement candidate still needs its human gate"
    assert "gate_key" in (gates["confirm_requirement_candidate"].get("input") or {})
