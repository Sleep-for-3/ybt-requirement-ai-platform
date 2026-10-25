"""人工核对「不通过」必须压住就绪度，而且只压它登记的那一版产物。

三条固定行为：
1. 最新产物被判「不通过」→ 就绪度变 `human_rejected`（排在已交付之前，不能被"可直接重新导出"盖住）；
2. 重新导出后新的产物没被否过 → 回到原来的就绪度，旧登记只留在审计里（`on_latest_artifact` 变假）；
3. 判「通过」不影响就绪度——人工确认过不等于验证通过，只是记录有人看过。
"""

from __future__ import annotations

from pathlib import Path

from test_requirement_acceptance import _export
from test_requirement_export_unified import _use_temp_storage
from test_requirement_snapshot_api import snapshot_api, snapshot_db  # noqa: F401  夹具复用


def _status(client, project_id: int) -> dict:
    response = client.get(f"/projects/{project_id}/requirements-status")
    assert response.status_code == 200, response.text
    return response.json()


def _item(body: dict, requirement_id: int) -> dict:
    return next(entry for entry in body["items"] if entry["requirement_id"] == requirement_id)


def _attest(client, base: str, artifact_id: int, conclusion: str, basis: str):
    return client.post(
        f"{base}/render-artifacts/{artifact_id}/attestations",
        json={"conclusion": conclusion, "basis": basis},
    )


def test_rejected_attestation_overrides_readiness(tmp_path: Path, monkeypatch, snapshot_api):
    client, db, project, field, req, _ = snapshot_api
    _use_temp_storage(tmp_path, monkeypatch)
    base = f"/projects/{project.id}/requirements/{req.id}"
    # 内置版式 xlsx 没有可自检的表级结构，正是「只能人工核对」的那一类。
    artifact_id = _export(client, project, req, layout="standard")

    before = _item(_status(client, project.id), req.id)
    assert before["readiness"] == "exportable"
    assert before["human_rejected"] is False
    assert before["latest_attestation"] is None

    rejected = _attest(client, base, artifact_id, "rejected", "客户模板第三列表头错位，业务口径第 4 段漏了分母说明")
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["attestation"]["conclusion"] == "rejected"

    body = _status(client, project.id)
    item = _item(body, req.id)
    assert item["readiness"] == "human_rejected"
    assert item["human_rejected"] is True
    assert item["latest_attestation"]["artifact_id"] == artifact_id
    assert item["latest_attestation"]["on_latest_artifact"] is True
    assert item["latest_attestation"]["conclusion"] == "rejected"
    assert body["summary"]["human_rejected"] == 1
    # 就绪度被压住，但"已冻结/可导出"这些事实不能被改写。
    assert item["frozen"] is True
    assert item["artifact_count"] == 1


def test_rejected_attestation_stops_mattering_once_a_newer_artifact_exists(tmp_path: Path, monkeypatch, snapshot_api):
    client, db, project, field, req, _ = snapshot_api
    _use_temp_storage(tmp_path, monkeypatch)
    base = f"/projects/{project.id}/requirements/{req.id}"
    first = _export(client, project, req, layout="standard")

    # 同一份快照重复导出会复用同一个产物（渲染身份相同），所以"新版本产物"必须来自内容变化。
    assert client.post(base + "/revisions", json={"expected_version": req.version or 1}).status_code == 201
    edit = client.put(
        f"{base}/fields/{field.id}",
        json={
            "section": "business",
            "changes": {"business_definition": "被人判不通过后按依据改的业务定义"},
            "expected_content_version": client.get(base + "/document").json()["revision"]["content_version"],
        },
    )
    assert edit.status_code == 200, edit.text

    assert _attest(client, base, first, "rejected", "第一次导出封面缺报送机构名称").status_code == 200
    assert _item(_status(client, project.id), req.id)["readiness"] == "human_rejected"

    second = _export(client, project, req, layout="standard")
    assert second != first

    body = _status(client, project.id)
    item = _item(body, req.id)
    # 新产物没被否过：恢复成原来的就绪度，但历史登记仍然读得到。
    assert item["readiness"] == "exportable"
    assert item["human_rejected"] is False
    assert item["latest_attestation"]["artifact_id"] == first
    assert item["latest_attestation"]["on_latest_artifact"] is False
    assert body["summary"]["human_rejected"] == 0


def test_confirmed_attestation_does_not_change_readiness(tmp_path: Path, monkeypatch, snapshot_api):
    client, db, project, field, req, _ = snapshot_api
    _use_temp_storage(tmp_path, monkeypatch)
    base = f"/projects/{project.id}/requirements/{req.id}"
    artifact_id = _export(client, project, req, layout="standard")
    assert _attest(client, base, artifact_id, "confirmed", "逐列核对过表头与口径，与监管模板一致").status_code == 200

    body = _status(client, project.id)
    item = _item(body, req.id)
    assert item["readiness"] == "exportable"
    assert item["human_rejected"] is False
    assert item["latest_attestation"]["conclusion"] == "confirmed"
    assert body["summary"]["human_rejected"] == 0
