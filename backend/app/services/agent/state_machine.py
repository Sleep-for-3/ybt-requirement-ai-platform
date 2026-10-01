"""Pure agent state machine: statuses, legal transitions and derived roll-ups.

The orchestrator never invents a status. Every step status change goes through
:func:`transition_step`, so an illegal edge (for example ``completed`` back to
``running``) fails loudly instead of silently corrupting a durable task.

Step status vocabulary (execution spec): ``pending``, ``running``,
``completed``, ``blocked``, ``failed``, ``waiting_human``, ``skipped``.

Task status vocabulary: ``created``, ``planning``, ``running``,
``waiting_human``, ``blocked``, ``completed``, ``failed``, ``cancelled``.

Cancellation reuses ``skipped`` for not-yet-run steps rather than adding an
eighth step status, so the step vocabulary stays exactly the documented one.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Final

STEP_PENDING: Final = "pending"
STEP_RUNNING: Final = "running"
STEP_COMPLETED: Final = "completed"
STEP_BLOCKED: Final = "blocked"
STEP_FAILED: Final = "failed"
STEP_WAITING_HUMAN: Final = "waiting_human"
STEP_SKIPPED: Final = "skipped"

STEP_STATUSES: Final[tuple[str, ...]] = (
    STEP_PENDING, STEP_RUNNING, STEP_COMPLETED, STEP_BLOCKED, STEP_FAILED, STEP_WAITING_HUMAN, STEP_SKIPPED,
)
# A step that can no longer change without an explicit human/retry/replan action.
STEP_TERMINAL: Final[frozenset[str]] = frozenset({STEP_COMPLETED, STEP_SKIPPED})
# A step the runner may still advance on its own.
STEP_RUNNABLE: Final[frozenset[str]] = frozenset({STEP_PENDING, STEP_FAILED, STEP_BLOCKED})
STEP_ACTIVE: Final[frozenset[str]] = frozenset({STEP_RUNNING, STEP_WAITING_HUMAN})

TASK_CREATED: Final = "created"
TASK_PLANNING: Final = "planning"
TASK_RUNNING: Final = "running"
TASK_WAITING_HUMAN: Final = "waiting_human"
TASK_BLOCKED: Final = "blocked"
TASK_COMPLETED: Final = "completed"
TASK_FAILED: Final = "failed"
TASK_CANCELLED: Final = "cancelled"

TASK_STATUSES: Final[tuple[str, ...]] = (
    TASK_CREATED, TASK_PLANNING, TASK_RUNNING, TASK_WAITING_HUMAN, TASK_BLOCKED, TASK_COMPLETED, TASK_FAILED,
    TASK_CANCELLED,
)
TASK_TERMINAL: Final[frozenset[str]] = frozenset({TASK_COMPLETED, TASK_CANCELLED})
# Statuses a user action (retry / replan / decision) may resume from.
TASK_RESUMABLE: Final[frozenset[str]] = frozenset({TASK_FAILED, TASK_BLOCKED, TASK_WAITING_HUMAN})

STEP_TRANSITIONS: Final[dict[str, frozenset[str]]] = {
    # A step can fail before it ever runs (invalid input, permission denial), so a
    # pending step may go straight to failed/blocked instead of being left pending.
    STEP_PENDING: frozenset({STEP_RUNNING, STEP_BLOCKED, STEP_FAILED, STEP_SKIPPED}),
    STEP_RUNNING: frozenset({STEP_COMPLETED, STEP_FAILED, STEP_WAITING_HUMAN, STEP_BLOCKED, STEP_SKIPPED}),
    STEP_WAITING_HUMAN: frozenset({STEP_RUNNING, STEP_COMPLETED, STEP_BLOCKED, STEP_FAILED, STEP_SKIPPED, STEP_PENDING}),
    STEP_FAILED: frozenset({STEP_RUNNING, STEP_BLOCKED, STEP_SKIPPED, STEP_PENDING}),
    STEP_BLOCKED: frozenset({STEP_PENDING, STEP_RUNNING, STEP_FAILED, STEP_SKIPPED, STEP_WAITING_HUMAN}),
    STEP_COMPLETED: frozenset(),
    STEP_SKIPPED: frozenset(),
}

TASK_TRANSITIONS: Final[dict[str, frozenset[str]]] = {
    TASK_CREATED: frozenset({TASK_PLANNING, TASK_RUNNING, TASK_FAILED, TASK_CANCELLED}),
    TASK_PLANNING: frozenset({TASK_RUNNING, TASK_FAILED, TASK_CANCELLED}),
    TASK_RUNNING: frozenset({TASK_WAITING_HUMAN, TASK_BLOCKED, TASK_COMPLETED, TASK_FAILED, TASK_CANCELLED}),
    # A human gate can settle in any of these ways: resumed, rejected (blocked),
    # finished (the gate was the last outstanding step) or cancelled.
    TASK_WAITING_HUMAN: frozenset({TASK_RUNNING, TASK_BLOCKED, TASK_COMPLETED, TASK_FAILED, TASK_CANCELLED}),
    TASK_BLOCKED: frozenset({TASK_RUNNING, TASK_FAILED, TASK_CANCELLED}),
    TASK_FAILED: frozenset({TASK_RUNNING, TASK_PLANNING, TASK_CANCELLED, TASK_FAILED}),
    TASK_COMPLETED: frozenset(),
    TASK_CANCELLED: frozenset(),
}

# Human decisions and the step edge each one drives.
DECISION_APPROVE: Final = "approve"
DECISION_REJECT: Final = "reject"
DECISION_EDIT_AND_APPROVE: Final = "edit_and_approve"
DECISION_REQUEST_REANALYSIS: Final = "request_reanalysis"
DECISIONS: Final[tuple[str, ...]] = (
    DECISION_APPROVE, DECISION_REJECT, DECISION_EDIT_AND_APPROVE, DECISION_REQUEST_REANALYSIS,
)
# Decision -> (accepted?, next step status)
DECISION_STEP_TARGET: Final[dict[str, str]] = {
    DECISION_APPROVE: STEP_COMPLETED,
    DECISION_EDIT_AND_APPROVE: STEP_COMPLETED,
    DECISION_REJECT: STEP_BLOCKED,
    DECISION_REQUEST_REANALYSIS: STEP_PENDING,
}


class AgentStateError(RuntimeError):
    """An illegal state transition was attempted."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def require_step_transition(current: str, target: str) -> None:
    if current not in STEP_TRANSITIONS:
        raise AgentStateError("unknown_step_status", f"unknown step status: {current}")
    if target not in STEP_STATUSES:
        raise AgentStateError("unknown_step_status", f"unknown step status: {target}")
    if target not in STEP_TRANSITIONS[current]:
        raise AgentStateError(
            "illegal_step_transition", f"step transition {current} -> {target} is not allowed"
        )


