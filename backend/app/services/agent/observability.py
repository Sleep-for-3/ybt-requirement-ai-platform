"""Agent-level observability metrics derived from the durable records.

Every metric is computed from persisted rows (``agent_tasks``,
``agent_tool_calls``, ``agent_human_decisions``, ``agent_artifacts``); nothing is
estimated. A metric whose denominator is empty is reported as ``None`` with the
denominator, never as a flattering ``1.0``/``0.0``.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.models import AgentArtifact, AgentHumanDecision, AgentStep, AgentTask, AgentToolCall

# Tools whose output passes through a model guard; the denominator of the
# hallucination-guard metric.
MODEL_TOOLS = frozenset({
    "rerank_field_candidates",
    "generate_mapping_draft",
    "generate_requirement_candidate",
    "generate_requirement_document",
    "compare_policy_and_implementation",
})
GUARD_FAILURE_REASONS = frozenset({
    "model_output_unavailable", "invalid_claim_references", "tool_result_invalid",
    "tool_input_invalid", "tool_timeout",
})
REJECT_DECISIONS = frozenset({"reject"})


def _ratio(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 4)


def agent_metrics(db, *, project_id: int | None = None, limit: int = 500) -> dict[str, Any]:
    task_query = select(AgentTask).order_by(AgentTask.id.desc()).limit(limit)
    if project_id is not None:
        task_query = task_query.where(AgentTask.project_id == project_id)
    tasks = list(db.scalars(task_query).all())
    task_ids = [task.id for task in tasks]
    if not task_ids:
        return {
            "task_count": 0, "terminal_task_count": 0,
            "metrics": {key: None for key in (
                "task_success_rate", "avg_steps", "avg_retries", "avg_replans", "tool_success_rate",
                "human_reject_rate", "evidence_coverage", "unsupported_claim_rate",
                "hallucination_guard_failure_rate", "final_artifact_acceptance_rate",
            )},
            "denominators": {}, "status_counts": {},
        }

    steps = list(db.scalars(select(AgentStep).where(AgentStep.task_id.in_(task_ids))).all())
    calls = list(db.scalars(select(AgentToolCall).where(AgentToolCall.task_id.in_(task_ids))).all())
    decisions = list(db.scalars(select(AgentHumanDecision).where(AgentHumanDecision.task_id.in_(task_ids))).all())
    artifacts = list(db.scalars(select(AgentArtifact).where(AgentArtifact.task_id.in_(task_ids))).all())

    completed_tasks = [task for task in tasks if task.status == "completed"]
    terminal_tasks = [task for task in tasks if task.status in {"completed", "failed", "cancelled"}]
    failed_or_completed = [task for task in tasks if task.status in {"completed", "failed"}]

    executed_steps = [step for step in steps if int(step.attempt_count or 0) > 0]
    steps_with_evidence = [step for step in executed_steps if int(step.evidence_count or 0) > 0]

    completed_calls = [call for call in calls if call.status == "completed"]
    model_calls = [call for call in calls if call.tool_key in MODEL_TOOLS]
    guard_failures = [call for call in model_calls if (call.failure_reason or "") in GUARD_FAILURE_REASONS
                      or call.degraded_path == "model_output_unavailable"]

    accepted_claims = 0
    rejected_claims = 0
    for step in steps:
        summary = step.output_summary_json or {}
        accepted_claims += len(summary.get("claims") or [])
        metadata = summary.get("model_metadata") or {}
        rejected = metadata.get("rejected_claims")
        if isinstance(rejected, list):
            rejected_claims += len(rejected)

    confirmed_artifacts = [item for item in artifacts if item.status == "confirmed"]
    rejected_artifacts = [item for item in artifacts if item.status == "rejected"]

    status_counts: dict[str, int] = {}
    for task in tasks:
        status_counts[task.status] = status_counts.get(task.status, 0) + 1

    metrics = {
        "task_success_rate": _ratio(len(completed_tasks), len(failed_or_completed)),
        "avg_steps": round(sum(len([s for s in steps if s.task_id == task.id]) for task in tasks) / len(tasks), 4),
        "avg_retries": round(sum(int(task.retry_count or 0) for task in tasks) / len(tasks), 4),
        "avg_replans": round(sum(int(task.replanning_count or 0) for task in tasks) / len(tasks), 4),
        "tool_success_rate": _ratio(len(completed_calls), len(calls)),
        "human_reject_rate": _ratio(len([item for item in decisions if item.decision in REJECT_DECISIONS]), len(decisions)),
        "evidence_coverage": _ratio(len(steps_with_evidence), len(executed_steps)),
        "unsupported_claim_rate": _ratio(rejected_claims, accepted_claims + rejected_claims),
        "hallucination_guard_failure_rate": _ratio(len(guard_failures), len(model_calls)),
        "final_artifact_acceptance_rate": _ratio(len(confirmed_artifacts), len(confirmed_artifacts) + len(rejected_artifacts)),
    }
    return {
        "task_count": len(tasks),
        "terminal_task_count": len(terminal_tasks),
        "status_counts": status_counts,
        "metrics": metrics,
        "denominators": {
            "task_success_rate": len(failed_or_completed),
            "tool_success_rate": len(calls),
            "human_reject_rate": len(decisions),
            "evidence_coverage": len(executed_steps),
            "unsupported_claim_rate": accepted_claims + rejected_claims,
            "hallucination_guard_failure_rate": len(model_calls),
            "final_artifact_acceptance_rate": len(confirmed_artifacts) + len(rejected_artifacts),
        },
    }
