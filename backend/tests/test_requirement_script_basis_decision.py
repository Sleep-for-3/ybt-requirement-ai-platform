"""脚本依据滞后后的复核决定：只登记，不代替动作。"""

from __future__ import annotations

import pytest

from app.services.requirement_script_basis_decision import (
    DECISION_CHOICES,
    ScriptBasisDecisionError,
    decisions_for_project,
    record_decision,
)
from test_requirement_script_basis_diff import _script_version
from test_requirement_snapshot_api import snapshot_api, snapshot_db  # noqa: F401


def _versions(db, project):
    script, first = _script_version(db, project, file_name="YBT_T_1_5.sql", version_no=1)
    _, second = _script_version(db, project, file_name="YBT_T_1_5.sql", version_no=2)
    return script, first, second


def test_decision_requires_note_for_defer_and_rejects_unknown(snapshot_api):
    _client, db, project, _field, req, _membership = snapshot_api
    script, first, second = _versions(db, project)

    with pytest.raises(ScriptBasisDecisionError) as missing:
        record_decision(
            db,
            project_id=project.id,
            requirement_id=req.id,
            script_file_id=script.id,
            frozen_version_id=first.id,
            latest_version_id=second.id,
            decision="defer",
            note="   ",
            actor_id=None,
        )
    assert missing.value.code == "note_required"

    with pytest.raises(ScriptBasisDecisionError) as unknown:
        record_decision(
            db,
            project_id=project.id,
            requirement_id=req.id,
            script_file_id=script.id,
            frozen_version_id=first.id,
            latest_version_id=second.id,
            decision="whatever",
            note=None,
            actor_id=None,
        )
    assert unknown.value.code == "decision_unknown"
    assert set(DECISION_CHOICES) == {"follow_planned", "defer", "reject_change"}


def test_decision_upserts_and_can_be_queried(snapshot_api):
    _client, db, project, _field, req, _membership = snapshot_api
    script, first, second = _versions(db, project)

    row, created = record_decision(
        db,
        project_id=project.id,
        requirement_id=req.id,
        script_file_id=script.id,
        frozen_version_id=first.id,
        latest_version_id=second.id,
        decision="follow_planned",
        note=None,
        actor_id=None,
    )
    assert created is True
    assert row.decision == "follow_planned"
    assert (req.id, script.id, second.id) in decisions_for_project(db, project.id)

    # 同一 (需求, 脚本, 最新版本) 重复登记只更新，不新增行——否则决定会越攒越多、无法判断哪个有效。
    again, created_again = record_decision(
        db,
        project_id=project.id,
        requirement_id=req.id,
        script_file_id=script.id,
        frozen_version_id=first.id,
        latest_version_id=second.id,
        decision="defer",
        note="脚本改动只是补了一条非空过滤，旧口径仍成立",
        actor_id=None,
    )
    assert created_again is False
    assert again.id == row.id
    assert again.decision == "defer"
    assert again.note.startswith("脚本改动只是补了一条非空过滤")


def test_freshness_marks_requirement_fully_decided(snapshot_api, monkeypatch):
    from app.services import requirement_delivery_status as status_module

    _client, db, project, _field, req, _membership = snapshot_api
    script, first, second = _versions(db, project)

    def fake_content(_db, row):
        return {
            "target_table": {"table_code": "T_1_5"},
            "script_basis": {
                "versions": [
                    {
                        "id": first.id,
                        "script_file_id": script.id,
                        "version_no": 1,
                        "parse_status": "parsed",
                        "path": "YBT_T_1_5.sql",
                    }
                ]
            },
        }

    monkeypatch.setattr(status_module, "document_content", fake_content)

    before = status_module.build_script_basis_freshness(db, project.id)
    item = next(row for row in before["items"] if row["requirement_id"] == req.id)
    assert item["state"] == "script_updated"
    assert item["fully_decided"] is False
    assert before["summary"].get("decided_requirements", 0) == 0

    record_decision(
        db,
        project_id=project.id,
        requirement_id=req.id,
        script_file_id=script.id,
        frozen_version_id=first.id,
        latest_version_id=second.id,
        decision="defer",
        note="已核对：只加了一条非空过滤，不影响本需求口径",
        actor_id=None,
    )
    db.commit()

    after = status_module.build_script_basis_freshness(db, project.id)
    item = next(row for row in after["items"] if row["requirement_id"] == req.id)
    assert item["decided_version_count"] == 1
    assert item["fully_decided"] is True
    assert item["versions"][0]["decision"]["decision"] == "defer"
    assert after["summary"]["decided_requirements"] == 1


def test_decision_endpoint_requires_edit_permission(snapshot_api):
    client, db, project, _field, req, membership = snapshot_api
    script, first, second = _versions(db, project)
    body = {
        "script_file_id": script.id,
        "frozen_version_id": first.id,
        "latest_version_id": second.id,
        "decision": "follow_planned",
    }

    membership.project_role = "viewer"
    db.commit()
    denied = client.post(f"/projects/{project.id}/requirements/{req.id}/script-basis-decisions", json=body)
    assert denied.status_code == 403, denied.text

    membership.project_role = "project_manager"
    db.commit()
    ok = client.post(f"/projects/{project.id}/requirements/{req.id}/script-basis-decisions", json=body)
    assert ok.status_code == 200, ok.text
    payload = ok.json()
    assert payload["created"] is True
    assert payload["decision"]["decision"] == "follow_planned"

    missing_note = client.post(
        f"/projects/{project.id}/requirements/{req.id}/script-basis-decisions",
        json={**body, "decision": "defer"},
    )
    assert missing_note.status_code == 422
    assert "原因" in missing_note.json()["detail"]
