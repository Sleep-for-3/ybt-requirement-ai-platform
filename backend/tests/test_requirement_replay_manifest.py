"""交付复核清单测试：三态判定、筛选、facets、只读、端点。"""

from __future__ import annotations

from app.models.entities import TargetTable
from app.models.requirement_render import RequirementRenderArtifact
from app.services.requirement_export_stability import BUILTIN_DOCX, BUILTIN_XLSX, current_renderer_version
from app.services.requirement_replay_manifest import (
    MANIFEST_VERSION,
    build_replay_manifest,
    manifest_state,
)
from test_requirement_acceptance import _export
from test_requirement_export_unified import _use_temp_storage
from test_requirement_snapshot_api import snapshot_api, snapshot_db  # noqa: F401  注册夹具


def _project_with_table(client, db, project, requirement):
    """在夹具建好的需求上补监管表与需求名，便于按表/需求检索。"""

    artifact_id = _export(client, project, requirement)
    table = TargetTable(project_id=project.id, table_code="T_9_9", table_name="复核清单测试表")
    db.add(table)
    db.flush()
    requirement.scope_json = {**dict(requirement.scope_json or {}), "target_table_id": int(table.id)}
    requirement.name = "复核清单演示需求"
    db.commit()
    return artifact_id


def _add_template_artifact(db, requirement_id: int, project_id: int, source_id: int, content_hash: str):
    """加一份客户模板产物：这类本来就不支持字节重放。"""

    row = RequirementRenderArtifact(
        project_id=project_id,
        requirement_id=requirement_id,
        render_identity="manifest-demo-customer-template",
        source_kind="draft_snapshot",
        source_id=source_id,
        format="docx",
        file_name="复核清单-客户模板.docx",
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        file_sha256="0" * 64,
        file_size=1024,
        storage_key="",
        storage_backend="local",
        status="ready",
        content_hash=content_hash,
        renderer_version="customer-template-render-v1",
        template_sha256="a" * 64,
        config_version="",
    )
    db.add(row)
    db.commit()
    return row


def test_manifest_lists_three_states(tmp_path, monkeypatch, snapshot_api) -> None:
    client, db, project, field, requirement, *_ = snapshot_api
    _use_temp_storage(tmp_path, monkeypatch)
    artifact_id = _project_with_table(client, db, project, requirement)

    exported = db.get(RequirementRenderArtifact, artifact_id)
    exported.renderer_version = "survey-requirement-doc-v3"  # 旧版渲染器
    db.commit()
    client_row = _add_template_artifact(db, requirement.id, project.id, int(exported.source_id), exported.content_hash)

    payload = build_replay_manifest(db, project.id)

    assert payload["manifest_version"] == MANIFEST_VERSION
    assert payload["summary"]["artifacts"] == 2
    assert payload["summary"]["replayable"] == 0
    assert payload["summary"]["historical"] == 1
    assert payload["summary"]["unsupported"] == 1

    by_id = {item["artifact_id"]: item for item in payload["items"]}
    assert by_id[artifact_id]["replay_state"] == "historical"
    assert by_id[artifact_id]["replay_reason"] == "renderer_version_superseded"
    assert by_id[artifact_id]["renderer_matches_current"] is False
    assert by_id[artifact_id]["current_renderer_version"] == current_renderer_version(exported)
    assert by_id[client_row.id]["replay_state"] == "unsupported"
    assert by_id[client_row.id]["replay_reason"] == "template_not_replayable"

    # 需求名与监管表码要带得出来，否则"哪个需求、哪张表受影响"查不到。
    assert by_id[artifact_id]["requirement_name"] == "复核清单演示需求"
    assert by_id[artifact_id]["target_table_code"] == "T_9_9"

    assert payload["facets"]["by_table"] == [{"target_table_code": "T_9_9", "count": 2}]
    assert {row["requirement_id"] for row in payload["facets"]["by_requirement"]} == {requirement.id}
    renderer_facets = {(row["renderer_version"], row["replay_state"]) for row in payload["facets"]["by_renderer"]}
    assert ("survey-requirement-doc-v3", "historical") in renderer_facets
    assert ("customer-template-render-v1", "unsupported") in renderer_facets


