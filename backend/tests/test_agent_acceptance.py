"""End-to-end acceptance for the governed agent chain.

Scenario: "分析二级市场福费廷报送需求" on isolated synthetic data. The test
drives the real tools (no stubs), pauses at every human gate, and asserts the
governance invariants an acceptance reviewer cares about:

* every conclusion is evidence-linked and the policy basis is a governed clause,
* the agent never rules on regulatory compliance by itself,
* the deliverable is only produced after a human approval,
* a project without a governed clause cannot produce a "compliant" document.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base

import app.models as _models  # noqa: F401  - populates Base.metadata
from app.models import AgentArtifact, AgentStep, AgentTask, AgentToolCall, AuditLog, Project, ReviewTask
from app.services.agent import runtime, state_machine as sm
from app.services.auth.dependencies import Principal

from agent_acceptance_fixture import OBJECTIVE, seed_agent_acceptance

MAX_GATES = 8


@pytest.fixture()
def db_session():
    """Override conftest's fixture: tool handlers run off the event-loop thread, so the
    in-memory SQLite database must be shared through one connection (StaticPool)."""

    from sqlalchemy import create_engine

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


def _steps(db, task) -> list[AgentStep]:
    return list(db.scalars(select(AgentStep).where(AgentStep.task_id == task.id)
                           .order_by(AgentStep.order_index, AgentStep.id)).all())


def _waiting_step(db, task) -> AgentStep | None:
    return db.scalar(select(AgentStep).where(
        AgentStep.task_id == task.id, AgentStep.status == sm.STEP_WAITING_HUMAN,
    ).order_by(AgentStep.order_index))


def _approve_open_gate(db, principal, task, job, comment: str) -> AgentStep:
    step = _waiting_step(db, task)
    assert step is not None, "expected an open human gate"
    review_task = db.get(ReviewTask, step.review_task_id)
    assert review_task is not None and review_task.status == "pending"
    runtime.decide(db, principal, task, step, "approve", comment=comment)
    runtime.run_agent_task(db, job)  # the queue continues the same way asynchronously
    db.refresh(task)
    return step


def _artifacts(db, task) -> dict[str, AgentArtifact]:
    rows = db.scalars(select(AgentArtifact).where(AgentArtifact.task_id == task.id)).all()
    return {row.artifact_type: row for row in rows}


def test_regulatory_field_analysis_reaches_gates_with_governed_evidence(db_session) -> None:
    ids = seed_agent_acceptance(db_session)
    project = db_session.get(Project, ids["project_id"])
    principal = Principal(ids["user_id"], ids["username"], "Agent 验收用户")

    task = runtime.create_task(db_session, principal, project, OBJECTIVE)
    job = runtime.submit_task(db_session, project, principal, task)
    runtime.run_agent_task(db_session, job)
    db_session.refresh(task)

    # --- the plan is the governed regulatory chain, not a free-form model plan ---
    snapshot = runtime.task_snapshot(db_session, task)
    assert snapshot["plan"]["planner_source"] == "deterministic"
    plan_keys = [step["step_key"] for step in snapshot["plan"]["steps"]]
    assert plan_keys[0] == "search_policy"
    assert plan_keys.index("confirm_requirement_candidate") < plan_keys.index("generate_requirement_document")

    # --- the policy basis is a governed clause from a normative source ---
    policy_step = next(step for step in _steps(db_session, task) if step.step_key == "search_policy")
    policy = (policy_step.output_summary_json or {}).get("policy_evidence") or []
    assert policy and policy[0]["kind"] == "policy_clause"
    assert policy[0]["source"]["source_type"] == "knowledge_clause"
    assert policy[0]["id"] == f"knowledge:{ids['document_version_id']}:unit:{ids['unit_id']}"

    # --- the agent parked at a real human gate instead of concluding compliance ---
    detail = [(step.step_key, step.status, step.error_code) for step in _steps(db_session, task)]
    assert task.status == sm.TASK_WAITING_HUMAN, detail
    compare_step = next(step for step in _steps(db_session, task) if step.step_key == "compare_policy")
    assert compare_step.status == sm.STEP_WAITING_HUMAN
    comparisons = (compare_step.output_summary_json or {}).get("policy_comparisons") or []
    assert comparisons, "the comparison must be evidence-linked"
    assert comparisons[0]["status"] == "pending"  # never matched/conflict by the agent itself
    assert "Agent 不自行判定合规一致性" in comparisons[0]["difference"]
    assert "requirement_document" not in _artifacts(db_session, task)

    # --- every declaration of human confirmation becomes a real gate, in plan order ---
    approved_keys = []
    while task.status == sm.TASK_WAITING_HUMAN and len(approved_keys) < MAX_GATES:
        approved_keys.append(
            _approve_open_gate(db_session, principal, task, job,
                               f"验收确认 #{len(approved_keys) + 1}").step_key)
    assert approved_keys[0] == "compare_policy"
    assert "generate_requirement_candidate" in approved_keys
    assert "confirm_requirement_candidate" in approved_keys
    # The document is only finished after its own gate was approved.
    document_step = next(step for step in _steps(db_session, task)
                         if step.step_key == "generate_requirement_document")
    assert document_step.status == sm.STEP_COMPLETED
    assert "requirement_document" in _artifacts(db_session, task)
    assert task.status in {sm.TASK_COMPLETED, sm.TASK_BLOCKED}
    if task.status == sm.TASK_BLOCKED:
        # an optional/degraded step must not be reported as a finished deliverable
        assert (task.result_summary_json or {}).get("incomplete") is True
        degraded = [step for step in _steps(db_session, task) if step.status == sm.STEP_SKIPPED
                    and step.error_code == "optional_step_failed"]
        assert degraded, "a blocked run must show which step was degraded"

    # --- the final deliverables exist, are draft artefacts and stay evidence-linked ---
    artifacts = _artifacts(db_session, task)
    assert {"requirement_candidate", "requirement_document", "evidence_summary", "gap_report"} <= set(artifacts)
    for row in artifacts.values():
        assert row.status in {"draft", "confirmed"}
    candidate = artifacts["requirement_candidate"]
    assert (candidate.summary_json or {}).get("evidence_ids"), "the candidate must carry its evidence ids"
    gap_summary = artifacts["gap_report"].summary_json or {}
    assert {"gap_count", "conflict_count", "unsupported_basis_count"} <= set(gap_summary)
    assert task.evidence_count > 0
    assert task.artifact_count == len(artifacts)

    # --- human decisions are in the canonical review ledger and in the audit log ---
    decisions = db_session.scalars(select(AgentToolCall).where(AgentToolCall.task_id == task.id)).all()
    confirmed = [call for call in decisions if call.human_confirmed]
    assert confirmed, "the approved tool calls must be marked human_confirmed"
    actions = {row.action for row in db_session.scalars(
        select(AuditLog).where(AuditLog.project_id == project.id)).all()}
    assert {"create", "agent_human_gate", "agent_human_decision"} <= actions


def test_project_without_a_governed_clause_cannot_produce_a_document(db_session) -> None:
    """The same objective on a project with no normative source must not invent a basis."""

    ids = seed_agent_acceptance(db_session)
    empty = Project(name="无监管依据验收项目", institution_id=ids["institution_id"],
                    project_status="active", confidentiality_level="internal")
    db_session.add(empty)
    db_session.flush()
    from app.models import ProjectMembership
    db_session.add(ProjectMembership(project_id=empty.id, user_id=ids["user_id"],
                                     project_role="project_manager", status="active"))
    db_session.commit()
    principal = Principal(ids["user_id"], ids["username"], "Agent 验收用户")

    task = runtime.create_task(db_session, principal, empty, OBJECTIVE)
    job = runtime.submit_task(db_session, empty, principal, task)
    runtime.run_agent_task(db_session, job)
    db_session.refresh(task)

    assert task.status in {sm.TASK_BLOCKED, sm.TASK_FAILED}
    assert "requirement_document" not in _artifacts(db_session, task)
    gaps = runtime.task_snapshot(db_session, task)["gaps"]
    codes = {item.get("code") for item in gaps}
    assert "missing_basis" in codes
