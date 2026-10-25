"""项目级交付审计：哪些产物查过、结论是什么、哪些还没查。

三条固定行为：
1. 刚导出的产物 → `unchecked`（"导出成功"不等于"交付前查过"）；
2. 记录一次通过的检查 → `passed`，并带上结论时间与记录人；
3. 文件被替换后再记录 → `failed`，汇总里的 failed 必须涨。
"""

from __future__ import annotations

from pathlib import Path

from test_requirement_export_unified import _frozen_snapshot, _use_temp_storage
from test_requirement_snapshot_api import snapshot_api, snapshot_db  # noqa: F401  夹具复用


def _export(client, base: str, snapshot_id: int, *, format: str, layout: str) -> int:
    response = client.post(
        base + "/exports",
        data={"format": format, "layout": layout, "source_kind": "draft_snapshot", "source_id": str(snapshot_id)},
    )
    assert response.status_code == 200, response.text
    return int(response.headers["x-requirement-render-artifact-id"])


def _audit(client, project_id: int, **params) -> dict:
    query = "&".join(f"{key}={value}" for key, value in params.items())
    response = client.get(f"/projects/{project_id}/delivery-audit{('?' + query) if query else ''}")
    assert response.status_code == 200, response.text
    return response.json()


def test_fresh_artifact_is_unchecked_until_a_check_is_recorded(tmp_path: Path, monkeypatch, snapshot_api):
    client, db, project, field, req, _ = snapshot_api
    _use_temp_storage(tmp_path, monkeypatch)
    base = f"/projects/{project.id}/requirements/{req.id}"
    snapshot_id = _frozen_snapshot(client, base, req)
    artifact_id = _export(client, base, snapshot_id, format="xlsx", layout="survey")

    body = _audit(client, project.id)
    assert body["audit_version"] == "requirement-delivery-audit-v3"
    item = next(entry for entry in body["items"] if entry["artifact_id"] == artifact_id)
    assert item["state"] == "unchecked"
    assert item["latest_check"] is None
    assert item["file_sha256"]
    assert body["summary"]["unchecked"] >= 1

    recorded = client.post(base + f"/render-artifacts/{artifact_id}/delivery-checks")
    assert recorded.status_code == 200, recorded.text

    after = _audit(client, project.id)
    entry = next(entry for entry in after["items"] if entry["artifact_id"] == artifact_id)
    assert entry["state"] == "passed"
    assert entry["latest_check"]["verdict"] == "pass"
    assert entry["latest_check"]["created_at"]
    assert after["summary"]["passed"] == 1


def test_tampered_artifact_shows_failed_in_audit(tmp_path: Path, monkeypatch, snapshot_api):
    client, db, project, field, req, _ = snapshot_api
    _use_temp_storage(tmp_path, monkeypatch)
    base = f"/projects/{project.id}/requirements/{req.id}"
    snapshot_id = _frozen_snapshot(client, base, req)
    artifact_id = _export(client, base, snapshot_id, format="xlsx", layout="survey")

    from app.models import RequirementRenderArtifact
    from app.services.storage.factory import get_storage_service
    from sqlalchemy import select

    record = db.scalar(select(RequirementRenderArtifact).where(RequirementRenderArtifact.id == artifact_id))
    root = get_storage_service().root
    (root / record.storage_key).write_bytes(b"tampered-bytes")

    recorded = client.post(base + f"/render-artifacts/{artifact_id}/delivery-checks")
    assert recorded.status_code == 200, recorded.text
    assert recorded.json()["record"]["verdict"] == "fail"

    body = _audit(client, project.id)
    entry = next(item for item in body["items"] if item["artifact_id"] == artifact_id)
    assert entry["state"] == "failed"
    assert "integrity" in entry["latest_check"]["blocking_keys"]
    assert body["summary"]["failed"] == 1


def test_audit_respects_limit_and_only_ready_artifacts(tmp_path: Path, monkeypatch, snapshot_api):
    client, db, project, field, req, _ = snapshot_api
    _use_temp_storage(tmp_path, monkeypatch)
    base = f"/projects/{project.id}/requirements/{req.id}"
    snapshot_id = _frozen_snapshot(client, base, req)
    first = _export(client, base, snapshot_id, format="xlsx", layout="survey")
    second = _export(client, base, snapshot_id, format="docx", layout="standard")

    limited = _audit(client, project.id, limit=1)
    assert limited["summary"]["artifact_count"] == 1
    assert len(limited["items"]) == 1
    assert limited["items"][0]["artifact_id"] == second

    full = _audit(client, project.id)
    ids = {item["artifact_id"] for item in full["items"]}
    assert {first, second} <= ids
    assert all(item["format"] in {"xlsx", "docx"} for item in full["items"])


def test_audit_reports_replay_state_for_every_artifact(tmp_path: Path, monkeypatch, snapshot_api):
    """能不能复核：当前渲染器产物记 replayable，旧版渲染器记 historical，客户模板记 unsupported。

    这条不能靠"看起来对"：historical 与 unsupported 都必须出现在计数里，
    否则交付时没人知道这批文件当前代码已经重放不出来了。
    """

    client, db, project, field, req, _ = snapshot_api
    _use_temp_storage(tmp_path, monkeypatch)
    base = f"/projects/{project.id}/requirements/{req.id}"
    snapshot_id = _frozen_snapshot(client, base, req)
    survey = _export(client, base, snapshot_id, format="xlsx", layout="survey")
    docx = _export(client, base, snapshot_id, format="docx", layout="standard")

    from app.models import RequirementRenderArtifact
    from sqlalchemy import select

    row = db.scalar(select(RequirementRenderArtifact).where(RequirementRenderArtifact.id == survey))
    # 把它登记成"旧版渲染器产物"：版本号没有源码指纹后缀，与当前代码不一致。
    row.renderer_version = "survey-requirement-doc-v3"
    db.commit()

    body = _audit(client, project.id)
    survey_item = next(entry for entry in body["items"] if entry["artifact_id"] == survey)
    docx_item = next(entry for entry in body["items"] if entry["artifact_id"] == docx)

    assert survey_item["replay"]["state"] == "historical"
    assert survey_item["replay"]["label"].startswith("旧版渲染器产物")
    assert survey_item["replay"]["current_renderer_version"]
    assert docx_item["replay"]["state"] == "replayable"
    assert docx_item["replay"]["reason"] is None

    summary = body["summary"]
    assert summary["historical_replay"] == 1
    assert summary["replayable"] >= 1
    assert summary["unsupported_replay"] == 0
    # 重放风险与"查没查过"分开计数：没检查过就是没检查过，不会因为能重放变成已检查。
    assert survey_item["state"] == "unchecked"
    assert summary["checked"] == 0