"""Controlled follow-up reproductions, commit 8d76006.

Run from ai-platform/backend: .venv/Scripts/python.exe ../docs/reviews/2026-10-04/backend_followup_repro.py
Never imports the app until database/provider/storage environment is isolated.
Only synthetic SQLite databases inside TemporaryDirectory are used.
No network, credentials, service restarts, migrations, or existing business data writes.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
import sys
import tempfile


def emit(case, **result):
    print(json.dumps({"case": case, **result}, ensure_ascii=False))


def main():
    with tempfile.TemporaryDirectory(prefix="backend-followup-repro-") as directory:
        temporary = Path(directory)
        backend = Path(__file__).resolve().parents[3] / "backend"
        sys.path.insert(0, str(backend))
        os.environ.update({
            "DATABASE_URL": "sqlite:///:memory:", "ENVIRONMENT": "development",
            "AUTH_MODE": "optional", "JWT_SECRET_KEY": secrets.token_urlsafe(48),
            "TASK_QUEUE_PROVIDER": "inline", "STORAGE_PROVIDER": "local",
            "STORAGE_DIR": str(temporary / "storage"),
            "LLM_PROVIDER": "mock", "EMBEDDING_PROVIDER": "mock",
            "VECTOR_STORE_PROVIDER": "mock", "LLM_BASE_URL": "", "LLM_MODEL": "",
            "EMBEDDING_BASE_URL": "", "EMBEDDING_MODEL": "",
        })
        from datetime import UTC, datetime, timedelta
        from sqlalchemy import create_engine, text, update
        from sqlalchemy.orm import sessionmaker
        from app.core.database import Base
        from app.models import (BackgroundJob, DataSource, MartField, MartTable, Project,
                                SourceToMartMapping, User, WorkflowInstance)
        from app.schemas import SourceToMartMappingUpdate
        from app.api import mapping_rules
        from app.services.db.safe_sql_executor import SafeSqlExecutor
        from app.services.governance.workflow import start_workflow, _definition
        from app.services.task_queue.inline import InlineTaskQueue, _claim_job, _lease_owner
        from app.services.task_queue.celery import CeleryTaskQueue

        source_path = temporary / "synthetic-source.sqlite"
        source_engine = create_engine("sqlite:///" + source_path.as_posix())
        with source_engine.begin() as connection:
            connection.execute(text("CREATE TABLE customers (phone TEXT)"))
            connection.execute(text("INSERT INTO customers VALUES ('13800001111')"))
        datasource = DataSource(id=1, project_id=1, name="synthetic_source", db_type="sqlite",
                                database_name=str(source_path), enabled=True,
                                readonly_flag=True, connection_params_json={})
        for case, query in [
            ("SQL_CONTROL_SIMPLE_ALIAS", "SELECT phone AS cnt FROM customers"),
            ("SQL_NESTED_ALIAS", "SELECT phone AS cnt FROM customers WHERE EXISTS (SELECT COUNT(*) AS cnt FROM customers)"),
            ("SQL_MIXED_AGGREGATE", "SELECT phone || '-' || CAST(COUNT(*) AS TEXT) AS cnt FROM customers GROUP BY phone"),
        ]:
            executor = SafeSqlExecutor()
            response = executor.execute(datasource, query, project_id=1, max_rows=5)
            emit(case, status=response.status, columns=response.columns,
                 raw_synthetic_phone_returned=any("13800001111" in str(v) for row in response.rows for v in row.values()),
                 aggregate_alias_flags=getattr(executor, "_safe_aggregate_aliases", {}),
                 warning_count=len(response.warnings), warnings=response.warnings)
        source_engine.dispose()

        engine = create_engine("sqlite:///" + (temporary / "synthetic-domain.sqlite").as_posix(),
                               connect_args={"check_same_thread": False})
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        with factory() as db:
            user = User(username="isolated_reviewer", display_name="Synthetic", status="active")
            project = Project(name="Synthetic follow-up")
            db.add_all([user, project]); db.flush()
            table = MartTable(project_id=project.id, table_code="SYN", table_name="Synthetic")
            db.add(table); db.flush()
            field = MartField(project_id=project.id, mart_table_id=table.id,
                              field_code="SYN_F", field_name="Synthetic field")
            db.add(field); db.flush()
            mapping = SourceToMartMapping(project_id=project.id, mart_field_id=field.id,
                                           final_content="before-submission", mapping_status="draft")
            db.add(mapping); _definition(db, "double_layer_mapping_review"); db.commit()
            user_id, project_id, mapping_id = user.id, project.id, mapping.id

        for same_owner in (False, True):
            with factory() as db:
                job = BackgroundJob(idempotency_key="same-owner-" + str(same_owner), job_type="isolated_probe",
                                    status="queued", created_by=user_id, payload_summary_json={})
                db.add(job); db.commit()
                observations = {}
                def handler(session, running):
                    old_owner = running.lease_owner
                    with factory() as successor:
                        successor.execute(update(BackgroundJob).where(BackgroundJob.id == running.id)
                                          .values(lease_expires_at=datetime.now(UTC) - timedelta(seconds=1)))
                        successor.commit()
                        current = successor.get(BackgroundJob, running.id)
                        new_owner = _lease_owner() if same_owner else old_owner + ":different-attempt"
                        observations["takeover_claimed"] = _claim_job(successor, current, owner=new_owner)
                        observations["owners_equal"] = new_owner == old_owner
                    return {"success_count": 1, "marker": "OLD_ATTEMPT"}
                result = InlineTaskQueue().execute_existing(db, job, handler)
                emit("JOB_TAKEOVER_SAME_OWNER" if same_owner else "JOB_TAKEOVER_DIFFERENT_OWNER_CONTROL",
                     **observations, status_after_old_runner_returns=result.status,
                     successor_lease_preserved=result.lease_owner is not None,
                     old_result_overwrote_successor=result.result_summary_json.get("marker") == "OLD_ATTEMPT")

        original_guard = mapping_rules._guard_double_layer_write
        interleaving = {}
        def guard_then_submit(db, mapping_type, mapping, updates):
            editable = original_guard(db, mapping_type, mapping, updates)
            with factory() as submitter:
                workflow = start_workflow(submitter, project_id=project_id,
                                          workflow_key="double_layer_mapping_review",
                                          target_type="source_to_mart", target_id=mapping_id,
                                          created_by=user_id)
                interleaving["workflow_id"] = workflow.id
                interleaving["submitted_status"] = workflow.status
            return editable
        mapping_rules._guard_double_layer_write = guard_then_submit
        try:
            with factory() as editor:
                result = mapping_rules.update_source_to_mart_mapping(
                    mapping_id, SourceToMartMappingUpdate(final_content="after-submission"), db=editor)
            with factory() as observer:
                workflow = observer.get(WorkflowInstance, interleaving["workflow_id"])
                emit("WORKFLOW_EDIT_INTERLEAVING", submission_committed_before_edit_commit=True,
                     workflow_status=workflow.status, content_after_edit=result.final_content,
                     controlled_sqlite_schedule=True, postgres_live_run=False)
        finally:
            mapping_rules._guard_double_layer_write = original_guard

        class FailingBroker:
            def __init__(self): self.calls = 0
            def send_task(self, *args, **kwargs):
                self.calls += 1
                raise ConnectionError("Synthetic broker unavailable")
        broker = FailingBroker()
        queue = CeleryTaskQueue(celery_app=broker)
        parameters = dict(job_type="isolated_broker_probe", institution_id=None, project_id=project_id,
                          created_by=user_id, idempotency_key="broker-gap", payload_summary={})
        with factory() as db:
            try:
                queue.enqueue(db, **parameters)
            except ConnectionError:
                pass
            replay = queue.enqueue(db, **parameters)
            emit("CELERY_OUTBOX_PENDING", broker_publish_calls=broker.calls, replay_status=replay.status,
                 celery_task_id_missing=replay.celery_task_id is None,
                 known_documented_gap=True)
        engine.dispose()


if __name__ == "__main__":
    main()
