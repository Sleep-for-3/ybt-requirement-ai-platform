"""标注表导入的确定性测试：可验收的标注才进数据集。"""

import pytest

from app.services.requirement_golden_import import (
    GoldenAnnotationError,
    build_dataset,
    parse_annotation_csv,
)
from app.services.requirement_golden_metrics import evaluate

HEADER = "case_id,field_code,expected_definition,expected_processing_logic,required_tokens,quality,case_family,annotator,reviewer,annotated_at,evidence_positions\n"


def _csv(*lines: str) -> str:
    return HEADER + "".join(line + "\n" for line in lines)


def test_synthetic_rows_are_imported_with_tokens_and_evidence():
    text = _csv(
        "SYN-001,CUST_NO,客户号,取 CUST_NO|保留原值,CUST_NO|原值|去空格,synthetic,mapping,,,,制度A|3|第2条;制度B|7|表1",
    )
    parsed = parse_annotation_csv(text)
    assert parsed["issues"] == []
    assert parsed["dropped"] == []
    case = parsed["cases"][0]
    assert case["required_tokens"] == ["CUST_NO", "原值", "去空格"]
    assert case["evidence_positions"] == [
        {"source": "制度A", "page": 3, "locator": "第2条"},
        {"source": "制度B", "page": 7, "locator": "表1"},
    ]


def test_business_rows_without_independent_annotation_are_rejected_at_import():
    text = _csv(
        "BIZ-001,LOAN_BAL,贷款余额,按余额取数,LOAN_BAL,business,mapping,,,,",
        "BIZ-002,LOAN_BAL2,贷款余额,按余额取数,LOAN_BAL2,business,mapping,张三,,2026-10-20,制度A|3|第2条",
    )
    parsed = parse_annotation_csv(text)
    assert [case["case_id"] for case in parsed["cases"]] == ["BIZ-002"]
    reasons = " ".join(issue for issue in parsed["issues"])
    assert "标注人" in reasons
    assert parsed["dropped"][0]["case_id"] == "BIZ-001"


def test_business_rows_missing_time_or_evidence_are_rejected():
    text = _csv(
        "BIZ-003,LOAN_BAL,贷款余额,按余额取数,,business,mapping,张三,,2026-10-20,制度A|3|第2条",
        "BIZ-004,LOAN_BAL,贷款余额,按余额取数,,business,mapping,张三,,,,制度A|3|第2条",
        "BIZ-005,LOAN_BAL,贷款余额,按余额取数,,business,mapping,张三,,2026-10-20,",
    )
    parsed = parse_annotation_csv(text)
    assert [case["case_id"] for case in parsed["cases"]] == ["BIZ-003"]
    issues = " ".join(parsed["issues"])
    assert "标注时间" in issues and "证据位置" in issues


def test_duplicate_case_id_is_dropped_without_overwriting():
    text = _csv(
        "DUP-001,F1,定义一,逻辑一,,synthetic,mapping,,,,",
        "DUP-001,F2,定义二,逻辑二,,synthetic,mapping,,,,",
    )
    parsed = parse_annotation_csv(text)
    assert [case["field_code"] for case in parsed["cases"]] == ["F1"]
    assert "重复出现" in " ".join(parsed["issues"])


def test_missing_required_columns_fail_loudly():
    with pytest.raises(GoldenAnnotationError) as failure:
        parse_annotation_csv("case_id,expected_definition\nA,B\n")
    assert "field_code" in str(failure.value)
    assert failure.value.missing == ["field_code"]


def test_unknown_columns_are_reported_not_guessed():
    text = "case_id,field_code,口径备注\nSYN-009,F9,随便写\n"
    parsed = parse_annotation_csv(text)
    assert parsed["unknown_columns"] == ["口径备注"]
    assert parsed["cases"][0]["field_code"] == "F9"
    # 未知列不得被当成 expected_definition。
    assert parsed["cases"][0]["expected_definition"] == ""


def test_imported_dataset_feeds_evaluate_and_stays_unverified_without_business_labels():
    text = _csv(
        "SYN-001,CUST_NO,客户号,取 CUST_NO,CUST_NO,synthetic,mapping,,,,",
        "BIZ-001,LOAN_BAL,贷款余额,按余额取数,LOAN_BAL,business,mapping,,,,",  # 缺标注人 → 丢弃
    )
    dataset = build_dataset(text, dataset_version="demo-v1")
    assert dataset["dataset_version"] == "demo-v1"
    assert len(dataset["cases"]) == 1 and dataset["dropped"]
    report = evaluate(dataset["cases"], results=[], timings=[],
                      dataset_version=dataset["dataset_version"])
    assert report["business_accuracy"]["status"] == "N/A"
    assert report["verdict"] == "UNVERIFIED"
    assert report["dataset_sha256"] == dataset["dataset_sha256"]


def test_dataset_version_defaults_to_content_hash():
    text = _csv("SYN-001,F1,,,token,synthetic,mapping,,,,")
    first = build_dataset(text)
    second = build_dataset(text)
    assert first["dataset_version"] == second["dataset_version"]
    assert first["dataset_version"].startswith("annotation-")
    other = build_dataset(_csv("SYN-002,F2,,,token,synthetic,mapping,,,,"))
    assert other["dataset_version"] != first["dataset_version"]
