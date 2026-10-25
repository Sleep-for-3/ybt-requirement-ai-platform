"""P2-A 事实包注入生成输入：只能降级表述，不能被当成运行已验证。

边界：事实包在导入时冻结，生成输入里传递的是"每类事实可以说到什么强度"，
不是让模型把 static_inference 的推断写进正文而不留痕迹。
"""

from __future__ import annotations

from sqlalchemy import select

from app.models import Requirement, RequirementGenerationInput, RequirementRuntimeFactPack
from app.services.requirement_runtime_fact import FACT_PACK_VERSION
from test_requirement_snapshot_api import snapshot_api, snapshot_db  # noqa: F401

PACK_URL = "/projects/{pid}/requirements/{rid}/runtime-fact-packs"

FULL_PACK = {
    "pack_version": FACT_PACK_VERSION,
    "source": {"kind": "bank_authorized_export", "exported_by": "data-ops",
               "exported_at": "2026-10-20T09:00:00+08:00", "file_sha256": "a" * 64},
    "script": {"version_id": 12, "batch_id": "batch-20261020", "script_hash": "b" * 64},
    "run": {"execution_batch": "run-20261020-01", "business_date": "2026-10-19",
            "parameters": {"loan_type": "normal"}, "metadata_version": "metadata-2026-10-01"},
    "quality": {
        "key_uniqueness": [{"keys": ["CUST_NO", "BRANCH_NO"], "unique_rate": 1.0}],
        "null_rates": {"CUST_NO": 0.0},
        "join_counts": [{"name": "loan_to_customer", "left_rows": 1000,
                         "right_rows": 1200, "matched_rows": 998}],
        "sampled_rows": 1000,
    },
}

# 数字本身不合法的包（空值率为负）：校验必须判为 error 并降级到静态推断，
# 不能因为"看起来有数据"就当样例验证通过。
WEAK_PACK = {
    "pack_version": FACT_PACK_VERSION,
    "quality": {"null_rates": {"CUST_NO": -0.3}, "sampled_rows": 200},
}


def _make_input(client, db, project, req, field, key):
    base = f"/projects/{project.id}/requirements/{req.id}"
    assert client.post(base + "/revisions", json={"expected_version": 1}).status_code == 201
    response = client.post(base + "/generation-inputs", json={
        "expected_content_version": 1, "field_ids": [field.id],
        "sections": ["business", "lineage"], "idempotency_key": key,
    })
    assert response.status_code == 201, response.text
    return db.get(RequirementGenerationInput, response.json()["id"]).input_json


def test_generation_input_without_fact_pack_has_no_runtime_block(snapshot_api):
    client, db, project, field, req, _ = snapshot_api
    frozen = _make_input(client, db, project, req, field, "no-facts")
    assert "runtime_facts" not in frozen


def test_verified_fact_pack_is_projectable_as_full_run(snapshot_api):
    client, db, project, field, req, _ = snapshot_api
    resp = client.post(PACK_URL.format(pid=project.id, rid=req.id), json=FULL_PACK)
    assert resp.status_code == 201, resp.text
    pack_id = resp.json()["pack"]["id"]

    frozen = _make_input(client, db, project, req, field, "facts-full")
    runtime = frozen["runtime_facts"]
    assert runtime["fact_pack_id"] == pack_id
    assert runtime["level"] == "full_run_validation"
    assert runtime["verified"] is True
    assert runtime["frozen_at_import"] is True
    assert runtime["gaps"] == []
    key_uniqueness = next(item for item in runtime["facts"] if item["fact"] == "key_uniqueness")
    assert key_uniqueness["allowed_level"] == "full_run_validation"
    assert any("导入时冻结" in text for text in frozen["limitations"])
    assert not any("运行时事实缺口" in text for text in frozen["limitations"])


def test_weak_fact_pack_downgrades_claims_and_surfaces_gap(snapshot_api):
    client, db, project, field, req, _ = snapshot_api
    resp = client.post(PACK_URL.format(pid=project.id, rid=req.id), json=WEAK_PACK)
    assert resp.status_code == 201, resp.text
    assert resp.json()["pack"]["level"] == "static_inference"

    frozen = _make_input(client, db, project, req, field, "facts-weak")
    runtime = frozen["runtime_facts"]
    assert runtime["level"] == "static_inference"
    assert runtime["verified"] is False
    # 事实包自称弱，任何事实都不得被说成运行已验证。
    assert {item["allowed_level"] for item in runtime["facts"]} == {"static_inference"}
    assert runtime["gaps"] and runtime["gaps"][0]["id"] == "runtime_fact:unverified"
    assert any("只能作为静态推断" in text for text in frozen["limitations"])
    assert any("运行时事实缺口" in text for text in frozen["limitations"])


def test_fact_pack_scope_is_requirement_level(snapshot_api):
    """另一个需求的事实包不能出现在本需求的生成输入里。"""

    client, db, project, field, req, _ = snapshot_api
    other = Requirement(project_id=project.id, name="另一个需求", scope_json={}, content_version=0)
    db.add(other)
    db.commit()
    assert client.post(PACK_URL.format(pid=project.id, rid=other.id), json=FULL_PACK).status_code == 201

    frozen = _make_input(client, db, project, req, field, "facts-scope")
    assert "runtime_facts" not in frozen

    rows = db.scalars(select(RequirementRuntimeFactPack)).all()
    assert len(rows) == 1 and rows[0].requirement_id == other.id
