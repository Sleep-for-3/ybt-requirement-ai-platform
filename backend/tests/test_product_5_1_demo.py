from __future__ import annotations

import json
import sqlite3
import sys
from datetime import date
from pathlib import Path

import httpx
import pytest
from openpyxl import Workbook


ROOT = Path(__file__).resolve().parents[2]
DEMO_SCRIPT_ROOT = ROOT / "scripts" / "demo"
if str(DEMO_SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(DEMO_SCRIPT_ROOT))

from build_product_5_1_demo import build_demo  # noqa: E402
from bootstrap_product_5_1_platform import Api, _wait_for_background_job  # noqa: E402
from product_5_1_common import (  # noqa: E402
    DEMO_PROJECT_NAME,
    SOURCE_DATABASES,
    TARGET_COLUMN_BY_CODE,
    TARGET_TABLE_NAME,
    parse_regulatory_workbook,
)
from run_product_5_1_verification import _context_summary, _workspace_summary  # noqa: E402


FIELD_NAMES = {
    "E010001": "产品ID",
    "E010002": "机构ID",
    "E010003": "产品名称",
    "E010004": "产品编号",
    "E010005": "科目类型",
    "E010007": "产品类别",
    "E010008": "自营标识",
    "E010009": "产品币种",
    "E010010": "产品期限",
    "E010011": "产品成立日期",
    "E010012": "产品到期日期",
    "E010013": "产品期次",
    "E010014": "利率类型",
    "E010015": "产品状态代码",
    "E010018": "代客产品所属机构名称",
    "E010016": "备注",
    "E010017": "采集日期",
}


def _write_regulatory_workbook(path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["数据表名称", None, TARGET_TABLE_NAME])
    sheet.append(["采集范围", None, "测试监管采集范围"])
    sheet.append(["一表通报送范围确认", None, "测试报送范围确认"])
    sheet.append(
        [
            "数据项编码",
            "数据项名称",
            "数据类别",
            "数据格式",
            "字段业务定义（监管原始口径）",
            "字段业务定义（监管定义细化）",
        ]
    )
    for code in TARGET_COLUMN_BY_CODE:
        sheet.append(
            [
                code,
                FIELD_NAMES[code],
                "代码类",
                "anc",
                f"{code}监管原始口径",
                f"{code}监管定义细化",
            ]
        )
    sheet.append(["补充字段", "停用日期", "状态02且停用日期为空时使用采集日期"])
    sheet.append(["补充字段", "产品归属部门"])
    workbook.save(path)


def test_regulatory_workbook_contract_preserves_regulatory_language(tmp_path: Path) -> None:
    workbook_path = tmp_path / "product_5_1.xlsx"
    _write_regulatory_workbook(workbook_path)

    parsed = parse_regulatory_workbook(workbook_path)

    assert parsed["table_name"] == TARGET_TABLE_NAME
    assert parsed["collection_scope"] == "测试监管采集范围"
    assert {item["field_code"] for item in parsed["fields"]} == set(TARGET_COLUMN_BY_CODE)
    product_term = next(item for item in parsed["fields"] if item["field_code"] == "E010010")
    assert product_term["regulatory_original_definition"] == "E010010监管原始口径"
    assert product_term["regulatory_refined_definition"] == "E010010监管定义细化"
    assert parsed["supplemental_fields"][0] == {
        "field_name": "停用日期",
        "rule": "状态02且停用日期为空时使用采集日期",
    }


def test_demo_build_creates_deterministic_bank_scale_sources_and_mart(tmp_path: Path) -> None:
    workbook_path = tmp_path / "product_5_1.xlsx"
    runtime_root = tmp_path / "runtime"
    _write_regulatory_workbook(workbook_path)

    summary = build_demo(workbook_path, runtime_root)

    assert summary["demo_seed"] == 20260830
    assert summary["product_count"] == 1280
    assert summary["domain_counts"] == {
        "card": 80,
        "deposit": 340,
        "fund": 90,
        "insurance": 60,
        "loan": 370,
        "treasury": 180,
        "wealth": 160,
    }
    assert 0.03 <= summary["controlled_exception_ratio"] <= 0.05
    assert set(summary["databases"]) == set(SOURCE_DATABASES)
    assert all((runtime_root / file_name).is_file() for file_name in SOURCE_DATABASES.values())
    assert summary["databases"]["product_center"]["tables"]["product_master"] == 1280
    assert summary["databases"]["regulatory_mart"]["tables"] == {
        "mart_product_attribute": 1280,
        "mart_product_channel": 1280,
        "mart_product_hierarchy": 1280,
        "mart_product_lifecycle": 1280,
        "mart_product_master": 1280,
        "mart_product_partner": 142,
        "mart_product_policy": 1280,
        "mart_product_quality_issue": 50,
        "mart_product_region": 1280,
        "mart_product_regulatory_classification": 1280,
        "mart_product_scope": 1280,
        "mart_product_snapshot": 2560,
        "mart_source_record_reference": 2480,
        "ybt_5_1_product_business_basic": 1280,
    }

    with sqlite3.connect(runtime_root / SOURCE_DATABASES["regulatory_mart"]) as db:
        continuous = db.execute(
            "SELECT product_term, maturity_date FROM mart_product_master "
            "WHERE product_term = 0 LIMIT 1"
        ).fetchone()
        one_off = db.execute(
            "SELECT product_term, establishment_date, maturity_date "
            "FROM mart_product_master WHERE product_term > 0 AND maturity_date IS NOT NULL LIMIT 1"
        ).fetchone()
        stopped_without_date = db.execute(
            "SELECT product_status_code, stop_date, collection_date "
            "FROM mart_product_master WHERE product_id = 'YBTDEP00000021'"
        ).fetchone()
        agency_counts = db.execute(
            "SELECT "
            "SUM(CASE WHEN proprietary_flag = '02' AND agency_institution_name IS NOT NULL THEN 1 ELSE 0 END), "
            "SUM(CASE WHEN proprietary_flag != '02' AND agency_institution_name IS NOT NULL THEN 1 ELSE 0 END) "
            "FROM ybt_5_1_product_business_basic"
        ).fetchone()

    assert continuous == (0, "9999-12-31")
    assert one_off[0] == (date.fromisoformat(one_off[2]) - date.fromisoformat(one_off[1])).days
    assert stopped_without_date == ("02", "2026-08-31", "2026-08-31")
    assert agency_counts[0] > 0
    assert agency_counts[1] == 0


