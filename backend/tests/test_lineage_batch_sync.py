"""Batch lineage atomicity: one sync run must produce exactly one revision."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    BackgroundJob,
    BackgroundJobItem,
    CodeRepository,
    Institution,
    LineageRevision,
    Project,
    ScriptFile,
    StoredFile,
    User,
)
from app.services.lineage.archive_ingestion import ArchivedScript
from app.services.lineage.git_repository import GitRepositorySnapshot
from app.services.lineage import jobs as lineage_jobs
from app.services.storage.local import LocalStorageService


def _seed_project(db_session: Session, *, code: str, name: str) -> tuple[Institution, User, Project]:
    institution = Institution(institution_code=code, institution_name=f"{code} Bank")
    user = User(username=f"batch-user-{code.lower()}", status="active")
    db_session.add_all([institution, user])
    db_session.flush()
    project = Project(name=name, institution_id=institution.id)
    db_session.add(project)
    db_session.flush()
    return institution, user, project


def _archive_job(
    db_session: Session,
    project: Project,
    user: User,
    storage: LocalStorageService,
    entries: dict[str, bytes],
    *,
    key: str,
) -> BackgroundJob:
    stream = BytesIO()
    with ZipFile(stream, "w") as archive:
        for path, content in entries.items():
            archive.writestr(path, content)
    saved = storage.save(stream.getvalue(), file_name=f"{key}.zip", project_id=project.id)
    stored = StoredFile(
        institution_id=project.institution_id,
        project_id=project.id,
        storage_key=saved.storage_key,
        original_file_name=f"{key}.zip",
        content_type="application/zip",
        byte_size=saved.byte_size,
        content_hash=saved.content_hash,
        classification="internal",
        created_by=user.id,
        enabled=True,
    )
    db_session.add(stored)
    db_session.flush()
    job = BackgroundJob(
        institution_id=project.institution_id,
        project_id=project.id,
        idempotency_key=key,
        job_type="script_upload_ingestion",
        status="running",
        progress=0,
        payload_summary_json={"stored_file_id": stored.id, "dialect": "sqlite"},
        result_summary_json={},
        created_by=user.id,
    )
    db_session.add(job)
    db_session.commit()
    return job


def _storage(tmp_path: Path, monkeypatch) -> LocalStorageService:
    storage = LocalStorageService(tmp_path / "storage")
    monkeypatch.setattr(lineage_jobs, "get_storage_service", lambda: storage)
    return storage


def _revisions(db_session: Session, project: Project) -> list[LineageRevision]:
    return list(db_session.scalars(select(LineageRevision).where(
        LineageRevision.project_id == project.id,
    ).order_by(LineageRevision.revision_no)).all())


def test_zip_batch_creates_one_published_revision(tmp_path: Path, monkeypatch, db_session: Session) -> None:
    _institution, user, project = _seed_project(db_session, code="BATCH1", name="batch project")
    storage = _storage(tmp_path, monkeypatch)
    job = _archive_job(
        db_session, project, user, storage,
        {
            "sql/a.sql": b"insert into MART.T(A) select A from ODS.S",
            "sql/b.sql": b"insert into MART.U(B) select B from ODS.S",
            "sql/c.sql": b"insert into MART.V(C) select C from ODS.S",
        },
        key="batch-1",
    )

    result = lineage_jobs.script_archive_ingestion_handler(db_session, job)

    assert result["success_count"] == 3
    assert result["failed_count"] == 0
    assert result["lineage_revision_published"] is True
    revisions = _revisions(db_session, project)
    assert len(revisions) == 1, "one batch must not publish one revision per file"
    revision = revisions[0]
    assert revision.id == result["lineage_revision_id"]
    assert revision.status == "published"
    assert len(revision.source_manifest_json or []) == 3
    assert revision.node_count > 0 and revision.edge_count > 0
    assert db_session.scalar(select(ScriptFile).where(ScriptFile.project_id == project.id)) is not None


def test_repeated_batch_run_stays_idempotent(tmp_path: Path, monkeypatch, db_session: Session) -> None:
    _institution, user, project = _seed_project(db_session, code="BATCH2", name="batch retry")
    storage = _storage(tmp_path, monkeypatch)
    job = _archive_job(
        db_session, project, user, storage,
        {
            "sql/a.sql": b"insert into MART.T(A) select A from ODS.S",
            "sql/b.sql": b"insert into MART.U(B) select B from ODS.S",
        },
        key="batch-2",
    )

    first = lineage_jobs.script_archive_ingestion_handler(db_session, job)
    second = lineage_jobs.script_archive_ingestion_handler(db_session, db_session.get(BackgroundJob, job.id))

    assert first["lineage_revision_id"] == second["lineage_revision_id"]
    assert second["skipped_completed_count"] == 2
    assert second["lineage_revision_published"] is True
    revisions = _revisions(db_session, project)
    assert len(revisions) == 1
    assert revisions[0].status == "published"
    # Every item was recorded as completed exactly once for this job.
    items = list(db_session.scalars(select(BackgroundJobItem).where(
        BackgroundJobItem.background_job_id == job.id,
    )).all())
    assert len(items) == 2
    assert {item.status for item in items} == {"completed"}


def test_failed_batch_never_replaces_published_revision(tmp_path: Path, monkeypatch, db_session: Session) -> None:
    _institution, user, project = _seed_project(db_session, code="BATCH3", name="batch failure")
    storage = _storage(tmp_path, monkeypatch)
    good = _archive_job(
        db_session, project, user, storage,
        {"sql/a.sql": b"insert into MART.T(A) select A from ODS.S"},
        key="batch-3-good",
    )
    baseline = lineage_jobs.script_archive_ingestion_handler(db_session, good)
    assert baseline["lineage_revision_published"] is True

    broken = _archive_job(
        db_session, project, user, storage,
        {
            "sql/b.sql": b"insert into MART.U(B) select B from ODS.S",
            "sql/c.sql": b"insert into MART.V(C) select C from ODS.S \xff\xfe",
        },
        key="batch-3-broken",
    )
    result = lineage_jobs.script_archive_ingestion_handler(db_session, broken)

    assert result["failed_count"] == 1
    assert result["success_count"] == 1
    assert result["lineage_revision_published"] is False
    revisions = _revisions(db_session, project)
    assert len(revisions) == 2
    published = [item for item in revisions if item.status == "published"]
    assert [item.id for item in published] == [baseline["lineage_revision_id"]]
    assert revisions[-1].status == "needs_review"
    assert result["lineage_revision_id"] == revisions[-1].id


def _repository(db_session: Session, tmp_path: Path, institution: Institution, user: User, project: Project) -> CodeRepository:
    repository = CodeRepository(
        institution_id=institution.id,
        project_id=project.id,
        repository_name="local",
        repository_type="git_repository",
        repository_url=str(tmp_path),
        default_branch="main",
        enabled=True,
        created_by=user.id,
    )
    db_session.add(repository)
    db_session.commit()
    return repository


def _sync_job(db_session: Session, project: Project, user: User, repository: CodeRepository, key: str) -> BackgroundJob:
    job = BackgroundJob(
        institution_id=project.institution_id,
        project_id=project.id,
        idempotency_key=key,
        job_type="script_repository_sync",
        status="running",
        progress=1,
        payload_summary_json={"repository_id": repository.id},
        result_summary_json={},
        created_by=user.id,
    )
    db_session.add(job)
    db_session.commit()
    return job


def _patch_git(monkeypatch, tmp_path: Path, files: tuple[ArchivedScript, ...], sha: str = "a" * 40) -> None:
    monkeypatch.setattr(
        lineage_jobs,
        "read_git_repository_scripts",
        lambda *args, **kwargs: GitRepositorySnapshot(sha, files),
    )
    monkeypatch.setattr(
        lineage_jobs,
        "get_settings",
        lambda: SimpleNamespace(
            lineage_git_allowed_host_list=["github.com"],
            lineage_git_allowed_local_root_list=[str(tmp_path)],
            lineage_repository_max_bytes=1024 * 1024,
            lineage_repository_max_file_count=100,
            lineage_script_max_bytes=1024 * 1024,
        ),
    )


def test_repository_sync_projects_ingest_rename_and_delete_into_one_revision(tmp_path: Path, monkeypatch, db_session: Session) -> None:
    institution, user, project = _seed_project(db_session, code="BATCH4", name="repository sync")
    repository = _repository(db_session, tmp_path, institution, user, project)
    first_file = ArchivedScript("sql/a.sql", "a.sql", b"insert into MART.T(A) select A from ODS.S")
    second_file = ArchivedScript("sql/b.sql", "b.sql", b"insert into MART.U(B) select B from ODS.S")
    _patch_git(monkeypatch, tmp_path, (first_file, second_file))

    result = lineage_jobs.script_repository_sync_handler(
        db_session, _sync_job(db_session, project, user, repository, "sync-1"),
    )

    assert result["success_count"] == 2
    assert result["failed_count"] == 0
    assert result["deleted_count"] == 0
    assert result["lineage_revision_published"] is True
    revisions = _revisions(db_session, project)
    assert len(revisions) == 1
    published_id = result["lineage_revision_id"]
    assert revisions[0].id == published_id
    assert revisions[0].trigger_type == "repository_sync"
    assert len(revisions[0].source_manifest_json or []) == 2

    # A re-run with one file deleted must add exactly one reviewable revision
    # and leave the previously published graph untouched.
    _patch_git(monkeypatch, tmp_path, (first_file,), sha="b" * 40)
    second = lineage_jobs.script_repository_sync_handler(
        db_session, _sync_job(db_session, project, user, repository, "sync-2"),
    )

    assert second["deleted_count"] == 1
    assert second["lineage_revision_published"] is False
    revisions = _revisions(db_session, project)
    assert len(revisions) == 2, "one sync run must produce at most one revision"
    assert revisions[-1].status == "needs_review"
    assert [item.id for item in revisions if item.status == "published"] == [published_id]
