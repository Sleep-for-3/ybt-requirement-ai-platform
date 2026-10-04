"""N03 acceptance: submission vs edit must serialize on the mapping row (real PostgreSQL).

The review found that the submission entry (start_workflow -> _snapshot_target) read the mapping
with ``db.get`` and no row lock, while the edit/delete paths take ``SELECT ... FOR UPDATE``.  A
submission could therefore snapshot a row another transaction was still editing and both could
commit.  Both entries now take the same row lock (``with_for_update`` + ``populate_existing``).

This script proves the two directions on real PostgreSQL with two independent connections
(SQLite ignores FOR UPDATE, so the unit tests cannot):

  A) submission holds the lock first -> the edit waits for the submission commit, then is
     refused with the review-in-progress conflict (no silent write);
  B) edit holds the lock first -> the submission waits, then reviews the *committed* revision
     (the snapshot sees the new content, not the stale pre-state).

Safety: dedicated throw-away database (default ``ybt_upgrade_w02_iso``, created by the sibling
scripts), the N13 isolated-target guard runs before any DDL, credentials are never printed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[3] / "backend"
sys.path.insert(0, str(BACKEND))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", default="ybt_upgrade_w02_iso")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5432)
    parser.add_argument("--user", default="postgres")
    parser.add_argument("--allow-reset-existing", action="store_true",
                        help="N13: allow resetting an existing non-empty isolated DB (the business DB is always refused)")
    args = parser.parse_args()

    password = os.environ.get("PGPASSWORD") or ""
    if not password:
        print(json.dumps({"ok": False, "error": "PGPASSWORD is not set"}, ensure_ascii=False))
        return 2

    # N13: refuse any target that is not this run's throw-away isolated database, before any DDL.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "2026-10-03"))
    from isolated_pg_guard import require_isolated_target

    require_isolated_target(
        args.database,
        script="n03_postgres_submission_edit_race.py",
        host=args.host,
        port=args.port,
        user=args.user,
        password=password,
        allow_existing=args.allow_reset_existing,
    )

    url = f"postgresql+psycopg://{args.user}:{password}@{args.host}:{args.port}/{args.database}"
    os.environ["DATABASE_URL"] = url

    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker

    from app.core.database import Base
    from app.models import Institution, MartField, MartTable, Project, SourceToMartMapping, User
    from app.services.governance.double_layer_review import (
        MappingGenerationNotEditable,
        ensure_double_layer_mapping_writable,
    )
    from app.services.governance.workflow import start_workflow

    engine = create_engine(url, pool_size=10, max_overflow=10)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    with factory() as db:
        institution = Institution(institution_code="N03ISO", institution_name="N03", institution_type="bank", status="active")
        db.add(institution); db.flush()
        user = User(username="n03_iso_user", display_name="N03", status="active")
        db.add(user); db.flush()
        user_id = int(user.id)
        project = Project(name="N03 iso", institution_id=institution.id)
        db.add(project); db.flush()
        mart_table = MartTable(project_id=project.id, table_code="MART_N03", table_name="集市表")
        db.add(mart_table); db.flush()
        mart_field = MartField(project_id=project.id, mart_table_id=mart_table.id, field_code="F1", field_name="字段1")
        db.add(mart_field); db.flush()

        def approved_mapping(content: str) -> int:
            mapping = SourceToMartMapping(project_id=project.id, mart_field_id=mart_field.id,
                                          final_content=content, mapping_status="approved")
            db.add(mapping); db.flush()
            return int(mapping.id)

        mapping_a = approved_mapping("已批准口径-A")
        mapping_b = approved_mapping("已批准口径-B")
        project_id = int(project.id)
        db.commit()

    errors: list[str] = []
    result: dict[str, object] = {}

    # ------------------------------------------------------------------ scenario A
    # Submission acquires the row lock first; the edit must wait for its commit and then be
    # refused because a review is now in progress.
    sub_locked = threading.Event()
    edit_attempted = threading.Event()
    allow_sub_commit = threading.Event()
    sub_events: dict[str, float] = {}

    def submission_first() -> None:
        try:
            with factory() as db:
                start_workflow(
                    db, project_id=project_id, workflow_key="double_layer_mapping_review",
                    target_type="source_to_mart", target_id=mapping_a,
                    created_by=user_id, assignments={}, commit=False,
                )
                sub_locked.set()            # row lock held, not yet committed
                allow_sub_commit.wait(30)
                db.commit()
                sub_events["committed_at"] = time.monotonic()
        except Exception as exc:  # noqa: BLE001
            errors.append("submission_first: " + type(exc).__name__ + ": " + str(exc)[:160])
            sub_locked.set()

    def edit_after_submission() -> None:
        try:
            sub_locked.wait(30)
            edit_attempted.set()
            with factory() as db:
                row = db.scalars(
                    select(SourceToMartMapping).where(SourceToMartMapping.id == mapping_a)
                    .with_for_update().execution_options(populate_existing=True)
                ).one()
                sub_events["edit_acquired_at"] = time.monotonic()
                try:
                    ensure_double_layer_mapping_writable(
                        db, "source_to_mart", row, updates={"final_content": "并发编辑-A"}
                    )
                    sub_events["edit_outcome"] = "unexpected-allowed"
                except MappingGenerationNotEditable as exc:
                    sub_events["edit_outcome"] = exc.reason_code
                db.rollback()
        except Exception as exc:  # noqa: BLE001
            errors.append("edit_after_submission: " + type(exc).__name__ + ": " + str(exc)[:160])

    thread_sub = threading.Thread(target=submission_first)
    thread_edit = threading.Thread(target=edit_after_submission)
    thread_sub.start()
    sub_locked.wait(30)
    thread_edit.start()
    edit_attempted.wait(30)
    time.sleep(1.0)                     # let the edit block on the row lock
    allow_sub_commit.set()
    thread_sub.join(timeout=60)
    thread_edit.join(timeout=60)

    with factory() as db:
        final_a = db.get(SourceToMartMapping, mapping_a)
        final_a_content = final_a.final_content
        from app.models import WorkflowInstance
        instance_a = db.scalar(select(WorkflowInstance).where(
            WorkflowInstance.target_type == "source_to_mart", WorkflowInstance.target_id == mapping_a))

    scenario_a = {
        "edit_outcome": sub_events.get("edit_outcome"),
        "content_unchanged": final_a_content == "已批准口径-A",
        "edit_waited_for_submission": (
            sub_events.get("edit_acquired_at", 0) >= sub_events.get("committed_at", 10**9)
        ),
        "review_instance_status": instance_a.status if instance_a else None,
        "wait_ms": round((sub_events.get("edit_acquired_at", 0) - sub_events.get("committed_at", 0)) * 1000, 1),
    }

    # ------------------------------------------------------------------ scenario B
    # Edit acquires the row lock first (re-opening a new draft); the submission must wait and
    # then snapshot the committed revision, not the stale pre-state.
    edit2_locked = threading.Event()
    sub2_attempted = threading.Event()
    allow_edit2_commit = threading.Event()
    edit_events: dict[str, object] = {}

    def edit_first() -> None:
        try:
            with factory() as db:
                row = db.scalars(
                    select(SourceToMartMapping).where(SourceToMartMapping.id == mapping_b)
                    .with_for_update().execution_options(populate_existing=True)
                ).one()
                ensured = ensure_double_layer_mapping_writable(
                    db, "source_to_mart", row, updates={"mapping_status": "draft", "final_content": "编辑后内容-B"}
                )
                row.mapping_status = "draft"
                row.final_content = "编辑后内容-B"
                row.reviewed_by = None
                row.reviewed_at = None
                edit_events["reopened"] = bool(ensured)
                edit2_locked.set()          # row lock held, not yet committed
                allow_edit2_commit.wait(30)
                db.commit()
                edit_events["committed_at"] = time.monotonic()
        except Exception as exc:  # noqa: BLE001
            errors.append("edit_first: " + type(exc).__name__ + ": " + str(exc)[:160])
            edit2_locked.set()

    def submission_after_edit() -> None:
        try:
            edit2_locked.wait(30)
            sub2_attempted.set()
            with factory() as db:
                start_workflow(
                    db, project_id=project_id, workflow_key="double_layer_mapping_review",
                    target_type="source_to_mart", target_id=mapping_b,
                    created_by=user_id, assignments={}, commit=False,
                )
                edit_events["sub_acquired_at"] = time.monotonic()   # unblocked after edit commit
                # The submission transaction must see the revision the edit just committed.
                edit_events["snapshot_content"] = db.scalar(
                    select(SourceToMartMapping.final_content).where(SourceToMartMapping.id == mapping_b)
                )
                edit_events["snapshot_status"] = db.scalar(
                    select(SourceToMartMapping.mapping_status).where(SourceToMartMapping.id == mapping_b)
                )
                db.commit()
        except Exception as exc:  # noqa: BLE001
            errors.append("submission_after_edit: " + type(exc).__name__ + ": " + str(exc)[:160])

    thread_edit2 = threading.Thread(target=edit_first)
    thread_sub2 = threading.Thread(target=submission_after_edit)
    thread_edit2.start()
    edit2_locked.wait(30)
    thread_sub2.start()
    sub2_attempted.wait(30)
    time.sleep(1.0)                     # let the submission block on the row lock
    allow_edit2_commit.set()
    thread_edit2.join(timeout=60)
    thread_sub2.join(timeout=60)

    scenario_b = {
        "reopened_draft": bool(edit_events.get("reopened")),
        "snapshot_content": edit_events.get("snapshot_content"),
        "snapshot_status": edit_events.get("snapshot_status"),
        "submission_waited_for_edit": (
            edit_events.get("sub_acquired_at", 0) >= edit_events.get("committed_at", 10**9)
        ),
        "wait_ms": round((edit_events.get("sub_acquired_at", 0) - edit_events.get("committed_at", 0)) * 1000, 1),
    }

    result = {
        "ok": (
            not errors
            and scenario_a["edit_outcome"] == "DOUBLE_LAYER_REVIEW_IN_PROGRESS"
            and scenario_a["content_unchanged"]
            and scenario_a["edit_waited_for_submission"]
            and scenario_a["review_instance_status"] == "in_progress"
            and scenario_b["reopened_draft"]
            and scenario_b["snapshot_content"] == "编辑后内容-B"
            and scenario_b["snapshot_status"] == "draft"
            and scenario_b["submission_waited_for_edit"]
        ),
        "database": args.database,
        "scenario_a_submission_first": scenario_a,
        "scenario_b_edit_first": scenario_b,
        "unexpected_errors": errors,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    engine.dispose()
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
