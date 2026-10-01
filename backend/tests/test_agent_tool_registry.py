"""Governance tests for the controlled tool registry and the constrained planner."""
from __future__ import annotations

import pytest

from app.services.agent import planner
from app.services.agent.tools import registry


def test_every_registered_tool_is_governable() -> None:
    tools = registry.registered_tools()
    assert len(tools) >= 15
    for key, spec in tools.items():
        assert registry.validate_spec(spec) == [], key
        assert spec.required_permissions, key
        assert spec.evidence_contract.get("fact_kinds") is not None, key
    expected = {
        "search_regulatory_knowledge", "search_metadata", "recall_field_candidates",
        "rerank_field_candidates", "prepare_field_candidate", "get_lineage",
        "analyze_lineage_impact", "inspect_sql_rule", "compare_policy_and_implementation",
        "generate_mapping_draft", "generate_requirement_candidate", "generate_requirement_document",
        "create_gap_report", "request_human_confirmation", "summarize_evidence",
    }
    assert expected <= set(tools)


def _base_spec(**overrides):
    values = dict(
        display_name="坏工具", description="这是一个无法治理的工具示例",
        input_schema={"type": "object", "properties": {}},
        output_schema={"type": "object", "properties": {}},
        required_permissions=frozenset({"project.view"}), risk_level="low",
        timeout_seconds=10, retry_policy={"max_attempts": 1}, read_only=True,
        requires_human_confirmation=False,
        evidence_contract={"fact_kinds": [], "artifact_types": []},
        audit_fields=(), handler=lambda ctx: None,
    )
    values.update(overrides)
    return values


def test_spec_validation_rejects_ungovernable_tools() -> None:
    with pytest.raises(registry.ToolRegistryError):
        registry.register_tool(registry.AgentToolSpec(tool_key="Bad-Key", **_base_spec()))
    with pytest.raises(registry.ToolRegistryError) as no_permission:
        registry.register_tool(registry.AgentToolSpec(tool_key="no_permission_tool", **_base_spec(required_permissions=frozenset())))
    assert no_permission.value.code == "invalid_tool_spec"
    with pytest.raises(registry.ToolRegistryError):
        registry.register_tool(registry.AgentToolSpec(
            tool_key="human_low_risk", **_base_spec(requires_human_confirmation=True)))
    with pytest.raises(registry.ToolRegistryError):
        registry.register_tool(registry.AgentToolSpec(
            tool_key="write_without_audit", **_base_spec(read_only=False)))
    with pytest.raises(registry.ToolRegistryError):
        registry.register_tool(registry.AgentToolSpec(tool_key="no_contract", **_base_spec(evidence_contract={})))
    with pytest.raises(registry.ToolRegistryError):
        registry.register_tool(registry.AgentToolSpec(tool_key="no_handler", **_base_spec(handler=None)))


def test_duplicate_registration_is_rejected() -> None:
    with pytest.raises(registry.ToolRegistryError) as duplicate:
        registry.register_tool(registry.AgentToolSpec(tool_key="get_lineage", **_base_spec()))
    assert duplicate.value.code == "duplicate_tool_key"


def test_unknown_tool_lookup_fails_closed() -> None:
    assert registry.get_tool("not_a_tool") is None
    with pytest.raises(registry.ToolRegistryError) as unknown:
        registry.require_tool("not_a_tool")
    assert unknown.value.code == "unknown_tool"


def test_input_validation_matches_the_declared_schema() -> None:
    lineage = registry.require_tool("get_lineage")
    assert registry.validate_input(lineage.input_schema, {}) == []
    assert registry.validate_input(lineage.input_schema, {"depth": "three"})
    assert registry.validate_input(lineage.input_schema, {"direction": "sideways"})
    assert registry.validate_input(lineage.input_schema, {"unknown": 1})

    inspect = registry.require_tool("inspect_sql_rule")
    assert registry.validate_input(inspect.input_schema, {"script_file_id": 3}) == []

    search = registry.require_tool("search_regulatory_knowledge")
    assert registry.validate_input(search.input_schema, {"retrieval_mode": "magic"})


def test_registry_listing_is_permission_filtered() -> None:
    everything = sorted({permission for spec in registry.registered_tools().values()
                         for permission in spec.required_permissions})
    manager = registry.tools_visible_for_permissions(everything)
    viewer = registry.tools_visible_for_permissions({"project.view"})
    assert len(viewer) < len(manager)
    viewer_keys = {item["tool_key"] for item in viewer}
    assert {"create_gap_report", "summarize_evidence"} <= viewer_keys
    assert "recall_field_candidates" not in viewer_keys


def test_regulatory_plan_is_registry_valid_and_human_gated() -> None:
    draft = planner.deterministic_plan(
        "分析二级市场福费廷报送需求", scenario_key="regulatory_field_analysis",
        subject={"target_field_id": 7, "target_field_code": "FT_BAL", "target_field_name": "福费廷余额"},
    )
    assert planner.validate_plan_draft(draft) == []
    keys = [step.step_key for step in draft.steps]
    assert keys[0] == "search_policy"
    # the human gate must sit between the candidate and the document it feeds
    assert keys.index("confirm_requirement_candidate") < keys.index("generate_requirement_document")
    for step in draft.steps:
        assert registry.get_tool(step.tool_key) is not None, step.tool_key
    subject_steps = [step for step in draft.steps if step.tool_key in
                     {"recall_field_candidates", "rerank_field_candidates", "get_lineage"}]
    for step in subject_steps:
        assert step.input.get("target_field_id") == 7


def test_planner_rejects_unregistered_tools_and_bad_dependencies() -> None:
    with pytest.raises(Exception):
        planner.PlanDraft(objective="x", steps=[
            planner.PlannedStep(step_key="a", tool_key="get_lineage", reason="r"),
            planner.PlannedStep(step_key="a", tool_key="get_lineage", reason="r"),
        ])
    with pytest.raises(Exception):
        planner.PlanDraft(objective="x", steps=[
            planner.PlannedStep(step_key="a", tool_key="get_lineage", reason="r", depends_on=["b"]),
            planner.PlannedStep(step_key="b", tool_key="get_lineage", reason="r"),
        ])
    bad = planner.PlanDraft(objective="x", steps=[
        planner.PlannedStep(step_key="a", tool_key="bash_exec", reason="r"),
    ])
    errors = planner.validate_plan_draft(bad)
    assert errors and "unregistered tool_key" in errors[0]


def test_scenario_detection_defaults_to_the_regulatory_chain() -> None:
    assert planner.detect_scenario("分析二级市场福费廷报送需求") == planner.SCENARIO_REGULATORY_FIELD_ANALYSIS
    assert planner.detect_scenario("随便说点什么") == planner.DEFAULT_SCENARIO
