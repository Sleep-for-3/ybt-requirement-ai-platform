"""统一导出入口（POST /exports）：带客户模板走模板渲染，不带模板走内置版式。

这把 P1-B 的"客户模板"和既有 `/export` 内置版式收进同一套渲染产物身份，
避免"两个入口两份字节"。固定四件事：

1. 不带模板时与旧 GET 端点返回**同一份字节和同一个产物 id**（不是两次渲染）；
2. 带模板时按模板渲染，响应头给出模板 hash；
3. 只给配置不给模板要被拒（不能对未上传的模板应用锚点映射）；
4. 冻结来源非法要被拒。
"""

from __future__ import annotations

import hashlib
import json
from io import BytesIO
from pathlib import Path

from docx import Document
from openpyxl import load_workbook

from app.services.requirement_survey_export import SURVEY_DOC_VERSION
from app.services.storage.factory import get_storage_service
from docx_template_fixtures import build_customer_template, customer_config
from test_requirement_snapshot_api import snapshot_api, snapshot_db  # noqa: F401  夹具复用

DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _use_temp_storage(tmp_path: Path, monkeypatch) -> Path:
    root = tmp_path / "storage"
    monkeypatch.setenv("STORAGE_DIR", str(root))
    get_storage_service.cache_clear()
    return root


def _frozen_snapshot(client, base: str, req) -> int:
    current = client.get(base + "/document").json()
    created = client.post(base + "/snapshots", json={
        "expected_version": req.version, "expected_hash": current["content_hash"]})
    assert created.status_code == 201, created.text
    return created.json()["id"]


def _form(snapshot_id: int, **overrides):
    payload = {"format": "docx", "source_kind": "draft_snapshot", "source_id": str(snapshot_id)}
    payload.update(overrides)
    return payload


def test_unified_builtin_export_matches_legacy_endpoint_bytes(tmp_path, monkeypatch, snapshot_api):
    client, db, project, field, req, _ = snapshot_api
    _use_temp_storage(tmp_path, monkeypatch)
    base = f"/projects/{project.id}/requirements/{req.id}"
    snapshot_id = _frozen_snapshot(client, base, req)

    unified = client.post(base + "/exports", data=_form(snapshot_id))
    legacy = client.get(base + f"/snapshots/{snapshot_id}/export?format=docx")

    assert unified.status_code == 200, unified.text
    assert legacy.status_code == 200, legacy.text
    assert unified.content == legacy.content
    assert (unified.headers["x-requirement-render-artifact-id"]
            == legacy.headers["x-requirement-render-artifact-id"]), "两个入口必须复用同一产物"
    assert Document(BytesIO(unified.content)).paragraphs, "产物必须是可打开的 docx"

    again = client.post(base + "/exports", data=_form(snapshot_id))
    assert again.content == unified.content
    assert again.headers["x-requirement-rendered-file-sha256"] == unified.headers["x-requirement-rendered-file-sha256"]

    listed = client.get(base + "/render-artifacts").json()
    assert len(listed) == 1, "同一渲染身份不应产生第二个产物"


def test_unified_export_with_customer_template(tmp_path, monkeypatch, snapshot_api):
    client, db, project, field, req, _ = snapshot_api
    _use_temp_storage(tmp_path, monkeypatch)
    base = f"/projects/{project.id}/requirements/{req.id}"
    snapshot_id = _frozen_snapshot(client, base, req)

    template = build_customer_template()
    config = customer_config(template)

    response = client.post(
        base + "/exports",
        data=_form(snapshot_id, config=json.dumps(config, ensure_ascii=False)),
        files={"template": ("客户需求模板.docx", template, DOCX_TYPE)},
    )
    assert response.status_code == 200, response.text
    assert response.headers["x-requirement-template-sha256"] == hashlib.sha256(template).hexdigest()
    assert response.headers["x-requirement-renderer-version"] == "customer-template-render-v1"

    text = "\n".join(paragraph.text for paragraph in Document(BytesIO(response.content)).paragraphs)
    assert "{{" not in text, "不得残留占位符"

    listed = client.get(base + "/render-artifacts").json()
    assert len(listed) == 1
    assert listed[0]["template_sha256"] == hashlib.sha256(template).hexdigest()


def test_config_without_template_is_rejected(tmp_path, monkeypatch, snapshot_api):
    client, db, project, field, req, _ = snapshot_api
    _use_temp_storage(tmp_path, monkeypatch)
    base = f"/projects/{project.id}/requirements/{req.id}"
    snapshot_id = _frozen_snapshot(client, base, req)

    response = client.post(base + "/exports", data=_form(snapshot_id, config='{"anchors": {}}'))
    assert response.status_code == 422
    assert "同时上传客户模板" in response.json()["detail"]


