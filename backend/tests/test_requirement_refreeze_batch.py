"""批量"只重新冻结"（POST /requirements/refreeze-batch）。

真实问题：模板表级口径更新后，看板上十几条需求变成"快照落后于当前内容"（正文没改）。
用户要的是把快照对齐，而不是再生成一批文件；逐条进导出面板重新冻结，既要点开每条，
又会顺手多出一批用不上的产物。这里的语义必须严格是"只冻结、不渲染"：

1. 与批量导出共用同一条预检：任何一条版本或内容哈希对不上，**一条都不冻结**；
2. 只写快照（`RequirementDelivery`），不写 `RequirementRenderArtifact`；
3. 同一份内容重复请求是幂等的（`created=False`），不会堆出一串内容相同的快照。
"""

from __future__ import annotations

import json

from sqlalchemy import func, select

from app.models import Requirement, RequirementDelivery, RequirementRenderArtifact
from test_requirement_snapshot_api import snapshot_api, snapshot_db  # noqa: F401  夹具复用


def _selection(client, project_id: int, requirements) -> list[dict]:
    entries = []
    for req in requirements:
        current = client.get(f"/projects/{project_id}/requirements/{req.id}/document").json()
        entries.append({"requirement_id": req.id, "expected_version": req.version,
                        "expected_hash": current["content_hash"]})
    return entries


def _second_requirement(db, project, req, name: str = "重新冻结第二条需求"):
    clone = Requirement(project_id=project.id, name=name, version=1, scope_json=dict(req.scope_json))
    db.add(clone)
    db.flush()
    return clone


def test_refreeze_batch_creates_snapshots_without_artifacts(snapshot_api):
    client, db, project, _, req, _ = snapshot_api
    second = _second_requirement(db, project, req)
    selection = _selection(client, project.id, [req, second])

    response = client.post(f"/projects/{project.id}/requirements/refreeze-batch",
                           json={"selection": selection})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["item_count"] == 2
    assert body["snapshots_created"] == 2
    assert [entry["requirement_id"] for entry in body["items"]] == [req.id, second.id]
    assert all(entry["created"] is True for entry in body["items"])
    assert all(entry["snapshot_id"] for entry in body["items"])

    assert db.scalar(select(func.count()).select_from(RequirementDelivery)) == 2
    assert db.scalar(select(func.count()).select_from(RequirementRenderArtifact)) == 0, \
        "只重新冻结，不得产生任何渲染产物"

    again = client.post(f"/projects/{project.id}/requirements/refreeze-batch",
                        json={"selection": selection})
    assert again.status_code == 200, again.text
    assert again.json()["snapshots_created"] == 0, "同一份内容重复冻结必须幂等"
    assert [entry["snapshot_id"] for entry in again.json()["items"]] == \
        [entry["snapshot_id"] for entry in body["items"]], "重复冻结必须复用同一快照"
    assert db.scalar(select(func.count()).select_from(RequirementDelivery)) == 2


def test_refreeze_batch_rejects_stale_hash_without_freezing_anything(snapshot_api):
    client, db, project, _, req, _ = snapshot_api
    second = _second_requirement(db, project, req)
    selection = _selection(client, project.id, [req, second])
    selection[-1]["expected_hash"] = "0" * 64

    response = client.post(f"/projects/{project.id}/requirements/refreeze-batch",
                           json={"selection": selection})
    assert response.status_code == 409
    assert "本次未冻结任何需求" in response.json()["detail"]
    assert db.scalar(select(func.count()).select_from(RequirementDelivery)) == 0, \
        "校验失败时不能留下半份快照"


def test_refreeze_batch_validates_selection_and_permissions(snapshot_api):
    client, db, project, _, req, membership = snapshot_api
    endpoint = f"/projects/{project.id}/requirements/refreeze-batch"
    good = _selection(client, project.id, [req])

    assert client.post(endpoint, json={"selection": "not-json"}).status_code == 422
    assert client.post(endpoint, json={}).status_code == 422
    assert client.post(endpoint, json={"selection": []}).status_code == 422
    assert client.post(endpoint, json={"selection": good * 2}).status_code == 422

    membership.project_role = "viewer"
    db.flush()
    assert client.post(endpoint, json={"selection": good}).status_code == 403
    assert db.scalar(select(func.count()).select_from(RequirementDelivery)) == 0


def test_refreeze_batch_accepts_json_string_selection(snapshot_api):
    client, db, project, _, req, _ = snapshot_api
    selection = _selection(client, project.id, [req])

    response = client.post(f"/projects/{project.id}/requirements/refreeze-batch",
                           json={"selection": json.dumps(selection, ensure_ascii=False)})
    assert response.status_code == 200, response.text
    assert response.json()["item_count"] == 1
