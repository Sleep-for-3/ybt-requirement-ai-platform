"""G2 smoke probe: expansion on/off for one processing and one scenario query."""

from __future__ import annotations

import sys

from app.core.database import SessionLocal
from app.core.settings import get_settings
from app.models import KnowledgeUnit, Project
from app.services.retrieval.hybrid_retriever import HybridRetriever
from app.services.retrieval.query_expansion import expand_query

PROJECT_ID = 9

QUERIES = [
    ("processing", "E010005 科目类型 的加工逻辑是什么"),
    ("scenario", "借记卡场景下 E010001 产品ID 的业务口径是什么"),
]


def run(db, query: str, expansion: bool):
    settings = get_settings()
    previous = settings.query_expansion_enabled
    settings.query_expansion_enabled = expansion
    try:
        log, items = HybridRetriever(db).search(PROJECT_ID, query, top_k=5, commit=False)
        rows = []
        for item in items:
            unit = db.get(KnowledgeUnit, item["knowledge_unit_id"])
            rows.append(
                {
                    "id": item["knowledge_unit_id"],
                    "score": round(item.get("final_score") or 0.0, 4),
                    "doc": unit.document_id if unit else None,
                    "field": unit.target_field_code if unit else None,
                    "scenario": unit.scenario_id if unit else None,
                    "title": (unit.title or "")[:40] if unit else "",
                }
            )
        return {"variants": expand_query(query), "rows": rows}, log
    finally:
        settings.query_expansion_enabled = previous


def main() -> int:
    db = SessionLocal()
    try:
        project = db.get(Project, PROJECT_ID)
        print("project:", project.name if project else None)
        for label, query in QUERIES:
            print(f"\n=== {label}: {query}")
            for expansion in (False, True):
                result, log = run(db, query, expansion)
                print(f"-- expansion={expansion} variants={len(result['variants'])}")
                for row in result["rows"]:
                    print("   ", row)
                db.rollback()
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
