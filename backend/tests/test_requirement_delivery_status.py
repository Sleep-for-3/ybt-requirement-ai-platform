"""项目级交付状态：冻结态、产物数、打开缺口的聚合口径。

真实动机：项目负责人在十几条需求之间反复点开，才能知道"哪些已经冻结、可以导出"。
这里的判据必须与工作台完全一致（content_hash），且不能把已关闭的缺口算进待办。
"""

from sqlalchemy import func, select

from app.models import RequirementDelivery, TargetTable, User
from test_requirement_snapshot_api import snapshot_api, snapshot_db  # noqa: F401


def _status(client, project_id):
    response = client.get(f"/projects/{project_id}/requirements-status")
    assert response.status_code == 200, response.text
    return response.json()


def test_delivery_status_tracks_frozen_then_stale(snapshot_api):
    client, db, project, field, req, _ = snapshot_api
    base = f"/projects/{project.id}/requirements/{req.id}"

    empty = _status(client, project.id)
    assert empty["requirement_count"] == 1
    item = empty["items"][0]
    assert item["requirement_id"] == req.id
    assert item["frozen"] is False and item["stale"] is False
    assert item["snapshot_count"] == 0 and item["latest_snapshot"] is None
    assert empty["summary"]["no_snapshot"] == 1
    assert empty["summary"]["frozen"] == 0

    preview = client.get(base + "/document").json()
    frozen = client.post(base + "/snapshots", json={"expected_version": 1, "expected_hash": preview["content_hash"]})
    assert frozen.status_code == 201, frozen.text
    snapshot_id = frozen.json()["id"]

    after = _status(client, project.id)
    item = after["items"][0]
    assert item["frozen"] is True and item["stale"] is False
    assert item["latest_snapshot"]["id"] == snapshot_id
    assert item["latest_snapshot"]["content_hash"] == preview["content_hash"]
    assert item["current_content_hash"] == preview["content_hash"]
    assert after["summary"]["frozen"] == 1 and after["summary"]["stale"] == 0

    # 真实编辑后应立刻变"有未冻结改动"，且判据只看 content_hash，不看版本号。
    assert client.post(base + "/revisions", json={"expected_version": 1}).status_code == 201
    edit = client.put(f"{base}/fields/{field.id}", json={
        "section": "business",
        "changes": {"business_definition": "修改后的业务定义（交付状态用例）"},
        "expected_content_version": client.get(base + "/document").json()["revision"]["content_version"],
    })
    assert edit.status_code == 200, edit.text

    stale = _status(client, project.id)
    item = stale["items"][0]
    assert item["frozen"] is False and item["stale"] is True
    assert item["current_content_hash"] != item["latest_snapshot"]["content_hash"]
    assert stale["summary"]["stale"] == 1 and stale["summary"]["frozen"] == 0
    assert db.scalar(select(func.count()).select_from(RequirementDelivery)) == 1


def test_delivery_status_counts_only_open_gaps(snapshot_api):
    client, db, project, field, req, _ = snapshot_api
    document = client.get(f"/projects/{project.id}/requirements/{req.id}/document").json()
    gaps = document.get("gaps") or []
    expected = [gap for gap in gaps if str(gap.get("status") or "open") not in ("resolved", "rejected", "closed")]
    expected_fields = {gap["field_id"] for gap in expected if gap.get("field_id")}

    item = _status(client, project.id)["items"][0]
    assert item["open_gap_count"] == len(expected)
    assert item["open_gap_field_count"] == len(expected_fields)
    assert item["field_count"] == len(document.get("fields") or [])


def test_delivery_status_requires_project_permission(snapshot_api):
    client, db, project, _, _, membership = snapshot_api
    membership.status = "inactive"
    db.flush()
    response = client.get(f"/projects/{project.id}/requirements-status")
    assert response.status_code == 404


