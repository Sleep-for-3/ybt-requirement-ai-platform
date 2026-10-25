"""P1-A：正式导出产物冻结。

冻结的是“文件字节”，不是“能不能再渲一次”。这些用例固定四件事：

1. 同一渲染身份只渲染一次，重复下载返回同一份字节；
2. 换模板 / 换配置得到新产物，旧产物不被覆盖；
3. 产物文件被篡改或丢失时拒绝下载，而不是静默重渲染；
4. 产物记录可按冻结来源列出并按 id 下载。
"""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select

from app.models import RequirementRenderArtifact
from app.services.storage.factory import get_storage_service
from docx_template_fixtures import build_customer_template, customer_config
from test_requirement_snapshot_api import snapshot_api, snapshot_db  # noqa: F401  夹具复用

DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


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


def _files(template: bytes, name: str = "客户需求模板.docx"):
    return {"template": (name, template, DOCX_TYPE)}


def test_snapshot_docx_export_renders_once_and_repeats_identical(tmp_path, monkeypatch, snapshot_api):
    client, db, project, field, req, _ = snapshot_api
    _use_temp_storage(tmp_path, monkeypatch)
    base = f"/projects/{project.id}/requirements/{req.id}"
    snapshot_id = _frozen_snapshot(client, base, req)

    import app.services.requirement_word as word

    original = word.export_word
    calls: list[int] = []

    def counted(content):
        calls.append(1)
        return original(content)

    monkeypatch.setattr(word, "export_word", counted)

    first = client.get(base + f"/snapshots/{snapshot_id}/export?format=docx")
    second = client.get(base + f"/snapshots/{snapshot_id}/export?format=docx")
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.content == second.content
    assert len(calls) == 1, "第二次下载不应再次渲染"
    assert first.headers["x-requirement-render-artifact-id"] == second.headers["x-requirement-render-artifact-id"]
    assert len(first.headers["x-requirement-rendered-file-sha256"]) == 64

    listed = client.get(base + "/render-artifacts").json()
    assert len(listed) == 1
    assert listed[0]["format"] == "docx"
    assert listed[0]["source_kind"] == "draft_snapshot"
    assert listed[0]["source_id"] == snapshot_id
    assert listed[0]["file_sha256"] == first.headers["x-requirement-rendered-file-sha256"]

    by_id = client.get(base + f"/render-artifacts/{listed[0]['id']}/download")
    assert by_id.status_code == 200, by_id.text
    assert by_id.content == first.content
    assert by_id.headers["content-type"].startswith(DOCX_TYPE)


def test_snapshot_xlsx_export_is_stored_and_listed_separately(tmp_path, monkeypatch, snapshot_api):
    client, db, project, field, req, _ = snapshot_api
    _use_temp_storage(tmp_path, monkeypatch)
    base = f"/projects/{project.id}/requirements/{req.id}"
    snapshot_id = _frozen_snapshot(client, base, req)

    first = client.get(base + f"/snapshots/{snapshot_id}/export?format=xlsx")
    second = client.get(base + f"/snapshots/{snapshot_id}/export?format=xlsx")
    assert first.status_code == 200, first.text
    assert first.content == second.content
    assert first.headers["content-type"].startswith(XLSX_TYPE)

    listed = client.get(base + f"/render-artifacts?source_kind=draft_snapshot&source_id={snapshot_id}").json()
    assert [row["format"] for row in listed] == ["xlsx"]


def test_tampered_artifact_is_rejected_instead_of_rendered_again(tmp_path, monkeypatch, snapshot_api):
    client, db, project, field, req, _ = snapshot_api
    root = _use_temp_storage(tmp_path, monkeypatch)
    base = f"/projects/{project.id}/requirements/{req.id}"
    snapshot_id = _frozen_snapshot(client, base, req)

    exported = client.get(base + f"/snapshots/{snapshot_id}/export?format=docx")
    assert exported.status_code == 200, exported.text

    db.expire_all()
    row = db.scalars(select(RequirementRenderArtifact)).first()
    assert row is not None
    stored_path = root / row.storage_key
    assert stored_path.exists()
    stored_path.write_bytes(b"tampered-docx-bytes")

    blocked = client.get(base + f"/render-artifacts/{row.id}/download")
    assert blocked.status_code == 409
    assert "完整性校验失败" in blocked.json()["detail"]

    rerun = client.get(base + f"/snapshots/{snapshot_id}/export?format=docx")
    assert rerun.status_code == 409
    assert "完整性校验失败" in rerun.json()["detail"]


def test_template_change_creates_new_artifact_without_overwriting(tmp_path, monkeypatch, snapshot_api):
    client, db, project, field, req, _ = snapshot_api
    _use_temp_storage(tmp_path, monkeypatch)
    base = f"/projects/{project.id}/requirements/{req.id}"
    snapshot_id = _frozen_snapshot(client, base, req)

    plain = build_customer_template()
    split = build_customer_template(split_anchor=True)
    assert plain != split

    first = client.post(base + "/template-exports", files=_files(plain),
                        data={"format": "docx", "config": json.dumps(customer_config(plain), ensure_ascii=False),
                              "snapshot_id": snapshot_id})
    assert first.status_code == 200, first.text
    second = client.post(base + "/template-exports", files=_files(split),
                         data={"format": "docx", "config": json.dumps(customer_config(split), ensure_ascii=False),
                               "snapshot_id": snapshot_id})
    assert second.status_code == 200, second.text
    assert first.headers["x-requirement-render-artifact-id"] != second.headers["x-requirement-render-artifact-id"]
    assert first.headers["x-requirement-template-sha256"] != second.headers["x-requirement-template-sha256"]

    listed = client.get(base + f"/render-artifacts?source_kind=draft_snapshot&source_id={snapshot_id}").json()
    assert len(listed) == 2
    assert {row["template_sha256"] for row in listed} == {
        first.headers["x-requirement-template-sha256"], second.headers["x-requirement-template-sha256"]}
    for row in listed:
        assert row["status"] == "ready"


def test_customer_template_export_reuses_stored_bytes(tmp_path, monkeypatch, snapshot_api):
    client, db, project, field, req, _ = snapshot_api
    _use_temp_storage(tmp_path, monkeypatch)
    base = f"/projects/{project.id}/requirements/{req.id}"
    snapshot_id = _frozen_snapshot(client, base, req)
    template = build_customer_template()
    body = {"format": "docx", "config": json.dumps(customer_config(template), ensure_ascii=False),
            "snapshot_id": snapshot_id}

    first = client.post(base + "/template-exports", files=_files(template), data=body)
    second = client.post(base + "/template-exports", files=_files(template), data=body)
    assert first.status_code == 200 and second.status_code == 200
    assert first.content == second.content
    assert first.headers["x-requirement-render-artifact-id"] == second.headers["x-requirement-render-artifact-id"]
    assert len(first.headers["x-requirement-snapshot-hash"]) == 64

    listed = client.get(base + f"/render-artifacts?source_kind=draft_snapshot&source_id={snapshot_id}").json()
    assert len(listed) == 1
    assert listed[0]["template_sha256"] == first.headers["x-requirement-template-sha256"]
