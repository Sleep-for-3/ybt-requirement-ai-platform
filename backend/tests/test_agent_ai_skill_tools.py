"""Governance, degradation and input-validation tests for the AI-skill agent tools.

No live settings and no network: the mock LLM/embedding environment comes from
``tests/conftest.py``.
"""

from types import SimpleNamespace

import pytest

from app.models import (
    AgentPlan,
    AgentStep,
    AgentTask,
    Institution,
    Project,
    ProjectMembership,
    TargetField,
    TargetTable,
    User,
)
from app.services.agent.tools import ai_skill_tools, registry
from app.services.auth.dependencies import Principal

EXPECTED_TOOL_KEYS = {
    "recall_field_candidates",
    "rerank_field_candidates",
    "prepare_field_candidate",
    "generate_mapping_draft",
    "generate_requirement_candidate",
    "generate_requirement_document",
}
HUMAN_GATED_TOOL_KEYS = (
    "generate_mapping_draft",
    "generate_requirement_candidate",
    "generate_requirement_document",
)
TARGET_FIELD_TOOL_KEYS = (
    "recall_field_candidates",
    "rerank_field_candidates",
    "prepare_field_candidate",
    "generate_requirement_candidate",
)


@pytest.fixture()
def agent_env(db_session):
    """Synthetic user + institution + project + membership + agent task."""

    institution = Institution(
        institution_code="tool-bank",
        institution_name="工具测试机构",
        institution_type="bank",
        status="active",
    )
    user = User(username="tool_manager", display_name="工具管理员", status="active")
    db_session.add_all([institution, user])
    db_session.flush()
    project = Project(
        name="工具项目",
        institution_id=institution.id,
        project_status="active",
        confidentiality_level="internal",
    )
    db_session.add(project)
    db_session.flush()
    db_session.add(
        ProjectMembership(
            project_id=project.id,
            user_id=user.id,
            project_role="project_manager",
            status="active",
        )
    )
    target_table = TargetTable(project_id=project.id, table_code="RPT", table_name="监管表")
    db_session.add(target_table)
    db_session.flush()
    target_field = TargetField(
        project_id=project.id,
        target_table_id=target_table.id,
        field_code="balance",
        field_name="余额",
    )
    db_session.add(target_field)
    db_session.flush()
    task = AgentTask(
        institution_id=institution.id,
        project_id=project.id,
        objective="验证 AI Skill 工具",
        status="running",
        created_by=user.id,
    )
    db_session.add(task)
    db_session.flush()
    plan = AgentPlan(
        task_id=task.id,
        version_no=1,
        status="active",
        objective=task.objective,
        created_by=user.id,
    )
    db_session.add(plan)
    db_session.flush()
    step = AgentStep(
        task_id=task.id,
        plan_id=plan.id,
        step_key="recall_candidates",
        order_index=0,
        tool_key="recall_field_candidates",
        status="running",
    )
    db_session.add(step)
    db_session.commit()
    return SimpleNamespace(
        db=db_session,
        principal=Principal(user.id, user.username, user.display_name),
        project=project,
        task=task,
        step=step,
        target_field=target_field,
    )


def _context(env, tool_input):
    return registry.ToolContext(
        db=env.db,
        principal=env.principal,
        project=env.project,
        task=env.task,
        step=env.step,
        tool_input=tool_input,
    )


def test_tool_keys_are_exposed_and_every_tool_is_registered():
    assert set(ai_skill_tools.TOOL_KEYS) == EXPECTED_TOOL_KEYS
    for key in ai_skill_tools.TOOL_KEYS:
        spec = registry.get_tool(key)
        assert spec is not None, key
        assert spec.tool_key == key


def test_every_ai_skill_tool_declares_a_governable_spec():
    for key in ai_skill_tools.TOOL_KEYS:
        spec = registry.get_tool(key)
        assert registry.validate_spec(spec) == [], key


def test_declared_permissions_risk_and_target_field_flags_match_contract():
    expected = {
        # recall_fields() itself requires technical.edit, so the declared tool permission
        # must match the service it wraps instead of advertising a weaker one.
        "recall_field_candidates": ({"technical.edit"}, "medium", True, False),
        "rerank_field_candidates": ({"technical.edit"}, "medium", True, False),
        "prepare_field_candidate": ({"technical.edit"}, "medium", False, False),
        "generate_mapping_draft": ({"business.edit"}, "high", False, True),
        "generate_requirement_candidate": ({"deliverable.generate"}, "high", False, True),
        "generate_requirement_document": ({"deliverable.generate"}, "high", False, True),
    }
    for key, (permissions, risk, read_only, human_confirmation) in expected.items():
        spec = registry.get_tool(key)
        assert spec.required_permissions == frozenset(permissions), key
        assert spec.risk_level == risk, key
        assert spec.read_only is read_only, key
        assert spec.requires_human_confirmation is human_confirmation, key
    for key in TARGET_FIELD_TOOL_KEYS:
        assert registry.get_tool(key).requires_target_field is True, key
    assert registry.get_tool("generate_mapping_draft").requires_target_field is False
    assert registry.get_tool("generate_requirement_document").requires_target_field is False


