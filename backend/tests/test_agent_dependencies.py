"""Dependency semantics: ALL required dependencies must succeed (V2)."""
from __future__ import annotations

from app.services.agent import dependencies as deps
from app.services.agent import state_machine as sm


def test_no_dependencies_is_executable():
    evaluation = deps.evaluate_dependencies([], [], {})
    assert evaluation.disposition == deps.EXECUTE
    assert evaluation.executable is True


def test_all_required_completed_is_executable():
    evaluation = deps.evaluate_dependencies(
        ["a", "b"], [], {"a": sm.STEP_COMPLETED, "b": sm.STEP_COMPLETED},
    )
    assert evaluation.disposition == deps.EXECUTE
    assert set(evaluation.satisfied) == {"a", "b"}
    assert evaluation.gap_codes == ()


def test_one_required_failed_blocks_even_if_the_other_completed():
    evaluation = deps.evaluate_dependencies(
        ["a", "b"], [], {"a": sm.STEP_COMPLETED, "b": sm.STEP_FAILED},
    )
    assert evaluation.disposition == deps.BLOCK
    assert evaluation.executable is False
    assert evaluation.failed_required == ("b",)
    assert deps.DEPENDENCY_FAILED in evaluation.gap_codes


def test_one_required_blocked_also_blocks():
    evaluation = deps.evaluate_dependencies(
        ["a", "b"], [], {"a": sm.STEP_COMPLETED, "b": sm.STEP_BLOCKED},
    )
    assert evaluation.disposition == deps.BLOCK
    assert evaluation.blocked_required == ("b",)


def test_one_required_skipped_is_not_success():
    evaluation = deps.evaluate_dependencies(
        ["a", "b"], [], {"a": sm.STEP_COMPLETED, "b": sm.STEP_SKIPPED},
    )
    assert evaluation.disposition == deps.SKIP
    assert evaluation.executable is False
    assert evaluation.skipped_required == ("b",)
    assert deps.DEPENDENCY_GAP in evaluation.gap_codes


def test_waiting_human_pauses_the_whole_chain():
    evaluation = deps.evaluate_dependencies(
        ["a", "b"], [], {"a": sm.STEP_COMPLETED, "b": sm.STEP_WAITING_HUMAN},
    )
    assert evaluation.disposition == deps.PAUSE
    assert evaluation.executable is False
    assert evaluation.waiting_required == ("b",)


def test_pending_and_absent_dependencies_wait():
    assert deps.evaluate_dependencies(["a"], [], {"a": sm.STEP_RUNNING}).disposition == deps.WAIT
    assert deps.evaluate_dependencies(["a"], [], {"a": sm.STEP_PENDING}).disposition == deps.WAIT
    absent = deps.evaluate_dependencies(["a"], [], {})
    assert absent.disposition == deps.WAIT
    assert absent.absent == ("a",)


def test_optional_dependency_missing_still_executes_with_a_gap():
    evaluation = deps.evaluate_dependencies(
        ["a"], ["opt"], {"a": sm.STEP_COMPLETED, "opt": sm.STEP_SKIPPED},
    )
    assert evaluation.disposition == deps.EXECUTE
    assert evaluation.optional_missing == (("opt", sm.STEP_SKIPPED),)
    assert deps.OPTIONAL_DEPENDENCY_MISSING in evaluation.gap_codes
    assert "opt" in deps.optional_gap_message(evaluation.optional_missing)


def test_optional_dependency_waiting_human_still_pauses():
    evaluation = deps.evaluate_dependencies(
        ["a"], ["opt"], {"a": sm.STEP_COMPLETED, "opt": sm.STEP_WAITING_HUMAN},
    )
    assert evaluation.disposition == deps.PAUSE


def test_a_dependency_declared_required_and_optional_is_deduplicated():
    evaluation = deps.evaluate_dependencies(
        ["a"], ["a"], {"a": sm.STEP_COMPLETED},
    )
    assert evaluation.disposition == deps.EXECUTE
    assert evaluation.satisfied == ("a",)
    assert evaluation.optional_missing == ()


def test_evaluation_is_json_projection_safe():
    payload = deps.evaluate_dependencies(
        ["a"], ["opt"], {"a": sm.STEP_FAILED, "opt": sm.STEP_SKIPPED},
    ).as_dict()
    assert payload["disposition"] == deps.BLOCK
    assert payload["failed_required"] == ["a"]
    assert payload["optional_missing"] == [{"step_key": "opt", "status": sm.STEP_SKIPPED}]
    assert isinstance(payload["reason"], str) and payload["reason"]
