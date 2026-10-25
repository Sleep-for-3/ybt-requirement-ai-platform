"""人工核对登记：只给自动验收跑不了的产物用，且不能冒充机器检查。"""

from __future__ import annotations

from test_requirement_acceptance import _export
from test_requirement_export_unified import _use_temp_storage
from test_requirement_snapshot_api import snapshot_api, snapshot_db  # noqa: F401  注册夹具

BASIS = "按客户模板逐列核对：字段名、口径、示例值与本行一致（2026-10-25 复核）"


def _url(project, requirement, artifact_id: int) -> str:
    return f"/projects/{project.id}/requirements/{requirement.id}/render-artifacts/{artifact_id}/attestations"


def test_attestation_records_a_manual_check_for_unsupported_artifact(tmp_path, monkeypatch, snapshot_api) -> None:
    client, db, project, field, requirement, *_ = snapshot_api
    _use_temp_storage(tmp_path, monkeypatch)
    # 内置版式 xlsx：自动验收明确不适用（layout_not_survey），正是人工核对的场景。
    artifact_id = _export(client, project, requirement, fmt="xlsx", layout="standard")

    response = client.post(_url(project, requirement, artifact_id), json={"conclusion": "confirmed", "basis": BASIS})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["attestation_version"] == "requirement-artifact-attestation-v1"
    attestation = payload["attestation"]
    assert attestation["conclusion"] == "confirmed"
    assert attestation["conclusion_label"] == "人工核对通过"
    assert attestation["scope_code"] == "layout_not_survey"
    assert attestation["basis"] == BASIS
    assert "不改变交付状态" in payload["note"]

    listing = client.get(_url(project, requirement, artifact_id))
    assert listing.status_code == 200
    assert len(listing.json()["items"]) == 1


def test_attestation_appends_and_never_overwrites(tmp_path, monkeypatch, snapshot_api) -> None:
    client, db, project, field, requirement, *_ = snapshot_api
    _use_temp_storage(tmp_path, monkeypatch)
    artifact_id = _export(client, project, requirement, fmt="xlsx", layout="standard")
    url = _url(project, requirement, artifact_id)

    first = client.post(url, json={"conclusion": "confirmed", "basis": BASIS})
    second = client.post(url, json={"conclusion": "rejected", "basis": "复核发现第 3 列口径与调研表不一致"})
    assert first.status_code == 200 and second.status_code == 200
    assert first.json()["attestation"]["id"] != second.json()["attestation"]["id"]

    items = client.get(url).json()["items"]
    assert [item["id"] for item in items] == [second.json()["attestation"]["id"], first.json()["attestation"]["id"]]
    assert items[0]["conclusion"] == "rejected"


def test_attestation_refuses_artifact_that_can_be_auto_checked(tmp_path, monkeypatch, snapshot_api) -> None:
    client, db, project, field, requirement, *_ = snapshot_api
    _use_temp_storage(tmp_path, monkeypatch)
    artifact_id = _export(client, project, requirement)  # survey xlsx：可自动验收

    response = client.post(_url(project, requirement, artifact_id), json={"conclusion": "confirmed", "basis": BASIS})
    assert response.status_code == 422, response.text
    assert "attestation_not_needed" in response.json()["detail"]


def test_attestation_requires_a_useful_basis(tmp_path, monkeypatch, snapshot_api) -> None:
    client, db, project, field, requirement, *_ = snapshot_api
    _use_temp_storage(tmp_path, monkeypatch)
    artifact_id = _export(client, project, requirement, fmt="xlsx", layout="standard")
    url = _url(project, requirement, artifact_id)

    empty = client.post(url, json={"conclusion": "confirmed", "basis": "  "})
    assert empty.status_code == 422 and "basis_required" in empty.json()["detail"]

    placeholder = client.post(url, json={"conclusion": "confirmed", "basis": "详见附件"})
    assert placeholder.status_code == 422 and "basis_placeholder" in placeholder.json()["detail"]

    unknown = client.post(url, json={"conclusion": "looks_fine", "basis": BASIS})
    assert unknown.status_code == 422 and "conclusion_invalid" in unknown.json()["detail"]

    assert client.get(url).json()["items"] == []


def test_attestation_does_not_count_as_a_machine_check(tmp_path, monkeypatch, snapshot_api) -> None:
    """人工核对是人的判断：审计里"已检查"不能因此 +1，检查记录也不能凭空多一条。"""

    client, db, project, field, requirement, *_ = snapshot_api
    _use_temp_storage(tmp_path, monkeypatch)
    artifact_id = _export(client, project, requirement, fmt="xlsx", layout="standard")

    response = client.post(_url(project, requirement, artifact_id), json={"conclusion": "confirmed", "basis": BASIS})
    assert response.status_code == 200, response.text

    checks = client.get(f"/projects/{project.id}/requirements/{requirement.id}/delivery-checks")
    assert checks.json()["count"] == 0

    audit = client.get(f"/projects/{project.id}/delivery-audit?limit=50").json()
    assert audit["summary"]["checked"] == 0
    assert audit["summary"]["unchecked"] == 1
    assert audit["summary"]["attested"] == 1
    assert audit["summary"]["unattested"] == 0
    item = next(item for item in audit["items"] if item["artifact_id"] == artifact_id)
    assert item["state"] == "unchecked"
    assert item["attestation"]["conclusion"] == "confirmed"
    assert item["attestation"]["scope_code"] == "layout_not_survey"
