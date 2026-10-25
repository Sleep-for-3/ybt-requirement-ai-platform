"""交付稳定性核对：同一冻结内容重放一次，字节必须一致；不一致要分清是谁变了。"""

from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy import select

from app.models import RequirementDelivery  # noqa: F401  快照模型在此模块导入链里
from app.models.requirement_render import RequirementRenderArtifact
from app.services import requirement_export_stability as stability
from test_requirement_acceptance import _export
from test_requirement_export_unified import _use_temp_storage
from test_requirement_snapshot_api import snapshot_api, snapshot_db  # noqa: F401  注册夹具


def _artifact(db, artifact_id: int) -> RequirementRenderArtifact:
    return db.scalar(select(RequirementRenderArtifact).where(RequirementRenderArtifact.id == artifact_id))


def test_survey_artifact_replays_byte_identical(tmp_path, monkeypatch, snapshot_api) -> None:
    client, db, project, field, requirement, *_ = snapshot_api
    _use_temp_storage(tmp_path, monkeypatch)
    artifact_id = _export(client, project, requirement)

    payload = stability.build_stability(db, project.id, limit=5)
    assert payload["stability_version"] == "requirement-export-stability-v1"
    assert payload["summary"]["artifacts"] == 1
    assert payload["summary"]["identical"] == 1, payload
    assert payload["verdict"] == "stable"
    item = payload["items"][0]
    assert item["artifact_id"] == artifact_id
    assert item["status"] == "identical"
    assert item["replay_sha256"] == item["stored_sha256"]
    assert payload["status_labels"]["identical"] == "重放一致"
    assert "不写库" in payload["note"]


def test_renderer_drift_is_reported_not_hidden(tmp_path, monkeypatch, snapshot_api) -> None:
    """内容没变、字节变了 = 渲染器改了没升版本；这是最该被抓住的一类。"""

    client, db, project, field, requirement, *_ = snapshot_api
    _use_temp_storage(tmp_path, monkeypatch)
    artifact_id = _export(client, project, requirement)

    original = stability.replay_bytes

    def drifted(db_session, artifact, kind):
        return original(db_session, artifact, kind) + b"\x00"

    monkeypatch.setattr(stability, "replay_bytes", drifted)
    payload = stability.build_stability(db, project.id, limit=5)
    item = payload["items"][0]
    assert item["artifact_id"] == artifact_id
    assert item["status"] == "renderer_drift"
    assert "没有升版本" in item["reason"]
    assert payload["summary"]["renderer_drift"] == 1
    assert payload["verdict"] == "attention"
    assert payload["drift_artifacts"] == [artifact_id]


def test_changed_snapshot_content_is_content_drift(tmp_path, monkeypatch, snapshot_api) -> None:
    """快照内容被人改过（摘要与登记时不同）→ 报 content_changed，不能算"渲染器漂移"。"""

    client, db, project, field, requirement, *_ = snapshot_api
    _use_temp_storage(tmp_path, monkeypatch)
    artifact_id = _export(client, project, requirement)

    original = stability.load_frozen_draft

    def drifted_snapshot(db_session, project_id, requirement_id, snapshot_id):
        row = original(db_session, project_id, requirement_id, snapshot_id)
        clone = SimpleNamespace(content_json=row.content_json, content_hash="f" * 64)
        return clone

    monkeypatch.setattr(stability, "load_frozen_draft", drifted_snapshot)
    payload = stability.build_stability(db, project.id, limit=5)
    item = payload["items"][0]
    assert item["status"] == "content_changed", item["reason"]
    assert "快照" in item["reason"]
    assert payload["summary"]["content_changed"] == 1
    assert payload["verdict"] == "attention"


def test_customer_template_artifact_is_unsupported_not_passed(tmp_path, monkeypatch, snapshot_api) -> None:
    client, db, project, field, requirement, *_ = snapshot_api
    _use_temp_storage(tmp_path, monkeypatch)
    artifact_id = _export(client, project, requirement)
    artifact = _artifact(db, artifact_id)
    artifact.renderer_version = "customer-template-render-v1"
    artifact.template_sha256 = "a" * 64
    db.commit()

    payload = stability.build_stability(db, project.id, limit=5)
    item = payload["items"][0]
    assert item["status"] == "unsupported"
    assert "模板" in item["reason"]
    assert payload["summary"]["identical"] == 0
    assert payload["verdict"] == "stable"  # 不支持重放既不算通过也不算失败


def test_endpoint_returns_project_scope(tmp_path, monkeypatch, snapshot_api) -> None:
    client, db, project, field, requirement, *_ = snapshot_api
    _use_temp_storage(tmp_path, monkeypatch)
    artifact_id = _export(client, project, requirement)

    response = client.get(f"/projects/{project.id}/export-stability?limit=5")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["project_id"] == project.id
    assert body["items"][0]["artifact_id"] == artifact_id
    assert body["items"][0]["status"] == "identical"

    bad = client.get(f"/projects/{project.id}/export-stability?limit=0")
    assert bad.status_code in (404, 422), bad.text

    scoped = client.get(f"/projects/{project.id}/export-stability?requirement_id={requirement.id}")
    assert scoped.status_code == 200
    assert scoped.json()["requirement_id"] == requirement.id

def test_older_renderer_version_is_historical_not_drift(tmp_path, monkeypatch, snapshot_api) -> None:
    """旧版渲染器产物不能拿当前代码重放：当漂移报会冒出大量假警。"""

    client, db, project, field, requirement, *_ = snapshot_api
    _use_temp_storage(tmp_path, monkeypatch)
    artifact_id = _export(client, project, requirement)
    artifact = _artifact(db, artifact_id)
    original = artifact.renderer_version
    artifact.renderer_version = "survey-requirement-doc-v6"
    db.commit()

    payload = stability.build_stability(db, project.id, limit=5)
    item = payload["items"][0]
    assert item["status"] == "historical", item
    assert original in item["reason"]
    assert "survey-requirement-doc-v6" in item["reason"]
    assert payload["summary"]["historical"] == 1
    assert payload["summary"]["renderer_drift"] == 0
    assert payload["verdict"] == "stable"
