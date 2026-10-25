"""项目级待办派工清单：只归并已有信号，不改内容。"""

from __future__ import annotations

from app.models import (
    Requirement,
    RequirementGenerationInput,
    RequirementGenerationItem,
    RequirementRevision,
    RequirementDelivery,
    TargetField,
    TargetTable,
)
from app.services.requirement_field_dispatch import record_dispatch
from app.services.requirement_field_worklist import (
    REASON_LABELS,
    WORKLIST_VERSION,
    build_field_worklist,
)
from app.services.requirement_scope import content_digest
from test_requirement_snapshot_api import snapshot_api, snapshot_db  # noqa: F401  注册夹具


def _target_table(db, project) -> TargetTable:
    table = db.query(TargetTable).filter(TargetTable.project_id == project.id).first()
    if table is None:
        table = TargetTable(
            project_id=project.id,
            table_code="T_W1",
            table_name="派工表",
            description="",
        )
        db.add(table)
        db.flush()
    return table


def _fields(db, project, count: int = 2) -> list[TargetField]:
    table = _target_table(db, project)
    fields = list(db.query(TargetField).filter(TargetField.target_table_id == table.id).order_by(TargetField.id))
    while len(fields) < count:
        index = len(fields) + 1
        field = TargetField(
            project_id=project.id,
            target_table_id=table.id,
            field_code=f"W{index:05d}",
            field_name=f"派工字段{index}",
            field_definition="模板定义",
        )
        db.add(field)
        db.flush()
        fields.append(field)
    return fields[:count]


def _requirement(db, project, fields, requirement_name: str) -> Requirement:
    table = _target_table(db, project)
    requirement = Requirement(
        project_id=project.id,
        name=requirement_name,
        version=1,
        scope_json={
            "name": requirement_name,
            "target_table_id": table.id,
            "field_ids": [field.id for field in fields],
            "scenario_id": None,
        },
        content_version=0,
    )
    db.add(requirement)
    db.flush()
    return requirement


def _content(requirement, table, fields) -> dict:
    return {
        "requirement": {
            "id": requirement.id,
            "name": requirement.name,
            "version": requirement.version,
            "inclusion": "",
            "exclusion": "",
            "objective": "",
        },
        "target_table": {"id": table.id, "table_code": table.table_code, "table_name": table.table_name},
        "scenario": {"id": None, "scenario_name": None},
        "fields": [
            {
                "field": {"id": fields[0].id, "field_code": fields[0].field_code, "field_name": fields[0].field_name},
                "business": {"business_definition": "取自借据表借据号"},
                "lineage": {"processing_logic": "直取"},
                "mart_mappings": [
                    {"mart_field_id": 1, "mart_table_summary": "集市表(HYF_X)", "mart_field_summary": "字段(F1)"}
                ],
            },
            {
                "field": {"id": fields[1].id, "field_code": fields[1].field_code, "field_name": fields[1].field_name},
                "business": {"business_definition": ""},
                "lineage": {"processing_logic": ""},
                "mart_mappings": [],
            },
        ],
        "gaps": [
            {"id": f"{fields[0].id}:definition", "field_id": fields[0].id, "status": "open", "message": "缺少业务口径"},
            {"id": f"{fields[1].id}:evidence", "field_id": fields[1].id, "status": "resolved", "message": "已补"},
        ],
    }


def _revision(db, requirement, content) -> RequirementRevision:
    revision = RequirementRevision(
        project_id=requirement.project_id,
        requirement_id=requirement.id,
        content_version=1,
        scope_version=1,
        content_json=content,
        content_hash=content_digest(content),
        status="draft",
        created_by=1,
    )
    db.add(revision)
    db.flush()
    requirement.content_version = 1
    db.commit()
    return revision


def test_worklist_merges_reasons_per_field(snapshot_api) -> None:
    client, db, project, *_ = snapshot_api
    table = _target_table(db, project)
    fields = _fields(db, project)
    requirement = _requirement(db, project, fields, "派工需求")
    content = _content(requirement, table, fields)
    # 真实需求都有场景（工作台按 tableId + scenarioId + requirementId 还原需求），夹具默认是 None，
    # 这里显式给一个场景号，才能验证"派工行带得动深链"。
    content["scenario"] = {"id": 7, "scenario_name": "夹具场景"}
    _revision(db, requirement, content)

    payload = build_field_worklist(db, project.id)
    assert payload["worklist_version"] == WORKLIST_VERSION
    assert payload["reason_labels"] == REASON_LABELS
    assert payload["truncated"] is False
    # 夹具项目里本来就有一条需求（也挂着 1 号字段），所以这里只对本需求的行做断言。
    ours = [item for item in payload["items"] if item["requirement_id"] == requirement.id]
    assert len(ours) == 2
    first, second = ours
    # 待办项多的排前面：字段 2（缺正文 + 缺集市映射）应在字段 1（只有一条缺口）之前。
    assert first["field_id"] == fields[1].id
    assert first["reasons"] == ["business_definition_missing", "mart_mapping_missing"]
    assert second["field_id"] == fields[0].id
    assert second["reasons"] == ["open_gap"]
    assert second["open_gap_count"] == 1
    assert second["pending_candidate_count"] == 0
    assert payload["reason_totals"]["business_definition_missing"] >= 1
    assert payload["reason_totals"]["pending_candidate"] == 0
    assert payload["note"].startswith("这份清单只是把四处已有的待办归并到字段维度")
    # 派工单要能直接落到"那一条需求的那一个字段"：工作台按 tableId + scenarioId + requirementId 还原需求，
    # 同表有多条需求时只给 requirementId 会打开另一条需求的同名字段。
    assert first["target_table_id"] == table.id
    assert first["scenario_id"] == 7
    assert first["requirement_id"] == requirement.id


