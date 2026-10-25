"""生成过程中权限被撤销后，剩余分片不得继续调用模型，也不得留下候选。"""

from sqlalchemy import select

from app.models import BackgroundJob, RequirementGenerationItem, TargetField
from test_requirement_snapshot_api import snapshot_api, snapshot_db  # noqa: F401


def _three_field_scope(client, db, project, field, req):
    ids = [field.id]
    for index in range(2):
        added = TargetField(project_id=project.id, target_table_id=field.target_table_id,
            field_code=f"REVOKE_{index}", field_name=f"撤销用例字段{index}")
        db.add(added)
        db.flush()
        ids.append(added.id)
    req.scope_json = {**req.scope_json, "field_ids": ids}
    db.commit()
    base = f"/projects/{project.id}/requirements/{req.id}"
    assert client.post(base + "/revisions", json={"expected_version": 1}).status_code == 201
    return base, ids


def test_revocation_blocks_every_remaining_item_without_model_calls(snapshot_api, monkeypatch):
    from app.services.task_queue.inline import InlineTaskQueue
    from app.services.requirement_generation_worker import requirement_generation_handler  # noqa: F401

    client, db, project, field, req, membership = snapshot_api
    base, ids = _three_field_scope(client, db, project, field, req)
    monkeypatch.setattr("app.services.task_queue.factory.get_task_queue", lambda: InlineTaskQueue())

    calls: list[int] = []

    def generate(db, row, item, project):
        calls.append(item.field_id)
        # 第一个分片生成期间被降权：候选必须被丢弃，后面的分片不得再生成。
        membership.project_role = "viewer"
        db.commit()
        return {"final_content": "不得落库的候选", "gaps": []}

    monkeypatch.setattr("app.services.requirement_generation_worker.generate_candidate", generate)

    response = client.post(base + "/generation-runs", json={"expected_content_version": 1,
        "field_ids": ids, "sections": ["business"], "idempotency_key": "revoke-multi"})
    assert response.status_code == 201, response.text
    input_id = response.json()["input_id"]

    items = list(db.scalars(select(RequirementGenerationItem)
        .where(RequirementGenerationItem.input_id == input_id)
        .order_by(RequirementGenerationItem.id)))
    assert len(items) == 3
    # 撤销后不再调用模型：只有正在执行的那一个分片进过 generate_candidate。
    assert len(calls) == 1
    for item in items:
        assert item.status == "blocked", (item.field_id, item.status)
        assert item.reason_code == "generation_permission_denied"
        assert item.candidate_json is None and item.candidate_hash is None
        # 账目仍要留痕：被阻断的尝试也有 final_status 与版本信息。
        usage = item.usage_json or {}
        assert usage.get("final_status") == "blocked"
        assert usage.get("schema_version") == "requirement-generation-ledger-v1"

    job = db.get(BackgroundJob, response.json()["job_id"])
    assert job.payload_summary_json == {"input_id": input_id}
    assert job.status in {"completed", "partially_completed", "failed"}


def test_revocation_after_completion_does_not_rewrite_finished_items(snapshot_api, monkeypatch):
    """已完成的分片保持已完成；撤销只影响尚未执行的分片。"""

    from app.services.task_queue.inline import InlineTaskQueue

    client, db, project, field, req, membership = snapshot_api
    base, ids = _three_field_scope(client, db, project, field, req)
    monkeypatch.setattr("app.services.task_queue.factory.get_task_queue", lambda: InlineTaskQueue())

    completed: list[int] = []

    def generate(db, row, item, project):
        completed.append(item.field_id)
        if len(completed) == 2:
            membership.project_role = "viewer"
            db.commit()
        return {"final_content": f"合成候选 {item.field_id}", "gaps": []}

    monkeypatch.setattr("app.services.requirement_generation_worker.generate_candidate", generate)

    response = client.post(base + "/generation-runs", json={"expected_content_version": 1,
        "field_ids": ids, "sections": ["business"], "idempotency_key": "revoke-late"})
    assert response.status_code == 201, response.text

    items = list(db.scalars(select(RequirementGenerationItem)
        .where(RequirementGenerationItem.input_id == response.json()["input_id"])
        .order_by(RequirementGenerationItem.id)))
    assert len(items) == 3
    # 两次生成都在撤销前完成；撤销后 handler 的完成前复核会把第二个候选也判为阻断。
    assert len(completed) == 2
    assert [item.status for item in items] == ["completed", "blocked", "blocked"]
    assert items[0].candidate_json is not None
    assert items[1].candidate_json is None and items[1].reason_code == "generation_permission_denied"
    assert items[2].candidate_json is None and items[2].reason_code == "generation_permission_denied"
    assert items[2].usage_json.get("final_status") == "blocked"
