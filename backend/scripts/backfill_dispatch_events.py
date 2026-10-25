r"""round 62 一次性回填：为已存在的派工补一条"最近一次处置"事件。

这不是伪造历史：事件内容与时间都取自已有的 `requirement_field_dispatches` 行（同一份事实），
只是让轨迹从历史处置开始连续。脚本可重复执行，已有事件的字段会跳过。
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from sqlalchemy import select  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    RequirementFieldDispatch,
    RequirementFieldDispatchEvent,
)


def main() -> int:
    db = SessionLocal()
    try:
        dispatches = list(db.scalars(select(RequirementFieldDispatch)))
        existing = {
            (row.requirement_id, row.field_id)
            for row in db.scalars(select(RequirementFieldDispatchEvent))
        }
        created = 0
        for row in dispatches:
            key = (row.requirement_id, row.field_id)
            if key in existing:
                continue
            event = RequirementFieldDispatchEvent(
                project_id=row.project_id,
                requirement_id=row.requirement_id,
                field_id=row.field_id,
                owner=row.owner,
                status=row.status,
                note=row.note,
                actor_id=row.created_by,
            )
            if row.updated_at is not None:
                event.created_at = row.updated_at
            db.add(event)
            created += 1
        db.commit()
        print(f"backfilled {created} of {len(dispatches)} dispatches")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
