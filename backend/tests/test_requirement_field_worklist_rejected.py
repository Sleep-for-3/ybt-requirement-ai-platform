"""被人判「不通过」的产物要进待办派工清单，否则"不通过"没有下家。

三条固定行为：
1. 最新产物被判「不通过」→ 这份文档里的每个字段都以 `artifact_rejected` 出现在派工清单里，
   并且清单顶部单独列出这份产物（谁判的、凭什么、影响多少字段）；
2. 重新导出后新产物没被否过 → 这些字段不再因为"被否"进清单，旧登记只留在审计里；
3. 判「通过」不往清单里加东西——看过一圈不等于有活要派。
"""

from __future__ import annotations

from pathlib import Path

from test_requirement_acceptance import _export
from test_requirement_export_unified import _use_temp_storage
from test_requirement_snapshot_api import snapshot_api, snapshot_db  # noqa: F401  夹具复用

from app.models import RequirementRenderArtifact
from app.services.requirement_field_worklist import WORKLIST_VERSION, build_field_worklist
from sqlalchemy import select


def _worklist(client, project_id: int) -> dict:
    response = client.get(f"/projects/{project_id}/requirements-worklist?limit=3000")
    assert response.status_code == 200, response.text
    return response.json()


def _attest(client, base: str, artifact_id: int, conclusion: str, basis: str):
    return client.post(
        f"{base}/render-artifacts/{artifact_id}/attestations",
        json={"conclusion": conclusion, "basis": basis},
    )


def _ours(payload: dict, requirement_id: int) -> list[dict]:
    return [item for item in payload["items"] if item["requirement_id"] == requirement_id]


def test_rejected_artifact_puts_its_fields_on_the_worklist(tmp_path: Path, monkeypatch, snapshot_api):
    client, db, project, field, req, _ = snapshot_api
    _use_temp_storage(tmp_path, monkeypatch)
    base = f"/projects/{project.id}/requirements/{req.id}"
    artifact_id = _export(client, project, req, layout="standard")

    before = _worklist(client, project.id)
    assert before["worklist_version"] == WORKLIST_VERSION
    assert before["rejected_requirement_count"] == 0
    assert before["rejected_requirements"] == []
    assert before["reason_totals"]["artifact_rejected"] == 0

    rejected = _attest(client, base, artifact_id, "rejected", "客户模板第三列表头错位，业务口径第 4 段漏了分母说明")
    assert rejected.status_code == 200, rejected.text

    payload = _worklist(client, project.id)
    assert payload["rejected_requirement_count"] == 1
    entry = payload["rejected_requirements"][0]
    assert entry["requirement_id"] == req.id
    assert entry["artifact_id"] == artifact_id
    assert entry["conclusion"] == "rejected"
    assert entry["conclusion_label"] == "人工核对不通过"
    assert "第三列表头错位" in entry["basis"]
    assert entry["field_count"] >= 1

    rows = _ours(payload, req.id)
    assert rows, "被否的产物应该把字段带进派工清单"
    for row in rows:
        assert "artifact_rejected" in row["reasons"]
        assert row["reason_labels"][row["reasons"].index("artifact_rejected")] == "所在产物被人工核对判不通过"
        assert row["artifact_rejected"]["artifact_id"] == artifact_id
        # 只读归并：被否不会替人关掉缺口，也不会改写处置。
        assert row["dispatch"] is None
    assert payload["reason_totals"]["artifact_rejected"] == entry["field_count"]
    # 这份清单不改任何东西：导出/冻结的事实仍在，处置仍为空。
    assert _worklist(client, project.id)["rejected_requirement_count"] == 1


def test_new_artifact_clears_the_rejection_reason(tmp_path: Path, monkeypatch, snapshot_api):
    client, db, project, field, req, _ = snapshot_api
    _use_temp_storage(tmp_path, monkeypatch)
    base = f"/projects/{project.id}/requirements/{req.id}"
    first = _export(client, project, req, layout="standard")
    assert _attest(client, base, first, "rejected", "封面缺报送机构名称").status_code == 200

    # 同一份快照重复导出复用同一产物，所以"新产物"必须来自内容变化。
    assert client.post(base + "/revisions", json={"expected_version": req.version or 1}).status_code == 201
    edit = client.put(
        f"{base}/fields/{field.id}",
        json={
            "section": "business",
            "changes": {"business_definition": "按人工核对依据改过的业务定义"},
            "expected_content_version": client.get(base + "/document").json()["revision"]["content_version"],
        },
    )
    assert edit.status_code == 200, edit.text
    second = _export(client, project, req, layout="standard")
    assert second != first

    payload = _worklist(client, project.id)
    assert payload["rejected_requirement_count"] == 0
    assert all("artifact_rejected" not in row["reasons"] for row in _ours(payload, req.id))
    # 历史登记不删除，只是不再压当前这份文档：两条产物都在，旧登记仍指向旧的。
    db.expire_all()
    artifacts = list(
        db.scalars(
            select(RequirementRenderArtifact)
            .where(RequirementRenderArtifact.requirement_id == req.id)
            .order_by(RequirementRenderArtifact.id.desc())
        )
    )
    assert [row.id for row in artifacts][:2] == [second, first]


def test_confirmed_attestation_does_not_add_work(tmp_path: Path, monkeypatch, snapshot_api):
    client, db, project, field, req, _ = snapshot_api
    _use_temp_storage(tmp_path, monkeypatch)
    base = f"/projects/{project.id}/requirements/{req.id}"
    artifact_id = _export(client, project, req, layout="standard")
    assert _attest(client, base, artifact_id, "confirmed", "逐列核对过表头与口径，与监管模板一致").status_code == 200

    payload = _worklist(client, project.id)
    assert payload["rejected_requirement_count"] == 0
    assert all("artifact_rejected" not in row["reasons"] for row in _ours(payload, req.id))


def test_service_layer_reports_the_reason_without_the_endpoint(snapshot_api):
    """判定逻辑在服务里，接口只是薄壳：直接调服务也能拿到同一份口径。"""

    _, db, project, *_ = snapshot_api
    payload = build_field_worklist(db, project.id)
    assert payload["worklist_version"] == WORKLIST_VERSION
    assert "artifact_rejected" in payload["reason_labels"]
    assert payload["rejected_requirement_count"] == 0
