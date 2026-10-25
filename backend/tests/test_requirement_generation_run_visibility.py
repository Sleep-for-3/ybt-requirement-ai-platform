"""阻断/失败原因必须随生成条目返回。

真实事故：`K010002` 的 `filter_column_missing` 只能靠在数据库里查 `usage_json->>'detail'`
才知道原因，界面上只有"阻断"两个字——用户不知道该补什么。本用例固定：
1. 阻断条目必须带 `failure_detail`（等于记账时写入的 detail）；
2. 没有 record 原因的条目返回 None，不编造原因；
3. 该字段不是权限判断依据，viewer 也能看到自己项目里的原因。
"""

from __future__ import annotations

from app.models import Project, User
from test_requirement_snapshot_api import snapshot_api, snapshot_db  # noqa: F401  夹具复用

REASON = "候选正文主张与固定事实冲突（c3/filter_column_missing）：主张未提及固定过滤列 GROUP_INFO（漏过滤）"


def _blocked_item(db, input_id: int, field_id: int, *, detail: str | None):
    from app.models import RequirementGenerationItem

    item = RequirementGenerationItem(
        input_id=input_id,
        field_id=field_id,
        section="lineage",
        status="blocked",
        decision="pending",
        reason_code="generation_validation_blocked",
        usage_json={"schema_version": "requirement-generation-ledger-v1", "final_status": "blocked",
                    "self_correction_attempts": 2, "attempts": [], **({"detail": detail} if detail else {})},
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def test_blocked_item_reports_failure_detail(snapshot_api):
    client, db, project, field, req, _ = snapshot_api
    base = f"/projects/{project.id}/requirements/{req.id}"
    client.post(base + "/revisions", json={"expected_version": 1})
    prepared = client.post(base + "/generation-inputs", json={
        "expected_content_version": 1,
        "field_ids": [field.id],
        "sections": ["business", "lineage"],
        "idempotency_key": "blocked-detail-1",
    })
    assert prepared.status_code in (200, 201), prepared.text
    input_id = prepared.json()["id"]
    item = _blocked_item(db, input_id, field.id, detail=REASON)

    runs = client.get(base + "/generation-runs")
    assert runs.status_code == 200, runs.text
    entry = next(row for row in runs.json() if row["id"] == input_id)
    serialized = next(row for row in entry["items"] if row["id"] == item.id)
    assert serialized["status"] == "blocked"
    assert serialized["reason_code"] == "generation_validation_blocked"
    assert serialized["failure_detail"] == REASON, "阻断原因必须原样返回，界面才能告诉用户要补什么"
    assert entry["counts"]["blocked"] == 1


def test_item_without_recorded_reason_returns_none(snapshot_api):
    client, db, project, field, req, _ = snapshot_api
    base = f"/projects/{project.id}/requirements/{req.id}"
    client.post(base + "/revisions", json={"expected_version": 1})
    prepared = client.post(base + "/generation-inputs", json={
        "expected_content_version": 1,
        "field_ids": [field.id],
        "sections": ["business"],
        "idempotency_key": "blocked-detail-2",
    })
    input_id = prepared.json()["id"]
    item = _blocked_item(db, input_id, field.id, detail=None)

    runs = client.get(base + "/generation-runs")
    serialized = next(row for row in next(entry for entry in runs.json() if entry["id"] == input_id)["items"]
                      if row["id"] == item.id)
    assert serialized["failure_detail"] is None, "没有记录原因时返回 None，不得编造"
