"""监管表覆盖度：每张目标监管表"有没有需求、脚本能不能产出它、字段绑了多少集市映射"。

真实问题：项目 9 有 92 张监管表、20 条需求，评审问"还差多少张表没做"时只能人工数；
而有些表**脚本本身被屏蔽**（`YBT_T_3_5.sql` 整段注释），只按"有没有需求"统计会把它们
算成待办。所以这里必须把需求维与脚本维分开陈述，不能把"脚本不产出"说成"需求没做"。
"""

from __future__ import annotations

from sqlalchemy import select

from app.models import (
    LineageEdge,
    LineageNode,
    MartField,
    MartTable,
    MartToYbtMapping,
    ScriptFile,
    ScriptFileVersion,
    StoredFile,
    TargetField,
    TargetTable,
)
from app.services.requirement_table_coverage import disabled_reason
from test_requirement_snapshot_api import snapshot_api, snapshot_db  # noqa: F401  夹具复用


def _frozen_snapshot(client, base: str, req) -> int:
    current = client.get(base + "/document").json()
    created = client.post(base + "/snapshots", json={
        "expected_version": req.version, "expected_hash": current["content_hash"]})
    assert created.status_code == 201, created.text
    return created.json()["id"]


def _table(db, project, code: str, name: str) -> TargetTable:
    table = TargetTable(project_id=project.id, table_code=code, table_name=name)
    db.add(table)
    db.flush()
    return table


def _script_version(db, project, membership, code: str = "T_9_2") -> ScriptFileVersion:
    stored = StoredFile(
        institution_id=membership.user.institution_id if getattr(membership, "user", None) else 0,
        project_id=project.id,
        storage_key=f"projects/{project.id}/coverage/{code}.sql",
        original_file_name=f"YBT_{code}.sql",
        content_type="text/plain",
        byte_size=10,
        content_hash="a" * 64,
        classification="internal",
        created_by=membership.user_id,
        enabled=True,
    )
    db.add(stored)
    db.flush()
    script = ScriptFile(
        project_id=project.id,
        relative_path=f"GBASE/YBT_{code}.sql",
        file_name=f"YBT_{code}.sql",
        file_type="sql",
        enabled=True,
        current_version_no=1,
    )
    db.add(script)
    db.flush()
    version = ScriptFileVersion(
        project_id=project.id,
        script_file_id=script.id,
        version_no=1,
        file_hash="b" * 64,
        normalized_hash="c" * 64,
        raw_content_storage_file_id=stored.id,
        parse_status="parsed",
    )
    db.add(version)
    db.flush()
    return version


def _write_edge(db, project, version, table_code: str) -> None:
    source = LineageNode(project_id=project.id, node_type="source", logical_name="src.AMT",
                         table_name="HYF_SOURCE", column_name="AMT")
    target = LineageNode(project_id=project.id, node_type="target", logical_name=f"SAFE_INSTANCE_GB.{table_code}",
                         schema_name="SAFE_INSTANCE_GB", table_name=table_code, column_name="AMT")
    db.add_all([source, target])
    db.flush()
    db.add(LineageEdge(
        project_id=project.id,
        script_file_version_id=version.id,
        source_node_id=source.id,
        target_node_id=target.id,
        edge_type="column_lineage",
        confidence_level="high",
        evidence_json={},
        enabled=True,
    ))
    db.flush()


def test_coverage_lists_table_with_requirement_but_not_frozen(snapshot_api):
    client, db, project, field, req, _ = snapshot_api
    response = client.get(f"/projects/{project.id}/table-coverage")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["coverage_version"] == "requirement-table-coverage-v1"
    assert body["summary"]["table_count"] == len(body["items"]) >= 1
    row = next(item for item in body["items"] if item["table_id"] == field.target_table_id)
    assert row["requirement_count"] == 1
    assert row["frozen_requirement_count"] == 0
    assert row["state"] == "covered_draft"
    assert row["state_label"] == "有需求未冻结"
    assert row["field_count"] >= 1


def test_coverage_marks_frozen_only_after_snapshot(snapshot_api):
    client, db, project, field, req, _ = snapshot_api
    base = f"/projects/{project.id}/requirements/{req.id}"
    _frozen_snapshot(client, base, req)

    body = client.get(f"/projects/{project.id}/table-coverage").json()
    row = next(item for item in body["items"] if item["table_id"] == field.target_table_id)
    assert row["state"] == "frozen"
    assert row["frozen_requirement_count"] == 1
    assert row["requirements"][0]["frozen"] is True
    assert body["summary"]["frozen"] == 1