def require_task_transition(current: str, target: str) -> None:
    if current not in TASK_TRANSITIONS:
        raise AgentStateError("unknown_task_status", f"unknown task status: {current}")
    if target not in TASK_STATUSES:
        raise AgentStateError("unknown_task_status", f"unknown task status: {target}")
    if target not in TASK_TRANSITIONS[current]:
        raise AgentStateError(
            "illegal_task_transition", f"task transition {current} -> {target} is not allowed"
        )


def derive_task_status(statuses: Iterable[str], *, cancelled: bool = False) -> str:
    """Roll step statuses up into the task status the UI should show.

    Precedence is deliberate: an active human gate outranks a sibling failure,
    because the user must act before anything else can progress.
    """
    values = list(statuses)
    if cancelled:
        return TASK_CANCELLED
    if not values:
        return TASK_CREATED
    if STEP_RUNNING in values:
        return TASK_RUNNING
    if STEP_WAITING_HUMAN in values:
        return TASK_WAITING_HUMAN
    if STEP_FAILED in values:
        return TASK_FAILED
    if STEP_BLOCKED in values:
        return TASK_BLOCKED
    if all(value in STEP_TERMINAL for value in values):
        return TASK_COMPLETED
    return TASK_RUNNING


def step_counts(statuses: Iterable[str]) -> dict[str, int]:
    counts = {status: 0 for status in STEP_STATUSES}
    for value in statuses:
        if value in counts:
            counts[value] += 1
    counts["total"] = len(list(statuses)) if not isinstance(statuses, list) else len(statuses)
    return counts
