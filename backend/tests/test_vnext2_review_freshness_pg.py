"""VNext2 P0-A 并发证据：在真实 PostgreSQL 上验证跨事务锁与问题可见性。

SQLite 会忽略 ``SELECT ... FOR UPDATE``，单进程 TestClient 也无法证明跨事务安全，
因此本文件只在显式提供隔离开发库时运行::

    $env:VNEXT_PG_URL = "postgresql+psycopg://<user>:<pwd>@127.0.0.1:5432/<isolated_db>"
    .venv\\Scripts\\python.exe -m pytest tests/test_vnext2_review_freshness_pg.py -q

证据级别：REAL_COMPONENT（真实 PostgreSQL 事务与行锁），不是真实银行数据。
所有夹具数据带 ``VNEXT2-P0A-PG`` 前缀并在用例结束时删除。
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.models import PendingQuestion, Project, Requirement, TargetTable
from app.services.requirement_delivery_safety import (
    lock_project_requirements,
    unresolved_question_risks,
)

PG_URL = os.environ.get("VNEXT_PG_URL", "").strip()
pytestmark = pytest.mark.skipif(
    not PG_URL,
    reason="需要 VNEXT_PG_URL 指向隔离开发 PostgreSQL 才能验证跨事务锁（SQLite 忽略 FOR UPDATE）",
)

MARKER = "VNEXT2-P0A-PG"


@pytest.fixture()
def pg_env():
    engine = create_engine(PG_URL, pool_size=5, max_overflow=5, connect_args={"connect_timeout": 5})
    with Session(engine) as db:
        project = Project(name=f"{MARKER} 锁验证项目", description="isolated dev resource")
        db.add(project)
        db.flush()
        table = TargetTable(project_id=project.id, table_code="YBT_LOCK_TEST", table_name="锁验证目标表")
        db.add(table)
        db.flush()
        requirement = Requirement(
            project_id=project.id,
            name=f"{MARKER} 借据产品需求",
            version=1,
            content_version=0,
            scope_json={"target_table_id": table.id, "field_ids": [], "scenario_id": None},
        )
        db.add(requirement)
        db.commit()
        ids = (project.id, table.id, requirement.id)
    try:
        yield engine, ids
    finally:
        with Session(engine) as db:
            db.execute(text("DELETE FROM pending_questions WHERE project_id = :p"), {"p": ids[0]})
            db.execute(text("DELETE FROM requirements WHERE project_id = :p"), {"p": ids[0]})
            db.execute(text("DELETE FROM target_tables WHERE project_id = :p"), {"p": ids[0]})
            db.execute(text("DELETE FROM projects WHERE id = :p"), {"p": ids[0]})
            db.commit()
        engine.dispose()


def _add_question(session: Session, project_id: int, table_id: int, status: str = "open",
                  resolution: str | None = None) -> PendingQuestion:
    question = PendingQuestion(
        project_id=project_id,
        target_table_id=table_id,
        question_type="uniqueness",
        question_text=f"{MARKER} 产品ID+期限唯一性依据待确认",
        question_status=status,
        priority="high",
        resolution_text=resolution,
    )
    session.add(question)
    session.flush()
    return question


def test_question_write_waits_for_the_requirement_lock(pg_env):
    """问题写入必须先取得需求行锁；另一个事务持锁时写入被阻塞（真实 PG 行为）。"""
    engine, (project_id, table_id, _requirement_id) = pg_env
    holder = Session(engine)
    holder.begin()
    lock_project_requirements(holder, project_id)

    other = Session(engine)
    try:
        other.begin()
        other.execute(text("SET LOCAL lock_timeout = '400ms'"))
        with pytest.raises(OperationalError) as blocked:
            lock_project_requirements(other, project_id)
        message = str(blocked.value).lower()
        assert "lock timeout" in message or "canceling statement" in message
    finally:
        other.rollback()

    holder.commit()

    other.begin()
    lock_project_requirements(other, project_id)
    question = _add_question(other, project_id, table_id)
    other.commit()
    try:
        # 锁释放后写入成功，后续读取立即可见
        with Session(engine) as reader:
            requirement = reader.get(Requirement, _requirement_id)
            risks = unresolved_question_risks(reader, requirement)
            assert [risk["code"] for risk in risks] == [f"manual:{question.id}"]
    finally:
        with Session(engine) as cleanup:
            cleanup.execute(text("DELETE FROM pending_questions WHERE project_id = :p"), {"p": project_id})
            cleanup.commit()


def test_no_question_can_slip_between_check_and_delivery_commit(pg_env):
    """模拟定稿事务：先持锁并完成检查，再提交；期间新增问题只能等待（不会插入检查与提交之间）。"""
    engine, (project_id, table_id, requirement_id) = pg_env
    finalize = Session(engine)
    finalize.begin()
    lock_project_requirements(finalize, project_id)
    requirement = finalize.get(Requirement, requirement_id)
    assert unresolved_question_risks(finalize, requirement) == []  # 检查时无风险

    writer = Session(engine)
    try:
        writer.begin()
        writer.execute(text("SET LOCAL lock_timeout = '400ms'"))
        with pytest.raises(OperationalError):
            lock_project_requirements(writer, project_id)
    finally:
        writer.rollback()

    finalize.commit()  # 定稿事务提交（真实流程此处会写入正式交付记录）

    writer.begin()
    lock_project_requirements(writer, project_id)
    _add_question(writer, project_id, table_id)
    writer.commit()
    try:
        with Session(engine) as reader:
            requirement = reader.get(Requirement, requirement_id)
            risks = unresolved_question_risks(reader, requirement)
            assert len(risks) == 1, "定稿之后出现的问题必须对下一次检查可见"
    finally:
        with Session(engine) as cleanup:
            cleanup.execute(text("DELETE FROM pending_questions WHERE project_id = :p"), {"p": project_id})
            cleanup.commit()


def test_closed_question_needs_a_resolution_basis_on_real_postgres(pg_env):
    """真实库上复核状态语义：closed 无依据仍阻断，closed + resolution_text 才解除。"""
    engine, (project_id, table_id, requirement_id) = pg_env
    with Session(engine) as db:
        question = _add_question(db, project_id, table_id, status="closed")
        db.commit()
        requirement = db.get(Requirement, requirement_id)
        risks = unresolved_question_risks(db, requirement)
        assert len(risks) == 1 and "缺少解决依据" in risks[0]["message"]

        question.question_status = "closed"
        question.resolution_text = "依据合成制度第 4.2 条：以产品ID+期限作为唯一键"
        db.commit()
        assert unresolved_question_risks(db, requirement) == []
        db.execute(text("DELETE FROM pending_questions WHERE project_id = :p"), {"p": project_id})
        db.commit()
