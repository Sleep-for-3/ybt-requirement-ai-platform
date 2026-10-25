"""脚本版本差异：冻结依据与同一脚本最新版本在目标字段层面的差异。

真实动机：看板只说"脚本有更新"，评审还得回答"这次更新到底动没动我绑定的字段"。
这里只比较目标字段与其上的加工事实，不给"是否要重建需求"的结论。
"""

from sqlalchemy import select

from app.services.requirement_script_basis_diff import (
    DIFF_VERSION,
    _impact,
    diff_signatures,
)
from test_requirement_snapshot_api import snapshot_api, snapshot_db  # noqa: F401


def _sig(**fields):
    base = {
        "transformation_expression": set(),
        "join_condition": set(),
        "filter_condition": set(),
        "aggregation_rule": set(),
        "code_mapping_rule": set(),
    }
    base.update(fields)
    return base


def test_diff_signatures_reports_added_removed_changed():
    frozen = {
        ("T_1_5", "A050001"): _sig(filter_condition={"P1.DATA_DT = '#{DATA_DATE}'"}),
        ("T_1_5", "A050002"): _sig(transformation_expression={"P1.NAME"}),
        ("T_1_5", "A050003"): _sig(transformation_expression={"P1.OLD"}),
    }
    latest = {
        ("T_1_5", "A050001"): _sig(
            filter_condition={"P1.DATA_DT = '#{DATA_DATE}'", "P1.DATA_DT IS NOT NULL"}
        ),
        ("T_1_5", "A050002"): _sig(transformation_expression={"P1.NAME"}),
        ("T_1_5", "A050004"): _sig(transformation_expression={"P1.NEW"}),
    }

    body = diff_signatures(frozen, latest)

    assert body["diff_version"] == DIFF_VERSION
    assert body["added_count"] == 1 and body["added"][0]["label"] == "T_1_5.A050004"
    assert body["removed_count"] == 1 and body["removed"][0]["label"] == "T_1_5.A050003"
    assert body["changed_count"] == 1
    changed = body["changed"][0]
    assert changed["label"] == "T_1_5.A050001"
    assert changed["fields"] == ["过滤条件"]
    # 变更必须给出前后样本，否则"变更"二字无法核对。
    assert "#{DATA_DATE}" in (changed["before"]["过滤条件"] or "")
    assert "IS NOT NULL" in (changed["after"]["过滤条件"] or "")
    assert body["unchanged_count"] == 1


def test_diff_signatures_truncates_display_but_keeps_real_counts():
    frozen = {}
    latest = {("T_9_9", f"COL{i:03d}"): _sig(transformation_expression={f"X{i}"}) for i in range(7)}

    body = diff_signatures(frozen, latest, max_entries=3)

    assert body["added_count"] == 7
    assert len(body["added"]) == 3
    assert body["truncated"] is True
    assert body["max_entries"] == 3


def _script_version(db, project, *, file_name, version_no):
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
        content_hash="d" * 64,
        created_by=user.id,
    )
    db.add(stored)
    db.flush()
    script = db.scalar(
        select(ScriptFile).where(ScriptFile.project_id == project.id, ScriptFile.relative_path == file_name)
    )
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
        normalized_hash=f"{version_no + 3:064d}",
        raw_content_storage_file_id=stored.id,
        parse_status="parsed",
    )
    db.add(version)
    db.commit()
    return script, version


def _edge(db, project, version, *, table_name, column_name, filter_condition=None, expression=None):
    from app.models import LineageEdge, LineageNode

    source = LineageNode(
        project_id=project.id,
        node_type="source_column",
        logical_name=f"S.{column_name}",
        table_name="HYF_SRC",
        column_name=column_name,
    )
    target = LineageNode(
        project_id=project.id,
        node_type="target_column",
        logical_name=f"{table_name}.{column_name}",
        table_name=table_name,
        column_name=column_name,
    )
    db.add_all([source, target])
    db.flush()
    db.add(
        LineageEdge(
            project_id=project.id,
            script_file_version_id=version.id,
            source_node_id=source.id,
            target_node_id=target.id,
            edge_type="direct",
            transformation_expression=expression,
            filter_condition=filter_condition,
            enabled=True,
        )
    )
    db.commit()


