"""批量验收：一次把"还没查过的产物"跑完，单个失败不中断整批。"""

from __future__ import annotations

from pathlib import Path

from test_requirement_acceptance import _export
from test_requirement_export_unified import _use_temp_storage
from test_requirement_snapshot_api import snapshot_api, snapshot_db  # noqa: F401  注册夹具


def _batch(client, project, **body):
    return client.post(f"/projects/{project.id}/requirements-acceptance/batch", json=body or {})


def test_batch_runs_only_unchecked_and_records_each(tmp_path, monkeypatch, snapshot_api) -> None:
    client, db, project, field, requirement, *_ = snapshot_api
    _use_temp_storage(tmp_path, monkeypatch)
    first = _export(client, project, requirement)
    second = _export(client, project, requirement, fmt="docx", layout="standard")

    response = _batch(client, project)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["batch_version"] == "requirement-acceptance-batch-v1"
    assert payload["summary"]["attempted"] == 2
    assert payload["summary"]["passed"] == 2
    assert payload["summary"]["failed"] == 0
    assert payload["summary"]["unchecked_after"] == 0
    assert {row["artifact_id"] for row in payload["results"]} == {first, second}
    assert all(row["record_id"] for row in payload["results"])
    assert "不代表业务口径已确认" in payload["note"]

    # 再跑一次：没有"未检查"的产物了，就什么都不做——不重复刷记录。
    again = _batch(client, project)
    assert again.status_code == 200, again.text
    assert again.json()["summary"]["attempted"] == 0

    history = client.get(f"/projects/{project.id}/requirements/{requirement.id}/delivery-checks")
    assert history.json()["count"] == 2


def test_batch_can_recheck_all_with_limit(tmp_path, monkeypatch, snapshot_api) -> None:
    client, db, project, field, requirement, *_ = snapshot_api
    _use_temp_storage(tmp_path, monkeypatch)
    _export(client, project, requirement)
    _export(client, project, requirement, fmt="docx", layout="standard")

    assert _batch(client, project).json()["summary"]["attempted"] == 2
    recheck = _batch(client, project, only_unchecked=False, limit=1)
    assert recheck.status_code == 200, recheck.text
    payload = recheck.json()
    assert payload["summary"]["attempted"] == 1
    assert payload["limit"] == 1
    history = client.get(f"/projects/{project.id}/requirements/{requirement.id}/delivery-checks")
    assert history.json()["count"] == 3


def test_batch_keeps_going_when_one_artifact_is_broken(tmp_path, monkeypatch, snapshot_api) -> None:
    client, db, project, field, requirement, *_ = snapshot_api
    _use_temp_storage(tmp_path, monkeypatch)
    good = _export(client, project, requirement)
    broken = _export(client, project, requirement, fmt="docx", layout="standard")

    from app.models import RequirementRenderArtifact
    from app.services.storage.factory import get_storage_service

    record = db.get(RequirementRenderArtifact, broken)
    Path(get_storage_service().root, record.storage_key).write_bytes(b"tampered")
    db.commit()

    response = _batch(client, project)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["summary"]["attempted"] == 2
    assert payload["summary"]["passed"] == 1
    assert payload["summary"]["errored"] == 1
    errored = next(row for row in payload["results"] if row["artifact_id"] == broken)
    assert errored["verdict"] == "error"
    assert errored["code"] == "artifact_integrity_failed"
    passed = next(row for row in payload["results"] if row["artifact_id"] == good)
    assert passed["record_id"]


def test_batch_skips_layouts_it_cannot_check(tmp_path, monkeypatch, snapshot_api) -> None:
    """内置版式 xlsx 没有可自检的表级结构：跳过并单列，不算失败、不写记录、不重复报错。"""

    client, db, project, field, requirement, *_ = snapshot_api
    _use_temp_storage(tmp_path, monkeypatch)
    survey = _export(client, project, requirement)
    builtin = _export(client, project, requirement, fmt="xlsx", layout="standard")

    payload = _batch(client, project).json()
    assert payload["summary"]["attempted"] == 1
    assert payload["summary"]["passed"] == 1
    assert payload["summary"]["skipped"] == 1
    assert payload["summary"]["errored"] == 0
    assert {row["artifact_id"] for row in payload["results"]} == {survey}
    assert [row["artifact_id"] for row in payload["unsupported"]] == [builtin]
    assert payload["unsupported"][0]["code"] == "layout_not_survey"
    assert "unsupported" in payload["note"]

    history = client.get(f"/projects/{project.id}/requirements/{requirement.id}/delivery-checks")
    assert history.json()["count"] == 1

    # 再跑一次：跳过的仍然跳过（不会变成通过，也不会每次重跑报错）。
    again = _batch(client, project).json()
    assert again["summary"]["attempted"] == 0
    assert again["summary"]["skipped"] == 1
    assert again["summary"]["errored"] == 0


def test_batch_requires_positive_limit(tmp_path, monkeypatch, snapshot_api) -> None:
    client, db, project, field, requirement, *_ = snapshot_api
    _use_temp_storage(tmp_path, monkeypatch)
    response = _batch(client, project, limit=0)
    assert response.status_code == 422, response.text
    assert "limit" in response.json()["detail"]
