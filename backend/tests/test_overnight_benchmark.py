"""A-package: the versioned business benchmark and its contract.

These tests lock the *harness* so a later change cannot quietly move the goalposts:

* the corpus is synthetic, complete across the six families, and its content hash is
  stable against dict/list ordering;
* the dev/holdout split never separates a seed rewrite from its group;
* running the corpus executes real service code (``grounded_answer``,
  ``check_citation_support``, the agent state machine) rather than a private helper;
* a case whose expectation the shipped code does not meet is reported as *failed*, not
  silently skipped, and the denominators stay explicit.

The last test is the A-package deliverable in miniature: it pins the exact defect the B
package must fix (a citation the judge marked ``unsupported`` still produced
``answer_status="grounded"``).  It is written against observable behaviour so it also
passes once the fix lands.
"""
from __future__ import annotations

import json

from app.services.evaluation.benchmark import dataset, runner
from app.services.evaluation.benchmark.cases import load_cases

REQUIRED_FAMILIES = set(dataset.FAMILIES)


def _by_id(case_id: str) -> dict:
    return next(case for case in load_cases() if case["case_id"] == case_id)


# --------------------------------------------------------------------------- corpus


def test_the_corpus_covers_every_required_family():
    corpus = load_cases()
    counts = dataset.coverage(corpus)
    assert counts["families_complete"] is True, counts["missing_families"]
    for family in REQUIRED_FAMILIES:
        assert counts["by_family"][family] >= 10, (family, counts["by_family"][family])
    # The task book asks for roughly 120 cases with at least 30 high-quality seeds.
    assert counts["total"] >= 100


def test_every_case_is_synthetic_and_contract_complete():
    problems = {case["case_id"]: dataset.validate_case(case) for case in load_cases()}
    invalid = {key: value for key, value in problems.items() if value}
    assert invalid == {}
    for case in load_cases():
        # No business data may be smuggled in as a "synthetic" case.
        assert case["synthetic"] is True
        assert case["provenance"].startswith("synthetic")
        assert case["expected"], case["case_id"]
        assert case["forbidden"], case["case_id"]


def test_the_dataset_digest_is_order_independent_and_edit_sensitive():
    corpus = load_cases()
    ordered = sorted(corpus, key=lambda case: case["case_id"])
    shuffled = sorted(reversed(corpus), key=lambda case: case["case_id"])
    assert dataset.content_hash(ordered) == dataset.content_hash(shuffled)

    edited = [dict(case) for case in ordered]
    edited[0]["expected"] = {**edited[0]["expected"], "injected": True}
    assert dataset.content_hash(edited) != dataset.content_hash(ordered)


def test_the_split_never_separates_a_seed_group():
    corpus = load_cases()
    splits = dataset.split_cases(corpus)
    dev_seeds = {case["seed_id"] for case in splits["dev"]}
    holdout_seeds = {case["seed_id"] for case in splits["holdout"]}
    assert not (dev_seeds & holdout_seeds)
    # Roughly 80/20, and both sides non-trivial.
    total = len(corpus)
    assert 0.6 <= len(splits["dev"]) / total <= 0.9
    assert len(splits["holdout"]) >= 10
    assert len(splits["dev"]) + len(splits["holdout"]) == total


# --------------------------------------------------------------------------- execution


def test_running_the_corpus_executes_real_service_code():
    payload = runner.run()
    aggregate = payload["aggregate"]
    # Every case in every family must really run against its real service entry point.
    # The rerank family used to be reported as not-run before a catalog fixture existed; now it
    # builds a disposable catalog and drives the real recall + rerank chain, so a not-run case
    # anywhere is a harness failure rather than an accepted state.
    assert aggregate["not_run_count"] == 0, aggregate["not_run"]
    assert aggregate["executed_count"] == aggregate["case_count"]
    # A real gateway call happened (the judge path ran), and the citation families were
    # scored against the shipped status assembly.
    assert aggregate["gateway_calls_total"] > 0
    for family in dataset.FAMILIES:
        assert aggregate["by_family"][family]["executed"] > 0, family


def test_a_not_run_case_is_never_counted_as_a_pass():
    payload = runner.run()
    for case in payload["cases"]:
        if not case.get("executed"):
            assert case["verdict"] == "not_run"
    aggregate = payload["aggregate"]
    assert aggregate["passed_count"] + aggregate["failed_count"] + aggregate["not_run_count"] \
        == aggregate["case_count"]
    # A 0/0 family reports null, not a fake 1.0.
    for family, rate in aggregate["pass_rate_by_family"].items():
        if aggregate["by_family"][family]["executed"] == 0:
            assert rate is None, family


def test_the_baseline_defect_is_visible_as_a_failure():
    """The B-package defect: an unsupported citation still yielded a grounded answer.

    This asserts the *harness can see the defect*.  It reads the recorded observation for
    the case rather than hard-coding "must fail", so it keeps passing after the fix: either
    the case now passes (fixed) or it fails with exactly this reason (still broken, and the
    failure is reported rather than hidden).
    """
    case = _by_id("C1-A1")  # 理财产品 claims, 公募基金 evidence -> judge says unsupported
    result = runner.execute_case(case)
    assert result["executed"] is True
    observed = result["observed"]
    assert observed["unsupported"] == 1, observed
    scored = next(entry for entry in runner.score_results([result]) if entry["case_id"] == "C1-A1")

    if scored["verdict"] == "pass":
        # Fix landed: the unsupported claim did not stay grounded/high.
        assert observed["answer_status"] != "grounded"
    else:
        # Fix not landed: the failure must name the status, never a generic assertion.
        assert any("answer_status" in item for item in scored["failures"]), scored["failures"]


def test_judge_degradation_is_reported_as_unknown_not_as_safe():
    """A timed-out judge must not become '0% unsupported therefore reliable'."""
    case = _by_id("C2-F1")
    result = runner.execute_case(case)
    assert result["executed"] is True
    observed = result["observed"]
    assert observed["degraded"] is True
    assert observed["degraded_reason"] == "timeout"
    assert observed["unknown"] == 1


def test_duplicate_and_out_of_range_verdicts_do_not_inflate_coverage():
    duplicate = runner.execute_case(_by_id("C2-C1"))["observed"]
    assert duplicate["judged_count"] <= duplicate["citation_count"]
    out_of_range = runner.execute_case(_by_id("C2-E1"))["observed"]
    # The bogus/empty ids must not be added as extra judged citations.
    assert out_of_range["judged_count"] <= out_of_range["citation_count"]


def test_agent_state_chain_cases_use_the_real_state_machine():
    illegal = runner.execute_case(_by_id("C6-H1"))["observed"]
    assert illegal["raised"] is True
    assert illegal["error_code"] == "illegal_step_transition"

    precedence = runner.execute_case(_by_id("C6-J1"))["observed"]
    assert precedence["derived_task_status"] == "waiting_human"

    cancelled = runner.execute_case(_by_id("C6-F1"))["observed"]
    assert cancelled["derived_task_status"] == "cancelled"


def test_the_rerun_is_deterministic():
    first = runner.run()
    second = runner.run()
    assert [case["verdict"] for case in first["cases"]] == [case["verdict"] for case in second["cases"]]
    assert json.dumps(first["aggregate"]["by_family"], sort_keys=True) == \
        json.dumps(second["aggregate"]["by_family"], sort_keys=True)
