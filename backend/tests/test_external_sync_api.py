"""P2-B 外部同步落库：幂等、游标单调、只产生待复核。

这些用例守的是"外部系统不能直接改写需求"这条边界：无论事件重复、乱序、重放、
删除还是权限变化，平台只记账 + 待复核，不产生任何自动应用动作。

夹具复用 `snapshot_db` / `fixture` 的隔离库，但挂自己的 app——因为 `snapshot_api`
只包含 requirements 路由，而同步入口是独立 router。
"""

from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.external_sync import router
from app.core.database import get_db
from app.models import ProjectMembership, User
from app.services.auth.dependencies import Principal, get_current_principal
from app.services.auth.resource_guard import guard_project_resource
from test_requirement_draft_snapshots import fixture
from test_requirement_snapshot_api import snapshot_db  # noqa: F401  (共用隔离库夹具)

EVENTS_URL = "/projects/{pid}/external-sync/events"
PENDING_URL = "/projects/{pid}/external-sync/pending"
CURSORS_URL = "/projects/{pid}/external-sync/cursors"


@pytest.fixture
def sync_api(snapshot_db):  # noqa: F811
    db_session = snapshot_db
    project, field, requirement, content = fixture(db_session)
    user = db_session.scalar(select(User))
    membership = ProjectMembership(project_id=project.id, user_id=user.id,
                                   project_role="project_manager", status="active")
    db_session.add(membership)
    db_session.flush()
    app = FastAPI()
    app.include_router(router, dependencies=[Depends(guard_project_resource)])
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_principal] = lambda: Principal(user.id, user.username, None)
    with TestClient(app) as client:
        yield client, db_session, project, membership


def _event(**overrides):
    base = {
        "source": "metadata-platform",
        "object_kind": "source_table",
        "object_key": "LOAN",
        "source_version": 1,
        "cursor": 10,
        "payload": {"name": "LOAN", "columns": 12},
        "observed_at": "2026-10-23T10:00:00+08:00",
    }
    base.update(overrides)
    return base


def test_new_versions_are_stored_as_pending_review(sync_api):
    client, db, project, _ = sync_api

    resp = client.post(EVENTS_URL.format(pid=project.id), json={
        "events": [_event(source_version=1, cursor=10), _event(source_version=2, cursor=11)],
    })
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["stored"] == 2
    assert body["duplicates"] == 0
    assert body["out_of_order"] == 0
    assert len(body["review_required"]) == 2
    assert {d["action"] for d in body["decisions"]} == {"pending_review"}
    assert body["cursors"] == {"metadata-platform": 11}
    for decision in body["decisions"]:
        assert "不自动改写需求" in decision["reason"]

    pending = client.get(PENDING_URL.format(pid=project.id)).json()
    assert pending["count"] == 2
    assert {item["decision"] for item in pending["items"]} == {"pending_review"}
    assert {item["source_version"] for item in pending["items"]} == {1, 2}

    cursors = client.get(CURSORS_URL.format(pid=project.id)).json()
    assert cursors["items"][0]["cursor"] == 11


def test_same_batch_twice_is_idempotent_and_adds_nothing(sync_api):
    client, db, project, _ = sync_api
    url = EVENTS_URL.format(pid=project.id)
    batch = {"events": [_event(source_version=1, cursor=10)]}

    first = client.post(url, json=batch).json()
    second = client.post(url, json=batch).json()

    assert first["stored"] == 1
    assert second["stored"] == 0
    assert second["duplicates"] == 1
    assert second["decisions"][0]["action"] == "skip_duplicate"
    assert client.get(PENDING_URL.format(pid=project.id)).json()["count"] == 1


def test_lower_version_is_out_of_order_and_not_stored(sync_api):
    client, db, project, _ = sync_api
    url = EVENTS_URL.format(pid=project.id)

    client.post(url, json={"events": [_event(source_version=3, cursor=12)]})
    resp = client.post(url, json={"events": [_event(source_version=2, cursor=13)]})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["stored"] == 0
    assert body["out_of_order"] == 1
    assert body["decisions"][0]["action"] == "skip_out_of_order"
    assert "旧于已知版本" in body["decisions"][0]["reason"]
    # 游标仍然前进：事件被处理过，不能让外部系统误以为平台卡住了。
    assert body["cursors"]["metadata-platform"] == 13
    assert client.get(PENDING_URL.format(pid=project.id)).json()["count"] == 1


