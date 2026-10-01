"""Structured observation state for Observe -> Replan.

The planner must never receive the whole history. This module projects the persisted
task rows into a bounded, structured state:

* objective / scenario / subject resolution,
* what already ran (step key, status, tool, evidence count, gap codes, one-line summary),
* an evidence summary by kind and the coverage figure,
* gaps and the still-unresolved questions,
* the tools the actor may actually use,
* the human decisions already applied,
* and the remaining budget (steps, replans, human gates).

``observation_digest`` renders that state as a compact text block for the planner
prompt, with hard character caps so a large document or SQL body can never be pasted
into the model context.
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select

from app.models import AgentArtifact, AgentHumanDecision, AgentStep, AgentTask
from app.services.agent import state_machine as sm
from app.services.agent.scenarios import scenario_requires_subject, scenario_spec
from app.services.agent.tools.registry import registered_tools, tools_visible_for_permissions

MAX_STEPS_IN_STATE = 24
MAX_GAPS_IN_STATE = 20
MAX_DECISIONS_IN_STATE = 12
MAX_DIGEST_CHARS = 4000
SUMMARY_CHARS = 160


def _clip(value: Any, limit: int = SUMMARY_CHARS) -> str:
    text = "" if value is None else str(value)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _step_summary(step: AgentStep) -> str:
    summary = (step.output_summary_json or {}).get("summary")
    if isinstance(summary, dict):
        for key in ("summary", "detail", "message", "title", "status"):
            if summary.get(key):
                return _clip(summary[key])
        return _clip(json.dumps(summary, ensure_ascii=False))
    return _clip(summary)


def observation_state(db, task: AgentTask, *, permitted: frozenset[str] | None = None,
                      project_id: int | None = None) -> dict[str, Any]:
    """Bounded, structured view of everything the planner may reason about."""

    steps = list(db.scalars(select(AgentStep).where(AgentStep.task_id == task.id)
                            .order_by(AgentStep.order_index, AgentStep.id)).all())
    latest: dict[str, AgentStep] = {}
    for step in steps:
        latest[step.step_key] = step
    summary = dict(task.result_summary_json or {})
    kinds: dict[str, int] = {}
    terminal = [step for step in steps if step.status in sm.STEP_TERMINAL]
    executed = [step for step in steps if step.status not in {sm.STEP_PENDING}]
    with_evidence = [step for step in executed if step.evidence_count]
    for step in steps:
        for fact in (step.output_summary_json or {}).get("facts") or []:
            kind = str((fact or {}).get("kind") or "unknown")
            kinds[kind] = kinds.get(kind, 0) + 1
        for policy in (step.output_summary_json or {}).get("policy_evidence") or []:
            kinds["policy_clause"] = kinds.get("policy_clause", 0) + 1

    gaps: list[dict[str, Any]] = []
    for step in steps:
        for code in step.gap_codes_json or []:
            gaps.append({"step_key": step.step_key, "code": str(code)})
            if len(gaps) >= MAX_GAPS_IN_STATE:
                break
        if len(gaps) >= MAX_GAPS_IN_STATE:
            break

    decisions = [
        {"step_key": record_step_key(db, record), "decision": record.decision,
         "comment": _clip(record.comment, 80)}
        for record in db.scalars(select(AgentHumanDecision).where(AgentHumanDecision.task_id == task.id)
                                 .order_by(AgentHumanDecision.id.desc()).limit(MAX_DECISIONS_IN_STATE)).all()
    ]
    artifacts = [
        {"artifact_type": artifact.artifact_type, "status": artifact.status}
        for artifact in db.scalars(select(AgentArtifact).where(AgentArtifact.task_id == task.id)
                                   .order_by(AgentArtifact.id)).all()
    ]

    if permitted is None:
        tool_keys = sorted(registered_tools())
    else:
        tool_keys = sorted(item["tool_key"] for item in tools_visible_for_permissions(permitted))
    scenario_key = task.scenario_key or ""
    spec = scenario_spec(scenario_key) if scenario_key else None
    pending = [step.step_key for step in steps if step.status == sm.STEP_PENDING]
    return {
        "objective": task.objective,
        "scenario": {
            "scenario_key": scenario_key,
            "label": spec.label if spec else None,
            "requires_subject": scenario_requires_subject(scenario_key) if scenario_key else None,
        },
        "subject": summary.get("subject") or {},
        "subject_resolution": summary.get("subject_resolution") or {},
        "completed_steps": [
            {"step_key": step.step_key, "tool_key": step.tool_key, "status": step.status,
             "required": step.required, "evidence_count": step.evidence_count,
             "gap_codes": list(step.gap_codes_json or [])[:6], "summary": _step_summary(step)}
            for step in steps[-MAX_STEPS_IN_STATE:]
        ],
        "evidence_summary": {
            "evidence_items": sum(step.evidence_count for step in steps),
            "kinds": kinds,
            "steps_with_evidence": len(with_evidence),
            "coverage": round(len(with_evidence) / len(executed), 4) if executed else None,
        },
        "gaps": gaps,
        "unresolved_questions": _unresolved_questions(task, gaps, summary),
        "available_tools": tool_keys,
        "human_decisions": decisions,
        "artifacts": artifacts,
        "remaining_budget": {
            "steps_total": len(steps),
            "steps_pending": len(pending),
            "pending_step_keys": pending[:MAX_STEPS_IN_STATE],
            "steps_terminal": len(terminal),
            "replans_used": int(task.replanning_count or 0),
            "retries_used": int(task.retry_count or 0),
        },
    }


def record_step_key(db, record: AgentHumanDecision) -> str | None:
    step = db.get(AgentStep, record.step_id) if record.step_id else None
    return step.step_key if step is not None else None


def _unresolved_questions(task: AgentTask, gaps: list[dict[str, Any]], summary: dict[str, Any]) -> list[str]:
    questions: list[str] = []
    resolution = summary.get("subject_resolution") or {}
    if resolution.get("status") in {"ambiguous", "not_found"}:
        questions.append("目标字段尚未确定：" + _clip(resolution.get("rationale"), 120))
    codes = {gap["code"] for gap in gaps}
    mapping = {
        "missing_basis": "缺少可引用的监管条款依据。",
        "sql_baseline_missing": "脚本没有可比对的上一版本。",
        "skill_binding_missing": "所需技能未发布/未绑定，只得到确定性降级结果。",
        "metadata_not_found": "元数据目录中未找到对应实体。",
        "dependency_gap": "上游步骤被跳过，下游无法继续。",
    }
    for code, question in mapping.items():
        if code in codes:
            questions.append(question)
    if (task.result_summary_json or {}).get("incomplete") is True:
        questions.append("本次运行不完整，需人工确认是否继续。")
    return questions[:8]


def observation_digest(state: dict[str, Any]) -> str:
    """Compact planner-facing rendering of the state (hard character cap)."""

    lines = [
        f"业务目标：{_clip(state.get('objective'), 200)}",
        f"场景：{(state.get('scenario') or {}).get('scenario_key')}",
        f"主体：{json.dumps(state.get('subject') or {}, ensure_ascii=False)}",
    ]
    evidence = state.get("evidence_summary") or {}
    lines.append(f"证据：{evidence.get('evidence_items', 0)} 条，覆盖 {evidence.get('coverage')}，"
                 f"类型 {json.dumps(evidence.get('kinds') or {}, ensure_ascii=False)}")
    for step in state.get("completed_steps") or []:
        lines.append(f"- [{step['status']}] {step['step_key']}（{step['tool_key']}，证据 {step['evidence_count']}）"
                     f" {step.get('summary') or ''}")
    gaps = state.get("gaps") or []
    if gaps:
        lines.append("缺口：" + "、".join(f"{gap['step_key']}:{gap['code']}" for gap in gaps[:10]))
    questions = state.get("unresolved_questions") or []
    if questions:
        lines.append("未决问题：" + "；".join(questions[:5]))
    decisions = state.get("human_decisions") or []
    if decisions:
        lines.append("人工决策：" + "；".join(f"{item['step_key']}={item['decision']}" for item in decisions[:6]))
    budget = state.get("remaining_budget") or {}
    lines.append(f"预算：剩余未执行 {budget.get('steps_pending')} 步，已重规划 {budget.get('replans_used')} 次，"
                 f"可执行工具 {len(state.get('available_tools') or [])} 个")
    digest = "\n".join(lines)
    return digest if len(digest) <= MAX_DIGEST_CHARS else digest[: MAX_DIGEST_CHARS - 1] + "…"
