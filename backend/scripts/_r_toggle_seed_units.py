r"""Toggle the M1 seeded knowledge units on/off for A/B retrieval evaluation.

The retrieval pipeline drops disabled units (``hybrid_retriever``: ``if not
historical and not unit.enabled: continue``), so flipping ``enabled`` gives an
honest "corpus before M1" vs "corpus after M1" comparison without touching code.

Usage::

    python scripts/_r_toggle_seed_units.py --state off
    python scripts/_r_toggle_seed_units.py --state on
"""

from __future__ import annotations

import argparse

from sqlalchemy import func, select, update

from app.core.database import SessionLocal
from app.models import KnowledgeUnit

SEEDED_DOCUMENT_IDS = (4, 5, 6)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", choices=("on", "off"), required=True)
    args = parser.parse_args()
    enabled = args.state == "on"
    db = SessionLocal()
    try:
        result = db.execute(
            update(KnowledgeUnit)
            .where(KnowledgeUnit.document_id.in_(SEEDED_DOCUMENT_IDS))
            .values(enabled=enabled)
        )
        db.commit()
        rows = db.execute(
            select(KnowledgeUnit.document_id, func.count())
            .where(KnowledgeUnit.project_id == 9)
            .group_by(KnowledgeUnit.document_id)
        ).all()
        total = db.scalar(
            select(func.count()).select_from(KnowledgeUnit).where(
                KnowledgeUnit.project_id == 9, KnowledgeUnit.enabled.is_(True)
            )
        )
        print({
            "state": args.state,
            "updated_rows": result.rowcount,
            "enabled_units": total,
            "by_document": {int(doc): int(count) for doc, count in rows},
        })
    finally:
        db.close()


if __name__ == "__main__":
    main()
