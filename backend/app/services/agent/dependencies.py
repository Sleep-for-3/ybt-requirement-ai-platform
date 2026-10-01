"""Dependency semantics for agent steps.

V1 asked ``any(dependency completed)`` before running a step, so a step could run
while a *required* predecessor had failed, been skipped, or was waiting for a
human. V2 applies the documented matrix instead:

===========  ===================  =============================================
dependency   state                effect on the dependent step
===========  ===================  =============================================
required     completed            satisfied
required     failed / blocked     must not run → ``block`` (replan / human path)
required     skipped              must not run → ``skip`` + ``dependency_gap``
required     waiting_human        the whole task pauses (``pause``)
required     pending / running    wait (``wait``)
required     absent               wait (it may still be materialized)
optional     completed            satisfied
optional     anything else        the step may still run, but the missing input
                                  is recorded as a gap
===========  ===================  =============================================

``waiting_human`` pauses for optional dependencies too: an open human gate must
never let the chain run ahead.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from app.services.agent import state_machine as sm

WAIT = "wait"
PAUSE = "pause"
BLOCK = "block"
SKIP = "skip"
EXECUTE = "execute"

DEPENDENCY_GAP = "dependency_gap"
DEPENDENCY_FAILED = "dependency_failed"
DEPENDENCY_SKIPPED = "dependency_skipped"
DEPENDENCY_WAITING = "dependency_waiting_human"
OPTIONAL_DEPENDENCY_MISSING = "optional_dependency_missing"

_NOT_READY = frozenset({sm.STEP_PENDING, sm.STEP_RUNNING})


@dataclass(frozen=True)
class DependencyEvaluation:
    disposition: str
    satisfied: tuple[str, ...] = ()
    waiting: tuple[str, ...] = ()
    pending: tuple[str, ...] = ()
    absent: tuple[str, ...] = ()
    failed_required: tuple[str, ...] = ()
    blocked_required: tuple[str, ...] = ()
    skipped_required: tuple[str, ...] = ()
    waiting_required: tuple[str, ...] = ()
    optional_missing: tuple[tuple[str, str], ...] = ()
    gap_codes: tuple[str, ...] = ()
    reason: str = ""

    @property
    def executable(self) -> bool:
        return self.disposition == EXECUTE

    def as_dict(self) -> dict[str, object]:
        return {
            "disposition": self.disposition,
            "satisfied": list(self.satisfied),
            "waiting": list(self.waiting),
            "pending": list(self.pending),
            "absent": list(self.absent),
            "failed_required": list(self.failed_required),
            "blocked_required": list(self.blocked_required),
            "skipped_required": list(self.skipped_required),
            "waiting_required": list(self.waiting_required),
            "optional_missing": [{"step_key": key, "status": status} for key, status in self.optional_missing],
            "gap_codes": list(self.gap_codes),
            "reason": self.reason,
        }


def evaluate_dependencies(
    required: Iterable[str],
    optional: Iterable[str],
    states: Mapping[str, str | None],
) -> DependencyEvaluation:
    """Evaluate one step's dependencies. Pure: ``states`` maps step_key → status."""

    required_keys = [key for key in dict.fromkeys(required)]
    optional_keys = [key for key in dict.fromkeys(optional) if key not in set(required_keys)]

    satisfied: list[str] = []
    waiting: list[str] = []
    pending: list[str] = []
    absent: list[str] = []
    failed: list[str] = []
    blocked: list[str] = []
    skipped: list[str] = []
    waiting_required: list[str] = []
    optional_missing: list[tuple[str, str]] = []

    for key in required_keys:
        status = states.get(key)
        if status == sm.STEP_COMPLETED:
            satisfied.append(key)
        elif status == sm.STEP_WAITING_HUMAN:
            waiting.append(key)
            waiting_required.append(key)
        elif status == sm.STEP_FAILED:
            failed.append(key)
        elif status == sm.STEP_BLOCKED:
            blocked.append(key)
        elif status == sm.STEP_SKIPPED:
            skipped.append(key)
        elif status in _NOT_READY:
            pending.append(key)
        else:  # unknown / not materialized yet
            absent.append(key)

    for key in optional_keys:
        status = states.get(key)
        if status == sm.STEP_COMPLETED:
            satisfied.append(key)
        elif status == sm.STEP_WAITING_HUMAN:
            waiting.append(key)
            optional_missing.append((key, str(status)))
        elif status is None:
            optional_missing.append((key, "absent"))
        else:
            optional_missing.append((key, str(status)))

    gap_codes: list[str] = []
    if optional_missing:
        gap_codes.append(OPTIONAL_DEPENDENCY_MISSING)

    if waiting:
        # An open human gate pauses the whole dependency chain (required or optional).
        return DependencyEvaluation(
            disposition=PAUSE, satisfied=tuple(satisfied), waiting=tuple(waiting), pending=tuple(pending),
            absent=tuple(absent), waiting_required=tuple(waiting_required),
            optional_missing=tuple(optional_missing),
            gap_codes=tuple(gap_codes), reason="依赖步骤正在等待人工确认，任务暂停。",
        )
    if failed or blocked:
        return DependencyEvaluation(
            disposition=BLOCK, satisfied=tuple(satisfied), pending=tuple(pending), absent=tuple(absent),
            failed_required=tuple(failed), blocked_required=tuple(blocked),
            optional_missing=tuple(optional_missing),
            gap_codes=tuple([*gap_codes, DEPENDENCY_FAILED]),
            reason="必需依赖步骤未成功（失败/阻断），当前步骤不能按成功路径继续。",
        )
    if skipped:
        return DependencyEvaluation(
            disposition=SKIP, satisfied=tuple(satisfied), pending=tuple(pending), absent=tuple(absent),
            skipped_required=tuple(skipped), optional_missing=tuple(optional_missing),
            gap_codes=tuple([*gap_codes, DEPENDENCY_GAP]),
            reason="必需依赖步骤被跳过，不能当作成功，按缺口跳过当前步骤。",
        )
    if pending or absent:
        return DependencyEvaluation(
            disposition=WAIT, satisfied=tuple(satisfied), pending=tuple(pending), absent=tuple(absent),
            optional_missing=tuple(optional_missing), gap_codes=tuple(gap_codes),
            reason="依赖步骤尚未结束，等待其完成。",
        )
    return DependencyEvaluation(
        disposition=EXECUTE, satisfied=tuple(satisfied), optional_missing=tuple(optional_missing),
        gap_codes=tuple(gap_codes),
        reason="全部必需依赖已完成。" if not optional_missing else "必需依赖已完成；可选依赖缺失已记为缺口。",
    )


def optional_gap_message(optional_missing: Iterable[tuple[str, str]]) -> str:
    parts = [f"{key}({status})" for key, status in optional_missing]
    return "可选依赖未提供结果：" + "、".join(parts) if parts else ""