def test_same_version_is_duplicate_not_a_new_review_item(sync_api):
    client, db, project, _ = sync_api
    url = EVENTS_URL.format(pid=project.id)

    client.post(url, json={"events": [_event(source_version=4, cursor=20)]})
    resp = client.post(url, json={"events": [_event(source_version=4, cursor=19)]}).json()
    assert resp["stored"] == 0
    # 同一来源版本的幂等身份相同，落库路径判为重复；重放裁决属契约层
    # （plan_sync 的 skip_replay 需要调用方提供对象版本，见
    #  tests/test_requirement_source_sync.py 的 plan_sync 用例）。
    assert resp["duplicates"] == 1
    assert resp["decisions"][0]["action"] == "skip_duplicate"
    assert client.get(PENDING_URL.format(pid=project.id)).json()["count"] == 1


def test_older_version_inside_one_batch_is_out_of_order(sync_api):
    """同批内同一对象的旧版本不能被当成新版本（曾因按裸 object_key 记版本而漏判）。"""

    client, db, project, _ = sync_api
    url = EVENTS_URL.format(pid=project.id)

    resp = client.post(url, json={"events": [
        _event(source_version=6, cursor=40),
        _event(source_version=5, cursor=41),
    ]}).json()
    assert resp["stored"] == 1
    assert resp["out_of_order"] == 1
    actions = [d["action"] for d in resp["decisions"]]
    assert actions == ["pending_review", "skip_out_of_order"]
    assert resp["cursors"]["metadata-platform"] == 41


def test_deleted_and_permission_changes_only_mark_pending(sync_api):
    client, db, project, _ = sync_api
    url = EVENTS_URL.format(pid=project.id)

    resp = client.post(url, json={"events": [
        _event(source_version=5, cursor=30, deleted=True),
        _event(source="script-repo", object_kind="script_version", object_key="daily_load",
               source_version=2, cursor=3, permissions_changed=True),
    ]}).json()
    assert resp["stored"] == 2
    assert resp["deletions"] == 1
    assert resp["permission_changes"] == 1
    actions = {d["action"] for d in resp["decisions"]}
    assert actions == {"mark_deleted_pending_review", "mark_permission_pending_review"}

    pending = client.get(PENDING_URL.format(pid=project.id), params={"source": "script-repo"}).json()
    assert pending["count"] == 1
    assert pending["items"][0]["permissions_changed"] is True


def test_invalid_batches_are_rejected_with_reason(sync_api):
    client, db, project, _ = sync_api
    url = EVENTS_URL.format(pid=project.id)

    empty = client.post(url, json={"events": []})
    assert empty.status_code == 422
    assert "事件列表为空" in empty.json()["detail"]

    missing = client.post(url, json={"events": [{"source": "x", "object_kind": "t", "source_version": 1, "cursor": 1}]})
    assert missing.status_code == 422
    assert "source/object_kind/object_key" in missing.json()["detail"]

    bad_version = client.post(url, json={"events": [_event(source_version="1")]})
    assert bad_version.status_code == 422
    assert "source_version" in bad_version.json()["detail"]

    too_many = client.post(url, json={"events": [_event(source_version=i, cursor=i) for i in range(201)]})
    assert too_many.status_code == 422
    assert "单批最多" in too_many.json()["detail"]

    not_list = client.post(url, json={"events": {"a": 1}})
    assert not_list.status_code == 422


def test_viewer_cannot_submit_but_can_read(sync_api):
    client, db, project, membership = sync_api
    url = EVENTS_URL.format(pid=project.id)

    assert client.post(url, json={"events": [_event()]}).status_code == 201
    membership.project_role = "viewer"
    db.commit()

    denied = client.post(url, json={"events": [_event(source_version=9, cursor=99)]})
    assert denied.status_code == 403
    assert client.get(PENDING_URL.format(pid=project.id)).status_code == 200