def test_delivery_status_truncation_is_explicit(snapshot_api):
    client, db, project, _, _, _ = snapshot_api
    from app.services import requirement_delivery_status as service

    truncated = service.build_delivery_status(db, project.id, limit=0)
    assert truncated["items"] == []
    assert truncated["truncated"] is True
    assert truncated["requirement_count"] == 0
    assert truncated["status_version"] == service.STATUS_VERSION

    # 用户 id 只是审计字段，这里确认聚合没有依赖登录态以外的隐式上下文。
    assert db.scalar(select(func.count()).select_from(User)) >= 1


def test_delivery_status_names_who_froze_and_exported(snapshot_api):
    """看板要能回答"最后一次对齐 / 导出是谁做的"：快照与产物记录里本来就有 created_by。"""
    client, db, project, field, req, _ = snapshot_api
    base = f"/projects/{project.id}/requirements/{req.id}"

    item = _status(client, project.id)["items"][0]
    assert item["latest_snapshot"] is None and item["last_artifact"] is None

    preview = client.get(base + "/document").json()
    frozen = client.post(base + "/snapshots", json={"expected_version": 1, "expected_hash": preview["content_hash"]})
    assert frozen.status_code == 201, frozen.text
    snapshot_id = frozen.json()["id"]

    item = _status(client, project.id)["items"][0]
    actor = item["latest_snapshot"]["actor"]
    assert actor is not None and actor["id"] > 0
    assert actor["name"]

    export = client.post(
        f"{base}/exports",
        data={"format": "xlsx", "source_kind": "draft_snapshot", "source_id": str(snapshot_id), "layout": "standard"},
    )
    assert export.status_code == 200, export.text

    item = _status(client, project.id)["items"][0]
    assert item["last_artifact"]["actor"] is not None
    assert item["last_artifact"]["actor"]["name"]

    # 历史数据可能没有操作人（早期导入 / 已删号）。这时必须是 None，前端自己显示"未知用户"，
    # 服务端不能编一个名字。
    from app.models import RequirementDelivery

    row = db.query(RequirementDelivery).filter(RequirementDelivery.id == snapshot_id).one()
    row.created_by = None
    db.commit()
    item = _status(client, project.id)["items"][0]
    assert item["latest_snapshot"]["actor"] is None


def test_delivery_status_exposes_readiness_and_formal_delivery(snapshot_api):
    client, db, project, field, req, _ = snapshot_api
    base = f"/projects/{project.id}/requirements/{req.id}"

    # 没有快照：既不能直接出文件，也没有正式交付。
    item = _status(client, project.id)["items"][0]
    assert item["readiness"] == "no_snapshot"
    assert item["formal_delivery"] is None
    assert item["formal_delivery_count"] == 0
    assert _status(client, project.id)["summary"]["formal_delivered"] == 0

    preview = client.get(base + "/document").json()
    frozen = client.post(base + "/snapshots", json={"expected_version": 1, "expected_hash": preview["content_hash"]})
    assert frozen.status_code == 201
    snapshot_id = frozen.json()["id"]

    # 冻结但没导出过：是"已冻结，尚未导出"，不是"可直接重新导出"。
    after = _status(client, project.id)
    item = after["items"][0]
    assert item["readiness"] == "frozen"
    assert after["summary"]["frozen_pending_export"] == 1
    assert after["summary"]["exportable"] == 0

    # 有产物之后才算"可直接重新导出"。
    export = client.post(f"{base}/exports", data={"format": "xlsx", "source_kind": "draft_snapshot", "source_id": str(snapshot_id), "layout": "standard"})
    assert export.status_code == 200, export.text
    exported = _status(client, project.id)
    item = exported["items"][0]
    assert item["readiness"] == "exportable"
    assert item["artifact_count"] == 1
    assert exported["summary"]["exportable"] == 1


