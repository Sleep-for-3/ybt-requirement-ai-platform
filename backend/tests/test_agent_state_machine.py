"""Unit tests for the pure agent state machine."""
from __future__ import annotations

import pytest

from app.services.agent import state_machine as sm


def test_step_status_vocabulary_is_exactly_the_documented_set() -> None:
    assert sm.STEP_STATUSES == (
        "pending", "running", "completed", "blocked", "failed", "waiting_human", "skipped",
    )


def test_only_documented_step_transitions_are_allowed() -> None:
    sm.require_step_transition("pending", "running")
    sm.require_step_transition("running", "waiting_human")
    sm.require_step_transition("waiting_human", "completed")
    sm.require_step_transition("waiting_human", "blocked")
    sm.require_step_transition("waiting_human", "pending")
    sm.require_step_transition("failed", "running")
    sm.require_step_transition("blocked", "pending")

    with pytest.raises(sm.AgentStateError) as illegal:
        sm.require_step_transition("completed", "running")
    assert illegal.value.code == "illegal_step_transition"

    with pytest.raises(sm.AgentStateError):
        sm.require_step_transition("skipped", "pending")

    with pytest.raises(sm.AgentStateError) as unknown:
        sm.require_step_transition("pending", "nonsense")
    assert unknown.value.code == "unknown_step_status"


def test_task_transitions_terminals_and_resumables() -> None:
    sm.require_task_transition("created", "running")
    sm.require_task_transition("running", "waiting_human")
    sm.require_task_transition("waiting_human", "running")
    sm.require_task_transition("failed", "running")
    sm.require_task_transition("blocked", "running")

    for terminal in ("completed", "cancelled"):
        with pytest.raises(sm.AgentStateError):
            sm.require_task_transition(terminal, "running")

    assert sm.TASK_TERMINAL == frozenset({"completed", "cancelled"})
    assert sm.TASK_RESUMABLE == frozenset({"failed", "blocked", "waiting_human"})


def test_derived_task_status_precedence() -> None:
    assert sm.derive_task_status([]) == "created"
    assert sm.derive_task_status(["pending", "completed"]) == "running"
    assert sm.derive_task_status(["completed", "running"]) == "running"
    # an active human gate outranks a sibling failure: the user must act first
    assert sm.derive_task_status(["completed", "waiting_human", "failed"]) == "waiting_human"
    assert sm.derive_task_status(["completed", "failed"]) == "failed"
    assert sm.derive_task_status(["completed", "blocked"]) == "blocked"
    assert sm.derive_task_status(["completed", "skipped"]) == "completed"
    assert sm.derive_task_status(["completed"], cancelled=True) == "cancelled"


def test_human_decisions_map_to_legal_step_targets() -> None:
    assert sm.DECISIONS == ("approve", "reject", "edit_and_approve", "request_reanalysis")
    assert sm.DECISION_STEP_TARGET["approve"] == "completed"
    assert sm.DECISION_STEP_TARGET["edit_and_approve"] == "completed"
    assert sm.DECISION_STEP_TARGET["reject"] == "blocked"
    assert sm.DECISION_STEP_TARGET["request_reanalysis"] == "pending"
    for decision, target in sm.DECISION_STEP_TARGET.items():
        sm.require_step_transition("waiting_human", target)


def test_step_counts_reports_every_status() -> None:
    counts = sm.step_counts(["completed", "completed", "waiting_human"])
    assert counts["completed"] == 2
    assert counts["waiting_human"] == 1
    assert counts["failed"] == 0
    assert counts["total"] == 3
