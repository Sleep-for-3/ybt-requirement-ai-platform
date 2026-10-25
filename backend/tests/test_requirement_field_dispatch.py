"""字段级派工与处置登记的用例。"""

from __future__ import annotations

import pytest

from app.services.requirement_field_dispatch import (
    DispatchError,
    dispatch_events_for_project,
    dispatches_for_project,
    record_dispatch,
)

from test_requirement_snapshot_api import snapshot_api, snapshot_db  # noqa: F401


def test_record_dispatch_upserts_and_lists(snapshot_api) -> None:
    _client, db, project, field, req, _membership = snapshot_api

    row, created = record_dispatch(
        db,
        project_id=project.id,
        requirement_id=req.id,
        field_id=field.id,
        owner="张三",
        status="in_progress",
        note="在等业务确认口径",
        created_by=1,
    )
    assert created is True
    assert row.status == "in_progress"
    assert row.status_label if hasattr(row, "status_label") else True
    mapping = dispatches_for_project(db, project.id)
    assert mapping[(req.id, field.id)]["owner"] == "张三"
    assert mapping[(req.id, field.id)]["status_label"] == "处理中"

    again, created_again = record_dispatch(
        db,
        project_id=project.id,
        requirement_id=req.id,
        field_id=field.id,
        owner="张三",
        status="done",
        note="口径已补齐，待复核",
        created_by=1,
    )
    assert created_again is False
    assert again.id == row.id
    assert again.status == "done"


def test_record_dispatch_rejects_bad_input(snapshot_api) -> None:
    _client, db, project, field, req, _membership = snapshot_api

    with pytest.raises(DispatchError) as unknown:
        record_dispatch(
            db,
            project_id=project.id,
            requirement_id=req.id,
            field_id=field.id,
            status="shipped",
        )
    assert unknown.value.code == "status_unknown"

    with pytest.raises(DispatchError) as note_required:
        record_dispatch(
            db,
            project_id=project.id,
            requirement_id=req.id,
            field_id=field.id,
            status="paused",
            note="   ",
        )
    assert note_required.value.code == "note_required"

    with pytest.raises(DispatchError) as missing:
        record_dispatch(
            db,
            project_id=project.id,
            requirement_id=req.id,
            field_id=999999,
            status="in_progress",
        )
    assert missing.value.code == "field_missing"


def test_dispatch_endpoint_requires_edit_permission(snapshot_api) -> None:
    client, db, project, field, req, membership = snapshot_api
    body = {
        "requirement_id": req.id,
        "field_id": field.id,
        "owner": "李四",
        "status": "in_progress",
        "note": "本周内补齐",
    }

    membership.project_role = "viewer"
    db.commit()
    denied = client.post(f"/projects/{project.id}/requirements-worklist/dispatch", json=body)
    assert denied.status_code == 403

    membership.project_role = "project_manager"
    db.commit()
    ok = client.post(f"/projects/{project.id}/requirements-worklist/dispatch", json=body)
    assert ok.status_code == 200, ok.text
    payload = ok.json()
    assert payload["owner"] == "李四"
    assert payload["status_label"] == "处理中"
    assert payload["created"] is True

    invalid = client.post(
        f"/projects/{project.id}/requirements-worklist/dispatch",
        json={**body, "status": "shipped"},
    )
    assert invalid.status_code == 422
    assert "未知的处置状态" in invalid.json()["detail"]

def test_dispatch_keeps_append_only_history(snapshot_api) -> None:
    _client, db, project, field, req, _membership = snapshot_api
    base = dict(
        project_id=project.id,
        requirement_id=req.id,
        field_id=field.id,
        created_by=1,
    )

    record_dispatch(db, owner="张三", status="in_progress", note="先看口径", **base)
    record_dispatch(db, owner="张三", status="done", note="已补齐，待复核", **base)
    # 完全相同的内容再登记一次不应产生新事件（避免刷屏与假活跃）。
    record_dispatch(db, owner="张三", status="done", note="已补齐，待复核", **base)

    history = dispatch_events_for_project(db, project.id)[(req.id, field.id)]
    assert [event["status"] for event in history] == ["done", "in_progress"], history
    assert history[0]["note"] == "已补齐，待复核"
    assert all(event["actor_id"] == 1 for event in history)

    mapping = dispatches_for_project(db, project.id)
    assert mapping[(req.id, field.id)]["history"] == history