def test_manifest_filters(tmp_path, monkeypatch, snapshot_api) -> None:
    client, db, project, field, requirement, *_ = snapshot_api
    _use_temp_storage(tmp_path, monkeypatch)
    artifact_id = _project_with_table(client, db, project, requirement)

    exported = db.get(RequirementRenderArtifact, artifact_id)
    exported.renderer_version = "survey-requirement-doc-v3"
    db.commit()
    _add_template_artifact(db, requirement.id, project.id, int(exported.source_id), exported.content_hash)

    historical_only = build_replay_manifest(db, project.id, state="historical")
    assert historical_only["summary"]["matched"] == 1
    assert historical_only["items"][0]["artifact_id"] == artifact_id
    # 筛选只影响返回行：全量计数照旧（没有可复核的、1 份历史、1 份不支持）。
    assert historical_only["summary"]["artifacts"] == 2
    assert historical_only["summary"]["unsupported"] == 1

    assert build_replay_manifest(db, project.id, requirement_id=requirement.id)["summary"]["matched"] == 2
    assert build_replay_manifest(db, project.id, keyword="T_9_9")["summary"]["matched"] == 2
    assert build_replay_manifest(db, project.id, keyword="客户模板")["summary"]["matched"] == 1
    assert build_replay_manifest(db, project.id, renderer="survey-requirement-doc-v3")["summary"]["matched"] == 1
    assert build_replay_manifest(db, project.id, renderer="builtin-docx")["summary"]["matched"] == 0
    assert build_replay_manifest(db, project.id, keyword="没有这个关键字")["summary"]["matched"] == 0

    assert build_replay_manifest(db, project.id, limit=0)["summary"]["returned"] == 2

    one_only = build_replay_manifest(db, project.id, limit=1)
    assert one_only["summary"]["returned"] == 1
    assert one_only["summary"]["truncated"] is True

    try:
        build_replay_manifest(db, project.id, state="not-a-state")
    except ValueError as failure:
        assert "未知的复核状态" in str(failure)
    else:  # pragma: no cover - 只有实现退化时才会走到
        raise AssertionError("非法 state 必须报错")


def test_manifest_is_read_only(tmp_path, monkeypatch, snapshot_api) -> None:
    client, db, project, field, requirement, *_ = snapshot_api
    _use_temp_storage(tmp_path, monkeypatch)
    _project_with_table(client, db, project, requirement)

    before = db.query(RequirementRenderArtifact).count()
    payload = build_replay_manifest(db, project.id)
    assert payload["items"]
    assert db.query(RequirementRenderArtifact).count() == before
    assert "不读文件、不重放、不写库" in payload["note"]


def test_manifest_state_matches_audit(tmp_path, monkeypatch, snapshot_api) -> None:
    client, db, project, field, requirement, *_ = snapshot_api
    _use_temp_storage(tmp_path, monkeypatch)
    artifact_id = _project_with_table(client, db, project, requirement)

    artifact = db.get(RequirementRenderArtifact, artifact_id)
    assert manifest_state(artifact) == ("replayable", "")

    artifact.renderer_version = "survey-requirement-doc-v2"
    db.commit()
    assert manifest_state(artifact) == ("historical", "renderer_version_superseded")

    artifact.renderer_version = "customer-template-render-v1"
    artifact.template_sha256 = "b" * 64
    db.commit()
    assert manifest_state(artifact) == ("unsupported", "template_not_replayable")

    artifact.renderer_version = BUILTIN_XLSX
    artifact.template_sha256 = ""
    db.commit()
    assert manifest_state(artifact) == ("replayable", "")

    artifact.format = "docx"
    artifact.renderer_version = BUILTIN_DOCX
    db.commit()
    assert manifest_state(artifact) == ("replayable", "")


def test_manifest_endpoint(tmp_path, monkeypatch, snapshot_api) -> None:
    client, db, project, field, requirement, *_ = snapshot_api
    _use_temp_storage(tmp_path, monkeypatch)
    artifact_id = _project_with_table(client, db, project, requirement)

    response = client.get(f"/projects/{project.id}/replay-manifest")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["summary"]["artifacts"] >= 1
    assert any(item["artifact_id"] == artifact_id for item in body["items"])
    assert body["state_labels"]["historical"] == "仅旧渲染器可复核"

    filtered = client.get(f"/projects/{project.id}/replay-manifest", params={"keyword": "T_9_9"})
    assert filtered.status_code == 200
    assert filtered.json()["summary"]["matched"] >= 1

    invalid = client.get(f"/projects/{project.id}/replay-manifest", params={"state": "nope"})
    assert invalid.status_code == 422
    assert invalid.json()["detail"]["code"] == "manifest_filter_invalid"
