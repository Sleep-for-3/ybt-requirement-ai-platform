import importlib.util
import json
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "rag_regression", Path(__file__).resolve().parents[1] / "scripts" / "rag_regression.py")
regression = importlib.util.module_from_spec(spec)
spec.loader.exec_module(regression)


def test_dedup_retains_disagreeing_labels_and_groups(tmp_path):
    sources = []
    for index, required in enumerate(([1], [2])):
        path = tmp_path / f"cases{index}.json"
        path.write_text(json.dumps({"cases": [
            {"id": "C01", "question": " same question ", "family": "f",
             "expected": {"required_units": required}}]}), encoding="utf-8")
        sources.append(path)
    snapshot = regression.normalize_sources(sources)
    assert len(snapshot["cases"]) == 1
    assert len(snapshot["cases"][0]["annotations"]) == 2
    assert len(snapshot["cases"][0]["provenance"]) == 2
    assert "independent_holdout_unavailable" in snapshot["blockers"]


def test_incomplete_or_mock_results_never_pass_business_gate():
    result = regression.compare(
        {"dataset_version": "a", "corpus_hash": "b", "evaluation_environment": "test"},
        {"dataset_version": "a", "corpus_hash": "b", "evaluation_environment": "test",
         "evidence_tier": "mock", "metrics": {"hit5": 1}})
    assert not result["passed"]
    assert "business_acceptance_requires_real_components" in result["reasons"]


def test_comparison_checks_zero_tolerance_and_latency():
    base = {
        "dataset_version": "a", "corpus_hash": "b", "evaluation_environment": "test",
        "evidence_tier": "real_model", "metrics": {
            "hit5": .8, "mrr": .7, "citation_precision": .9,
            "hit5_samples": 50, "mrr_samples": 50, "citation_precision_samples": 50,
            "latency_p95_ms": 100, "latency_samples": 50, "permission_leaks": 0, "version_leaks": 0,
            "critical_failures": 0,
        }}
    assert regression.compare(base, base)["passed"]
    candidate = {**base, "metrics": {**base["metrics"], "version_leaks": 1, "latency_p95_ms": 121}}
    assert regression.compare(base, candidate)["reasons"] == ["regressed:latency_p95_ms", "version_leaks"]


def test_unreviewed_results_keep_unknown_safety_and_explicit_snapshot_mismatch():
    dataset = {"dataset_version": "v", "cases": [
        {"case_id": "a", "split": "holdout", "review_status": "needs_business_review"}]}
    manifest = {"dataset_version": "v", "corpus_hash": "corpus", "blockers": []}
    report = regression.evaluate_results(dataset, manifest, [
        {"case_id": "a", "status": "retrieval_only", "latency_ms": 25,
         "evidence_tier": "sqlite_keyword"}])
    assert report["metrics"]["permission_leaks"] is None
    assert report["metrics"]["hit5"] is None
    assert report["metrics"]["latency_samples"] == 1
    assert "result_snapshot_mismatch" in report["blockers"]
    assert not regression.compare(report, report)["passed"]


def test_reviewed_holdout_uses_explicit_ids_and_reports_denominators():
    dataset = {"dataset_version": "v", "cases": [
        {"case_id": "a", "split": "holdout", "review_status": "approved",
         "gold": {"reviewer": "business", "corpus_hash": "corpus", "relevant_ids": [2],
                  "must_refuse": False, "roles": {"clause": [2]}}}]}
    manifest = {"dataset_version": "v", "corpus_hash": "corpus",
                "evaluation_environment": "same-components", "blockers": []}
    report = regression.evaluate_results(dataset, manifest, [{
        "case_id": "a", "dataset_version": "v", "corpus_hash": "corpus",
        "status": "completed", "evidence_tier": "real_components",
        "permission_leaks": 0, "version_leaks": 0, "critical_failures": 0,
        "latency_ms": 100, "answer_status": "grounded", "retrieved_ids": [1, 2],
        "context_ids": [2], "cited_ids": [2],
        "assessment": {"reviewer": "business", "supported_citations": 1,
                       "total_citations": 1, "complete": True},
    }])
    assert report["metrics"]["mrr"] == .5
    assert report["metrics"]["hit5_samples"] == 1
    assert report["metrics"]["role_cited_rate"] == 1
    assert report["blockers"] == []
    assert regression.compare(report, report)["passed"]