def test_coverage_separates_script_ready_disabled_and_absent(snapshot_api):
    client, db, project, _, _, membership = snapshot_api
    ready = _table(db, project, "T_9_1", "脚本可建需")
    disabled = _table(db, project, "T_9_2", "脚本存在但被屏蔽")
    absent = _table(db, project, "T_9_3", "输入里没有脚本")
    version = _script_version(db, project, membership)  # 文件名 YBT_T_9002.sql，但不产出写入目标
    _write_edge(db, project, version, "T_9_1")
    db.flush()

    body = client.get(f"/projects/{project.id}/table-coverage").json()
    by_id = {item["table_id"]: item for item in body["items"]}
    assert by_id[ready.id]["state"] == "script_ready"
    assert by_id[ready.id]["script_version_count"] == 1
    assert by_id[disabled.id]["state"] == "script_disabled"
    assert by_id[disabled.id]["script_version_count"] == 0
    assert by_id[absent.id]["state"] == "script_absent"
    assert body["summary"]["script_ready"] == 1
    assert body["summary"]["script_disabled"] == 1
    assert body["summary"]["script_absent"] == 1


def test_coverage_counts_fields_that_have_a_mart_mapping(snapshot_api):
    client, db, project, field, _, _ = snapshot_api
    table = db.get(TargetTable, field.target_table_id)
    mart_table = MartTable(project_id=project.id, table_code="HYF_X", table_name="集市表",
                           is_existing=True)
    db.add(mart_table)
    db.flush()
    mart_field = MartField(project_id=project.id, mart_table_id=mart_table.id,
                           field_code="AMT", field_name="金额", is_existing=True)
    db.add(mart_field)
    db.flush()
    db.add(MartToYbtMapping(project_id=project.id, target_field_id=field.id,
                            mart_field_id=mart_field.id, mapping_status="confirmed",
                            confidence_level="high", lineage_status="unverified"))
    db.flush()

    body = client.get(f"/projects/{project.id}/table-coverage").json()
    row = next(item for item in body["items"] if item["table_id"] == table.id)
    assert row["mapped_field_count"] == 1
    assert body["summary"]["mapped_field_count"] == 1


def test_coverage_orders_actionable_first_and_respects_membership(snapshot_api):
    client, db, project, field, req, membership = snapshot_api
    base = f"/projects/{project.id}/requirements/{req.id}"
    _frozen_snapshot(client, base, req)
    _table(db, project, "T_9_4", "输入里没有脚本")
    db.flush()

    body = client.get(f"/projects/{project.id}/table-coverage").json()
    states = [item["state"] for item in body["items"]]
    assert states.index("frozen") < states.index("script_absent"), "需要动手的排在后面"

    membership.status = "inactive"
    db.flush()
    assert client.get(f"/projects/{project.id}/table-coverage").status_code == 404


def test_disabled_reason_tells_block_comment_from_parse_failure():
    """"被整段注释屏蔽"和"解析失败"是两种处置：前者人工确认停用，后者看解析器。"""
    kind, message = disabled_reason(text="SELECT 1;\n/* 屏蔽\nSELECT 2;\n", statement_statuses=[])
    assert kind == "block_comment"
    assert "未闭合的块注释" in message

    assert disabled_reason(text=None, statement_statuses=[]) == (
        "no_statements", "这个脚本版本没有解析出任何语句（可能不是可解析的 SQL 脚本）")
    assert disabled_reason(text=None, statement_statuses=["failed", "failed"])[0] == "parse_failed"
    assert disabled_reason(text="SELECT 1;", statement_statuses=["parsed"])[0] == "no_write_target"


def test_coverage_reports_reason_for_missing_and_disabled_scripts(snapshot_api):
    """覆盖度不能只说"没写入"，还要给出可核实的下一步。"""
    client, db, project, _, _, membership = snapshot_api
    disabled = _table(db, project, "T_9_2", "脚本存在但被屏蔽")
    absent = _table(db, project, "T_9_3", "输入里没有脚本")
    version = _script_version(db, project, membership)  # 文件名 YBT_T_9_2.sql，但没有语句
    db.flush()
    assert version.id

    body = client.get(f"/projects/{project.id}/table-coverage").json()
    by_id = {item["table_id"]: item for item in body["items"]}
    assert by_id[disabled.id]["script_reason_kind"] == "no_statements"
    assert "没有解析出任何语句" in by_id[disabled.id]["script_reason"]
    assert by_id[absent.id]["script_reason_kind"] == "script_missing"
    assert "需要补资料" in by_id[absent.id]["script_reason"]


def test_coverage_has_no_reason_for_healthy_scripts(snapshot_api):
    """没有问题的表不写原因，避免"每条都带一句解释"变成噪声。"""
    client, db, project, field, _, _ = snapshot_api
    body = client.get(f"/projects/{project.id}/table-coverage").json()
    row = next(item for item in body["items"] if item["table_id"] == field.target_table_id)
    assert row["script_reason"] is None
    assert row["script_reason_kind"] is None