def test_recall_and_rerank_degrade_without_catalog_rows_or_binding(agent_env):
    tool_input = {"target_field_id": agent_env.target_field.id}

    recall = registry.get_tool("recall_field_candidates").handler(_context(agent_env, tool_input))
    assert recall.status == "completed"
    assert recall.facts == []
    assert recall.evidence_refs == []
    assert recall.step_output["candidate_ids"] == []
    assert len(recall.step_output["context_hash"]) == 64
    assert {item["code"] for item in recall.gaps} == {"catalog_candidates_empty"}
    assert recall.output["candidate_count"] == 0
    assert recall.output["ranking_mode"] == "deterministic_recall"

    # No catalog rows and no published rerank skill binding: a labelled fallback,
    # never an exception and never a model_rerank relabel.
    rerank = registry.get_tool("rerank_field_candidates").handler(_context(agent_env, tool_input))
    assert rerank.status == "completed"
    assert rerank.degraded_path == "deterministic_recall"
    assert rerank.output["ranking_mode"] == "deterministic_recall"
    assert rerank.output["candidate_count"] == 0
    assert len(rerank.step_output["context_hash"]) == 64
    assert rerank.step_output["candidate_ids"] == []
    assert rerank.gaps and rerank.gaps[0]["code"] == "model_output_unavailable"


def test_requirement_document_blocks_without_binding_or_evidence(agent_env):
    result = registry.get_tool("generate_requirement_document").handler(
        _context(agent_env, {"target_field_id": agent_env.target_field.id})
    )
    assert result.status == "blocked"
    assert {item["code"] for item in result.gaps} == {"document_context_missing"}
    assert result.artifacts == []
    assert result.step_output["blocked_reason"] == "document_context_missing"


def test_requirement_candidate_degrades_to_a_labelled_deterministic_draft(agent_env):
    result = registry.get_tool("generate_requirement_candidate").handler(
        _context(agent_env, {"target_field_id": agent_env.target_field.id, "skill_key": "requirement_candidate_generation"})
    )
    assert result.status == "completed"
    assert result.degraded_path == "deterministic_draft"
    candidate = result.artifacts[0]["summary"]["candidate"]
    assert result.artifacts[0]["artifact_type"] == "requirement_candidate"
    assert result.artifacts[0]["evidence_refs"] == [item["id"] for item in result.facts]
    assert "不构成监管合规结论" in candidate["final_content"]
    assert {"skill_binding_missing"} <= set(candidate["gaps"])
    assert result.output["gap_codes"]


def test_illegal_inputs_are_rejected_by_validate_input():
    recall_schema = registry.get_tool("recall_field_candidates").input_schema
    assert registry.validate_input(recall_schema, {}) == ["missing required input: target_field_id"]
    assert registry.validate_input(recall_schema, {"target_field_id": "12"}) == [
        "input target_field_id must be an integer"
    ]
    assert registry.validate_input(recall_schema, {"target_field_id": 1, "top_k": "20"}) == [
        "input top_k must be an integer"
    ]
    assert registry.validate_input(recall_schema, {"target_field_id": 1, "unknown": 2}) == [
        "unknown input: unknown"
    ]

    prepare_schema = registry.get_tool("prepare_field_candidate").input_schema
    # candidate_id/scenario_id are discovered deterministically by the handler, so the
    # only hard requirement is the subject field; a wrong type is still rejected.
    assert registry.validate_input(prepare_schema, {"target_field_id": 1}) == []
    assert registry.validate_input(prepare_schema, {"target_field_id": 1, "candidate_id": 3}) == [
        "input candidate_id must be a string"
    ]

    mapping_schema = registry.get_tool("generate_mapping_draft").input_schema
    assert registry.validate_input(mapping_schema, {}) == []

    document_schema = registry.get_tool("generate_requirement_document").input_schema
    assert registry.validate_input(document_schema, {"requirement_id": "abc"}) == [
        "input requirement_id must be an integer"
    ]
    assert registry.validate_input(document_schema, {}) == []


def test_human_gated_tools_declare_high_risk_and_confirmation():
    for key in HUMAN_GATED_TOOL_KEYS:
        spec = registry.get_tool(key)
        assert spec.requires_human_confirmation is True, key
        assert spec.risk_level == "high", key
        assert spec.read_only is False, key
        assert spec.audit_fields, key
        assert spec.evidence_contract["artifact_types"], key
    for key in ("recall_field_candidates", "rerank_field_candidates"):
        spec = registry.get_tool(key)
        assert spec.requires_human_confirmation is False
        assert spec.risk_level == "medium"
        assert spec.read_only is True