def test_demo_build_is_repeatable_at_row_level(tmp_path: Path) -> None:
    workbook_path = tmp_path / "product_5_1.xlsx"
    _write_regulatory_workbook(workbook_path)
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"

    build_demo(workbook_path, first_root)
    build_demo(workbook_path, second_root)

    def target_rows(root: Path) -> list[tuple]:
        with sqlite3.connect(root / SOURCE_DATABASES["regulatory_mart"]) as db:
            return db.execute(
                "SELECT * FROM ybt_5_1_product_business_basic ORDER BY product_id"
            ).fetchall()

    assert target_rows(first_root) == target_rows(second_root)
    first_summary = json.loads((first_root / "build_summary.json").read_text(encoding="utf-8"))
    second_summary = json.loads((second_root / "build_summary.json").read_text(encoding="utf-8"))
    for database in SOURCE_DATABASES:
        first_summary["databases"][database].pop("sha256")
        second_summary["databases"][database].pop("sha256")
    assert first_summary == second_summary


def test_bootstrap_and_build_never_read_agent_evaluation_oracle() -> None:
    for path in (
        DEMO_SCRIPT_ROOT / "build_product_5_1_demo.py",
        DEMO_SCRIPT_ROOT / "bootstrap_product_5_1_platform.py",
        DEMO_SCRIPT_ROOT / "product_5_1_common.py",
    ):
        source = path.read_text(encoding="utf-8")
        assert "golden_mapping.json" not in source


def test_bootstrap_api_retries_rate_limited_requests() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, headers={"Retry-After": "0"}, json={"detail": "Rate limit exceeded"})
        return httpx.Response(200, json={"status": "ok"})

    api = Api("http://demo.invalid/api", transport=httpx.MockTransport(handler))
    try:
        assert api.get("/health/ready") == {"status": "ok"}
    finally:
        api.close()
    assert attempts == 2


def test_bootstrap_waits_for_production_background_job() -> None:
    statuses = iter(
        [
            {"id": 73, "status": "running", "progress": 50},
            {"id": 73, "status": "completed", "progress": 100},
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/jobs/73"
        return httpx.Response(200, json=next(statuses))

    api = Api("http://demo.invalid/api", transport=httpx.MockTransport(handler))
    try:
        result = _wait_for_background_job(
            api,
            {"id": 73, "status": "queued", "progress": 0},
            timeout_seconds=1,
            poll_seconds=0,
        )
    finally:
        api.close()

    assert result == {"id": 73, "status": "completed", "progress": 100}


def test_verification_summaries_follow_real_api_contract() -> None:
    context = {
        "semantic": [{"id": 1}],
        "regulatory": [{"id": 2}],
        "metadata": [{"id": 3}],
        "candidates": [{"id": 4}],
        "mappings": [{"id": 5}],
        "lineage": [{"id": 6}],
        "knowledge_evidence": [{"id": 7}],
        "historical": [{"id": 8}],
        "quality": [{"id": 9}],
        "conflicts": [{"id": 10}],
        "open_questions": ["question"],
        "build_metadata": {"fact_count": 9, "context_hash": "abc"},
    }

    summary = _context_summary(context)

    assert summary["fact_count"] == 9
    assert summary["semantic"] == 1
    assert summary["knowledge_evidence"] == 1
    assert summary["open_questions"] == 1
    assert summary["context_hash"] == "abc"
    assert _workspace_summary({"records": [{"id": 1}, {"id": 2}]})["field_rows"] == 2


def test_reset_requires_exact_project_confirmation_and_only_plans_known_runtime_files(tmp_path: Path) -> None:
    from reset_product_5_1_demo import build_reset_plan, validate_execute_confirmation

    runtime_root = tmp_path / "product_5_1"
    runtime_root.mkdir()
    known = runtime_root / SOURCE_DATABASES["product_center"]
    unknown = runtime_root / "do-not-delete.txt"
    known.write_text("demo", encoding="utf-8")
    unknown.write_text("user", encoding="utf-8")

    plan = build_reset_plan(runtime_root)

    assert plan["runtime_files"] == [str(known.resolve())]
    assert str(unknown.resolve()) in plan["retained_unknown_files"]
    assert validate_execute_confirmation(DEMO_PROJECT_NAME) is None
    with pytest.raises(ValueError, match="exact demo project name"):
        validate_execute_confirmation("wrong-project")