def test_readiness_mapping_covers_every_state():
    from app.services import requirement_delivery_status as service

    assert service._readiness(True, False, 2) == "exportable"
    assert service._readiness(True, False, 0) == "frozen"
    assert service._readiness(False, True, 5) == "stale"
    assert service._readiness(False, False, 3) == "no_snapshot"
    # 只有引用元数据变了：需要重新冻结，但不需要改正文——单独一态
    assert service._readiness(False, True, 0, False, False, True) == "metadata_stale"
    assert service._readiness(False, True, 5, False, False, True) == "metadata_stale"
    # 已冻结（含正式交付）优先，元数据标记不能盖过它
    assert service._readiness(True, False, 0, False, False, True) == "frozen"
    # 正式交付且内容一致才是最高态；"正式交付后又改过内容"不能算已交付
    assert service._readiness(False, False, 0, True, True) == "delivered"
    assert service._readiness(True, False, 2, True, True) == "delivered"
    assert service._readiness(True, False, 2, False, False) == "exportable"
    # 正式交付过但内容已改：既不冒充已完成，也不显示成"无快照"
    assert service._readiness(False, False, 0, False, True) == "delivered_stale"
    assert service._readiness(True, False, 1, False, True) == "delivered_stale"
    # round 67：最新产物被人判「不通过」是最高优先级——比"已正式交付"更需要负责人先处理。
    assert service._readiness(True, False, 2, True, True, False, True) == "human_rejected"
    assert service._readiness(True, False, 2, False, False, False, True) == "human_rejected"
    assert set(service.READINESS_LABELS) == {
        "delivered", "delivered_stale", "exportable", "frozen",
        "metadata_stale", "stale", "no_snapshot", "human_rejected",
    }


def test_formal_delivery_is_absent_when_none_was_delivered(snapshot_api):
    client, db, project, field, req, _ = snapshot_api
    item = _status(client, project.id)["items"][0]
    assert item["formal_delivery"] is None
    assert item["formal_delivery_count"] == 0
    assert _status(client, project.id)["summary"]["formal_delivered"] == 0

def test_delivery_status_separates_reference_meta_change_from_content_change(snapshot_api):
    """表级引用元数据变了，不等于需求正文改了。

    真实事故：调研表的"表级口径"（主题 / 报送数据域）补进 document_content 后，
    已冻结需求的 content_hash 全部变化，看板把十几条需求显示成"有未冻结改动"，
    而用户根本没有编辑任何正文。这里固定两条判据：
    - 只改 TargetTable.theme → stale=True 但 caliber_changed=False、reference_meta_only=True；
    - 真正改字段正文 → caliber_changed=True、reference_meta_only=False。
    """

    client, db, project, field, req, _ = snapshot_api
    base = f"/projects/{project.id}/requirements/{req.id}"

    preview = client.get(base + "/document").json()
    frozen = client.post(base + "/snapshots", json={"expected_version": 1, "expected_hash": preview["content_hash"]})
    assert frozen.status_code == 201, frozen.text

    table = db.get(TargetTable, req.scope_json["target_table_id"])
    table.theme = "改动后的数据主题（仅引用元数据）"
    db.commit()

    meta_only = _status(client, project.id)
    item = meta_only["items"][0]
    assert item["stale"] is True and item["frozen"] is False
    assert item["caliber_changed"] is False
    assert item["reference_meta_only"] is True
    assert item["current_caliber_hash"] == item["latest_snapshot"]["caliber_hash"]
    assert item["current_content_hash"] != item["latest_snapshot"]["content_hash"]
    assert meta_only["summary"]["reference_meta_only"] == 1
    assert meta_only["summary"]["caliber_changed"] == 0
    # 就绪度要把它和"正文真改了"分开：否则看板把只差一次重新冻结的需求
    # 显示成"要改正文"，评审会去改根本没错的口径。
    assert item["readiness"] == "metadata_stale"
    assert meta_only["summary"]["metadata_stale"] == 1
    assert meta_only["summary"]["stale"] == 0

    assert client.post(base + "/revisions", json={"expected_version": 1}).status_code == 201
    revision = client.get(base + "/document").json()
    edit = client.put(f"{base}/fields/{field.id}", json={
        "section": "business",
        "changes": {"business_definition": "真正改动的正文口径（引用元数据对照用）"},
        "expected_content_version": revision["revision"]["content_version"],
    })
    assert edit.status_code == 200, edit.text

    changed = _status(client, project.id)
    item = changed["items"][0]
    assert item["stale"] is True
    assert item["caliber_changed"] is True
    assert item["reference_meta_only"] is False
    assert item["readiness"] == "stale"
    assert item["current_caliber_hash"] != item["latest_snapshot"]["caliber_hash"]
    assert changed["summary"]["caliber_changed"] == 1
    assert changed["summary"]["reference_meta_only"] == 0
    assert changed["summary"]["metadata_stale"] == 0
    assert changed["summary"]["stale"] == 1


