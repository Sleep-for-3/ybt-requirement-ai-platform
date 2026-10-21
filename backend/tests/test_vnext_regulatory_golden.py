"""阶段1 独立业务黄金集与质量指标的回归测试。

这些测试验证的是"评测口径与数据结构"本身：
- 黄金集必须覆盖 6 大族、≥60 例、id 唯一、标签合法；
- 每个比例指标必须同时给出分子/分母，分母为 0 时 ratio 为 None；
- 引用级判定绝不能计入主张级支持；
- 没有观测结果的用例只能进入 not_run，不得被当成通过。
"""

from __future__ import annotations

import json

import pytest

from app.services.evaluation.regulatory_golden import (
    DEFAULT_DATASET_PATH,
    FAMILIES,
    GOLDEN_SET_VERSION,
    GoldenSetError,
    agent_decision_metrics,
    citation_metrics,
    dataset_summary,
    document_metrics,
    evaluate_golden_set,
    field_retrieval_metrics,
    load_golden_set,
)


def test_golden_set_has_required_coverage() -> None:
    cases = load_golden_set()
    assert len(cases) >= 60
    summary = dataset_summary(cases)
    assert summary["case_count"] == len(cases)
    for family in FAMILIES:
        assert summary["by_family"][family] >= 8, family
    assert summary["label_status"] == "UNVERIFIED"
    assert summary["independent_labeled"] == 0
    assert summary["version"] == GOLDEN_SET_VERSION


def test_golden_set_rejects_duplicate_ids(tmp_path) -> None:
    payload = json.loads(DEFAULT_DATASET_PATH.read_text(encoding="utf-8"))
    payload["cases"][1]["id"] = payload["cases"][0]["id"]
    path = tmp_path / "dup.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(GoldenSetError, match="重复"):
        load_golden_set(path)


def test_golden_set_rejects_missing_family_coverage(tmp_path) -> None:
    payload = json.loads(DEFAULT_DATASET_PATH.read_text(encoding="utf-8"))
    payload["cases"] = [case for case in payload["cases"] if case["family"] != "D_sql_semantics"]
    path = tmp_path / "missing.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(GoldenSetError):
        load_golden_set(path)


def test_ratio_never_fabricates_value_without_samples() -> None:
    cases = load_golden_set()
    metrics = field_retrieval_metrics(cases, {})
    assert metrics["status"] == "not_run"
    assert metrics["recall_at_k"]["ratio"] is None
    assert metrics["recall_at_k"]["denominator"] == 0


def test_field_retrieval_metrics_math() -> None:
    cases = load_golden_set()
    # 找两个 field_retrieval 用例做手工计算
    eligible = [case for case in cases if case.kind == "field_retrieval"][:2]
    first, second = eligible
    first_correct = first.expected["correct_candidates"][0]
    second_correct = second.expected["correct_candidates"][0]
    observed = {
        first.case_id: {"ranked": [first_correct], "truncated": False, "model_calls": 3},
        # 正确答案排第 3 位
        second.case_id: {
            "ranked": ["x1", "x2", second_correct],
            "truncated": True,
            "model_calls": 5,
        },
    }
    metrics = field_retrieval_metrics(cases, observed, k=5)
    assert metrics["scored_cases"] == 2
    assert metrics["top1_accuracy"]["numerator"] == 1
    assert metrics["top3_accuracy"]["numerator"] == 2
    assert metrics["recall_at_k"]["numerator"] == 2
    assert metrics["budget_truncation_rate"]["numerator"] == 1
    assert metrics["model_calls_total"] == 8
    assert round(metrics["mrr"]["numerator"] / metrics["mrr"]["denominator"], 4) == round((1 + 1 / 3) / 2, 4)


