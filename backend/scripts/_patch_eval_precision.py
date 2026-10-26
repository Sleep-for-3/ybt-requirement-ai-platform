r"""One-off patch: make the retrieval evaluation discriminate by source document.

Round 75. The first baseline resolved "gold" units by ILIKE on field code/name
across *all* seeded documents, so every question had ~10 acceptable units and
every configuration saturated at the same 0.861 recall.  A measurement that
cannot tell keyword from vector from hybrid is not a measurement.

The golden set is now resolved per case category against the document that is
supposed to answer it:
  regulatory  -> ybt-t51-regulatory-20261026 (监管口径)
  processing  -> ybt-t51-script-rules-20261026 (脚本规则)
  lineage     -> ybt-t51-lineage-20261026 (血缘/集市映射)
  scenario    -> ybt-t51-lineage-20261026 (场景口径)
Categories without a mapped document (loan/cross) keep the unfiltered golden.
Precision@5 is reported next to recall so a "return everything" ranking cannot
look good.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def patch(relative: str, replacements: list[tuple[str, str]]) -> None:
    path = ROOT / relative
    with path.open("r", encoding="utf-8", newline="") as handle:
        raw = handle.read()
    text = raw.replace("\r\n", "\n")
    for old, new in replacements:
        if text.count(old) != 1:
            raise SystemExit(f"anchor missing/not unique in {relative}: {old[:120]!r}")
        text = text.replace(old, new)
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(text.replace("\n", "\r\n"))
    print(f"patched {relative}")


patch("scripts/retrieval_eval.py", [
    (
        """def resolve_golden(db, predicate: dict) -> list[int]:
    values = [str(value) for value in predicate.get("values") or [] if value]
    if not values:
        return []""",
        """CATEGORY_DOCUMENTS = {
    "regulatory": ("ybt-t51-regulatory-20261026",),
    "processing": ("ybt-t51-script-rules-20261026",),
    "lineage": ("ybt-t51-lineage-20261026",),
    "scenario": ("ybt-t51-lineage-20261026",),
}


def resolve_golden(db, predicate: dict, category: str | None = None) -> list[int]:
    values = [str(value) for value in predicate.get("values") or [] if value]
    if not values:
        return []
    document_codes = CATEGORY_DOCUMENTS.get(category or "", ())
    if document_codes:
        scoped = _resolve_golden_units(db, values, document_codes)
        if scoped:
            return scoped
    return _resolve_golden_units(db, values, ())


def _resolve_golden_units(db, values: list[str], document_codes: tuple[str, ...]) -> list[int]:""",
    ),
    (
        """    rows = db.execute(
        select(KnowledgeUnit.id)
        .where(
            KnowledgeUnit.enabled.is_(True),
            or_(KnowledgeUnit.project_id == PROJECT_ID, KnowledgeUnit.knowledge_scope == "global"),
            or_(*clauses),
        )
        .order_by(KnowledgeUnit.id)
    ).all()
    return [row[0] for row in rows]""",
        """    query = select(KnowledgeUnit.id).where(
        KnowledgeUnit.enabled.is_(True),
        or_(KnowledgeUnit.project_id == PROJECT_ID, KnowledgeUnit.knowledge_scope == "global"),
        or_(*clauses),
    )
    if document_codes:
        query = query.join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeUnit.document_id).where(
            KnowledgeDocument.logical_code.in_(document_codes))
    rows = db.execute(query.order_by(KnowledgeUnit.id)).all()
    return [row[0] for row in rows]""",
    ),
    (
        """        golden = {case["case_id"]: set(resolve_golden(db, case.get("golden") or {})) for case in cases}""",
        """        golden = {case["case_id"]: set(resolve_golden(db, case.get("golden") or {}, case.get("category")))
                  for case in cases}""",
    ),
    (
        """    recall5: float = 0.0
    recall10: float = 0.0""",
        """    recall5: float = 0.0
    recall10: float = 0.0
    precision5: float = 0.0""",
    ),
    (
        """                    bucket = categories.setdefault(case["category"], {"cases": 0, "hit5": 0.0, "hit10": 0.0, "mrr": 0.0, "ndcg": 0.0})""",
        """                    bucket = categories.setdefault(case["category"], {"cases": 0, "hit5": 0.0, "hit10": 0.0,
                        "mrr": 0.0, "ndcg": 0.0, "precision5": 0.0})""",
    ),
    (
        """                    row.recall5 += hit5
                    row.recall10 += hit10
                    row.mrr10 += mrr
                    row.ndcg10 += ndcg""",
        """                    precision5 = (sum(1 for unit_id in ranked[:5] if unit_id in ids) / max(1, min(5, len(ranked))))
                    row.recall5 += hit5
                    row.recall10 += hit10
                    row.precision5 += precision5
                    row.mrr10 += mrr
                    row.ndcg10 += ndcg
                    bucket["precision5"] += precision5""",
    ),
    (
        """                row.recall5 = round(row.recall5 / denominator, 4)
                row.recall10 = round(row.recall10 / denominator, 4)""",
        """                row.recall5 = round(row.recall5 / denominator, 4)
                row.recall10 = round(row.recall10 / denominator, 4)
                row.precision5 = round(row.precision5 / denominator, 4)""",
    ),
    (
        """                    bucket.update({
                        "recall5": round(bucket["hit5"] / count, 3),
                        "recall10": round(bucket["hit10"] / count, 3),""",
        """                    bucket.update({
                        "recall5": round(bucket["hit5"] / count, 3),
                        "recall10": round(bucket["hit10"] / count, 3),
                        "precision5": round(bucket["precision5"] / count, 3),""",
    ),
    (
        """                    for key in ("hit5", "hit10", "mrr", "ndcg"):
                        bucket.pop(key, None)""",
        """                    for key in ("hit5", "hit10", "mrr", "ndcg", "precision5"):
                        bucket.pop(key, None)""",
    ),
    (
        """            f"| {row.config} | {row.recall5:.3f} | {row.recall10:.3f} | {row.mrr10:.3f} | {row.ndcg10:.3f} | \"""",
        """            f"| {row.config} | {row.recall5:.3f} | {row.recall10:.3f} | {row.precision5:.3f} | {row.mrr10:.3f} | {row.ndcg10:.3f} | \"""",
    ),
])

print("done")
