"""P1-C：黄金集标注元数据与真实性级别。

证明三件事：
1. 历史 ``reviewer_id`` 只有一个字符串不再自动算作“已独立标注”；
2. ``accepted`` 必须能证明独立性（作者/预期作者不同人、reviewed_at、basis），否则加载即报错；
3. 指标带样本量与 ``truth_level``，未执行的案例族显式 ``not_run``，不出现无依据的 100%。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.evaluation.regulatory_golden import (
    DEFAULT_DATASET_PATH,
    GOLDEN_SET_VERSION,
    GoldenSetError,
    dataset_summary,
    evaluate_golden_set,
    load_golden_set,
    load_golden_set_with_meta,
)


def _payload() -> dict:
    return json.loads(DEFAULT_DATASET_PATH.read_text(encoding="utf-8"))


def _write(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "golden.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _patch_case(payload: dict, case_id: str, **annotation) -> None:
    for raw in payload["cases"]:
        if raw["id"] == case_id:
            raw["annotation"] = annotation
            return
    raise AssertionError(f"case {case_id} 不存在")


# ---------------------------------------------------------------- 1. 旧口径不再自动成立


def test_legacy_reviewer_id_alone_is_not_an_independent_label(tmp_path):
    payload = _payload()
    _patch_case(payload, "A01", reviewer_id="bank-expert-01")

    cases, _ = load_golden_set_with_meta(_write(tmp_path, payload))
    case = next(item for item in cases if item.case_id == "A01")
    assert case.annotation.reviewer_id == "bank-expert-01"
    assert case.annotation.status == "draft"
    assert case.annotation.verified is False, "一个字符串不足以证明独立标注"
    summary = dataset_summary(cases)
    assert summary["independent_labeled"] == 0
    assert summary["label_status"] == "UNVERIFIED"
    assert summary["independent_labeled_ratio"]["ratio"] == 0.0


# ---------------------------------------------------------------- 2. accepted 的独立性校验


def test_self_labelled_accepted_case_is_rejected(tmp_path):
    payload = _payload()
    payload["annotation"]["defaults"] = {
        "case_author": "designer-a",
        "expected_author": "designer-b",
    }
    _patch_case(
        payload,
        "A01",
        status="accepted",
        reviewer_id="designer-a",  # 作者本人
        reviewed_at="2026-10-23",
        basis="对照制度条文",
    )
    with pytest.raises(GoldenSetError) as failure:
        load_golden_set_with_meta(_write(tmp_path, payload))
    assert "无法证明独立标注" in str(failure.value)


def test_accepted_case_without_basis_or_date_is_rejected(tmp_path):
    payload = _payload()
    payload["annotation"]["defaults"] = {
        "case_author": "designer-a",
        "expected_author": "designer-b",
    }
    _patch_case(payload, "A02", status="accepted", reviewer_id="expert-c", reviewed_at="2026-10-23")
    with pytest.raises(GoldenSetError) as failure:
        load_golden_set_with_meta(_write(tmp_path, payload))
    assert "缺少 reviewed_at 或 basis" in str(failure.value)

    _patch_case(payload, "A02", status="accepted", reviewer_id="expert-c", basis="复核制度与字段字典")
    with pytest.raises(GoldenSetError) as failure:
        load_golden_set_with_meta(_write(tmp_path, payload))
    assert "缺少 reviewed_at 或 basis" in str(failure.value)


def test_accepted_independent_annotation_is_counted_as_partial_verification(tmp_path):
    payload = _payload()
    payload["annotation"]["defaults"] = {
        "case_author": "designer-a",
        "expected_author": "designer-b",
    }
    _patch_case(
        payload,
        "C01",
        status="accepted",
        reviewer_id="bank-expert-01",
        reviewer_role="监管数据专家",
        reviewed_at="2026-10-23",
        basis="按《XX 监管制度》第 5 条与行内数据字典复核",
    )
    cases, meta = load_golden_set_with_meta(_write(tmp_path, payload))
    case = next(item for item in cases if item.case_id == "C01")
    assert case.annotation.verified is True
    summary = dataset_summary(cases, meta)
    assert summary["independent_labeled"] == 1
    assert summary["label_status"] == "PARTIALLY_VERIFIED"
    assert summary["reviewer_count"] == 1
    assert summary["annotation_status_counts"]["accepted"] == 1
    assert summary["dataset_version"].endswith("+annotation-2026-10-23")
    assert summary["accepted_without_provable_independence"] == []


# ---------------------------------------------------------------- 3. 争议案例


def test_disputed_case_needs_a_note_and_never_counts(tmp_path):
    payload = _payload()
    _patch_case(payload, "B01", status="disputed")
    with pytest.raises(GoldenSetError) as failure:
        load_golden_set_with_meta(_write(tmp_path, payload))
    assert "dispute_note" in str(failure.value)

    _patch_case(payload, "B01", status="disputed", dispute_note="两位专家对唯一键判断不一致，待业务确认")
    cases, _ = load_golden_set_with_meta(_write(tmp_path, payload))
    summary = dataset_summary(cases)
    assert summary["disputed_cases"] == ["B01"]
    assert summary["independent_labeled"] == 0
    assert summary["annotation_status_counts"]["disputed"] == 1


# ---------------------------------------------------------------- 4. 指标真实性级别与 not_run


def test_metrics_carry_truth_level_and_report_not_run_per_family():
    cases = load_golden_set()
    report = evaluate_golden_set(cases)

    for name in ("field_retrieval", "citation", "document", "agent_decision"):
        metric = report["metrics"][name]
        assert metric["status"] == "not_run", f"{name} 未执行必须显式 not_run"
        assert metric["scored_cases"] == 0
        assert metric["truth_level"] == "UNVERIFIED"
    for kind, coverage in report["coverage"].items():
        assert coverage["scored"] == 0 and coverage["not_run"] == coverage["cases"], kind
    assert report["dataset"]["independent_labeled"] == 0
    assert report["dataset"]["label_status"] == "UNVERIFIED"
    assert len(report["not_run_case_ids"]) == len(cases)


def test_only_executed_family_is_scored_and_its_ratio_has_a_denominator():
    cases = load_golden_set()
    citation_cases = [case for case in cases if case.kind == "citation"]
    observations = {case.case_id: {"citations": [], "claim_level": False} for case in citation_cases}
    report = evaluate_golden_set(cases, {"citation": observations})

    assert report["coverage"]["citation"]["scored"] == len(citation_cases)
    assert report["coverage"]["field_retrieval"]["scored"] == 0
    citation = report["metrics"]["citation"]
    assert citation["status"] == "scored"
    assert citation["truth_level"] == "UNVERIFIED", "合成期望一致率不得被写成真实监管准确率"
    assert citation["citation_support_precision"]["denominator"] == 0
    assert citation["citation_support_precision"]["ratio"] is None
    assert report["metrics"]["document"]["status"] == "not_run"


def test_business_golden_set_stays_synthetic_and_unverified():
    cases, meta = load_golden_set_with_meta()
    summary = dataset_summary(cases, meta)
    assert summary["case_count"] == 60
    assert summary["by_family"] == {
        "A_field_semantics": 10,
        "B_multitable_join": 10,
        "C_citation_evidence": 10,
        "D_sql_semantics": 10,
        "E_agent_decision": 10,
        "F_full_delivery": 10,
    }
    assert summary["label_status"] == "UNVERIFIED"
    assert summary["case_authors"] == ["vnext2-synthetic-design-v1"]
    assert GOLDEN_SET_VERSION in summary["dataset_version"]
