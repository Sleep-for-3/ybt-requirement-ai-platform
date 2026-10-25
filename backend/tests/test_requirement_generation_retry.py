"""真实观测（2026-10-24 一表通跑批）催生的重试行为。

推理型网关会偶发把输出预算全花在思维链上导致正文为空（LLMResponseError），
或返回结构不符 schema 的 JSON。这两种都是可重试的格式失败：必须重试一次并留账，
而不是把整条需求字段直接判失败。
"""

from __future__ import annotations

import pytest

from test_requirement_snapshot_api import snapshot_api, snapshot_db  # noqa: F401 (pytest fixtures)


def _prepare(snapshot_api, monkeypatch):
    from app.models import RequirementGenerationInput, RequirementGenerationItem
    from app.services import requirement_generation_worker as worker

    client, db, project, field, req, _ = snapshot_api
    base = f"/projects/{project.id}/requirements/{req.id}"
    client.post(base + "/revisions", json={"expected_version": 1})
    created = client.post(base + "/generation-inputs", json={
        "expected_content_version": 1, "field_ids": [field.id], "sections": ["business"],
        "idempotency_key": "retry-format", })
    assert created.status_code == 201, created.text
    input_id = created.json()["id"]
    item = RequirementGenerationItem(input_id=input_id, field_id=field.id, section="business",
                                     status="pending")
    db.add(item)
    db.commit()
    row = db.get(RequirementGenerationInput, input_id)
    project_row = db.get(type(project), project.id)
    return worker, db, row, item, project_row, base


def test_empty_model_answer_is_retried_once_then_completes(snapshot_api, monkeypatch):
    from app.services.llm.base import LLMResponseError

    worker, db, row, item, project, _base = _prepare(snapshot_api, monkeypatch)
    original = worker.execute_runtime_chat
    calls = {"count": 0}

    async def flaky(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise LLMResponseError("模型未返回结构化正文（finish_reason=length）")
        return await original(*args, **kwargs)

    monkeypatch.setattr(worker, "execute_runtime_chat", flaky)
    candidate = worker.generate_candidate(db, row, item, project)

    assert calls["count"] == 2
    assert candidate["business_definition"]
    usage = item.generation_usage
    assert usage["final_status"] == "completed"
    assert len(usage["attempts"]) == 2
    # 第一次失败必须留账，不能被重试吞掉
    assert usage["attempts"][0]["failed"] is True
    assert usage["attempts"][0]["error_type"] == "LLMResponseError"


def test_two_empty_answers_fail_instead_of_faking_a_candidate(snapshot_api, monkeypatch):
    from app.services.llm.base import LLMResponseError

    worker, db, row, item, project, _base = _prepare(snapshot_api, monkeypatch)

    async def always_empty(*_args, **_kwargs):
        raise LLMResponseError("模型未返回结构化正文（finish_reason=length）")

    monkeypatch.setattr(worker, "execute_runtime_chat", always_empty)
    with pytest.raises(LLMResponseError):
        worker.generate_candidate(db, row, item, project)

    usage = item.generation_usage
    assert usage["final_status"] == "failed"
    assert len(usage["attempts"]) == 2
    assert all(attempt["failed"] for attempt in usage["attempts"])
    assert "LLMResponseError" in usage["detail"]
    assert "finish_reason=length" in usage["detail"]