def test_citation_metrics_separate_citation_and_claim_level() -> None:
    cases = load_golden_set()
    supported_case = next(c for c in cases if c.case_id == "C01")
    unsupported_case = next(c for c in cases if c.case_id == "C02")
    observed = {
        supported_case.case_id: {
            "citations": [{"citation_id": "c1", "verdict": "supported"}],
            "claim_level": False,
            "claims": [{"claim_id": "m1", "verdict": "supported"}],  # 引用级判定，不得计入主张级
        },
        unsupported_case.case_id: {
            "citations": [{"citation_id": "c1", "verdict": "unsupported"}],
            "claim_level": False,
        },
    }
    metrics = citation_metrics(cases, observed)
    assert metrics["scored_cases"] == 2
    assert metrics["citation_support_precision"]["numerator"] == 1
    assert metrics["citation_support_precision"]["denominator"] == 1
    assert metrics["unsupported_detection_rate"]["numerator"] == 1
    assert metrics["unsupported_detection_rate"]["denominator"] == 1
    assert metrics["claim_judged_cases"] == 0
    assert metrics["claim_supported"] == 0, "引用级判定不得被记成主张级支持"
    assert metrics["claim_unsupported"] == 0


def test_claim_level_metrics_require_claim_level_flag() -> None:
    cases = load_golden_set()
    case = next(c for c in cases if c.case_id == "C01")
    observed = {
        case.case_id: {
            "citations": [{"citation_id": "c1", "verdict": "supported"}],
            "claim_level": True,
            "claims": [
                {"claim_id": "m1", "verdict": "supported"},
                {"claim_id": "m2", "verdict": "unknown"},
            ],
        }
    }
    metrics = citation_metrics(cases, observed)
    assert metrics["claim_judged_cases"] == 1
    assert metrics["claim_supported"] == 1
    assert metrics["claim_unknown"] == 1
    assert metrics["claim_supported"] <= metrics["claim_judged_cases"] * 2


def test_document_metrics_ratio_bounds() -> None:
    cases = load_golden_set()
    case = next(c for c in cases if c.case_id == "F01")
    observed = {
        case.case_id: {
            "required_fields_present": ["来源", "关联键", "证据"],
            "required_fields_total": 3,
            "source_paths_verified": 2,
            "source_paths_total": 2,
            "claims_total": 4,
            "claims_with_evidence": 3,
            "unsupported_facts": 1,
            "facts_total": 10,
            "gate_state": "deliverable",
        }
    }
    metrics = document_metrics(cases, observed)
    assert metrics["required_field_coverage"]["ratio"] == 1.0
    assert metrics["verified_source_path_ratio"]["ratio"] == 1.0
    assert metrics["unsupported_fact_rate"]["ratio"] == 0.1
    assert metrics["delivery_gate_accuracy"]["ratio"] == 1.0


def test_metrics_reject_numerator_above_denominator() -> None:
    from app.services.evaluation.regulatory_golden import _ratio

    with pytest.raises(ValueError, match="比例必须"):
        _ratio(5, 3, "bad_metric")


def test_agent_decision_metrics_detect_unsafe_release() -> None:
    cases = load_golden_set()
    blocking = next(c for c in cases if c.case_id == "E02")
    ok_case = next(c for c in cases if c.case_id == "E01")
    observed = {
        blocking.case_id: {"decision": "continue"},  # 错误放行
        ok_case.case_id: {"decision": "continue"},
    }
    metrics = agent_decision_metrics(cases, observed)
    assert metrics["scored_cases"] == 2
    assert metrics["unsafe_release_rate"]["numerator"] == 1
    assert metrics["decision_accuracy"]["numerator"] == 1


def test_evaluate_golden_set_marks_unobserved_cases_not_run() -> None:
    cases = load_golden_set()
    report = evaluate_golden_set(cases, {})
    assert set(report["not_run_case_ids"]) == {case.case_id for case in cases}
    assert report["metrics"]["field_retrieval"]["status"] == "not_run"
    assert report["dataset"]["label_status"] == "UNVERIFIED"