def test_script_basis_diff_endpoint_compares_frozen_with_latest(snapshot_api, monkeypatch):
    from app.services import requirement_delivery_status as status_module

    client, db, project, _field, req, _ = snapshot_api
    # 让差异里的目标列(A1)正好是本需求绑定的监管字段：绑定表的值是字段 id，差异表用的是列代码。
    _field.field_code = "A1"
    db.commit()
    script, version_one = _script_version(db, project, file_name="YBT_T_9_8.sql", version_no=1)
    _edge(db, project, version_one, table_name="T_9_8", column_name="A1", filter_condition="P1.DATA_DT = '#{DATA_DATE}'")
    _edge(db, project, version_one, table_name="T_9_8", column_name="A2", expression="P1.OLD")

    _, version_two = _script_version(db, project, file_name="YBT_T_9_8.sql", version_no=2)
    _edge(
        db,
        project,
        version_two,
        table_name="T_9_8",
        column_name="A1",
        filter_condition="P1.DATA_DT = '#{DATA_DATE}' AND P1.DATA_DT IS NOT NULL",
    )
    _edge(db, project, version_two, table_name="T_9_8", column_name="A3", expression="P1.NEW")

    def fake_content(_db, row):
        return {
            "script_basis": {
                "confirmation": {"field_bindings": {"A1": _field.id}},
                "versions": [
                    {
                        "id": version_one.id,
                        "script_file_id": script.id,
                        "version_no": 1,
                        "parse_status": "parsed",
                        "path": "YBT_T_9_8.sql",
                    }
                ]
            }
        }

    monkeypatch.setattr("app.api.requirements.document_content", fake_content)

    response = client.get(f"/projects/{project.id}/requirements/{req.id}/script-basis-diff")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["diff_version"] == DIFF_VERSION
    assert body["item_count"] == 1
    item = body["items"][0]
    assert item["state"] == "advanced"
    assert item["frozen_version_no"] == 1 and item["latest_version_no"] == 2
    assert item["changed_count"] == 1 and item["changed"][0]["label"] == "T_9_8.A1"
    assert item["changed"][0]["fields"] == ["过滤条件"]
    assert item["added_count"] == 1 and item["added"][0]["label"] == "T_9_8.A3"
    assert item["removed_count"] == 1 and item["removed"][0]["label"] == "T_9_8.A2"
    impact = item["impact"]
    assert impact["bound_field_count"] == 1
    assert impact["affected_field_count"] == 1
    assert impact["condition_field_count"] == 1 and impact["expression_field_count"] == 0
    assert impact["recommendation"] == "review_and_rebase"
    assert "取数条件变了" in impact["reason"]


def _diff_entry(column_name, *field_keys):
    return {
        "table_name": "T_1_5",
        "column_name": column_name,
        "label": f"T_1_5.{column_name}",
        "field_keys": list(field_keys),
        "fields": list(field_keys),
    }


def test_impact_flags_regenerate_when_expression_changes():
    diff = {"state": "advanced", "changed": [_diff_entry("A1", "transformation_expression")]}
    impact = _impact(diff, {"A1"})
    assert impact["recommendation"] == "regenerate"
    assert impact["expression_field_count"] == 1
    assert "只重新冻结不会更新正文" in impact["reason"]


def test_impact_says_no_action_when_update_touches_other_fields():
    diff = {"state": "advanced", "changed": [_diff_entry("A9", "filter_condition")]}
    impact = _impact(diff, {"A1"})
    assert impact["recommendation"] == "no_action"
    assert impact["affected_field_count"] == 0
    assert "没有触及本需求绑定的 1 个字段" in impact["reason"]


def test_impact_is_no_action_when_basis_is_already_latest():
    impact = _impact({"state": "aligned", "changed": []}, {"A1"})
    assert impact["recommendation"] == "no_action"
    assert impact["reason"] == "脚本依据就是最新版本，无需动作"
    missing = _impact({"state": "version_missing"}, {"A1"})
    assert missing["recommendation"] == "no_action"
    assert "冻结的脚本版本已不存在" in missing["reason"]
