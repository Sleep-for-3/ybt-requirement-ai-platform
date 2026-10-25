"""P0-A：金标指标必须拒绝“没有独立标注的业务验收”。

这些用例固定指标的诚实性规则：分母缺失输出 null、业务用例缺标注一律 N/A、
未执行案例族标 not_run、人工耗时扣除等待时间。
"""

from __future__ import annotations

from app.services.requirement_golden_metrics import (
    METRIC_VERSION,
    dataset_sha256,
    evaluate,
    summarize_timing,
    TimingRecord,
)

FILTER_TOKEN = "LOAN_STATUS = 'NORMAL'"

SYNTHETIC_CASE = {
    "case_id": "c1",
    "field_code": "LOAN_BAL",
    "quality": "synthetic",
    "expected_definition": "正常贷款余额",
    "expected_processing_logic": "按客户汇总，过滤 LOAN_STATUS = 'NORMAL'",
    "required_tokens": [FILTER_TOKEN],
    "case_family": "filter_semantics",
}

BUSINESS_CASE = {
    **SYNTHETIC_CASE,
    "case_id": "c2",
    "quality": "business",
    "annotator": "bank-expert-01",
    "annotated_at": "2026-10-20T10:00:00+08:00",
    "evidence_positions": [{"unit_id": 11, "quote": "正常类贷款指五级分类为正常的贷款"}],
}

RESULT_MATCH = {
    "case_id": "c1",
    "field_code": "LOAN_BAL",
    "definition": "正常贷款余额",
    "processing_logic": "按客户汇总，过滤 LOAN_STATUS = 'NORMAL'",
    "supported_claim_count": 2,
    "claim_count": 2,
}


def test_synthetic_only_dataset_never_reports_business_accuracy():
    report = evaluate([SYNTHETIC_CASE], [RESULT_MATCH], dataset_version="dev-set")
    assert report["metric_version"] == METRIC_VERSION
    assert report["synthetic_consistency"]["definition_exact_rate"] == 1.0
    assert report["business_accuracy"]["status"] == "N/A"
    assert "独立业务标注" in report["business_accuracy"]["reason"]
    assert report["verdict"] == "UNVERIFIED"


def test_business_case_with_full_metadata_is_measured():
    report = evaluate([BUSINESS_CASE], [{**RESULT_MATCH, "case_id": "c2"}], dataset_version="biz-set")
    assert report["metadata_issues"] == []
    assert report["business_accuracy"]["status"] == "BUSINESS_MEASURED"
    assert report["business_accuracy"]["definition_exact_rate"] == 1.0
    assert report["verdict"] == "BUSINESS_VERIFIED"


def test_missing_annotator_keeps_business_metrics_unavailable():
    broken = {key: value for key, value in BUSINESS_CASE.items() if key != "annotator"}
    report = evaluate([broken], [{**RESULT_MATCH, "case_id": "c2"}])
    assert report["business_accuracy"]["status"] == "N/A"
    assert any("annotator" in issue for issue in report["metadata_issues"])
    assert report["verdict"] == "UNVERIFIED"


def test_missing_denominator_is_null_not_zero():
    no_tokens = {**SYNTHETIC_CASE, "required_tokens": []}
    no_claims = {**RESULT_MATCH, "claim_count": 0, "supported_claim_count": 0}
    report = evaluate([no_tokens], [no_claims])
    assert report["synthetic_consistency"]["key_rule_recall"] is None
    assert report["synthetic_consistency"]["evidence_support_rate"] is None
    assert report["cases"][0]["key_rule_recall"] is None


def test_missing_filter_rule_lowers_key_rule_recall():
    wrong = {**RESULT_MATCH, "processing_logic": "按客户汇总全部贷款"}
    report = evaluate([SYNTHETIC_CASE], [wrong])
    assert report["cases"][0]["key_rule_recall"] == 0.0
    assert report["synthetic_consistency"]["key_rule_recall"] == 0.0
    assert report["synthetic_consistency"]["manual_edit_rate"] == 1.0


def test_unexecuted_family_is_not_counted_as_pass():
    report = evaluate([SYNTHETIC_CASE], [RESULT_MATCH], executed_families=["other_family"])
    assert report["case_families"]["filter_semantics"]["status"] == "not_run"


def test_missing_result_is_not_run_and_excluded_from_rates():
    report = evaluate([SYNTHETIC_CASE], [])
    assert report["cases"][0]["scored"] is False
    assert "not_run" in report["cases"][0]["reason"]
    assert report["synthetic_consistency"]["definition_exact_rate"] is None


def test_manual_effort_excludes_approval_and_system_wait():
    summary = summarize_timing([
        TimingRecord.from_mapping({"case_id": "c1", "phases_ms": {
            "reading": 60000, "editing": 90000, "verifying": 30000,
            "approval_wait": 600000, "system_wait": 120000}}),
        TimingRecord.from_mapping({"case_id": "c2", "phases_ms": {"reading": 30000, "editing": 0}}),
    ])
    assert summary["case_count"] == 2
    assert summary["total_effective_ms"] == 210000
    assert summary["effective_ms_per_field"] == 105000.0
    assert summary["wait_ms_per_field"] == 360000.0


def test_dataset_hash_is_stable_and_content_sensitive():
    first = dataset_sha256([SYNTHETIC_CASE])
    assert first == dataset_sha256([SYNTHETIC_CASE])
    changed = dataset_sha256([{**SYNTHETIC_CASE, "expected_definition": "正常类贷款余额"}])
    assert changed != first
