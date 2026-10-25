"""P2-A 事实包导入 API：内容去重、结论冻结、缺口可见、权限边界。

这里验证的是"平台不执行跑批，但必须把客户给的运行事实如实记账"这条边界：
导入成功不等于业务结论已验证，重复导入不会刷新当时的校验结论。
"""

from __future__ import annotations

import copy

from test_requirement_snapshot_api import snapshot_api, snapshot_db  # noqa: F401

from app.services.requirement_runtime_fact import FACT_PACK_VERSION

FULL_PACK = {
    "pack_version": FACT_PACK_VERSION,
    "source": {
        "kind": "bank_authorized_export",
        "exported_by": "data-ops",
        "exported_at": "2026-10-20T09:00:00+08:00",
        "file_sha256": "a" * 64,
    },
    "script": {"version_id": 12, "batch_id": "batch-20261020", "script_hash": "b" * 64},
    "run": {
        "execution_batch": "run-20261020-01",
        "business_date": "2026-10-19",
        "parameters": {"loan_type": "normal"},
        "metadata_version": "metadata-2026-10-01",
    },
    "quality": {
        "key_uniqueness": [{"keys": ["CUST_NO", "BRANCH_NO"], "unique_rate": 1.0}],
        "null_rates": {"CUST_NO": 0.0, "LOAN_BALANCE": 0.02},
        "join_counts": [{"name": "loan_to_customer", "left_rows": 1000, "right_rows": 1200, "matched_rows": 998}],
        "sampled_rows": 1000,
    },
}

URL = "/projects/{pid}/requirements/{rid}/runtime-fact-packs"


def _url(project, req):
    return URL.format(pid=project.id, rid=req.id)


def test_complete_pack_is_stored_as_full_run_verified(snapshot_api):
    client, db, project, field, req, _ = snapshot_api

    resp = client.post(_url(project, req), json=FULL_PACK)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["created"] is True
    pack = body["pack"]
    assert pack["level"] == "full_run_validation"
    assert pack["status"] == "verified"
    assert pack["execution_batch"] == "run-20261020-01"
    assert pack["business_date"] == "2026-10-19"
    assert len(pack["pack_sha256"]) == 64
    assert body["gaps"] == []
    assert pack["validation"]["validation_version"].startswith("runtime-fact-validation-")


def test_same_content_imports_once_without_refreshing_conclusions(snapshot_api):
    client, db, project, field, req, _ = snapshot_api

    first = client.post(_url(project, req), json=FULL_PACK).json()
    second = client.post(_url(project, req), json=copy.deepcopy(FULL_PACK)).json()

    assert first["created"] is True
    assert second["created"] is False
    assert first["pack"]["id"] == second["pack"]["id"]
    assert second["pack"]["validation"] == first["pack"]["validation"]

    listed = client.get(_url(project, req)).json()
    assert listed["count"] == 1


def test_pack_without_run_identity_stays_unverified_and_exposes_gaps(snapshot_api):
    client, db, project, field, req, _ = snapshot_api

    partial = copy.deepcopy(FULL_PACK)
    partial.pop("run")
    resp = client.post(_url(project, req), json=partial)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    pack = body["pack"]
    # 有脚本 hash / 元数据版本等抽样信号、但没有执行批次与业务日期：
    # 只能算抽样验证，不能称为"运行已验证"。
    assert pack["level"] == "sampled_validation"
    assert pack["status"] == "partially_verified"
    assert pack["execution_batch"] is None
    assert pack["business_date"] is None
    assert pack["validation"]["limitations"], "缺少运行身份必须写明限制"
    gaps = {item["id"] for item in body["gaps"]}
    assert "runtime_fact:unverified" in gaps

    # 缺口与结论在列表里同样可见，不依赖首次响应。
    listed = client.get(_url(project, req)).json()
    assert listed["items"][0]["status"] == "partially_verified"
    assert {item["id"] for item in listed["items"][0]["gaps"]} >= gaps


def test_invalid_numbers_downgrade_and_never_raise(snapshot_api):
    client, db, project, field, req, _ = snapshot_api

    broken = copy.deepcopy(FULL_PACK)
    broken["quality"]["key_uniqueness"] = [{"keys": ["CUST_NO"], "unique_rate": 1.7}]
    broken["quality"]["join_counts"] = [{"name": "bad", "left_rows": 10, "right_rows": 10, "matched_rows": 11}]
    resp = client.post(_url(project, req), json=broken)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["pack"]["level"] == "static_inference"
    assert body["pack"]["status"] == "unverified"
    codes = {issue["code"] for issue in body["pack"]["issues"]}
    assert {"key_uniqueness_rate_invalid", "join_counts_matched_exceeds_left"} <= codes


def test_empty_or_non_object_pack_is_rejected(snapshot_api):
    client, db, project, field, req, _ = snapshot_api

    empty = client.post(_url(project, req), json={})
    assert empty.status_code == 422
    assert "事实包为空" in empty.json()["detail"]

    array = client.post(_url(project, req), json=[1, 2, 3])
    assert array.status_code == 422


def test_viewer_cannot_import_but_can_read(snapshot_api):
    client, db, project, field, req, membership = snapshot_api

    imported = client.post(_url(project, req), json=FULL_PACK)
    assert imported.status_code == 201, imported.text

    membership.project_role = "viewer"
    db.commit()

    denied = client.post(_url(project, req), json=copy.deepcopy(FULL_PACK))
    assert denied.status_code == 403
    read = client.get(_url(project, req))
    assert read.status_code == 200
    assert read.json()["count"] == 1
