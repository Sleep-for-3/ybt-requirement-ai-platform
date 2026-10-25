"""P1-C 投影账：进入模型的范围必须可对账，超限必须给出真实数字且不截断。"""

from sqlalchemy import func, select

from app.models import RequirementGenerationInput, SourceField, SourceTable
from app.services.mapping.requirement_input import MAX_INPUT_BYTES
from app.services.mapping.requirement_projection import (
    KIND_PHYSICAL,
    PROJECTION_VERSION,
    limit_exceeded_message,
    limit_exceeded_summary,
    projection_summary,
    version_pin_omissions,
)
from test_requirement_resources import add_document
from test_requirement_snapshot_api import snapshot_api, snapshot_db  # noqa: F401
from test_requirement_generation_input import add_unit


def _scope_with_document_and_source(db, project, req, document, source_table):
    return {
        **req.scope_json,
        "name": req.name,
        "document_ids": [document.id],
        "source_table_ids": [source_table.id],
    }


def test_projection_block_is_recorded_in_frozen_input(snapshot_api):
    client, db, project, field, req, _ = snapshot_api
    document = add_document(db, project.id, "投影账资料")
    add_unit(db, project.id, document, "PROJECTION_EVIDENCE")
    source = db.scalar(select(SourceTable).where(SourceTable.project_id == project.id))
    base = f"/projects/{project.id}/requirements/{req.id}"
    assert client.put(base, json={**_scope_with_document_and_source(db, project, req, document, source),
                                  "expected_version": 1}).status_code == 200
    client.post(base + "/revisions", json={"expected_version": 2})
    response = client.post(base + "/generation-inputs", json={
        "expected_content_version": 1, "field_ids": [field.id],
        "sections": ["business", "lineage"], "idempotency_key": "projection-one",
    })
    assert response.status_code == 201, response.text
    frozen = db.get(RequirementGenerationInput, response.json()["id"]).input_json

    projection = frozen["projection"]
    assert projection["version"] == PROJECTION_VERSION
    assert projection["complete"] is True
    assert projection["field_count"] == 1
    assert projection["evidence_count"] >= 1
    assert projection["physical_source_count"] >= 1
    assert projection["sections"] == ["business", "lineage"]
    assert projection["limits"] == {"max_rows": 500, "max_input_bytes": MAX_INPUT_BYTES}
    assert projection["input_bytes"] > 0
    assert projection["omissions"] == []


def test_physical_row_limit_reports_real_total_and_never_truncates(snapshot_api, monkeypatch):
    client, db, project, field, req, _ = snapshot_api
    source = db.scalar(select(SourceTable).where(SourceTable.project_id == project.id))
    for code in ("EXTRA_F1", "EXTRA_F2"):
        db.add(SourceField(project_id=project.id, source_table_id=source.id,
                           field_code=code, field_name=code, field_type="string"))
    db.commit()
    real_total = db.scalar(select(func.count()).select_from(SourceField).where(
        SourceField.project_id == project.id, SourceField.source_table_id == source.id))
    assert real_total and real_total > 1, "夹具需要多字段的源表才能验证真实总数"
    base = f"/projects/{project.id}/requirements/{req.id}"
    assert client.put(base, json={**req.scope_json, "name": req.name,
                                  "source_table_ids": [source.id], "expected_version": 1}).status_code == 200
    client.post(base + "/revisions", json={"expected_version": 2})
    monkeypatch.setattr("app.services.mapping.requirement_input.MAX_ROWS", 1)

    response = client.post(base + "/generation-inputs", json={
        "expected_content_version": 1, "field_ids": [field.id],
        "sections": ["lineage"], "idempotency_key": "projection-over-row-limit",
    })

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert f"请求 {real_total} 行" in detail, detail
    assert "上限 1 行" in detail
    assert "不做截断" in detail


def test_input_byte_limit_reports_sizes(snapshot_api, monkeypatch):
    client, _, project, field, req, _ = snapshot_api
    base = f"/projects/{project.id}/requirements/{req.id}"
    client.post(base + "/revisions", json={"expected_version": 1})
    monkeypatch.setattr("app.services.mapping.requirement_input.MAX_INPUT_BYTES", 20)

    response = client.post(base + "/generation-inputs", json={
        "expected_content_version": 1, "field_ids": [field.id],
        "sections": ["business"], "idempotency_key": "projection-over-bytes",
    })

    assert response.status_code == 422
    detail = response.json()["detail"]
    # 字节预算必须报"字节"：早先这里固定写"行"，把 189880 字节报成"189880 行"，
    # 会让人按"行"去缩小资料范围而归因错误。
    assert "输入字节" in detail and "上限 20 字节" in detail and "超出" in detail
    assert "未被截断" in detail


def test_projection_summary_counts_and_bytes_are_deterministic():
    payload = {
        "fields": [{"target": {"id": 1}}],
        "physical_sources": [{"kind": "source"}, {"kind": "mart"}],
        "evidence": [{"unit_id": 7}],
    }
    first = projection_summary(payload, sections=("lineage", "business"),
                               limits={"max_rows": 500}, omissions=[])
    second = projection_summary(payload, sections=("business", "lineage"),
                                limits={"max_rows": 500}, omissions=[])
    assert first == second
    assert first["field_count"] == 1
    assert first["physical_source_count"] == 2
    assert first["evidence_count"] == 1
    assert first["sections"] == ["business", "lineage"]
    assert first["complete"] is True


def test_version_pin_exclusions_become_structured_omissions():
    entries = version_pin_omissions(["已排除 2025 版的 2 类版本证据", "缺少钉扎版本《X》"])
    assert [item["kind"] for item in entries] == ["version_pin_excluded"] * 2
    assert entries[0]["detail"] == "已排除 2025 版的 2 类版本证据"
    assert all(item["reason"] == "version_pin" for item in entries)


def test_limit_exceeded_summary_states_the_gap_explicitly():
    summary = limit_exceeded_summary(kind=KIND_PHYSICAL, requested=620, limit=500, phase="source 物理字段")
    assert summary["exceeded_by"] == 120
    assert summary["truncated"] is False
    assert summary["complete"] is False
    message = limit_exceeded_message(summary, "所选数据字段超出单次输入限制，请缩小资料范围")
    assert "请求 620 行" in message and "上限 500 行" in message and "超出 120 行" in message
