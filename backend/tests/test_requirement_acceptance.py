"""一键验收：字节 / 结构 / 模板列 / 检查单，一次给结论并留痕。"""

from __future__ import annotations

from pathlib import Path

from test_requirement_export_unified import _frozen_snapshot, _use_temp_storage
from test_requirement_snapshot_api import snapshot_api, snapshot_db  # noqa: F401  注册夹具


def _export(client, project, requirement, *, fmt: str = "xlsx", layout: str = "survey") -> int:
    snapshot_id = _frozen_snapshot(client, f"/projects/{project.id}/requirements/{requirement.id}", requirement)
    response = client.post(
        f"/projects/{project.id}/requirements/{requirement.id}/exports",
        data={
            "format": fmt,
            "layout": layout,
            "source_kind": "draft_snapshot",
            "source_id": str(snapshot_id),
        },
    )
    assert response.status_code == 200, response.text
    return int(response.headers["x-requirement-render-artifact-id"])


def test_acceptance_run_passes_and_records_a_check(tmp_path, monkeypatch, snapshot_api) -> None:
    client, db, project, field, requirement, *_ = snapshot_api
    _use_temp_storage(tmp_path, monkeypatch)
    artifact_id = _export(client, project, requirement)

    response = client.post(
        f"/projects/{project.id}/requirements/{requirement.id}/render-artifacts/{artifact_id}/acceptance-run"
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["acceptance_version"] == "requirement-acceptance-v1"
    assert payload["verdict"] == "pass", payload
    assert [step["key"] for step in payload["steps"]] == ["artifact", "structure", "fidelity", "checklist"]
    assert payload["record"]["id"]
    assert payload["record"]["verdict"] == "pass"
    assert "不关闭缺口" in payload["note"]

    history = client.get(f"/projects/{project.id}/requirements/{requirement.id}/delivery-checks")
    assert history.status_code == 200
    assert history.json()["count"] == 1


def test_acceptance_run_appends_a_second_record(tmp_path, monkeypatch, snapshot_api) -> None:
    client, db, project, field, requirement, *_ = snapshot_api
    _use_temp_storage(tmp_path, monkeypatch)
    artifact_id = _export(client, project, requirement)
    url = f"/projects/{project.id}/requirements/{requirement.id}/render-artifacts/{artifact_id}/acceptance-run"

    first = client.post(url)
    second = client.post(url)
    assert first.status_code == 200 and second.status_code == 200
    assert first.json()["record"]["id"] != second.json()["record"]["id"]

    history = client.get(f"/projects/{project.id}/requirements/{requirement.id}/delivery-checks")
    assert history.json()["count"] == 2


def test_acceptance_run_rejects_tampered_bytes(tmp_path, monkeypatch, snapshot_api) -> None:
    client, db, project, field, requirement, *_ = snapshot_api
    _use_temp_storage(tmp_path, monkeypatch)
    artifact_id = _export(client, project, requirement)

    from app.models import RequirementRenderArtifact
    from app.services.storage.factory import get_storage_service

    record = db.get(RequirementRenderArtifact, artifact_id)
    Path(get_storage_service().root, record.storage_key).write_bytes(b"tampered")
    db.commit()

    response = client.post(
        f"/projects/{project.id}/requirements/{requirement.id}/render-artifacts/{artifact_id}/acceptance-run"
    )
    assert response.status_code == 404, response.text
    assert "完整性" in response.json()["detail"]


def test_acceptance_run_refuses_layout_it_cannot_check(tmp_path, monkeypatch, snapshot_api) -> None:
    """内置版式 xlsx 没有调研表结构：明确拒绝"不适用"，而不是把结构检查报成失败。"""

    client, db, project, field, requirement, *_ = snapshot_api
    _use_temp_storage(tmp_path, monkeypatch)
    artifact_id = _export(client, project, requirement, fmt="xlsx", layout="standard")

    response = client.post(
        f"/projects/{project.id}/requirements/{requirement.id}/render-artifacts/{artifact_id}/acceptance-run"
    )
    assert response.status_code == 422, response.text
    assert "layout_not_survey" in response.json()["detail"]
    # 不适用就不留痕：不能把"没跑过"写成"查过了"。
    history = client.get(f"/projects/{project.id}/requirements/{requirement.id}/delivery-checks")
    assert history.json()["count"] == 0


def test_acceptance_run_skips_fidelity_for_docx(tmp_path, monkeypatch, snapshot_api) -> None:
    client, db, project, field, requirement, *_ = snapshot_api
    _use_temp_storage(tmp_path, monkeypatch)
    artifact_id = _export(client, project, requirement, fmt="docx", layout="standard")

    response = client.post(
        f"/projects/{project.id}/requirements/{requirement.id}/render-artifacts/{artifact_id}/acceptance-run"
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    fidelity = next(step for step in payload["steps"] if step["key"] == "fidelity")
    assert fidelity["skipped"] is True
    assert payload["fidelity"] is None