def test_invalid_source_kind_is_rejected(tmp_path, monkeypatch, snapshot_api):
    client, db, project, field, req, _ = snapshot_api
    _use_temp_storage(tmp_path, monkeypatch)
    base = f"/projects/{project.id}/requirements/{req.id}"

    response = client.post(base + "/exports", data=_form(1, source_kind="draft"))
    assert response.status_code == 422
    assert "draft_snapshot" in response.json()["detail"]


def test_missing_source_is_rejected(tmp_path, monkeypatch, snapshot_api):
    client, db, project, field, req, _ = snapshot_api
    _use_temp_storage(tmp_path, monkeypatch)
    base = f"/projects/{project.id}/requirements/{req.id}"

    response = client.post(base + "/exports", data=_form(9999))
    assert response.status_code in {404, 409}

def test_legacy_export_endpoints_are_marked_deprecated(tmp_path, monkeypatch, snapshot_api):
    """旧端点继续可用，但必须自报"已弃用"，把调用方导向统一入口。"""

    client, db, project, field, req, _ = snapshot_api
    _use_temp_storage(tmp_path, monkeypatch)
    base = f"/projects/{project.id}/requirements/{req.id}"
    snapshot_id = _frozen_snapshot(client, base, req)

    legacy = client.get(base + f"/snapshots/{snapshot_id}/export?format=docx")
    assert legacy.status_code == 200
    assert legacy.headers["deprecation"] == "true"
    assert legacy.headers["x-requirement-deprecated"].endswith("/requirements/{requirement_id}/exports")
    assert legacy.headers["x-requirement-render-artifact-id"]

    unified = client.post(base + "/exports", data=_form(snapshot_id, format="docx"))
    assert unified.status_code == 200
    assert "deprecation" not in unified.headers
    # 两条路径共用同一渲染身份：旧端点先把产物落库，统一入口直接复用。
    assert unified.headers["x-requirement-render-artifact-id"] == legacy.headers["x-requirement-render-artifact-id"]
    assert unified.content == legacy.content


def test_survey_layout_export_renders_survey_workbook(tmp_path, monkeypatch, snapshot_api):
    """一表通调研表式：只接受 xlsx，产物是"表级信息 + 按来源系统重复列组"的工作簿。"""

    client, db, project, field, req, _ = snapshot_api
    _use_temp_storage(tmp_path, monkeypatch)
    base = f"/projects/{project.id}/requirements/{req.id}"
    snapshot_id = _frozen_snapshot(client, base, req)

    response = client.post(
        base + "/exports", data=_form(snapshot_id, format="xlsx", layout="survey")
    )
    assert response.status_code == 200, response.text
    assert response.headers["x-requirement-renderer-version"].startswith(SURVEY_DOC_VERSION)
    workbook = load_workbook(BytesIO(response.content))
    sheet = workbook["需求文档"]
    assert sheet.cell(row=1, column=1).value == "返回目录"
    assert sheet.cell(row=3, column=1).value == "数据分类"
    titles = [sheet.cell(row=10, column=column).value for column in range(1, sheet.max_column + 1)]
    assert "一表通数据基础信息" in titles
    headers = [sheet.cell(row=11, column=column).value for column in range(1, sheet.max_column + 1)]
    assert "数据项编码" in headers and "来源系统" in headers
    # 重复导出复用同一产物，不二次渲染
    again = client.post(base + "/exports", data=_form(snapshot_id, format="xlsx", layout="survey"))
    assert again.content == response.content


def test_survey_layout_rejects_docx_and_unknown_layout(tmp_path, monkeypatch, snapshot_api):
    client, db, project, field, req, _ = snapshot_api
    _use_temp_storage(tmp_path, monkeypatch)
    base = f"/projects/{project.id}/requirements/{req.id}"
    snapshot_id = _frozen_snapshot(client, base, req)

    docx_survey = client.post(
        base + "/exports", data=_form(snapshot_id, format="docx", layout="survey")
    )
    assert docx_survey.status_code == 422
    assert "xlsx" in docx_survey.json()["detail"]

    unknown = client.post(base + "/exports", data=_form(snapshot_id, layout="fancy"))
    assert unknown.status_code == 422
    assert "standard" in unknown.json()["detail"]


