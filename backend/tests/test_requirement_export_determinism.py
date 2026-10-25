"""导出字节的跨秒确定性（P1-A 的真实缺口）。

真实事故（2026-10-24，项目 9 / 冻结快照 1）：同一冻结内容三次导出
`xlsx-standard`，文件大小都是 43489 字节，但 sha256 分别是
`3dbef3c1…`、`4c6a3570…`、`dbc3a675…`。根因是 openpyxl 把当前时间写进
`docProps/core.xml` 的 `dcterms:created/modified`，同时把时间写进 zip 条目头：
同一秒内两次渲染相同，跨秒就不同。旧测试「连续两次导出相同」正好落在同一秒里，
测不出这个缺陷。

因此这里分两层固定：

1. `normalize_office_bytes` 必须抹掉时间元素并固定 zip 条目时间（单元级）；
2. 真实冻结内容跨秒重新渲染必须字节一致（接口级，走真实存储服务）。

接口级用例会先删掉已存产物记录，强制走一次真实重渲染——这正是产物文件丢失后
重建的场景，也正是 P1-A「同一身份只渲一次」能成立的前提。
"""

from __future__ import annotations

import time
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from sqlalchemy import delete

from app.models import RequirementRenderArtifact
from app.services.office_determinism import FIXED_DATE_TIME, normalize_office_bytes
from app.services.requirement_survey_export import SURVEY_DOC_VERSION
from app.services.storage.factory import get_storage_service
from test_requirement_snapshot_api import snapshot_api, snapshot_db  # noqa: F401  夹具复用

SLEEP_SECONDS = 1.2
XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
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


def _drop_artifacts(db, requirement_id: int) -> None:
    """模拟产物记录丢失：删掉记录后下一次导出必须真的重渲染。"""
    db.execute(delete(RequirementRenderArtifact).where(
        RequirementRenderArtifact.requirement_id == requirement_id))
    db.commit()


def _export(client, base: str, snapshot_id: int, fmt: str, layout: str | None = None):
    data = {"format": fmt, "source_kind": "draft_snapshot", "source_id": str(snapshot_id)}
    if layout:
        data["layout"] = layout
    response = client.post(base + "/exports", data=data)
    assert response.status_code == 200, response.text
    return response.content, response.headers


def test_normalize_office_bytes_removes_clock_and_fixes_zip_time():
    stream = BytesIO()
    with ZipFile(stream, "w", ZIP_DEFLATED) as archive:
        archive.writestr(
            "docProps/core.xml",
            '<?xml version="1.0"?><cp:coreProperties>'
            '<dcterms:created xmlns:dcterms="http://purl.org/dc/terms/">2026-10-24T22:00:00Z</dcterms:created>'
            '<dcterms:modified xmlns:dcterms="http://purl.org/dc/terms/">2026-10-24T22:00:01Z</dcterms:modified>'
            '</cp:coreProperties>',
        )
        archive.writestr("word/document.xml", "<document/>")

    normalized = normalize_office_bytes(stream.getvalue())
    with ZipFile(BytesIO(normalized)) as archive:
        core = archive.read("docProps/core.xml").decode("utf-8")
        assert "2026-10-24" not in core
        assert all(info.date_time == FIXED_DATE_TIME for info in archive.infolist())
    # 归一化必须幂等，否则重放一次就换了字节。
    assert normalize_office_bytes(normalized) == normalized


def test_xlsx_export_is_byte_stable_across_seconds(tmp_path, monkeypatch, snapshot_api):
    client, db, project, _field, req, _ = snapshot_api
    _use_temp_storage(tmp_path, monkeypatch)
    base = f"/projects/{project.id}/requirements/{req.id}"
    snapshot_id = _frozen_snapshot(client, base, req)

    first, headers = _export(client, base, snapshot_id, "xlsx")
    assert headers["content-type"].startswith(XLSX_TYPE)
    assert "x-requirement-render-artifact-id" in headers

    _drop_artifacts(db, req.id)
    time.sleep(SLEEP_SECONDS)
    second, second_headers = _export(client, base, snapshot_id, "xlsx")

    assert len(first) == len(second)
    assert first == second, "跨秒重渲染得到不同字节：导出文件不可冻结"
    assert (second_headers["x-requirement-rendered-file-sha256"]
            == headers["x-requirement-rendered-file-sha256"])


def test_docx_export_is_byte_stable_across_seconds(tmp_path, monkeypatch, snapshot_api):
    client, db, project, _field, req, _ = snapshot_api
    _use_temp_storage(tmp_path, monkeypatch)
    base = f"/projects/{project.id}/requirements/{req.id}"
    snapshot_id = _frozen_snapshot(client, base, req)

    first, headers = _export(client, base, snapshot_id, "docx")
    assert headers["content-type"].startswith(DOCX_TYPE)

    _drop_artifacts(db, req.id)
    time.sleep(SLEEP_SECONDS)
    second, _ = _export(client, base, snapshot_id, "docx")

    assert first == second, "跨秒重渲染得到不同字节：Word 导出不可冻结"
    assert len(first) > 0


def test_survey_layout_export_is_byte_stable_across_seconds(tmp_path, monkeypatch, snapshot_api):
    client, db, project, _field, req, _ = snapshot_api
    _use_temp_storage(tmp_path, monkeypatch)
    base = f"/projects/{project.id}/requirements/{req.id}"
    snapshot_id = _frozen_snapshot(client, base, req)

    first, headers = _export(client, base, snapshot_id, "xlsx", layout="survey")
    assert headers["x-requirement-renderer-version"].startswith(SURVEY_DOC_VERSION)

    _drop_artifacts(db, req.id)
    time.sleep(SLEEP_SECONDS)
    second, _ = _export(client, base, snapshot_id, "xlsx", layout="survey")

    assert first == second, "一表通调研表式跨秒重渲染不一致"
