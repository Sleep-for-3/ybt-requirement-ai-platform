"""交付前检查单：一份产物一次性回答"能不能交出去"。

固定四件事：
1. 真实产物（xlsx 调研表式 / docx 内置版式）四项全过 → verdict pass；
2. 文件被替换 → integrity 失败并进 blocking（不是"能打开就行"）；
3. 客户模板 Word → 结构项失败（内置契约不适用），verdict fail；
4. 不存在的产物 → 404。
"""

from __future__ import annotations

from pathlib import Path

from test_requirement_export_unified import _frozen_snapshot, _use_temp_storage
from test_requirement_snapshot_api import snapshot_api, snapshot_db  # noqa: F401  夹具复用


def _export(client, base: str, snapshot_id: int, *, format: str, layout: str) -> tuple[int, dict]:
    response = client.post(
        base + "/exports",
        data={"format": format, "layout": layout, "source_kind": "draft_snapshot", "source_id": str(snapshot_id)},
    )
    assert response.status_code == 200, response.text
    return int(response.headers["x-requirement-render-artifact-id"]), response.headers


def _checklist(client, base: str, artifact_id: int) -> dict:
    response = client.get(base + f"/render-artifacts/{artifact_id}/delivery-checklist")
    assert response.status_code == 200, response.text
    return response.json()


def test_checklist_passes_for_real_survey_xlsx(tmp_path: Path, monkeypatch, snapshot_api):
    client, db, project, field, req, _ = snapshot_api
    _use_temp_storage(tmp_path, monkeypatch)
    base = f"/projects/{project.id}/requirements/{req.id}"
    snapshot_id = _frozen_snapshot(client, base, req)
    artifact_id, headers = _export(client, base, snapshot_id, format="xlsx", layout="survey")

    body = _checklist(client, base, artifact_id)
    assert body["checklist_version"] == "requirement-delivery-checklist-v1"
    assert body["verdict"] == "pass", body
    assert body["blocking_keys"] == []
    keys = {item["key"]: item for item in body["checks"]}
    assert keys["integrity"]["ok"] is True
    assert keys["identity"]["ok"] is True
    assert keys["structure"]["ok"] is True
    assert body["artifact"]["file_sha256"] == headers["x-requirement-rendered-file-sha256"]
    assert body["artifact"]["id"] == artifact_id


def test_checklist_passes_for_builtin_docx(tmp_path: Path, monkeypatch, snapshot_api):
    client, db, project, field, req, _ = snapshot_api
    _use_temp_storage(tmp_path, monkeypatch)
    base = f"/projects/{project.id}/requirements/{req.id}"
    snapshot_id = _frozen_snapshot(client, base, req)
    artifact_id, _ = _export(client, base, snapshot_id, format="docx", layout="standard")

    body = _checklist(client, base, artifact_id)
    assert body["verdict"] == "pass", body
    assert {item["key"] for item in body["checks"]} >= {"integrity", "identity", "structure", "fields"}


def test_checklist_blocks_tampered_bytes(tmp_path: Path, monkeypatch, snapshot_api):
    from app.services.storage.factory import get_storage_service

    client, db, project, field, req, _ = snapshot_api
    _use_temp_storage(tmp_path, monkeypatch)
    base = f"/projects/{project.id}/requirements/{req.id}"
    snapshot_id = _frozen_snapshot(client, base, req)
    artifact_id, _ = _export(client, base, snapshot_id, format="xlsx", layout="survey")

    service = get_storage_service()
    stored = client.get(base + f"/render-artifacts/{artifact_id}/download")
    assert stored.status_code == 200
    # 直接把落库文件改掉：字节 sha256 与产物记录不一致
    from app.models import RequirementRenderArtifact
    from sqlalchemy import select

    record = db.scalar(select(RequirementRenderArtifact).where(RequirementRenderArtifact.id == artifact_id))
    (service.root / record.storage_key).write_bytes(b"tampered-checklist-bytes")

    body = _checklist(client, base, artifact_id)
    assert body["verdict"] == "fail"
    assert "integrity" in body["blocking_keys"]
    assert body["summary"]["blocking_failed"] >= 1


