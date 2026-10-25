"""模板一致性比对（round 58）：导出产物的模板列必须与当前标准模板一致。

真实缺口：结构自检只证明"长得像标准模板"，不能证明"监管原始口径、报表名称这些业务方给定的
标准值没被改过"。这里用真实导出产物 + 真实接口取证。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from test_requirement_export_unified import _frozen_snapshot, _use_temp_storage
from test_requirement_snapshot_api import snapshot_api, snapshot_db  # noqa: F401


def _export_survey(client, base: str, snapshot_id: int) -> int:
    response = client.post(
        f"{base}/exports",
        data={"format": "xlsx", "source_kind": "draft_snapshot", "source_id": str(snapshot_id), "layout": "survey"},
    )
    assert response.status_code == 200, response.text
    artifact_id = response.headers.get("x-requirement-render-artifact-id")
    assert artifact_id and artifact_id.isdigit(), response.headers
    return int(artifact_id)


def test_fidelity_passes_when_document_matches_template(tmp_path: Path, monkeypatch, snapshot_api) -> None:
    client, db, project, field, req, _ = snapshot_api
    _use_temp_storage(tmp_path, monkeypatch)
    field.data_category = "编码类"
    field.data_format = "anc..32"
    field.regulatory_original_definition = "填报该笔贷款对应的借据号码，24 位。"
    field.report_name = "贷款借据"
    db.commit()

    base = f"/projects/{project.id}/requirements/{req.id}"
    snapshot_id = _frozen_snapshot(client, base, req)
    artifact_id = _export_survey(client, base, snapshot_id)

    response = client.get(f"{base}/render-artifacts/{artifact_id}/template-fidelity")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["fidelity_version"] == "requirement-template-fidelity-v1"
    assert body["verdict"] == "pass", body
    assert body["failed_labels"] == []
    columns = {column["key"]: column for column in body["columns"]}
    assert columns["regulatory_original_definition"]["matched_count"] == 1
    assert columns["regulatory_original_definition"]["mismatched_count"] == 0
    assert columns["report_name"]["matched_count"] == 1
    assert body["artifact"]["id"] == artifact_id
    assert body["artifact"]["file_sha256"]


def test_fidelity_reports_mismatch_after_template_change(tmp_path: Path, monkeypatch, snapshot_api) -> None:
    client, db, project, field, req, _ = snapshot_api
    _use_temp_storage(tmp_path, monkeypatch)
    field.regulatory_original_definition = "模板原话：借据号码 24 位。"
    db.commit()

    base = f"/projects/{project.id}/requirements/{req.id}"
    snapshot_id = _frozen_snapshot(client, base, req)
    artifact_id = _export_survey(client, base, snapshot_id)

    # 模板被业务方更新（或需求正文被改过）：文档里的旧值必须被查出来。
    field.regulatory_original_definition = "模板新话：借据号码 32 位，含校验位。"
    db.commit()

    response = client.get(f"{base}/render-artifacts/{artifact_id}/template-fidelity")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["verdict"] == "fail"
    assert "监管原始口径" in body["failed_labels"]
    column = next(item for item in body["columns"] if item["key"] == "regulatory_original_definition")
    assert column["mismatched_count"] == 1
    assert column["samples"][0]["field_code"] == field.field_code
    assert "32 位" in column["samples"][0]["expected"]
    assert "24 位" in column["samples"][0]["actual"]


def test_fidelity_marks_template_empty_columns_without_failing(
    tmp_path: Path, monkeypatch, snapshot_api
) -> None:
    client, db, project, field, req, _ = snapshot_api
    _use_temp_storage(tmp_path, monkeypatch)
    # 数据格式列在真实调研表里整列为空：模板没给值就不能判"不一致"。
    field.data_format = None
    db.commit()

    base = f"/projects/{project.id}/requirements/{req.id}"
    snapshot_id = _frozen_snapshot(client, base, req)
    artifact_id = _export_survey(client, base, snapshot_id)

    body = client.get(f"{base}/render-artifacts/{artifact_id}/template-fidelity").json()
    column = next(item for item in body["columns"] if item["key"] == "data_format")
    assert column["template_empty_count"] == 1
    assert column["mismatched_count"] == 0
    assert column["blank_in_document_count"] == 0
    assert body["verdict"] == "pass", body


def test_fidelity_scopes_template_values_to_the_requirement_target_table(
    tmp_path: Path, monkeypatch, snapshot_api
) -> None:
    """字段代码不是全局唯一：SFJJGDM 这类系统字段在每张表里都有同名行。

    比对必须限定在需求自己的目标表，否则会拿到别的表的模板值，把正确文档判成不一致。
    """

    from app.models import TargetField

    client, db, project, field, req, _ = snapshot_api
    _use_temp_storage(tmp_path, monkeypatch)
    field.report_name = "贷款借据"
    db.commit()

    # 另一张表里同名同代码的字段，模板值完全不同。
    other = TargetField(
        project_id=project.id,
        target_table_id=(field.target_table_id or 0) + 1,
        field_code=field.field_code,
        field_name=field.field_name,
        report_name="理财投资标的",
    )
    db.add(other)
    db.commit()

    base = f"/projects/{project.id}/requirements/{req.id}"
    snapshot_id = _frozen_snapshot(client, base, req)
    artifact_id = _export_survey(client, base, snapshot_id)

    body = client.get(f"{base}/render-artifacts/{artifact_id}/template-fidelity").json()
    column = next(item for item in body["columns"] if item["key"] == "report_name")
    assert column["mismatched_count"] == 0, column
    assert body["verdict"] == "pass", body


def test_fidelity_rejects_docx_and_missing_artifact(tmp_path: Path, monkeypatch, snapshot_api) -> None:
    client, db, project, field, req, _ = snapshot_api
    _use_temp_storage(tmp_path, monkeypatch)
    base = f"/projects/{project.id}/requirements/{req.id}"
    snapshot_id = _frozen_snapshot(client, base, req)
    response = client.post(
        f"{base}/exports",
        data={"format": "docx", "source_kind": "draft_snapshot", "source_id": str(snapshot_id), "layout": "standard"},
    )
    assert response.status_code == 200, response.text
    docx_id = int(response.headers["x-requirement-render-artifact-id"])

    unsupported = client.get(f"{base}/render-artifacts/{docx_id}/template-fidelity")
    assert unsupported.status_code == 422
    assert "一表通调研表式" in unsupported.json()["detail"]

    missing = client.get(f"{base}/render-artifacts/999999/template-fidelity")
    assert missing.status_code == 404
