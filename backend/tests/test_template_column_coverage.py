"""标准模板列填充率（项目级）：分清楚"模板没给"与"平台没填"。

真实问题：导出文档里 `数据格式` 整列为空，评审第一反应是"平台丢字段"。真实原因是调研表这一列
本身整列没填（2422 个字段全空），而 `数据类别` 只填了 396 行、集市映射 1297 行有值。
把缺口归属标出来，才能把"找业务要资料""补映射""等业务确认"分开处置。
"""

from __future__ import annotations

from app.models import (
    LineageEdge,
    LineageNode,
    MartField,
    MartTable,
    MartToYbtMapping,
    TargetField,
    TargetTable,
)
from test_requirement_snapshot_api import snapshot_api, snapshot_db  # noqa: F401  夹具复用
from test_requirement_table_coverage import _script_version


def _coverage(client, project_id: int) -> dict:
    response = client.get(f"/projects/{project_id}/template-coverage")
    assert response.status_code == 200, response.text
    return response.json()


def _content_version(client, project_id: int, requirement_id: int) -> int:
    """`/document` 把版本放在 requirement 段里；这里兼容两种位置。"""
    body = client.get(f"/projects/{project_id}/requirements/{requirement_id}/document").json()
    version = body.get("content_version")
    if version is None:
        version = (body.get("requirement") or {}).get("content_version")
    assert version, body
    return int(version)


def _column(body: dict, key: str) -> dict:
    return next(column for column in body["columns"] if column["key"] == key)


def test_template_coverage_reports_every_column_with_source(snapshot_api):
    client, db, project, field, req, _ = snapshot_api
    body = _coverage(client, project.id)
    assert body["coverage_version"] == "requirement-template-coverage-v1"
    assert body["field_count"] == 1
    assert [column["key"] for column in body["columns"]] == [
        "regulatory_definition",
        "data_category",
        "data_format",
        "report_name",
        "mart_mapping",
        "script_rule",
        "business_definition",
    ]
    sources = {column["key"]: column["source"] for column in body["columns"]}
    assert sources["data_format"] == "template"
    assert sources["mart_mapping"] == "mapping"
    assert sources["script_rule"] == "script"
    assert sources["business_definition"] == "requirement"
    # 缺口归属必须带一句人话，界面直接展示，不再二次解释
    assert "模板未提供" in _column(body, "data_format")["source_label"]
    assert "需补映射" in _column(body, "mart_mapping")["source_label"]


def test_template_coverage_counts_template_columns(snapshot_api):
    client, db, project, field, _, _ = snapshot_api
    before = _coverage(client, project.id)
    assert _column(before, "data_category")["filled"] == 0
    assert _column(before, "data_format")["filled"] == 0

    field.data_category = "基础类"
    # 只填了数据类别、数据格式仍空：两列必须分开统计，不能互相顶替
    db.flush()
    after = _coverage(client, project.id)
    assert _column(after, "data_category")["filled"] == 1
    assert _column(after, "data_format")["filled"] == 0
    assert _column(after, "data_category")["fill_rate"] == 1.0


def test_template_coverage_counts_mapping_and_script_independently(snapshot_api):
    client, db, project, field, _, membership = snapshot_api
    script_version = _script_version(db, project, membership, code="T_COV")
    db.flush()
    table = db.get(TargetTable, field.target_table_id)
    mart_table = MartTable(project_id=project.id, table_code="HYF_C", table_name="集市表", is_existing=True)
    db.add(mart_table)
    db.flush()
    mart_field = MartField(project_id=project.id, mart_table_id=mart_table.id,
                           field_code="AMT", field_name="金额", is_existing=True)
    db.add(mart_field)
    db.flush()
    db.add(MartToYbtMapping(project_id=project.id, target_field_id=field.id, mart_field_id=mart_field.id,
                            mapping_status="confirmed", confidence_level="high", lineage_status="unverified"))
    db.flush()

    source = LineageNode(project_id=project.id, node_type="source", logical_name="src.AMT",
                         table_name="HYF_SOURCE", column_name="AMT")
    target = LineageNode(project_id=project.id, node_type="target", logical_name=f"SAFE_INSTANCE_GB.{table.table_code}",
                         schema_name="SAFE_INSTANCE_GB", table_name=table.table_code, column_name=field.field_code)
    db.add_all([source, target])
    db.flush()
    db.add(LineageEdge(project_id=project.id, script_file_version_id=script_version.id, source_node_id=source.id,
                       target_node_id=target.id, edge_type="column_lineage", confidence_level="high",
                       evidence_json={}, enabled=True))
    db.flush()

    body = _coverage(client, project.id)
    assert _column(body, "mart_mapping")["filled"] == 1
    assert _column(body, "script_rule")["filled"] == 1
    # 集市映射有值不等于需求正文有值：这两列同样不能互相顶替
    assert _column(body, "business_definition")["filled"] == 0


