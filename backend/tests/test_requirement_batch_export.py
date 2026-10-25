"""批量冻结并导出（POST /requirements/exports-batch）。

真实问题：项目里十几条需求，评审要一次性拿到"这一批"文件，逐条点导出既慢又容易漏；
而"能导几条算几条"最危险——拿到半批文件的人不知道少了谁。所以批量导出必须：

1. 先做整体预检：任何一条需求的版本或内容哈希对不上，**一条都不冻结**；
2. 逐条冻结 + 渲染，复用与单条导出同一段渲染（同一份内容只产生一份产物）；
3. 打成一个可复现的 zip，附 ``manifest.json`` 记录每份文件来自哪份快照、哪条产物。
"""

from __future__ import annotations

import hashlib
import json
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

from sqlalchemy import func, select

from app.models import Requirement, RequirementDelivery
from app.services.requirement_batch_archive import MANIFEST_NAME, read_manifest
from app.services.storage.factory import get_storage_service
from test_requirement_snapshot_api import snapshot_api, snapshot_db  # noqa: F401  夹具复用


def _use_temp_storage(tmp_path: Path, monkeypatch) -> Path:
    root = tmp_path / "storage"
    monkeypatch.setenv("STORAGE_DIR", str(root))
    get_storage_service.cache_clear()
    return root


def _selection(client, project_id: int, requirements) -> str:
    entries = []
    for req in requirements:
        current = client.get(f"/projects/{project_id}/requirements/{req.id}/document").json()
        entries.append({"requirement_id": req.id, "expected_version": req.version,
                        "expected_hash": current["content_hash"]})
    return json.dumps(entries, ensure_ascii=False)


def _second_requirement(db, project, req, name: str = "批量导出第二条需求"):
    clone = Requirement(project_id=project.id, name=name, version=1, scope_json=dict(req.scope_json))
    db.add(clone)
    db.flush()
    return clone


def test_batch_export_archives_every_requirement_once(tmp_path, monkeypatch, snapshot_api):
    client, db, project, _, req, _ = snapshot_api
    _use_temp_storage(tmp_path, monkeypatch)
    second = _second_requirement(db, project, req)

    selection = _selection(client, project.id, [req, second])
    response = client.post(f"/projects/{project.id}/requirements/exports-batch",
                           data={"selection": selection, "format": "xlsx", "layout": "survey"})
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/zip"
    assert response.headers["x-requirement-batch-items"] == "2"

    archive_bytes = response.content
    digest = hashlib.sha256(archive_bytes).hexdigest()
    assert response.headers["x-requirement-batch-file-sha256"] == digest
    assert digest[:12] in response.headers["content-disposition"]

    with ZipFile(BytesIO(archive_bytes)) as archive:
        names = archive.namelist()
        manifest = read_manifest(archive_bytes)
        assert MANIFEST_NAME in names
        assert len(names) == 3, "两条需求两份文件 + 一份清单"
        assert manifest["archive_version"] == "requirement-batch-archive-v1"
        assert manifest["project_id"] == project.id
        assert manifest["item_count"] == 2
        assert [item["requirement_id"] for item in manifest["items"]] == [req.id, second.id]
        for item in manifest["items"]:
            payload = archive.read(item["file_name"])
            assert hashlib.sha256(payload).hexdigest() == item["file_sha256"]
            assert len(payload) == item["file_size"]
            assert item["snapshot_id"]
            assert item["artifact_id"]

    again = client.post(f"/projects/{project.id}/requirements/exports-batch",
                        data={"selection": selection, "format": "xlsx", "layout": "survey"})
    assert again.status_code == 200, again.text
    assert again.content == archive_bytes, "同一批内容重复导出必须字节一致"
    assert again.headers["x-requirement-batch-snapshots-created"] == "0", "第二次不应新建快照"
    assert db.scalar(select(func.count()).select_from(RequirementDelivery)) == 2


def test_batch_export_rejects_stale_hash_without_freezing_anything(tmp_path, monkeypatch, snapshot_api):
    client, db, project, _, req, _ = snapshot_api
    _use_temp_storage(tmp_path, monkeypatch)
    second = _second_requirement(db, project, req)

    selection = json.loads(_selection(client, project.id, [req, second]))
    selection[-1]["expected_hash"] = "0" * 64
    response = client.post(f"/projects/{project.id}/requirements/exports-batch",
                           data={"selection": json.dumps(selection, ensure_ascii=False),
                                 "format": "xlsx", "layout": "survey"})
    assert response.status_code == 409
    assert "本次未冻结任何需求" in response.json()["detail"]
    assert db.scalar(select(func.count()).select_from(RequirementDelivery)) == 0, "校验失败时不能留下半份快照"


def test_batch_export_validates_limits_and_permissions(tmp_path, monkeypatch, snapshot_api):
    client, db, project, _, req, membership = snapshot_api
    _use_temp_storage(tmp_path, monkeypatch)
    endpoint = f"/projects/{project.id}/requirements/exports-batch"
    good = _selection(client, project.id, [req])

    too_many = json.dumps([{"requirement_id": index, "expected_version": 1,
                            "expected_hash": "a" * 64} for index in range(1, 22)])
    assert client.post(endpoint, data={"selection": too_many}).status_code == 422

    duplicated = json.dumps(json.loads(good) * 2)
    assert client.post(endpoint, data={"selection": duplicated}).status_code == 422

    assert client.post(endpoint, data={"selection": "not-json"}).status_code == 422
    assert client.post(endpoint, data={"selection": good, "layout": "poster"}).status_code == 422
    assert client.post(endpoint, data={"selection": good, "format": "docx",
                                       "layout": "survey"}).status_code == 422

    membership.project_role = "viewer"
    db.flush()
    assert client.post(endpoint, data={"selection": good}).status_code == 403
    assert db.scalar(select(func.count()).select_from(RequirementDelivery)) == 0


def test_batch_export_manifest_matches_artifact_list(tmp_path, monkeypatch, snapshot_api):
    client, db, project, _, req, _ = snapshot_api
    _use_temp_storage(tmp_path, monkeypatch)
    selection = _selection(client, project.id, [req])

    response = client.post(f"/projects/{project.id}/requirements/exports-batch",
                           data={"selection": selection, "format": "xlsx", "layout": "survey"})
    assert response.status_code == 200, response.text
    manifest = read_manifest(response.content)
    item = manifest["items"][0]

    listed = client.get(f"/projects/{project.id}/requirements/{req.id}/render-artifacts").json()
    assert listed, "产物必须落库，不能只存在于压缩包里"
    match = [entry for entry in listed if entry["id"] == item["artifact_id"]]
    assert match, "清单里的产物 id 必须能在产物列表里找到"
    assert match[0]["file_sha256"] == item["file_sha256"]
