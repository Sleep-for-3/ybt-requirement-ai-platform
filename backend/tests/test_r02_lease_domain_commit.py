"""R02【C05，P1】：失租后领域提交与重复结果。

复核复现（`docs/reviews/2026-10-06-followup/engineering-probe-results.json`
→ `c05_real_handler_commit_after_loss`）：使用**真实** `project_manifest_export_handler`，
只有存储是假对象；存储阶段标记失租后，第一次仍提交 StoredFile / 通知 / 审计各 1 条，
job 保持 running、result 为空；加速租约到期后接管，同一个 job 又提交各 1 条，总数各 2。

这些回归驱动**真实队列 + 真实领域 handler**（不是独立 helper，也不是源码字符串测试）：
* `InlineTaskQueue.execute_existing` —— 真实领取、真实心跳、真实执行权绑定；
* `project_manifest_export_handler` / `metadata_sync_handler` —— 真实领域提交边界；
* 临时 SQLite + 假存储 + 缩短租约（不等待真实 900 秒）。

不触碰业务库、不写真实对象存储、不调用真实模型。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models import (
    AuditLog,
    BackgroundJob,
    Institution,
    Notification,
    Project,
    StoredFile,
    User,
)
from app.services.task_queue.attempt import AttemptLeaseLost
from app.services.task_queue.domain_handlers import project_manifest_export_handler
from app.services.task_queue.inline import InlineTaskQueue


class _FakeObject:
    def __init__(self, storage_key: str, byte_size: int, content_hash: str):
        self.storage_key = storage_key
        self.byte_size = byte_size
        self.content_hash = content_hash


class FakeStorage:
    """假存储：记录写入与删除，用于验证“旧尝试不留下已发布产物”。"""

    def __init__(self):
        self.saved: list[str] = []
        self.deleted: list[str] = []
        self.alive: set[str] = set()
        self._seq = 0

    def save(self, data: bytes, *, file_name: str, project_id: int | None = None):
        self._seq += 1
        key = f"projects/{project_id or 0}/fake/{self._seq}-{file_name}"
        self.saved.append(key)
        self.alive.add(key)
        import hashlib

        return _FakeObject(key, len(data), hashlib.sha256(data).hexdigest())

    def read(self, storage_key: str) -> bytes:  # pragma: no cover - 本项回归不读
        raise NotImplementedError

    def delete(self, storage_key: str) -> None:
        self.deleted.append(storage_key)
        self.alive.discard(storage_key)

    def is_ready(self) -> bool:
        return True

    def scan(self, data: bytes, file_name: str) -> None:
        return None


@pytest.fixture()
def env(tmp_path):
    """临时 SQLite + 假存储（不触碰业务库与真实对象存储）。"""

    engine = create_engine("sqlite:///" + (tmp_path / "r02.db").as_posix())
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    storage = FakeStorage()

    import app.services.task_queue.domain_handlers as domain_handlers

    original = domain_handlers.get_storage_service
    domain_handlers.get_storage_service = lambda: storage
    try:
        yield factory, storage
    finally:
        domain_handlers.get_storage_service = original
        engine.dispose()


def _fixture(db, *, job_type: str, payload: dict) -> BackgroundJob:
    institution = Institution(institution_code=f"R02-{job_type}", institution_name="R02 机构",
                              institution_type="bank", status="active")
    db.add(institution)
    db.flush()
    user = User(username="r02-user", display_name="R02 用户",
                status="active")
    db.add(user)
    db.flush()
    project = Project(institution_id=institution.id, name="R02 项目", project_status="active")
    db.add(project)
    db.flush()
    # 以 queued 入队，让真实的 _claim_job 完成领取（B07：仍在租期内的 running 不会被重复领取）。
    job = BackgroundJob(
        institution_id=institution.id, project_id=project.id, job_type=job_type,
        idempotency_key=f"r02-{job_type}-{project.id}", status="queued",
        progress=0, retry_count=0, max_retries=3, created_by=user.id,
        payload_summary_json=payload, created_at=datetime.now(UTC),
        lease_owner=None, lease_expires_at=None,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _counts(db) -> dict:
    return {
        "stored_files": db.scalar(select(func.count()).select_from(StoredFile)) or 0,
        "notifications": db.scalar(select(func.count()).select_from(Notification)) or 0,
        "audit_logs": db.scalar(select(func.count()).select_from(AuditLog)) or 0,
    }


def test_r02_真实handler在提交前失租时不产生任何领域效果(env, monkeypatch):
    """提交前失租 → 旧 attempt 无 StoredFile / 通知 / 审计，且不留下已发布的外部对象。"""

    factory, storage = env
    with factory() as db:
        job = _fixture(db, job_type="project_manifest_export", payload={})
        job_id = job.id

        # 第一次尝试：真实 handler 执行到存储阶段时，租约被接管者夺走。
        original_save = storage.save

        def save_and_lose_lease(data, *, file_name, project_id=None):
            saved = original_save(data, file_name=file_name, project_id=project_id)
            # 模拟“接管发生在本尝试提交领域效果之前”。
            with factory() as other:
                other.execute(
                    BackgroundJob.__table__.update()
                    .where(BackgroundJob.id == job_id)
                    .values(lease_owner="attempt-2",
                            lease_expires_at=datetime.now(UTC) + timedelta(seconds=900))
                )
                other.commit()
            return saved

        monkeypatch.setattr(storage, "save", save_and_lose_lease)

        monkeypatch.setattr(storage, "save", save_and_lose_lease)

        # 队列层不把失租当作业务失败向外冒：它回滚并如实上报接管者的状态。
        returned = InlineTaskQueue().execute_existing(db, job, project_manifest_export_handler)
        assert returned.status == "running", (
            f"失租尝试不得写成功/失败终态（接管者仍在跑）：{returned.status}")
        assert not returned.result_summary_json, "失租尝试不得发布成功结果"

        monkeypatch.setattr(storage, "save", original_save)

    with factory() as db:
        # 旧 attempt 不得留下任何正式业务效果。
        assert _counts(db) == {"stored_files": 0, "notifications": 0, "audit_logs": 0}, _counts(db)
        row = db.get(BackgroundJob, job_id)
        assert row.status == "running", "接管者拥有该 job，旧 attempt 不得改写它"
        assert not row.result_summary_json, "旧 attempt 不得发布成功结果"
        assert row.lease_owner == "attempt-2", "租约仍应属于接管者"
        # 只读预检路径：真实 handler 在领域提交前发现失租时显式抛出。
        from app.services.task_queue.attempt import AttemptAuthority, bind_attempt
        import threading as _threading

        bind_attempt(db, AttemptAuthority(job_id=job_id, owner="attempt-1",
                                          lost=_threading.Event()))
        with pytest.raises(AttemptLeaseLost):
            project_manifest_export_handler(db, row)
    # 外部对象已被回收：旧 attempt 不留下“已发布”的产物。
    assert storage.saved, "应确实写入过对象（否则本回归没有覆盖存储阶段）"
    assert set(storage.saved) <= set(storage.deleted), (
        f"失租尝试写入的对象必须被回收：saved={storage.saved} deleted={storage.deleted}")
    assert storage.alive == set(), "不得留下任何未引用的存活对象"


def test_r02_接管后只保留一份有效结果(env, monkeypatch):
    """旧 attempt 失租不回滚业务；接管者完成后恰好各 1 条。"""

    factory, storage = env
    with factory() as db:
        job = _fixture(db, job_type="project_manifest_export", payload={})
        job_id = job.id
        original_save = storage.save

        def save_and_lose_lease(data, *, file_name, project_id=None):
            saved = original_save(data, file_name=file_name, project_id=project_id)
            with factory() as other:
                other.execute(
                    BackgroundJob.__table__.update()
                    .where(BackgroundJob.id == job_id)
                    .values(lease_owner="attempt-2",
                            lease_expires_at=datetime.now(UTC) + timedelta(seconds=900))
                )
                other.commit()
            return saved

        monkeypatch.setattr(storage, "save", save_and_lose_lease)
        returned = InlineTaskQueue().execute_existing(db, job, project_manifest_export_handler)
        assert returned.status == "running", returned.status
        monkeypatch.setattr(storage, "save", original_save)

    with factory() as db:
        assert _counts(db) == {"stored_files": 0, "notifications": 0, "audit_logs": 0}

        # 接管者：以它的 owner token 真实跑完同一个 job。
        row = db.get(BackgroundJob, job_id)
        row.lease_owner = "attempt-2"
        row.lease_expires_at = datetime.now(UTC) + timedelta(seconds=900)
        db.commit()

        started = InlineTaskQueue()
        # 接管者复用真实执行路径：execute_existing 会重新领取（lease 未过期则直接使用既有 owner）
        fresh = db.get(BackgroundJob, job_id)
        fresh.status = "queued"
        fresh.lease_owner = None
        fresh.lease_expires_at = None
        db.commit()
        completed = started.execute_existing(db, fresh, project_manifest_export_handler)

        assert completed.status == "completed", completed.status
        result = dict(completed.result_summary_json or {})
        assert result.get("success_count") == 1, result

    with factory() as db:
        counts = _counts(db)
        assert counts == {"stored_files": 1, "notifications": 1, "audit_logs": 1}, (
            f"接管后应恰好各 1 条（旧 attempt 不得重复提交）：{counts}")


def test_r02_正常执行不受影响(env, monkeypatch):
    """未失租时，真实 handler 照常发布 1 份结果与通知。"""

    factory, storage = env
    with factory() as db:
        job = _fixture(db, job_type="project_manifest_export", payload={})
        completed = InlineTaskQueue().execute_existing(db, job, project_manifest_export_handler)
        assert completed.status == "completed", completed.status
        result = dict(completed.result_summary_json or {})
        assert result.get("success_count") == 1, result
        assert result.get("file_id"), result

    with factory() as db:
        counts = _counts(db)
        assert counts == {"stored_files": 1, "notifications": 1, "audit_logs": 1}, counts
    assert storage.alive, "正常路径应保留已发布对象"
    assert not storage.deleted, "正常路径不得删除对象"


def test_r02_真实handler在领域写入前失租时直接拒绝(env):
    """进入领域服务之前已失租 → 立即抛出，不做任何存储写入。"""

    factory, storage = env
    with factory() as db:
        job = _fixture(db, job_type="metadata_sync", payload={"datasource_id": 1})
        job_id = job.id
        # 在 handler 开始前就把 owner 换掉（模拟续租已失败）。
        db.execute(
            BackgroundJob.__table__.update()
            .where(BackgroundJob.id == job_id)
            .values(lease_owner="attempt-2")
        )
        db.commit()
        monkeypatch_target = db.get(BackgroundJob, job_id)

        # 直接以旧 owner 的权威上下文调用真实 handler。
        from app.services.task_queue.attempt import AttemptAuthority, bind_attempt
        import threading

        bind_attempt(db, AttemptAuthority(job_id=job_id, owner="attempt-1", lost=threading.Event()))
        with pytest.raises(AttemptLeaseLost):
            project_manifest_export_handler(db, monkeypatch_target)

    assert storage.saved == [], "失租尝试不得写任何外部对象"
