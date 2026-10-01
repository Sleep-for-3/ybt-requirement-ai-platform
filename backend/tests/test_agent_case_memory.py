"""Decision / case memory: human-confirmed experience only, never a policy basis.

The tests pin the hard rules: only an approving human decision (or a formal
review outcome) may become a case, recording is idempotent, retrieval is
labelled ``historical_decision`` (never ``policy_requirement``) and the
effective window is respected when a reference time is supplied.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.models import (
    AgentHumanDecision,
    AgentPlan,
    AgentStep,
    AgentTask,
    DecisionCase,
    Project,
    User,
)
from app.services.agent import case_memory as memory

NOW = datetime(2026, 10, 2, 2, 0, tzinfo=UTC)
FIELD_MAPPING = memory.DECISION_TYPE_FIELD_MAPPING
SOURCE_SELECTION = memory.DECISION_TYPE_SOURCE_SELECTION


def _scope(db):
    """A real (small) graph: author, approver, project, task/plan/step."""

    author = User(username="author", display_name="作者")
    approver = User(username="approver", display_name="审批人")
    db.add_all([author, approver])
    db.commit()

    project = Project(name="监管报送项目")
    db.add(project)
    db.commit()

    task = AgentTask(
        project_id=project.id,
        objective="生成监管需求",
        scenario_key="requirement_generation",
        created_by=author.id,
    )
    db.add(task)
    db.commit()

    plan = AgentPlan(task_id=task.id, version_no=1, objective=task.objective, created_by=author.id)
    db.add(plan)
    db.commit()

    step = AgentStep(
        task_id=task.id, plan_id=plan.id, step_key="draft", order_index=0, tool_key="requirement_draft",
    )
    db.add(step)
    db.commit()
    return author, approver, project, task, step


def _human_decision(db, task, step, approver, decision="approve"):
    record = AgentHumanDecision(
        task_id=task.id, step_id=step.id, decision=decision, decided_by=approver.id,
    )
    db.add(record)
    db.commit()
    return record


def _record(db, *, project, task, step, record, decision, **overrides):
    args = {
        "task": task,
        "step": step,
        "project": project,
        "decision_record": record,
        "decision_type": FIELD_MAPPING,
        "decision": decision,
        "subject_type": "target_field",
        "subject_id": "JR_YBT_001",
        "confidence_source": "human_decision",
    }
    args.update(overrides)
    return memory.record_decision_case(db, **args)


def _count(db) -> int:
    return len(list(db.scalars(select(DecisionCase)).all()))


def test_approving_human_decision_is_recorded(db_session):
    author, approver, project, task, step = _scope(db_session)
    record = _human_decision(db_session, task, step, approver)

    case = _record(
        db_session,
        project=project,
        task=task,
        step=step,
        record=record,
        decision="YBT 字段 JR_YBT_001 取自 SRC_LOAN.LOAN_AMT",
        rationale="人工确认：贷款金额口径与监管口径一致。",
        evidence_refs=[{"type": "source_field", "id": 12}],
        regulatory_refs=[{"type": "requirement", "id": 3}],
        related={"mapping_id": 11, "requirement_id": None, "script_id": 5},
        effective_from=NOW,
        effective_to=NOW + timedelta(days=30),
    )

    assert isinstance(case, DecisionCase)
    assert case.id is not None
    assert case.project_id == project.id
    assert case.decision_type == FIELD_MAPPING
    assert case.subject_type == "target_field"
    assert case.subject_id == "JR_YBT_001"
    assert case.confidence_source == "human_decision"
    assert case.approved_by == approver.id
    assert case.created_by == approver.id
    assert case.status == memory.STATUS_ACTIVE
    assert case.evidence_refs_json == [{"type": "source_field", "id": 12}]
    assert case.regulatory_refs_json == [{"type": "requirement", "id": 3}]
    assert case.related_mapping_id == 11
    assert case.related_requirement_id is None
    assert case.related_script_id == 5
    # A case never claims to be policy, not even after storage.
    assert memory.case_is_regulatory_basis(case) is False


def test_formal_review_outcome_is_recorded_without_bound_agent_task(db_session):
    author, approver, project, _task, _step = _scope(db_session)

    case = memory.record_decision_case(
        db_session,
        project=project,
        decision_record={"decision": "approved", "decided_by": approver.id},
        decision_type=SOURCE_SELECTION,
        decision="评审结论：选择核心系统作为来源。",
        confidence_source="review_outcome",
        scenario_key="source_selection",
    )

    assert case.confidence_source == "review_outcome"
    assert case.approved_by == approver.id
    assert case.scenario_key == "source_selection"


def test_model_suggestion_source_is_refused(db_session):
    author, approver, project, task, step = _scope(db_session)

    for source in ("llm_suggestion", "agent_inference", "model_default"):
        with pytest.raises(memory.CaseMemoryError) as excinfo:
            _record(
                db_session,
                project=project,
                task=task,
                step=step,
                record=None,
                decision="模型建议：字段映射到 SRC_A.F1",
                confidence_source=source,
                approved_by=approver.id,
            )
        assert excinfo.value.code == "unsupported_confidence_source"
        assert isinstance(excinfo.value, ValueError)

    assert _count(db_session) == 0


def test_rejected_and_reanalysis_decisions_are_refused(db_session):
    author, approver, project, task, step = _scope(db_session)

    for verb in ("reject", "request_reanalysis"):
        record = _human_decision(db_session, task, step, approver, decision=verb)
        with pytest.raises(memory.CaseMemoryError) as excinfo:
            _record(
                db_session,
                project=project,
                task=task,
                step=step,
                record=record,
                decision="这条决定被拒绝了，不应成为经验",
            )
        assert excinfo.value.code == "not_an_approving_decision"

    assert _count(db_session) == 0


def test_unknown_decision_verb_is_refused(db_session):
    author, approver, project, task, step = _scope(db_session)
    record = _human_decision(db_session, task, step, approver, decision="maybe")

    with pytest.raises(memory.CaseMemoryError) as excinfo:
        _record(db_session, project=project, task=task, step=step, record=record, decision="不确定")

    assert excinfo.value.code == "unsupported_decision"


def test_recording_without_any_human_approval_is_refused(db_session):
    author, approver, project, task, step = _scope(db_session)

    with pytest.raises(memory.CaseMemoryError) as excinfo:
        _record(db_session, project=project, task=task, step=step, record=None, decision="无审批人的决定")
    assert excinfo.value.code == "missing_human_approval"

    # A named approver is enough of a human act; an approving decision_record is too.
    case = _record(
        db_session,
        project=project,
        task=task,
        step=step,
        record=None,
        decision="带审批人的决定",
        approved_by=approver.id,
    )
    assert case.approved_by == approver.id


def test_edit_and_approve_is_accepted(db_session):
    author, approver, project, task, step = _scope(db_session)
    record = _human_decision(db_session, task, step, approver, decision="edit_and_approve")

    case = _record(
        db_session, project=project, task=task, step=step, record=record, decision="人工修改后批准的决定",
    )

    assert case.id is not None
    assert _count(db_session) == 1


def test_duplicate_recording_is_idempotent(db_session):
    author, approver, project, task, step = _scope(db_session)
    record = _human_decision(db_session, task, step, approver)

    first = _record(
        db_session,
        project=project,
        task=task,
        step=step,
        record=record,
        decision="YBT 字段 JR_YBT_001 取自 SRC_LOAN.LOAN_AMT",
        effective_from=NOW,
    )
    second = _record(
        db_session,
        project=project,
        task=task,
        step=step,
        record=record,
        decision="YBT 字段 JR_YBT_001 取自 SRC_LOAN.LOAN_AMT",
        effective_from=NOW,
    )

    assert second.id == first.id
    assert _count(db_session) == 1

    # A genuinely different decision (or window) is new experience, not a duplicate.
    third = _record(
        db_session,
        project=project,
        task=task,
        step=step,
        record=record,
        decision="YBT 字段 JR_YBT_001 取自 SRC_LOAN.LOAN_AMT_V2",
        effective_from=NOW,
    )
    assert third.id != first.id
    fourth = _record(
        db_session,
        project=project,
        task=task,
        step=step,
        record=record,
        decision="YBT 字段 JR_YBT_001 取自 SRC_LOAN.LOAN_AMT",
        effective_from=NOW + timedelta(days=1),
    )
    assert fourth.id != first.id
    assert _count(db_session) == 3


def test_search_returns_historical_labels_never_policy(db_session):
    author, approver, project, task, step = _scope(db_session)
    record = _human_decision(db_session, task, step, approver)
    _record(
        db_session,
        project=project,
        task=task,
        step=step,
        record=record,
        decision="贷款金额映射到 SRC_LOAN.LOAN_AMT",
        rationale="人工确认贷款金额口径。",
    )
    _record(
        db_session,
        project=project,
        task=task,
        step=step,
        record=record,
        decision="客户编号映射到 SRC_CUST.CUST_NO",
        decision_type=SOURCE_SELECTION,
        subject_id="JR_YBT_002",
    )

    hits = memory.search_decision_cases(db_session, project=project, query="贷款金额")

    assert hits, "a matching query must retrieve the recorded case"
    for hit in hits:
        assert hit["source_type"] == "historical_decision"
        assert hit["source_type"] in memory.CASE_SOURCE_TYPES
        assert hit["source_type"] != memory.POLICY_SOURCE_TYPE
        assert memory.POLICY_SOURCE_TYPE not in hit.values()
        assert hit["similarity"] > 0.0
        assert hit["score"] == hit["similarity"]
        assert hit["regulatory_basis"] is False
    assert len(hits) == 1
    assert hits[0]["decision"].startswith("贷款金额")


def test_search_field_filters_and_top_k(db_session):
    author, approver, project, task, step = _scope(db_session)
    record = _human_decision(db_session, task, step, approver)
    _record(
        db_session, project=project, task=task, step=step, record=record,
        decision="映射决定 A", subject_type="target_field", subject_id="JR_YBT_001",
    )
    _record(
        db_session, project=project, task=task, step=step, record=record,
        decision="需求决定 B", decision_type=memory.DECISION_TYPE_REQUIREMENT,
        subject_type="requirement", subject_id="REQ-9",
    )

    by_subject = memory.search_decision_cases(
        db_session, project=project, subject_type="target_field", subject_id="JR_YBT_001",
    )
    assert [hit["subject_id"] for hit in by_subject] == ["JR_YBT_001"]

    by_type = memory.search_decision_cases(db_session, project=project, decision_type=memory.DECISION_TYPE_REQUIREMENT)
    assert [hit["decision_type"] for hit in by_type] == [memory.DECISION_TYPE_REQUIREMENT]

    assert len(memory.search_decision_cases(db_session, project=project, top_k=1)) == 1
    assert memory.search_decision_cases(db_session, project=project, top_k=0) == []
    assert memory.search_decision_cases(db_session, project=project, query="完全无关的问题") == []


def test_effective_window_filters_results_when_reference_time_is_given(db_session):
    author, approver, project, task, step = _scope(db_session)
    record = _human_decision(db_session, task, step, approver)
    expired = _record(
        db_session, project=project, task=task, step=step, record=record,
        decision="旧口径：金额取自 SRC_LOAN.AMT_OLD",
        effective_from=NOW - timedelta(days=10), effective_to=NOW - timedelta(days=1),
    )
    current = _record(
        db_session, project=project, task=task, step=step, record=record,
        decision="新口径：金额取自 SRC_LOAN.AMT",
        effective_from=NOW - timedelta(days=1), effective_to=NOW + timedelta(days=10),
    )

    at_now = memory.search_decision_cases(db_session, project=project, at=NOW)
    assert [hit["id"] for hit in at_now] == [current.id]

    in_the_past = memory.search_decision_cases(db_session, project=project, at=NOW - timedelta(days=5))
    assert [hit["id"] for hit in in_the_past] == [expired.id]

    # Without a reference time the window is not applied (documented behaviour).
    assert {hit["id"] for hit in memory.search_decision_cases(db_session, project=project)} == {current.id, expired.id}


def test_retired_case_is_not_retrieved(db_session):
    author, approver, project, task, step = _scope(db_session)
    record = _human_decision(db_session, task, step, approver)
    case = _record(db_session, project=project, task=task, step=step, record=record, decision="将被废止的决定")

    assert memory.search_decision_cases(db_session, project=project) != []
    case.status = memory.STATUS_ARCHIVED
    db_session.commit()

    assert memory.search_decision_cases(db_session, project=project) == []
    assert _count(db_session) == 1  # history is retired, never deleted


def test_case_is_regulatory_basis_is_always_false(db_session):
    author, approver, project, task, step = _scope(db_session)
    record = _human_decision(db_session, task, step, approver)
    case = _record(db_session, project=project, task=task, step=step, record=record, decision="已确认的决定")

    assert memory.case_is_regulatory_basis(case) is False
    assert memory.case_is_regulatory_basis(None) is False
    assert memory.case_is_regulatory_basis({"source_type": "policy_requirement"}) is False


def test_search_and_record_require_a_project(db_session):
    with pytest.raises(memory.CaseMemoryError) as search_error:
        memory.search_decision_cases(db_session, project=None)
    assert search_error.value.code == "missing_project_scope"

    with pytest.raises(memory.CaseMemoryError) as record_error:
        memory.record_decision_case(
            db_session, decision_type=FIELD_MAPPING, decision="无项目决定",
            confidence_source="human_decision", approved_by=1,
        )
    assert record_error.value.code == "missing_project_scope"