def test_freeze_and_export_freezes_once_then_reuses_the_same_bytes(tmp_path, monkeypatch, snapshot_api):
    """冻结并导出：同一内容重复调用必须复用同一快照与同一产物（可复现、不堆快照）。"""

    client, db, project, field, req, _ = snapshot_api
    _use_temp_storage(tmp_path, monkeypatch)
    base = f"/projects/{project.id}/requirements/{req.id}"
    current = client.get(base + "/document").json()

    first = client.post(base + "/freeze-and-export", data={
        "format": "xlsx", "layout": "survey",
        "expected_version": str(req.version), "expected_hash": current["content_hash"]})
    assert first.status_code == 200, first.text
    assert first.headers["x-requirement-snapshot-created"] == "true"
    snapshot_id = first.headers["x-requirement-snapshot-id"]
    assert first.headers["x-requirement-snapshot-hash"] == current["content_hash"]

    second = client.post(base + "/freeze-and-export", data={
        "format": "xlsx", "layout": "survey",
        "expected_version": str(req.version), "expected_hash": current["content_hash"]})
    assert second.status_code == 200, second.text
    assert second.headers["x-requirement-snapshot-created"] == "false", "内容未变时不得重复冻结"
    assert second.headers["x-requirement-snapshot-id"] == snapshot_id
    assert second.content == first.content
    assert (second.headers["x-requirement-render-artifact-id"]
            == first.headers["x-requirement-render-artifact-id"])

    snapshots = client.get(base + "/snapshots").json()
    assert len(snapshots) == 1, "同一内容只应存在一个快照"
    artifacts = client.get(base + "/render-artifacts").json()
    assert len(artifacts) == 1

    # 用快照号重新导出也必须是同一字节：任何人拿到快照号都能复现这份文件。
    replay = client.post(base + "/exports", data={
        "format": "xlsx", "source_kind": "draft_snapshot", "source_id": snapshot_id, "layout": "survey"})
    assert replay.status_code == 200, replay.text
    assert replay.content == first.content
    assert open_workbook(first.content).active.max_row > 6, "survey 版式必须真的写出内容"


def open_workbook(data: bytes):
    from openpyxl import load_workbook

    return load_workbook(BytesIO(data))


def test_structure_check_verdicts_on_real_artifacts(tmp_path, monkeypatch, snapshot_api):
    """结构自检只看已落库字节：xlsx 由调查表式导出时必须 pass，Word 产物明确 422。"""

    client, db, project, field, req, _ = snapshot_api
    _use_temp_storage(tmp_path, monkeypatch)
    base = f"/projects/{project.id}/requirements/{req.id}"
    snapshot_id = _frozen_snapshot(client, base, req)

    xlsx = client.post(
        f"{base}/exports",
        data={
            "format": "xlsx",
            "source_kind": "draft_snapshot",
            "source_id": str(snapshot_id),
            "layout": "survey",
        },
    )
    assert xlsx.status_code == 200, xlsx.text
    artifact_id = int(xlsx.headers["x-requirement-render-artifact-id"])
    checked = client.get(
        f"{base}/render-artifacts/{artifact_id}/structure-check"
    )
    assert checked.status_code == 200, checked.text
    body = checked.json()
    assert body["verdict"] == "pass", body
    assert body["failed_keys"] == []
    assert body["field_rows"] >= 1
    assert body["check_version"] == "survey-structure-check-v1"
    assert body["artifact"]["id"] == artifact_id

    docx = client.post(
        f"{base}/exports",
        data={
            "format": "docx",
            "source_kind": "draft_snapshot",
            "source_id": str(snapshot_id),
            "layout": "standard",
        },
    )
    assert docx.status_code == 200, docx.text
    docx_artifact = int(docx.headers["x-requirement-render-artifact-id"])
    # Word 走内置版式契约：内置版式产物必须能自检通过，而不是一律 422。
    word_check = client.get(f"{base}/render-artifacts/{docx_artifact}/structure-check")
    assert word_check.status_code == 200, word_check.text
    word_body = word_check.json()
    assert word_body["verdict"] == "pass", word_body
    assert word_body["failed_keys"] == []
    assert word_body["check_version"] == "docx-structure-check-v1"
    assert word_body["contract"]["renderer_version"] == "builtin-docx-v1"
    assert word_body["artifact"]["format"] == "docx"


def test_freeze_and_export_rejects_stale_hash_and_illegal_layout(tmp_path, monkeypatch, snapshot_api):
    client, db, project, field, req, _ = snapshot_api
    _use_temp_storage(tmp_path, monkeypatch)
    base = f"/projects/{project.id}/requirements/{req.id}"
    stale = "0" * 64

    rejected = client.post(base + "/freeze-and-export", data={
        "format": "xlsx", "layout": "survey",
        "expected_version": str(req.version), "expected_hash": stale})
    assert rejected.status_code == 409, rejected.text
    assert client.get(base + "/snapshots").json() == [], "校验失败不得留下快照"

    current = client.get(base + "/document").json()
    for payload, message in (
        ({"format": "docx", "layout": "survey"}, "一表通调研表式只支持 xlsx"),
        ({"format": "xlsx", "layout": "poster"}, "导出布局只能是"),
    ):
        bad = client.post(base + "/freeze-and-export", data={
            **payload, "expected_version": str(req.version), "expected_hash": current["content_hash"]})
        assert bad.status_code == 422, bad.text
        assert message in bad.text
    assert client.get(base + "/snapshots").json() == []


