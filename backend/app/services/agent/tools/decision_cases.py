"""Agent tool: retrieve historical human decisions as supporting experience.

Hard rule: a historical decision is **supporting context only**. It is labelled
``historical_decision`` everywhere it appears and can never be a regulatory basis,
so this tool never emits policy evidence and never claims compliance.
"""
from __future__ import annotations

from typing import Any

from app.services.agent.case_memory import SOURCE_TYPE, search_decision_cases
from app.services.agent.tools.evidence import confidentiality_of, evidence, gap, project_scope
from app.services.agent.tools.registry import (
    AgentToolSpec,
    ToolContext,
    ToolResult,
    register_tool,
)

TOOL_KEY = "search_decision_cases"
MAX_CASES = 10


def _subject_of(ctx: ToolContext) -> dict[str, Any]:
    return (ctx.step.input_json or {}).get("subject") or {}


def _search_decision_cases(ctx: ToolContext) -> ToolResult:
    scope = project_scope(ctx.task)
    confidentiality = confidentiality_of(ctx.project)
    subject = _subject_of(ctx)
    field_id = subject.get("target_field_id")
    top_k = ctx.tool_input.get("top_k")
    top_k = int(top_k) if isinstance(top_k, int) and not isinstance(top_k, bool) else 5
    cases = search_decision_cases(
        ctx.db, project=ctx.project,
        query=ctx.tool_input.get("query"),
        subject_type="target_field" if field_id else None,
        subject_id=field_id,
        scenario_key=ctx.task.scenario_key,
        decision_type=ctx.tool_input.get("decision_type"),
        top_k=min(max(top_k, 1), MAX_CASES),
    )
    if not cases:
        return ToolResult(
            status="skipped",
            gaps=[gap("no_historical_case",
                      "没有找到与该主体/场景匹配的历史人工决策案例；不得以历史经验替代监管依据。").model_dump(mode="json")],
            output={"case_count": 0, "cases": []},
        )
    fact = evidence(
        evidence_id=f"decision_cases:{ctx.task.id}:{field_id or 'none'}",
        kind=SOURCE_TYPE,
        value={"case_count": len(cases),
               "cases": [{"decision_type": case.get("decision_type"), "decision": case.get("decision"),
                          "similarity": case.get("similarity"), "source_type": case.get("source_type")}
                         for case in cases[:MAX_CASES]]},
        source_type="decision_case",
        source_id=int(cases[0].get("id") or 0),
        source_version=str(cases[0].get("effective_from") or f"case:{cases[0].get('id')}"),
        locator=f"project:{ctx.project_id}",
        scope=scope,
        confidentiality=confidentiality,
    )
    return ToolResult(
        facts=[fact.model_dump(mode="json")],
        evidence_refs=[fact.id],
        output={"case_count": len(cases), "cases": cases[:MAX_CASES],
                "source_type": SOURCE_TYPE,
                "advisory_note": "历史人工决策仅作为经验参考，不能作为监管依据。"},
        step_output={"case_count": len(cases)},
        execution_metadata={"source_type": SOURCE_TYPE},
    )


def register_decision_case_tools() -> None:
    register_tool(AgentToolSpec(
        tool_key=TOOL_KEY,
        display_name="检索历史决策案例",
        description=("检索本项目已人工确认的历史决策（映射/口径/需求/SQL 影响/来源选择），"
                     "仅作为经验参考，绝不作为监管依据。"),
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "decision_type": {"type": "string"},
                "top_k": {"type": "integer"},
            },
            "required": [],
            "additionalProperties": False,
        },
        output_schema={"type": "object", "properties": {"case_count": {"type": "integer"}}},
        required_permissions=frozenset({"project.view"}),
        risk_level="low",
        timeout_seconds=30,
        retry_policy={"max_attempts": 1},
        read_only=True,
        requires_human_confirmation=False,
        evidence_contract={"fact_kinds": [SOURCE_TYPE], "policy_kinds": [], "artifact_types": []},
        audit_fields=("decision_type", "top_k"),
        handler=_search_decision_cases,
    ))


register_decision_case_tools()