def test_checklist_rejects_customer_template_docx(tmp_path: Path, monkeypatch, snapshot_api):
    from docx_template_fixtures import build_customer_template, customer_config

    client, db, project, field, req, _ = snapshot_api
    _use_temp_storage(tmp_path, monkeypatch)
    base = f"/projects/{project.id}/requirements/{req.id}"
    snapshot_id = _frozen_snapshot(client, base, req)

    template = build_customer_template()
    config = customer_config(template)
    import json

    rendered = client.post(
        base + "/template-exports",
        files={"template": ("customer.docx", template, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        data={"format": "docx", "snapshot_id": str(snapshot_id), "config": json.dumps(config)},
    )
    assert rendered.status_code == 200, rendered.text
    artifact_id = int(rendered.headers["x-requirement-render-artifact-id"])

    body = _checklist(client, base, artifact_id)
    assert body["verdict"] == "fail"
    assert "structure" in body["blocking_keys"]
    structure = [item for item in body["checks"] if item["key"] == "structure"][0]
    assert "artifact_not_builtin_layout" in structure["detail"]


def test_checklist_404_for_unknown_artifact(tmp_path: Path, monkeypatch, snapshot_api):
    client, db, project, field, req, _ = snapshot_api
    _use_temp_storage(tmp_path, monkeypatch)
    base = f"/projects/{project.id}/requirements/{req.id}"
    missing = client.get(base + "/render-artifacts/999999/delivery-checklist")
    assert missing.status_code == 404


def test_recording_a_check_keeps_a_row_with_verdict_and_blocking_keys(tmp_path: Path, monkeypatch, snapshot_api):
    """检查结果必须能留痕：实时算一遍给结论，但审计要问"什么时候查过、当时过没过"。"""

    client, db, project, field, req, _ = snapshot_api
    _use_temp_storage(tmp_path, monkeypatch)
    base = f"/projects/{project.id}/requirements/{req.id}"
    snapshot_id = _frozen_snapshot(client, base, req)
    artifact_id, _ = _export(client, base, snapshot_id, format="xlsx", layout="survey")

    response = client.post(base + f"/render-artifacts/{artifact_id}/delivery-checks")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["checklist"]["verdict"] == "pass"
    record = body["record"]
    assert record["id"] > 0
    assert record["artifact_id"] == artifact_id
    assert record["verdict"] == "pass"
    assert record["blocking_keys"] == []
    assert record["checklist_version"] == "requirement-delivery-checklist-v1"
    assert record["created_at"]

    from app.models import RequirementDeliveryCheck

    rows = db.query(RequirementDeliveryCheck).filter_by(artifact_id=artifact_id).all()
    assert len(rows) == 1
    assert rows[0].verdict == "pass"


def test_history_lists_newest_first_and_records_every_check(tmp_path: Path, monkeypatch, snapshot_api):
    """每次检查都新增一行：把多次检查压成一行会丢掉"先前通过、后来失败"的转折。"""

    client, db, project, field, req, _ = snapshot_api
    _use_temp_storage(tmp_path, monkeypatch)
    base = f"/projects/{project.id}/requirements/{req.id}"
    snapshot_id = _frozen_snapshot(client, base, req)
    artifact_id, _ = _export(client, base, snapshot_id, format="xlsx", layout="survey")

    first = client.post(base + f"/render-artifacts/{artifact_id}/delivery-checks")
    assert first.status_code == 200, first.text
    second = client.post(base + f"/render-artifacts/{artifact_id}/delivery-checks")
    assert second.status_code == 200, second.text

    history = client.get(base + "/delivery-checks")
    assert history.status_code == 200, history.text
    payload = history.json()
    assert payload["count"] == 2
    ids = [item["id"] for item in payload["items"]]
    assert ids == sorted(ids, reverse=True)
    assert payload["items"][0]["artifact_id"] == artifact_id

    from app.models import RequirementDeliveryCheck

    assert db.query(RequirementDeliveryCheck).count() == 2


def test_recording_a_check_on_missing_artifact_is_404(snapshot_api):
    client, db, project, field, req, _ = snapshot_api
    base = f"/projects/{project.id}/requirements/{req.id}"
    response = client.post(base + "/render-artifacts/999999/delivery-checks")
    assert response.status_code == 404


def test_history_can_be_filtered_by_artifact(tmp_path: Path, monkeypatch, snapshot_api):
    """一次交付会有多个产物：审计问的是"这个文件查没查过"，不是"这条需求查过几次"。"""

    client, db, project, field, req, _ = snapshot_api
    _use_temp_storage(tmp_path, monkeypatch)
    base = f"/projects/{project.id}/requirements/{req.id}"
    snapshot_id = _frozen_snapshot(client, base, req)
    xlsx_id, _ = _export(client, base, snapshot_id, format="xlsx", layout="survey")
    docx_id, _ = _export(client, base, snapshot_id, format="docx", layout="standard")

    for artifact_id in (xlsx_id, docx_id):
        recorded = client.post(base + f"/render-artifacts/{artifact_id}/delivery-checks")
        assert recorded.status_code == 200, recorded.text

    all_checks = client.get(base + "/delivery-checks")
    assert all_checks.json()["count"] == 2

    only_docx = client.get(base + f"/delivery-checks?artifact_id={docx_id}")
    assert only_docx.status_code == 200, only_docx.text
    payload = only_docx.json()
    assert payload["artifact_id"] == docx_id
    assert payload["count"] == 1
    assert payload["items"][0]["artifact_id"] == docx_id

    unknown = client.get(base + "/delivery-checks?artifact_id=999999")
    assert unknown.status_code == 200
    assert unknown.json()["count"] == 0