def test_gap_breakdown_splits_open_gaps_by_field_and_category():
    from app.services.requirement_delivery_status import gap_breakdown

    content = {
        "fields": [
            {"field": {"id": 11, "field_code": "H010001", "field_name": "借据ID"}},
            {"field": {"id": 12, "field_code": "H010010", "field_name": "借款余额"}},
        ],
        "gaps": [
            # 字段级
            {"id": "g1", "field_id": 11, "status": "open", "message": "未核验上游元数据：SAFE.GB.HYF_A"},
            {"id": "g2", "field_id": 11, "status": "open", "message": "未核验上游元数据：SAFE.GB.HYF_B"},
            {"id": "g3", "field_id": 12, "status": "open", "message": "缺少来源到集市字段的加工映射"},
            # 范围级
            {"id": "g4", "field_id": None, "status": None, "message": "Unknown template variable preserved"},
            # 已关闭的不计
            {"id": "g5", "field_id": 11, "status": "resolved", "message": "早期问题"},
            {"id": "g6", "field_id": 12, "status": "rejected", "message": "误报"},
        ],
    }

    body = gap_breakdown(content)
    assert body["breakdown_version"] == "requirement-gap-breakdown-v1"
    # 与 _open_gaps 同口径：4 条打开（3 字段级 + 1 范围级），覆盖 2 个字段
    assert body["open_gap_count"] == 4
    assert body["field_gap_count"] == 3
    assert body["scope_gap_count"] == 1
    assert body["field_count"] == 2
    assert [(item["field_code"], item["count"]) for item in body["fields"]] == [("H010001", 2), ("H010010", 1)]
    # 类别按"："之前归并，否则每条带具体表名的消息都会变成单例
    assert body["categories"][0]["category"] == "未核验上游元数据"
    assert body["categories"][0]["count"] == 2
    assert body["truncated_fields"] is False
    # 合成数据只有 3 类，未到默认上限 8：此时必须原样给全、不能凭空造"其他"行
    assert body["truncated_categories"] is False
    assert all(item["aggregated"] is False for item in body["categories"])
    assert sum(item["count"] for item in body["categories"]) == body["open_gap_count"]

    # 类别超过上限时尾巴折成"其他 N 类"，而不是只给前几类、让"还有多少类"无从判断。
    # 用 category_limit=2 触发折叠：真实数据里 406 条缺口归出 219 类，只给前 8 类等于没说清剩下 211 类。
    folded = gap_breakdown(content, category_limit=2)
    assert folded["truncated_categories"] is True
    assert folded["category_count"] == body["category_count"]
    assert len(folded["categories"]) == 3
    assert folded["categories"][-1]["aggregated"] is True
    assert folded["categories"][-1]["category"].startswith("其他 ")
    assert sum(item["count"] for item in folded["categories"]) == folded["open_gap_count"]


