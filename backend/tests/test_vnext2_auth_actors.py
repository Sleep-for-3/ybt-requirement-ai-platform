"""VNext2 P2-A：``legacy-system`` 材料化的权限与并发安全。

三件事必须可验证，而不是“看起来没事”：
1. 材料化出来的用户只是外键锚点：没有机构/项目成员身份，不能凭它拿到业务权限；
2. 匿名 legacy principal 的平台管理员身份只在 ``AUTH_MODE=optional`` 下成立；
3. 多 worker 同时首次材料化时，重复键冲突要走 savepoint 重试，而不是把整个事务打挂。

第 3 条在 SQLite 上验证重试分支，另在真实 PostgreSQL 上验证跨连接竞态（需 ``VNEXT_PG_URL``）。
"""

from __future__ import annotations

import os
import threading
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.models import Project, User
from app.services.auth import actors
from app.services.auth.dependencies import Principal
from app.services.auth.permission_service import PermissionService

PG_URL = os.environ.get("VNEXT_PG_URL", "").strip()


# ---------------------------------------------------------------- 1. 锚点用户没有业务权限


def test_materialised_actor_is_an_inert_foreign_key_anchor(db_session):
    first = actors.ensure_actor_user_id(db_session, None)
    second = actors.ensure_actor_user_id(db_session, None)
    assert first == second

    user = db_session.get(User, first)
    assert user.username == actors.LEGACY_SYSTEM_USERNAME
    assert user.status == "active"

    project = Project(name="P2A 锚点权限项目")
    db_session.add(project)
    db_session.flush()

    principal = Principal(first, user.username, user.display_name)
    service = PermissionService(db_session, principal)
    assert service.is_platform_admin() is False, "锚点用户不得因为用户名而成为平台管理员"
    assert service.capabilities()["can_manage_users"] is False
    with pytest.raises(HTTPException) as failure:
        service.require_project_permission(project.id, "business.edit")
    # 无成员身份时应“看不见”（404）或“无权限”（403），两者都表示拿不到业务权限。
    assert failure.value.status_code in {403, 404}


def test_existing_actor_id_is_returned_without_creating_the_anchor(db_session):
    user = User(username="p2a-real-actor", display_name="真实用户", status="active")
    db_session.add(user)
    db_session.flush()
    assert actors.ensure_actor_user_id(db_session, user.id) == user.id
    assert db_session.query(User).filter_by(username=actors.LEGACY_SYSTEM_USERNAME).count() == 0


# ---------------------------------------------------------------- 2. 只在 optional 模式授予 dev 管理员


def test_legacy_principal_is_platform_admin_only_in_optional_mode(db_session, monkeypatch):
    legacy = Principal(None, "legacy-system", "Legacy development mode", True)

    monkeypatch.setattr(
        "app.services.auth.permission_service.get_settings",
        lambda: SimpleNamespace(auth_mode="optional"),
    )
    assert PermissionService(db_session, legacy).is_platform_admin() is True

    monkeypatch.setattr(
        "app.services.auth.permission_service.get_settings",
        lambda: SimpleNamespace(auth_mode="required"),
    )
    assert PermissionService(db_session, legacy).is_platform_admin() is False, (
        "required 模式不得把匿名 principal 当成平台管理员"
    )
    assert PermissionService(db_session, legacy).capabilities()["can_manage_institutions"] is False


# ---------------------------------------------------------------- 3. 重复键竞态走重试


def _skip_first_lookup(monkeypatch):
    """第一次查不到锚点用户，模拟“另一个 worker 刚插入但本连接尚未看到”的窗口。"""

    real_select = actors.select
    state = {"calls": 0}

    def patched(*args, **kwargs):
        statement = real_select(*args, **kwargs)
        if state["calls"] == 0:
            state["calls"] += 1
            return statement.where(text("1 = 0"))
        return statement

    monkeypatch.setattr(actors, "select", patched)
    return state


def test_duplicate_actor_creation_is_retried_instead_of_crashing(db_session, monkeypatch):
    existing = User(username=actors.LEGACY_SYSTEM_USERNAME, display_name="Legacy system", status="active")
    db_session.add(existing)
    db_session.commit()
    existing_id = existing.id

    state = _skip_first_lookup(monkeypatch)
    actor_id = actors.ensure_actor_user_id(db_session, None)
    assert state["calls"] == 1, "前置查询应被执行一次（返回空）"
    assert actor_id == existing_id
    # savepoint 回滚后事务仍可用，否则后续业务查询会报 InFailedSqlTransaction
    assert db_session.scalar(text("SELECT COUNT(*) FROM users")) >= 1


# ---------------------------------------------------------------- 4. 真实 PostgreSQL 跨连接竞态


@pytest.mark.skipif(not PG_URL, reason="需要 VNEXT_PG_URL 指向隔离开发 PostgreSQL")
def test_real_postgres_race_converges_on_one_anchor_row(monkeypatch):
    engine = create_engine(PG_URL, pool_size=5, max_overflow=5, connect_args={"connect_timeout": 5})
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with Session(engine) as cleanup:
        cleanup.execute(text("DELETE FROM users WHERE username = :u"), {"u": actors.LEGACY_SYSTEM_USERNAME})
        cleanup.commit()

    holder = factory()
    winner = User(username=actors.LEGACY_SYSTEM_USERNAME, display_name="Legacy system", status="active")
    holder.add(winner)
    holder.commit()
    winner_id = winner.id

    try:
        results: list[int] = []
        errors: list[BaseException] = []

        def worker() -> None:
            session = factory()
            try:
                results.append(actors.ensure_actor_user_id(session, None))
                session.execute(text("SELECT 1"))  # 事务必须仍然可用
                session.commit()
            except BaseException as exc:  # pragma: no cover - 失败时用于断言
                errors.append(exc)
                session.rollback()
            finally:
                session.close()

        real_select = actors.select
        state = {"calls": 0}

        def patched(*args, **kwargs):
            statement = real_select(*args, **kwargs)
            state["calls"] += 1
            if state["calls"] <= 2:  # 每条连接各跳过首次查询
                return statement.where(text("1 = 0"))
            return statement

        monkeypatch.setattr(actors, "select", patched)

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        assert not errors, f"竞态未被安全处理: {errors!r}"
        assert results == [winner_id, winner_id]
        with Session(engine) as verify:
            assert verify.execute(
                text("SELECT COUNT(*) FROM users WHERE username = :u"), {"u": actors.LEGACY_SYSTEM_USERNAME}
            ).scalar_one() == 1
    finally:
        with Session(engine) as cleanup:
            cleanup.execute(text("DELETE FROM users WHERE username = :u"), {"u": actors.LEGACY_SYSTEM_USERNAME})
            cleanup.commit()
        holder.close()
        engine.dispose()
