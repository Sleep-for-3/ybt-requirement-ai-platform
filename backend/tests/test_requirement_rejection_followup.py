"""被否之后的闭环：重新导出的是同一份内容，还是真改了正文。

Round 67 按 artifact_id 判断"被否"，于是有个口子：把同一份冻结内容换个版式
（standard → survey）重新导出，会生成一个 id 更大的新产物，正文一个字没改，
但"被否"不再落在最新产物上，红牌自己就消失了。

Round 69 把判断换成 content_hash（``requirement-delivery-status-v7``），并新增
``/projects/{pid}/rejection-followup`` 只读跟随核对，固定三条行为：

1. 只换版式重导 → 红牌继续压着（``human_rejected``），跟进状态 ``reexported_same_content``；
2. 真改了正文再导 → 红牌解除、回到 ``exportable``，跟进状态 ``reexported_changed``（等人工再核对）；
3. 从没被否过 → 跟进清单为空，不去猜。
"""

from __future__ import annotations

from pathlib import Path

from test_requirement_acceptance import _export
from test_requirement_export_unified import _use_temp_storage
from test_requirement_snapshot_api import snapshot_api, snapshot_db  # noqa: F401  夹具复用


def _status_item(client, project_id: int, requirement_id: int) -> dict:
    response = client.get(f"/projects/{project_id}/requirements-status")
    assert response.status_code == 200, response.text
    return next(entry for entry in response.json()["items"] if entry["requirement_id"] == requirement_id)


def _followup(client, project_id: int) -> dict:
    response = client.get(f"/projects/{project_id}/rejection-followup")
    assert response.status_code == 200, response.text
    return response.json()


def _attest_rejected(client, base: str, artifact_id: int, basis: str) -> None:
    response = client.post(
        f"{base}/render-artifacts/{artifact_id}/attestations",
        json={"conclusion": "rejected", "basis": basis},
    )
    assert response.status_code == 200, response.text


def test_reexport_in_another_layout_keeps_the_rejection(tmp_path: Path, monkeypatch, snapshot_api):
    """只换了版式：新产物 id 更大，但 content_hash 相同 → 红牌必须继续压着。"""

    client, db, project, field, req, *_ = snapshot_api
    _use_temp_storage(tmp_path, monkeypatch)
    base = f"/projects/{project.id}/requirements/{req.id}"

    first = _export(client, project, req, layout="standard")
    _attest_rejected(client, base, first, "第 3 章缺「币种」列的换算口径，业务口径对不上")
    assert _status_item(client, project.id, req.id)["readiness"] == "human_rejected"

    # 同一份冻结内容，换个版式重导：渲染身份变了 → 新产物；正文没动 → content_hash 相同。
    second = _export(client, project, req, layout="survey")
    assert second != first

    item = _status_item(client, project.id, req.id)
    assert item["readiness"] == "human_rejected"
    assert item["human_rejected"] is True
    assert item["rejection"]["artifact_id"] == first
    assert item["rejection"]["on_latest_artifact"] is False
    assert item["rejection"]["same_content_as_latest"] is True
    assert item["rejection"]["superseded_by"] is not None
    assert item["rejection"]["superseded_by"]["id"] == second

    body = _followup(client, project.id)
    entry = next(row for row in body["items"] if row["requirement_id"] == req.id)
    assert entry["state"] == "reexported_same_content"
    assert entry["content_changed"] is False
    assert entry["rendering_only"] is True
    assert entry["rejected"]["artifact_id"] == first
    assert [row["artifact_id"] for row in entry["later_artifacts"]] == [second]
    assert entry["later_artifacts"][0]["same_content"] is True
    assert body["summary"]["reexported_same_content"] == 1
    assert "不等于复核通过" in body["note"]


def test_reexport_after_a_real_edit_clears_the_rejection(tmp_path: Path, monkeypatch, snapshot_api):
    """真改了正文：content_hash 变了 → 红牌解除，但在跟进清单里标成"等人工再核对"。"""

    client, db, project, field, req, *_ = snapshot_api
    _use_temp_storage(tmp_path, monkeypatch)
    base = f"/projects/{project.id}/requirements/{req.id}"

    first = _export(client, project, req, layout="standard")
    _attest_rejected(client, base, first, "业务口径第 2 段把「含税」写成了「不含税」")

    assert client.post(base + "/revisions", json={"expected_version": req.version or 1}).status_code == 201
    edit = client.put(
        f"{base}/fields/{field.id}",
        json={
            "section": "business",
            "changes": {"business_definition": "按登记依据改成含税口径，并补上换算说明"},
            "expected_content_version": client.get(base + "/document").json()["revision"]["content_version"],
        },
    )
    assert edit.status_code == 200, edit.text
    second = _export(client, project, req, layout="standard")
    assert second != first

    item = _status_item(client, project.id, req.id)
    assert item["readiness"] == "exportable"
    assert item["human_rejected"] is False
    assert item["rejection"]["same_content_as_latest"] is False

    body = _followup(client, project.id)
    entry = next(row for row in body["items"] if row["requirement_id"] == req.id)
    assert entry["state"] == "reexported_changed"
    assert entry["content_changed"] is True
    assert entry["rendering_only"] is False
    assert body["summary"]["reexported_changed"] == 1
    # 跟进清单只描述事实，不给"已通过"这种结论。
    assert "复核通过" not in entry["state_label"]


def test_followup_is_empty_when_nothing_was_rejected(tmp_path: Path, monkeypatch, snapshot_api):
    client, db, project, field, req, *_ = snapshot_api
    _use_temp_storage(tmp_path, monkeypatch)
    _export(client, project, req, layout="standard")

    body = _followup(client, project.id)
    assert body["items"] == []
    assert body["summary"] == {
        "rejected": 0,
        "still_rejected": 0,
        "reexported_same_content": 0,
        "reexported_changed": 0,
    }
    assert body["followup_version"] == "requirement-rejection-followup-v1"