def test_cross_origin_export_response_exposes_artifact_headers():
    """浏览器读不到这些响应头时，导出文件名会退化成默认值、产物身份也拿不到。

    真实缺陷：3010 的前端调 8011 的导出接口，CORSMiddleware 没有 expose_headers，
    浏览器 JS 读 content-disposition 得到 null，下载文件被命名为"需求文档.docx"，
    而实际内容是 xlsx —— 用户会拿到一个打不开的文件，且看不出为什么。
    """
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    response = client.get("/api/health", headers={"Origin": "http://127.0.0.1:3010"})
    exposed = response.headers.get("access-control-expose-headers", "")
    for header in (
        "Content-Disposition",
        "X-Requirement-Render-Artifact-Id",
        "X-Requirement-Rendered-File-Sha256",
        "X-Requirement-Renderer-Version",
        "X-Requirement-Snapshot-Hash",
        # 冻结并导出的快照身份头：少 expose 任何一个，界面都会显示"快照 #未返回"。
        "X-Requirement-Snapshot-Id",
        "X-Requirement-Snapshot-Created",
        # 批量导出的身份头：少 expose 任何一个，界面就显示不出条目数与压缩包哈希。
        "X-Requirement-Batch-Items",
        "X-Requirement-Batch-Snapshots-Created",
        "X-Requirement-Batch-File-Sha256",
    ):
        assert header in exposed


def test_snapshot_list_marks_only_the_latest_snapshot(snapshot_api):
    """快照列表要能回答"当前内容是否冻结在最近那份里"：只有最近一份标 is_latest。"""

    client, _db, project, _field, req, _membership = snapshot_api
    base = f"/projects/{project.id}/requirements/{req.id}"
    first = client.get(base + "/document").json()
    created = client.post(base + "/snapshots", json={
        "expected_version": req.version, "expected_hash": first["content_hash"]})
    assert created.status_code == 201, created.text
    first_id = created.json()["id"]

    # 制造第二份快照：改一个字段的业务定义后再冻结（content_hash 必须变，否则会被去重复用）。
    field_id = first["fields"][0]["field"]["id"]
    # 合成夹具的需求是"遗留需求"（没有 revision），真实工作台也是先建修订再编辑内容。
    revision = client.post(f"{base}/revisions", json={"expected_version": req.version})
    assert revision.status_code in (200, 201), revision.text
    prepared = client.get(base + "/document").json()
    content_version = (prepared.get("revision") or {}).get("content_version")
    assert content_version and content_version > 0, prepared.get("requirement")
    edited = client.put(f"{base}/fields/{field_id}", json={
        "expected_content_version": content_version,
        "section": "business",
        "changes": {"business_definition": "快照列表标记用的第二版口径"},
    })
    assert edited.status_code == 200, edited.text
    refreshed = client.get(base + "/document").json()
    assert refreshed["content_hash"] != first["content_hash"], "改口径后内容 hash 必须变化"
    second = client.post(base + "/snapshots", json={
        "expected_version": refreshed["requirement"]["version"],
        "expected_hash": refreshed["content_hash"]})
    assert second.status_code == 201, second.text
    second_id = second.json()["id"]

    items = client.get(base + "/snapshots").json()
    assert [item["is_latest"] for item in items] == [True, False]
    assert [item["id"] for item in items] == [second_id, first_id], "最新的排在最前"
    # 最近那份与当前内容一致；旧快照能看出落后（同一份 content_hash 判据）。
    assert items[0]["content_hash"] == refreshed["content_hash"]
    assert items[1]["content_hash"] == first["content_hash"]


def test_snapshot_content_endpoint_returns_frozen_payload(tmp_path, monkeypatch, snapshot_api):
    """快照内容只读接口：评审要能回答"上次冻结的那份里这个字段写的是什么"。"""

    client, db, project, field, req, _ = snapshot_api
    _use_temp_storage(tmp_path, monkeypatch)
    base = f"/projects/{project.id}/requirements/{req.id}"
    current = client.get(base + "/document").json()
    frozen = client.post(base + "/snapshots", json={
        "expected_version": req.version, "expected_hash": current["content_hash"]})
    assert frozen.status_code == 201, frozen.text
    snapshot_id = frozen.json()["id"]

    payload = client.get(f"{base}/snapshots/{snapshot_id}/content")
    assert payload.status_code == 200, payload.text
    body = payload.json()
    assert body["id"] == snapshot_id
    assert body["content"]["fields"], "冻结内容必须包含字段"
    assert body["content_hash"] == body["content_hash"] and len(body["content_hash"]) == 64

    missing = client.get(f"{base}/snapshots/9999/content")
    assert missing.status_code == 404
