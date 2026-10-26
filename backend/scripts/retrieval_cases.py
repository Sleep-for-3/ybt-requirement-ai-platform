"""Build the retrieval evaluation case set for project 9 (read-only).

Every case carries a *content-based golden predicate* instead of a hard-coded unit
id list.  The evaluator resolves the predicate to unit ids at run time, so the set
stays valid after the knowledge base is re-seeded while the judgement itself
("the unit that documents field E010001") never depends on retrieval scores.

Writes ``backend/scripts/out/retrieval/cases_v1.jsonl``.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models import ProductScenario, TargetField

PROJECT_ID = 9
TARGET_TABLE_ID = 59
OUT = Path(__file__).resolve().parent / "out" / "retrieval" / "cases_v1.jsonl"

# Loan-domain cases stay in the set because those are the only units the current
# corpus actually documents; they give the baseline a non-zero signal.
LOAN_CASES = [
    ("贷款余额的监管口径是什么", ["LOAN_BAL", "贷款余额"], ["余额"]),
    ("贷款状态字段怎么填报", ["LOAN_STATUS", "贷款状态"], ["状态"]),
    ("借据号在监管报送里怎么定义", ["DUEBILL_NO", "借据号"], ["借据"]),
]

CROSS_CASES = [
    ("贷款余额和借据号之间是什么关系", ["LOAN_BAL", "贷款余额", "DUEBILL_NO", "借据号"], ["余额", "借据"]),
    ("贷款余额的监管口径与贷款状态有什么区别", ["LOAN_BAL", "LOAN_STATUS"], ["余额", "状态"]),
    ("一表通客户统一标识怎么填报", ["CUSTOMER_ID", "客户统一标识"], ["标识"]),
    ("普查表里客户 ID 和证件号的关系", ["CUSTOMER_ID", "证件号"], ["客户"]),
    ("贷款余额为负数时怎么处理", ["LOAN_BAL", "贷款余额"], ["余额"]),
    ("借据状态与贷款状态是否需要保持一致", ["DUEBILL_NO", "LOAN_STATUS"], ["状态"]),
]


def template_queries(code: str, name: str) -> list[tuple[str, list[str], list[str]]]:
    return [
        (f"{code}（{name}）的监管口径是什么", [code, name], [name]),
        (f"{name}这个字段的来源系统和来源表", [code, name], [name]),
        (f"{name}字段要怎么加工、取数逻辑是什么", [code, name], [name]),
    ]


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    db = SessionLocal()
    try:
        fields = list(db.scalars(
            select(TargetField)
            .where(TargetField.project_id == PROJECT_ID, TargetField.target_table_id == TARGET_TABLE_ID)
            .order_by(TargetField.id)
        ).all())
        scenarios = list(db.scalars(
            select(ProductScenario).where(ProductScenario.project_id == PROJECT_ID).order_by(ProductScenario.id)
        ).all())
        scenario_names = [item.scenario_name for item in scenarios]
        records: list[dict] = []
        for field in fields:
            for index, (query, values, keywords) in enumerate(template_queries(field.field_code, field.field_name)):
                records.append({
                    "case_id": f"{field.field_code}-{index}",
                    "category": ("regulatory", "lineage", "processing")[index],
                    "query": query,
                    "target_field_id": field.id,
                    "scenario_id": None,
                    "golden": {"match": "any", "values": values},
                    "expected_keywords": keywords,
                    "expected_field_code": field.field_code,
                    "source": "t51-field",
                })
            # Scenario-scoped variants make the scenario filter measurable.
            for scenario_name in scenario_names:
                records.append({
                    "case_id": f"{field.field_code}-scenario",
                    "category": "scenario",
                    "query": f"{scenario_name}场景下{field.field_name}的业务口径是什么",
                    "target_field_id": field.id,
                    "scenario_id": None,
                    "golden": {"match": "any", "values": [field.field_code, field.field_name]},
                    "expected_keywords": [field.field_name],
                    "expected_field_code": field.field_code,
                    "source": "t51-scenario",
                })
                break
        for query, values, keywords in LOAN_CASES:
            records.append({
                "case_id": f"loan-{hashlib.sha1(query.encode()).hexdigest()[:8]}",
                "category": "loan",
                "query": query,
                "target_field_id": None,
                "scenario_id": None,
                "golden": {"match": "any", "values": values},
                "expected_keywords": keywords,
                "expected_field_code": None,
                "source": "loan-domain",
            })
        for query, values, keywords in CROSS_CASES:
            records.append({
                "case_id": f"cross-{hashlib.sha1(query.encode()).hexdigest()[:8]}",
                "category": "cross",
                "query": query,
                "target_field_id": None,
                "scenario_id": None,
                "golden": {"match": "any", "values": values},
                "expected_keywords": keywords,
                "expected_field_code": None,
                "source": "cross-field",
            })
    finally:
        db.close()

    with OUT.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    digest = hashlib.sha256(OUT.read_bytes()).hexdigest()
    categories: dict[str, int] = {}
    for record in records:
        categories[record["category"]] = categories.get(record["category"], 0) + 1
    print(json.dumps({
        "cases": len(records),
        "categories": categories,
        "fields": len(fields),
        "scenarios": scenario_names,
        "file": str(OUT),
        "sha256": digest,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