def test_gap_breakdown_api_matches_project_status_count(snapshot_api):
    client, db, project, field, req, _ = snapshot_api
    # 造一条字段级缺口：把该字段的集市映射删掉后重新评估，触发"缺少来源到集市字段的加工映射"
    status = client.get(f"/projects/{project.id}/requirements-status")
    assert status.status_code == 200, status.text
    item = [row for row in status.json()["items"] if row["requirement_id"] == req.id][0]

    body = client.get(f"/projects/{project.id}/requirements/{req.id}/gap-breakdown")
    assert body.status_code == 200, body.text
    payload = body.json()
    assert payload["requirement_id"] == req.id
    # 两处数字必须一致：看板上的"打开缺口"与弹层明细同源，否则评委会看到两个数
    assert payload["open_gap_count"] == item["open_gap_count"]
    assert payload["field_gap_count"] + payload["scope_gap_count"] == payload["open_gap_count"]
    assert payload["field_count"] <= len(payload["fields"]) + (1_000_000 if not payload["truncated_fields"] else 0)
    assert isinstance(payload["categories"], list)
    # 深链需要的定位信息：看板只有 requirement_id，工作台按 tableId+scenarioId 才能还原同一条需求。
    document = client.get(f"/projects/{project.id}/requirements/{req.id}/document").json()
    assert payload["target_table_id"] == document["requirement"]["target_table_id"]
    assert payload["scenario_id"] == document["requirement"]["scenario_id"]
    assert payload["target_table_code"] == document["target_table"]["table_code"]

    missing = client.get(f"/projects/{project.id}/requirements/99999/gap-breakdown")
    assert missing.status_code == 404

def test_script_binding_reports_fields_the_script_does_not_produce():
    from types import SimpleNamespace as NS
    from app.services import requirement_delivery_status as service

    field_a = NS(id=1, field_code="A010001", field_name="字段一", target_table_id=10)
    field_b = NS(id=2, field_code="A010002", field_name="字段二", target_table_id=10)
    field_c = NS(id=3, field_code="SFJJGDM", field_name="省局分局机构代码", target_table_id=10)
    row = NS(scope_json={"target_table_id": 10, "field_ids": [1, 2]})
    content = {"script_basis": {"confirmation": {"field_bindings": {"COL_A": 1, "COL_B": 2}}}}
    binding = service._script_binding(content, row, {10: [field_a, field_b, field_c]})
    assert binding["table_field_count"] == 3
    assert binding["bound_field_count"] == 2
    assert binding["unbound_count"] == 1
    assert binding["unbound"] == [{"field_id": 3, "field_code": "SFJJGDM", "field_name": "省局分局机构代码"}]


def test_script_binding_is_absent_without_script_basis():
    from types import SimpleNamespace as NS
    from app.services import requirement_delivery_status as service

    field_a = NS(id=1, field_code="A010001", field_name="字段一", target_table_id=10)
    row = NS(scope_json={"target_table_id": 10, "field_ids": [1]})
    # 手工建的需求没有 field_bindings：这时说“脚本没产出”是错的，必须是 None 而不是 0。
    assert service._script_binding({}, row, {10: [field_a]}) is None
    assert service._script_binding({"script_basis": {"confirmation": {"field_bindings": {}}}}, row, {10: [field_a]}) is None

def _script_version(db, project, *, file_name, version_no, parse_status="parsed"):
    from uuid import uuid4

    from app.models import ScriptFile, ScriptFileVersion, StoredFile, User

    user = db.scalar(select(User))
    stored = StoredFile(
        institution_id=project.institution_id,
        project_id=project.id,
        storage_key=f"tests/{uuid4().hex}/{file_name}",
        original_file_name=file_name,
        content_type="text/plain",
        byte_size=1,
        content_hash="c" * 64,
        created_by=user.id,
    )
    db.add(stored)
    db.flush()
    script = db.scalar(select(ScriptFile).where(
        ScriptFile.project_id == project.id, ScriptFile.relative_path == file_name
    ))
    if script is None:
        script = ScriptFile(
            institution_id=project.institution_id,
            project_id=project.id,
            relative_path=file_name,
            file_name=file_name,
            file_type="sql",
            current_version_no=version_no,
        )
        db.add(script)
        db.flush()
    version = ScriptFileVersion(
        project_id=project.id,
        script_file_id=script.id,
        version_no=version_no,
        file_hash=f"{version_no:064d}",
        normalized_hash=f"{version_no + 7:064d}",
        raw_content_storage_file_id=stored.id,
        parse_status=parse_status,
    )
    db.add(version)
    db.commit()
    return script, version