def test_template_coverage_counts_requirement_business_text(snapshot_api):
    client, db, project, field, req, _ = snapshot_api
    base = f"/projects/{project.id}/requirements/{req.id}"
    # 合成夹具的需求还没有修订（content_version=0）：先建修订，否则字段编辑会被 422 拒绝
    created = client.post(base + "/revisions", json={"expected_version": req.version})
    assert created.status_code in (200, 201), created.text
    response = client.put(
        f"/projects/{project.id}/requirements/{req.id}/fields/{field.id}",
        json={
            "expected_content_version": _content_version(client, project.id, req.id),
            "section": "business",
            "changes": {"business_definition": "取贷款余额表（HYF_LN_DUEBILL_INFO）借款余额，按借据号唯一。"},
        },
    )
    assert response.status_code == 200, response.text

    body = _coverage(client, project.id)
    assert _column(body, "business_definition")["filled"] == 1
    assert _column(body, "business_definition")["source"] == "requirement"


def _gaps(client, project_id: int, column_key: str, **params) -> dict:
    response = client.get(f"/projects/{project_id}/template-coverage/gaps/{column_key}", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def test_gap_rows_list_the_missing_fields_with_owner(snapshot_api):
    client, db, project, field, _, _ = snapshot_api
    second = TargetField(project_id=project.id, target_table_id=field.target_table_id,
                         field_code="GAP_002", field_name="第二个字段", required_flag=False)
    db.add(second)
    db.flush()

    body = _gaps(client, project.id, "data_format")
    assert body["gap_version"] == "requirement-template-coverage-gaps-v1"
    assert body["column_label"] == "数据格式"
    assert body["source"] == "template"
    assert "模板未提供" in body["source_label"]
    assert body["total"] == 2 and body["returned"] == 2 and body["truncated"] is False
    assert {item["field_code"] for item in body["items"]} == {field.field_code, "GAP_002"}
    # 缺口行必须带"值现在是空的"，派工的人才知道要填什么
    assert all(item["value"] is None for item in body["items"])
    assert all(item["table_code"] for item in body["items"])

    # 填上一个之后，缺口清单必须少一条（统计与清单同源）
    field.data_format = "an..32"
    db.flush()
    after = _gaps(client, project.id, "data_format")
    assert after["total"] == 1
    assert [item["field_code"] for item in after["items"]] == ["GAP_002"]
    assert after["items"][0]["value"] is None


def test_gap_rows_truncate_explicitly_instead_of_silently(snapshot_api):
    client, db, project, field, _, _ = snapshot_api
    for index in range(3):
        db.add(TargetField(project_id=project.id, target_table_id=field.target_table_id,
                           field_code=f"TRUNC_{index}", field_name=f"截断字段{index}", required_flag=False))
    db.flush()

    body = _gaps(client, project.id, "data_category", limit=2)
    assert body["total"] == 4
    assert body["returned"] == 2
    assert body["truncated"] is True
    assert body["limit"] == 2


def test_gap_rows_reject_unknown_column_and_bad_limit(snapshot_api):
    client, db, project, _, _, _ = snapshot_api
    unknown = client.get(f"/projects/{project.id}/template-coverage/gaps/no_such_column")
    assert unknown.status_code == 422, unknown.text
    assert "未知的模板列" in unknown.json()["detail"]

    bad_limit = client.get(f"/projects/{project.id}/template-coverage/gaps/data_format", params={"limit": 0})
    assert bad_limit.status_code == 422, bad_limit.text


def _second_table(db, project, code: str, name: str, field_code: str) -> TargetField:
    table = TargetTable(project_id=project.id, table_code=code, table_name=name)
    db.add(table)
    db.flush()
    field = TargetField(project_id=project.id, target_table_id=table.id, field_code=field_code,
                        field_name=f"{name}字段", required_flag=False)
    db.add(field)
    db.flush()
    return field


def test_gap_rows_filter_by_regulatory_table_without_losing_column_total(snapshot_api):
    client, db, project, field, _, _ = snapshot_api
    first = db.get(TargetTable, field.target_table_id)
    _second_table(db, project, "T_9_9", "另一张监管表", "OTHER_001")

    everything = _gaps(client, project.id, "data_format")
    assert everything["total"] == 2
    assert everything["filtered_total"] == 2
    assert everything["table_filter"] is None

    # 按表筛选只缩小本次返回范围，"该列共多少条缺口"仍是整列口径——
    # 否则派工的人会把"筛出来的 1 条"当成"整列只有 1 条"。
    only_first = _gaps(client, project.id, "data_format", table_code=first.table_code)
    assert only_first["total"] == 2
    assert only_first["filtered_total"] == 1
    assert only_first["table_filter"] == first.table_code
    assert [item["field_code"] for item in only_first["items"]] == [field.field_code]

    # 默认是**完全匹配**：真实事故里 ILIKE %T_8_1% 把 T_8_10/11… 一起筛进来，
    # 弹层却写"筛选「T_8_1」：164 个字段"。前缀必须显式写 `*`。
    substring_like = _gaps(client, project.id, "data_format", table_code="T_9")
    assert substring_like["filtered_total"] == 0

    prefix = _gaps(client, project.id, "data_format", table_code="T_9*")
    assert [item["table_code"] for item in prefix["items"]] == ["T_9_9"]

    # 只输入 `*` 等于没筛：不能回显"筛选「*」"却返回全部
    wildcard_only = _gaps(client, project.id, "data_format", table_code="*")
    assert wildcard_only["table_filter"] is None and wildcard_only["filtered_total"] == 2

    # 不存在的表：0 条，但整列总数照旧，前端能显示"筛选后 0 / 共 2"
    missing = _gaps(client, project.id, "data_format", table_code="T_404")
    assert missing["filtered_total"] == 0 and missing["items"] == []
    assert missing["total"] == 2


def test_gap_rows_escape_like_wildcards_in_table_code(snapshot_api):
    client, db, project, _, _, _ = snapshot_api
    # 显式造一对"只有下划线通配能区分"的表：T_8_1 与 TX8X1。
    # 不转义时 LIKE '%T_8_1%' 会把 TX8X1 也匹配进来，派工清单就多出别的表的字段。
    _second_table(db, project, "T_8_1", "目标监管表", "ESC_001")
    _second_table(db, project, "TX8X1", "下划线陷阱表", "TRAP_001")

    only_target = _gaps(client, project.id, "data_format", table_code="T_8_1")
    assert only_target["filtered_total"] == 1
    assert [item["table_code"] for item in only_target["items"]] == ["T_8_1"]

    trap = _gaps(client, project.id, "data_format", table_code="TX8X1")
    assert [item["table_code"] for item in trap["items"]] == ["TX8X1"]


def test_gap_rows_for_mapping_and_script_columns_follow_their_own_facts(snapshot_api):
    client, db, project, field, _, membership = snapshot_api
    script_version = _script_version(db, project, membership, code="T_GAP")
    db.flush()
    table = db.get(TargetTable, field.target_table_id)

    # 夹具里的字段本身已经有一条集市映射，所以它不该出现在映射缺口里；
    # 另建一个没有映射的字段，用来证明"缺口清单只列真的没映射的"。
    mapped_field = _gaps(client, project.id, "mart_mapping")
    assert mapped_field["total"] == 0
    assert "需补映射" in mapped_field["source_label"]

    unmapped = TargetField(project_id=project.id, target_table_id=field.target_table_id,
                           field_code="UNMAPPED_1", field_name="没有映射的字段", required_flag=False)
    db.add(unmapped)
    db.flush()
    after_add = _gaps(client, project.id, "mart_mapping")
    assert after_add["total"] == 1
    assert [item["field_code"] for item in after_add["items"]] == ["UNMAPPED_1"]

    mart_table = MartTable(project_id=project.id, table_code="HYF_GAP", table_name="集市表", is_existing=True)
    db.add(mart_table)
    db.flush()
    mart_field = MartField(project_id=project.id, mart_table_id=mart_table.id,
                           field_code="GAP", field_name="集市字段", is_existing=True)
    db.add(mart_field)
    db.flush()
    db.add(MartToYbtMapping(project_id=project.id, target_field_id=unmapped.id, mart_field_id=mart_field.id,
                            mapping_status="confirmed", confidence_level="high", lineage_status="unverified"))
    db.flush()
    assert _gaps(client, project.id, "mart_mapping")["total"] == 0

    # 脚本列同理：夹具字段没有写入血缘，补一条之后必须从缺口里消失。
    assert _gaps(client, project.id, "script_rule")["total"] == 2
    source = LineageNode(project_id=project.id, node_type="source", logical_name="src.GAP",
                         table_name="HYF_SOURCE", column_name="GAP")
    target = LineageNode(project_id=project.id, node_type="target",
                         logical_name=f"SAFE_INSTANCE_GB.{table.table_code}",
                         schema_name="SAFE_INSTANCE_GB", table_name=table.table_code, column_name=field.field_code)
    db.add_all([source, target])
    db.flush()
    db.add(LineageEdge(project_id=project.id, script_file_version_id=script_version.id, source_node_id=source.id,
                       target_node_id=target.id, edge_type="column_lineage", confidence_level="high",
                       evidence_json={}, enabled=True))
    db.flush()
    script_gaps = _gaps(client, project.id, "script_rule")
    assert script_gaps["total"] == 1
    assert [item["field_code"] for item in script_gaps["items"]] == ["UNMAPPED_1"]