def test_worklist_counts_pending_candidates(snapshot_api) -> None:
    client, db, project, *_ = snapshot_api
    table = _target_table(db, project)
    fields = _fields(db, project)
    requirement = _requirement(db, project, fields, "候选需求")
    revision = _revision(db, requirement, _content(requirement, table, fields))

    generation_input = RequirementGenerationInput(
        project_id=project.id,
        requirement_id=requirement.id,
        revision_id=revision.id,
        idempotency_key="worklist-test",
        request_hash="a" * 64,
        input_hash="b" * 64,
        input_json={"content_version": 1},
        created_by=1,
    )
    db.add(generation_input)
    db.flush()
    for field, section, decision, status in (
        (fields[0], "business", "pending", "completed"),
        (fields[0], "lineage", "adopted", "completed"),
        (fields[1], "business", "pending", "blocked"),
    ):
        db.add(
            RequirementGenerationItem(
                input_id=generation_input.id,
                field_id=field.id,
                section=section,
                status=status,
                decision=decision,
            )
        )
    db.commit()

    payload = build_field_worklist(db, project.id)
    target = [
        item
        for item in payload["items"]
        if item["requirement_id"] == requirement.id and item["field_id"] == fields[0].id
    ]
    assert target, payload
    assert target[0]["pending_candidate_count"] == 1
    assert "pending_candidate" in target[0]["reasons"]
    assert payload["reason_totals"]["pending_candidate"] == 1


def test_worklist_endpoint_is_limited_and_read_only(snapshot_api) -> None:
    client, db, project, *_ = snapshot_api
    table = _target_table(db, project)
    fields = _fields(db, project)
    requirement = _requirement(db, project, fields, "接口需求")
    _revision(db, requirement, _content(requirement, table, fields))

    response = client.get(f"/projects/{project.id}/requirements-worklist?limit=1")
    assert response.status_code == 200
    payload = response.json()
    assert payload["worklist_version"] == WORKLIST_VERSION
    assert payload["returned"] <= 1
    assert payload["field_count"] >= payload["returned"]
    assert RequirementDelivery  # 只读：不产生快照

    denied = client.get("/projects/999999/requirements-worklist")
    assert denied.status_code in (403, 404)


def test_worklist_flags_dispatch_done_but_gaps_still_open(snapshot_api) -> None:
    """处置登记不会关闭缺口：登记"已处置"而字段仍有打开缺口时，必须显式标成矛盾。"""

    client, db, project, *_ = snapshot_api
    table = _target_table(db, project)
    fields = _fields(db, project)
    requirement = _requirement(db, project, fields, "处置对照需求")
    _revision(db, requirement, _content(requirement, table, fields))

    # 字段 1 有 1 条打开缺口，字段 2 没有打开缺口（其缺口是 resolved）。
    record_dispatch(
        db,
        project_id=project.id,
        requirement_id=requirement.id,
        field_id=fields[0].id,
        owner="一表通交付负责人",
        status="done",
        note="口径已按脚本补齐",
        created_by=1,
    )
    record_dispatch(
        db,
        project_id=project.id,
        requirement_id=requirement.id,
        field_id=fields[1].id,
        owner="一表通交付负责人",
        status="done",
        note="映射已确认",
        created_by=1,
    )

    payload = build_field_worklist(db, project.id)
    ours = {
        item["field_id"]: item
        for item in payload["items"]
        if item["requirement_id"] == requirement.id
    }

    with_gaps = ours[fields[0].id]["gap_consistency"]
    assert with_gaps["state"] == "done_with_gaps"
    assert with_gaps["label"] == "已登记处置，但缺口仍未关闭"
    assert "处置登记不会关闭缺口" in with_gaps["detail"]

    clear = ours[fields[1].id]["gap_consistency"]
    assert clear["state"] == "done_clear"
    assert clear["label"] == "已登记处置，且无未关闭缺口"

    assert payload["gap_consistency_totals"]["done_with_gaps"] == 1
    assert payload["gap_consistency_totals"]["done_clear"] == 1
    assert payload["gap_consistency_labels"]["done_with_gaps"] == "已登记处置，但缺口仍未关闭"