def test_script_basis_freshness_flags_newer_script_version(snapshot_api, monkeypatch):
    """脚本重新导入产生新版本后，已冻结的脚本依据必须被标成「脚本有更新」。

    真实动机：需求冻结的是建需那一刻的脚本版本，脚本升级后需求不会自动跟着变（这是刻意的），
    但看板必须让人看到「这条需求依据落后了」，否则会在旧脚本上继续交付。
    """

    from app.services import requirement_delivery_status as module

    client, db, project, _field, req, _ = snapshot_api
    script, version_one = _script_version(db, project, file_name="YBT_T_9_9.sql", version_no=1)

    def fake_content(_db, row):
        if row.id != req.id:
            return {}
        return {
            "target_table": {"table_code": "T_9_9"},
            "script_basis": {
                "versions": [{
                    "id": version_one.id,
                    "script_file_id": script.id,
                    "version_no": 1,
                    "parse_status": "parsed",
                    "path": "YBT_T_9_9.sql",
                }]
            },
        }

    monkeypatch.setattr(module, "document_content", fake_content)

    response = client.get(f"/projects/{project.id}/script-basis-freshness")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["freshness_version"] == "requirement-script-basis-freshness-v1"
    assert body["summary"]["aligned"] == 1
    assert body["items"][0]["state"] == "aligned"

    _script_version(db, project, file_name="YBT_T_9_9.sql", version_no=2)
    body = client.get(f"/projects/{project.id}/script-basis-freshness").json()
    assert body["summary"]["script_updated"] == 1
    assert body["items"][0]["state"] == "script_updated"
    detail = body["items"][0]["versions"][0]
    assert detail["frozen_version_no"] == 1
    assert detail["latest_version_no"] == 2
    assert detail["file_name"] == "YBT_T_9_9.sql"
def test_delivery_status_counts_pending_candidates(snapshot_api, snapshot_db):
    """已生成未采纳的候选要在看板上数出来。

    真实坑：生成完成看起来像"正文已经改好"，实际候选还等着人工采纳；
    看板不显示这个数字，评审就会把"生成完成"当成"可以交付"。
    """
    from app.models import (
        RequirementGenerationInput,
        RequirementGenerationItem,
        RequirementRevision,
    )

    client, db, project, field, requirement, _ = snapshot_api
    client.post(f"/projects/{project.id}/requirements/{requirement.id}/revisions", json={"expected_version": requirement.version})
    db.refresh(requirement)
    revision = (
        db.query(RequirementRevision)
        .filter_by(requirement_id=requirement.id)
        .order_by(RequirementRevision.content_version.desc())
        .first()
    )
    row = RequirementGenerationInput(
        project_id=project.id,
        requirement_id=requirement.id,
        revision_id=revision.id,
        idempotency_key="test-pending-candidates",
        request_hash="0" * 64,
        input_hash="1" * 64,
        input_json={"content_version": revision.content_version, "field_ids": [field.id], "sections": ["business"]},
        created_by=getattr(project, "project_owner_id", None) or 1,
    )
    db.add(row)
    db.flush()
    db.add_all([
        RequirementGenerationItem(input_id=row.id, field_id=field.id, section="business",
                                  status="completed", decision="pending"),
        RequirementGenerationItem(input_id=row.id, field_id=field.id + 1000, section="lineage",
                                  status="completed", decision="pending"),
        RequirementGenerationItem(input_id=row.id, field_id=field.id + 2000, section="lineage",
                                  status="completed", decision="adopted"),
        RequirementGenerationItem(input_id=row.id, field_id=field.id + 3000, section="lineage",
                                  status="blocked", decision="pending"),
    ])
    db.commit()

    status = client.get(f"/projects/{project.id}/requirements-status")
    assert status.status_code == 200, status.text
    item = next(row for row in status.json()["items"] if row["requirement_id"] == requirement.id)
    # 只数"生成完成且未处理"的：已采纳的不算、阻断的也不算。
    assert item["pending_candidate_count"] == 2
    summary = status.json()["summary"]
    assert summary["with_pending_candidates"] >= 1
    assert summary["pending_candidate_total"] >= 2
