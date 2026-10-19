"""Read-only product audit repro; all writes target synthetic, disposable fixtures.

Run with the backend virtualenv Python. No service, existing database, provider,
token, password, or project configuration is contacted or printed. Results
describe the current defects; this is an evidence script, not a release suite.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
import sqlite3
import sys
from tempfile import TemporaryDirectory


def report(name: str, **facts) -> None:
    print(json.dumps({"case": name, **facts}, ensure_ascii=False))


def main() -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "backend"))
    with TemporaryDirectory(prefix="bank-platform-review-") as temp_dir:
        # Process-only overrides are set BEFORE application imports. Production
        # .env files are never changed and no existing DB connection is opened.
        for key, value in {
            "DATABASE_URL": "sqlite:///:memory:",
            "ENVIRONMENT": "development",
            "JWT_SECRET_KEY": secrets.token_urlsafe(48),
            "AUTH_MODE": "required",
            "TASK_QUEUE_PROVIDER": "inline",
            "STORAGE_PROVIDER": "local",
            "STORAGE_DIR": temp_dir,
            "LLM_PROVIDER": "mock",
            "LLM_BASE_URL": "",
            "LLM_MODEL": "",
            "LLM_API_KEY_ENV_NAME": "",
            "EMBEDDING_PROVIDER": "mock",
            "EMBEDDING_BASE_URL": "",
            "EMBEDDING_MODEL": "",
            "EMBEDDING_API_KEY_ENV_NAME": "",
            "VECTOR_STORE_PROVIDER": "mock",
            "MILVUS_URI": "",
        }.items():
            os.environ[key] = value

        from sqlalchemy import create_engine, select
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy.pool import StaticPool
        from fastapi.testclient import TestClient
        from app.core.database import Base, get_db
        from app.models import (BackgroundJob, Institution, InstitutionMembership,
            MappingVersion, MartField, MartTable, Project, ProjectMembership,
            RefreshToken, SourceToMartMapping, User, WorkflowInstance)
        from app.services.auth import authentication as auth
        from app.services.auth.dependencies import get_current_principal, Principal
        from app.services.auth.permission_service import PermissionService
        from app.services.db.safe_sql_executor import SafeSqlExecutor, _sanitize_rows
        from app.services.storage import get_storage_service
        from app.services.task_queue.domain_handlers import project_backup_handler
        from app.services.task_queue.inline import InlineTaskQueue
        from app.main import app

        sql_db = sqlite3.connect(":memory:")
        sql_db.executescript("create table sample(n integer); insert into sample values(1),(2),(3),(4),(5);")
        executor = SafeSqlExecutor(default_limit=2, max_limit=2)
        for label, query in [
            ("BA03_nested_limit", "select n from sample where n in (select n from sample limit 1) or n > 1"),
            ("BA03_literal_limit", "select 'limit 1' as marker, n from sample"),
        ]:
            prepared = executor.validate_and_prepare(query, max_rows=2, dialect="sqlite")
            count = len(sql_db.execute(prepared).fetchall())
            report(label, requested_max_rows=2, actual_rows=count, prepared_sql=prepared,
                   defect_present=count > 2)
        sql_db.close()
        for dialect in ["sqlserver", "oracle", "db2"]:
            prepared = executor.validate_and_prepare("select n from sample", max_rows=2, dialect=dialect)
            report("BA07_dialect", dialect=dialect, prepared_sql=prepared,
                   real_database_execution="not_performed")

        synthetic_phone = "13800000000"
        _, normal, _ = _sanitize_rows([{"phone": synthetic_phone}])
        _, aliased, _ = _sanitize_rows([{"cnt": synthetic_phone}])
        report("BA02_alias_redaction", original_removed=not bool(normal[0]),
               alias_preserves_sensitive_value=aliased[0].get("cnt") == synthetic_phone)

        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine)
        db, other = factory(), factory()
        try:
            user = User(username="synthetic_review_editor", status="active")
            db.add(user); db.commit()
            initial = auth.create_session(db, user)
            original_create = auth.create_session
            interleaved = []
            fired = False

            def scheduled_create(session, account):
                nonlocal fired
                replacement = original_create(session, account)
                if not fired:
                    fired = True
                    # Legal concurrent schedule: request B enters after A has
                    # committed its replacement but before A revokes the old one.
                    interleaved.append(auth.rotate_refresh_token(other, initial["refresh_token"]))
                return replacement

            auth.create_session = scheduled_create
            try:
                first = auth.rotate_refresh_token(db, initial["refresh_token"])
            finally:
                auth.create_session = original_create
            db.expire_all()
            active = db.scalars(select(RefreshToken).where(RefreshToken.revoked_at.is_(None))).all()
            report("BA04_refresh_rotation", successful_rotations_of_same_original=1 + len(interleaved),
                   active_replacements=len(active), replacements_are_distinct=
                   first["refresh_token"] != interleaved[0]["refresh_token"])

            disabled = Institution(institution_code="REVIEW_DISABLED", institution_name="Synthetic fixture", status="inactive")
            db.add(disabled); db.flush()
            disabled_project = Project(name="Synthetic disabled institution project", institution_id=disabled.id)
            db.add(disabled_project); db.flush()
            db.add(InstitutionMembership(institution_id=disabled.id, user_id=user.id,
                role="institution_admin", status="active", created_by=user.id)); db.commit()
            principal = Principal(user.id, user.username, None)
            permissions = PermissionService(db, principal)
            report("BA05_disabled_institution", visible_project_ids=permissions.visible_project_ids(),
                direct_manage_still_allowed=permissions.require_project_permission(disabled_project.id, "project.manage").id == disabled_project.id)

            executions = 0
            def handler(session, job):
                nonlocal executions
                executions += 1
                return {"success_count": 1}
            job = BackgroundJob(institution_id=disabled.id, project_id=disabled_project.id,
                job_type="synthetic_review_probe", idempotency_key="synthetic-review-probe", created_by=user.id)
            db.add(job); db.commit()
            queue = InlineTaskQueue()
            queue.execute_existing(db, job, handler)
            queue.execute_existing(db, job, handler)
            report("BA06_duplicate_delivery", same_job_deliveries=2, handler_executions=executions, status=job.status)

            bank = Institution(institution_code="REVIEW_ACTIVE", institution_name="Synthetic active bank")
            db.add(bank); db.flush()
            project = Project(name="Synthetic mapping review project", institution_id=bank.id, governance_workflow_enabled=True)
            db.add(project); db.flush()
            db.add_all([
                InstitutionMembership(institution_id=bank.id, user_id=user.id, role="member", created_by=user.id),
                ProjectMembership(project_id=project.id, user_id=user.id, project_role="technical_analyst", created_by=user.id),
            ])
            table = MartTable(project_id=project.id, table_code="SYNTHETIC", table_name="Synthetic table")
            db.add(table); db.flush()
            field = MartField(project_id=project.id, mart_table_id=table.id, field_code="SYNTHETIC", field_name="Synthetic field")
            db.add(field); db.flush()
            mapping = SourceToMartMapping(project_id=project.id, mart_field_id=field.id,
                mapping_status="approved", final_content="Reviewed baseline", reviewed_by="Synthetic reviewer")
            db.add(mapping); db.flush()
            version = MappingVersion(project_id=project.id, mapping_type="source_to_mart", mapping_id=mapping.id,
                version_no=1, content_snapshot=mapping.final_content, created_by="Synthetic reviewer")
            workflow = WorkflowInstance(project_id=project.id, workflow_key="double_layer_mapping_review",
                target_type="source_to_mart", target_id=mapping.id, status="approved", current_step="final_review", created_by=user.id)
            db.add_all([version, workflow]); db.commit()
            mapping_id, workflow_id = mapping.id, workflow.id

            def override_db():
                with factory() as session:
                    yield session
            previous_overrides = dict(app.dependency_overrides)
            app.dependency_overrides[get_db] = override_db
            app.dependency_overrides[get_current_principal] = lambda: principal
            try:
                client = TestClient(app)  # No lifespan/service bootstrapping.
                try:
                    response = client.put(f"/api/source-to-mart-mappings/{mapping_id}",
                        json={"final_content": "Changed after approval"})
                finally:
                    client.close()
            finally:
                app.dependency_overrides.clear()
                app.dependency_overrides.update(previous_overrides)
            data = response.json(); db.expire_all()
            report("BA01_approved_mapping_edit", http_status=response.status_code,
                new_content_persisted=data.get("final_content") == "Changed after approval",
                mapping_status=data.get("mapping_status"), workflow_status=db.get(WorkflowInstance, workflow_id).status,
                version_count=len(db.scalars(select(MappingVersion).where(MappingVersion.mapping_id == mapping_id)).all()))

            backup_job = BackgroundJob(institution_id=bank.id, project_id=project.id,
                job_type="project_backup", idempotency_key="synthetic-backup", created_by=user.id)
            db.add(backup_job); db.commit()
            result = project_backup_handler(db, backup_job)
            from app.models import StoredFile
            stored = db.get(StoredFile, result["file_id"])
            payload = json.loads(get_storage_service().read(stored.storage_key))
            report("BA08_backup_placeholder", backup_keys=sorted(payload),
                contains_mapping_data=any(k in payload for k in ["mappings", "source_to_mart_mappings", "tables", "requirements"]),
                handler_reports_success=result["success_count"] == 1)
        finally:
            db.close(); other.close(); engine.dispose()
            get_storage_service.cache_clear()


if __name__ == "__main__":
    main()
