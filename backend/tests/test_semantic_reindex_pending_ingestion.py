"""P0：知识资料仍在导入时提交重新索引，必须给出明确原因而不是留下一条失败任务。

真实事故（2026-10-25，项目 9）：上传 3 条知识单元后立刻 `POST
/api/projects/9/semantic-index/reindex`，任务以
`Knowledge corpus changed after submission; submit a fresh reindex task` 失败，
调用方只看到一条"失败"的任务，不知道原因是导入还没结束。
"""

from app.api.knowledge_rag import ingestion_in_progress_message, pending_ingestion_job_ids
from app.models import BackgroundJob, Institution, Project, User


def _owner(db) -> tuple[Institution, User]:
    institution = db.query(Institution).filter_by(institution_code="PENDING-INGESTION").one_or_none()
    if institution is None:
        institution = Institution(
            institution_code="PENDING-INGESTION",
            institution_name="导入中机构",
            institution_type="commercial_bank",
            status="active",
        )
        db.add(institution)
        db.flush()
    user = db.query(User).filter_by(username="pending-ingestion").one_or_none()
    if user is None:
        user = User(username="pending-ingestion", display_name="导入中用户", status="active")
        db.add(user)
        db.flush()
    return institution, user


def _project(db, name: str = "导入中项目") -> Project:
    institution, user = _owner(db)
    project = Project(
        name=name,
        bank_name="模拟机构",
        institution_id=institution.id,
        project_owner_id=user.id,
    )
    db.add(project)
    db.flush()
    return project


def _job(db, project: Project, status: str, job_type: str = "knowledge_ingestion") -> BackgroundJob:
    job = BackgroundJob(
        project_id=project.id,
        institution_id=project.institution_id,
        job_type=job_type,
        status=status,
        progress=0,
        idempotency_key=f"test-{job_type}-{status}-{db.query(BackgroundJob).count() + 1}",
        created_by=project.project_owner_id,
    )
    db.add(job)
    db.flush()
    return job


def test_pending_ingestion_ids_include_queued_and_running(db_session) -> None:
    project = _project(db_session)
    queued = _job(db_session, project, "queued")
    running = _job(db_session, project, "running")
    _job(db_session, project, "completed")
    _job(db_session, project, "failed")
    _job(db_session, project, "running", job_type="knowledge_embedding_reindex")

    ids = pending_ingestion_job_ids(db_session, project.id)

    assert ids == [running.id, queued.id]


def test_pending_ingestion_ids_are_scoped_to_project(db_session) -> None:
    mine = _project(db_session, "我的项目")
    other = _project(db_session, "别人的项目")
    _job(db_session, other, "running")

    assert pending_ingestion_job_ids(db_session, mine.id) == []


def test_message_names_the_jobs_and_the_consequence() -> None:
    message = ingestion_in_progress_message([11, 12])

    assert "#11" in message and "#12" in message
    assert "导入中" in message
    assert "语料变化失败" in message
    assert "等待导入完成" in message


def test_message_lists_at_most_five_jobs() -> None:
    message = ingestion_in_progress_message([1, 2, 3, 4, 5, 6, 7])

    assert "#5" in message
    assert "#6" not in message
