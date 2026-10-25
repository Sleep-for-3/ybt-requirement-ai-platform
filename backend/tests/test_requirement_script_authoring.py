"""从跑批脚本一键建需：候选判定、真实建需、重复调用不重复建。"""

from __future__ import annotations

import pytest

from app.models import (
    LineageEdge,
    LineageNode,
    ProductScenario,
    Requirement,
    ScriptFile,
    ScriptFileVersion,
    StoredFile,
    TargetField,
    TargetTable,
    TemplateDocument,
    TemplateVersion,
)
from test_requirement_snapshot_api import snapshot_api, snapshot_db  # noqa: F401


def _authoring_fixtures(db, project, user_id):
    table = TargetTable(project_id=project.id, table_code="T_9_1", table_name="测试监管表",
                        description=None)
    db.add(table)
    db.flush()
    fields = [
        TargetField(project_id=project.id, target_table_id=table.id, field_code="A090001",
                    field_name="字段一", field_type="string", required_flag=False),
        TargetField(project_id=project.id, target_table_id=table.id, field_code="SFJJGDM",
                    field_name="省局分局机构代码", field_type="string", required_flag=False),
        TargetField(project_id=project.id, target_table_id=table.id, field_code="UNBOUND_01",
                    field_name="脚本没有的字段", field_type="string", required_flag=False),
    ]
    db.add_all(fields)
    scenario = ProductScenario(project_id=project.id, scenario_code="AUTH-1", scenario_name="一键建需场景",
                               scenario_type="regulatory_reporting")
    db.add(scenario)
    stored = StoredFile(institution_id=project.institution_id, project_id=project.id,
                        storage_key="authing/T_9_1.sql", original_file_name="YBT_T_9_1.sql",
                        content_type="text/plain", content_hash="a" * 64, byte_size=10,
                        classification="internal", created_by=user_id)
    db.add(stored)
    db.flush()
    script = ScriptFile(institution_id=project.institution_id, project_id=project.id,
                        file_name="YBT_T_9_1.sql", relative_path="GBASE/YBT_T_9_1.sql",
                        file_type="sql", enabled=True)
    db.add(script)
    db.flush()
    version = ScriptFileVersion(project_id=project.id, script_file_id=script.id, version_no=1,
                                file_hash="b" * 64, normalized_hash="b" * 64,
                                raw_content_storage_file_id=stored.id, dialect="mysql",
                                parse_status="parsed")
    db.add(version)
    db.flush()
    source = LineageNode(project_id=project.id, node_type="column", database_name="SAFE_INSTANCE_GB",
                         schema_name=None, table_name="HYF_TEST_INFO", column_name="A090001",
                         logical_name="HYF_TEST_INFO.A090001")
    target = LineageNode(project_id=project.id, node_type="column", database_name="SAFE_INSTANCE_GB",
                         schema_name=None, table_name="T_9_1", column_name="A090001",
                         logical_name="T_9_1.A090001")
    constant = LineageNode(project_id=project.id, node_type="column", database_name="SAFE_INSTANCE_GB",
                           schema_name=None, table_name="T_9_1", column_name="SFJJGDM",
                           logical_name="T_9_1.SFJJGDM")
    db.add_all([source, target, constant])
    db.flush()
    db.add_all([
        LineageEdge(project_id=project.id, script_file_version_id=version.id, statement_id=None,
                    source_node_id=source.id, target_node_id=target.id, edge_type="derived",
                    transformation_type="direct", transformation_expression="A.A090001",
                    source_line_start=1, source_line_end=2, confidence_level="confirmed"),
        LineageEdge(project_id=project.id, script_file_version_id=version.id, statement_id=None,
                    source_node_id=source.id, target_node_id=constant.id, edge_type="derived",
                    transformation_type="constant", transformation_expression="'B1083H'",
                    source_line_start=3, source_line_end=3, confidence_level="confirmed"),
    ])
    document = TemplateDocument(project_id=project.id, file_name="survey.xlsx", file_type="xlsx",
                                storage_path="templates/survey.xlsx")
    db.add(document)
    db.flush()
    template = TemplateVersion(project_id=project.id, template_document_id=document.id,
                               template_code="YBT-SURVEY", version_no=1, file_name="survey.xlsx",
                               file_type="xlsx", storage_path="templates/survey.xlsx", file_hash="c" * 64,
                               regulatory_version="R2022",
                               parse_status="success", status="active",
                               parsed_snapshot_json=[{"table_code": "T_9_1", "sheet_name": "T_9_1-测试",
                                                      "rows": []}],
                               sheet_names_json=["T_9_1-测试"], parse_report_json={},
                               table_meta_json={})
    db.add(template)
    db.commit()
    return {"table": table, "fields": fields, "scenario": scenario, "version": version, "template": template}


def test_author_preview_reports_bindable_fields_and_reasons(snapshot_api):
    client, db, project, *_ = snapshot_api
    fixtures = _authoring_fixtures(db, project, 1)
    base = f"/projects/{project.id}/requirements"
    # 有这张表但没有对应脚本：原因要说清"缺脚本"，而不是和"表不存在"混在一起
    db.add(TargetTable(project_id=project.id, table_code="T_9_2", table_name="缺脚本的监管表"))
    db.flush()
    body = client.post(f"{base}/author-preview", json={"table_codes": ["T_9_1", "T_9_2", "T_NOFILE"]}).json()
    items = {item["table_code"]: item for item in body["items"]}
    assert items["T_9_1"]["authorable"] is True
    # 只绑同名列：A090001 与 SFJJGDM 命中，UNBOUND_01 不在脚本输出里
    assert items["T_9_1"]["bound_field_count"] == 2
    assert items["T_9_1"]["field_count"] == 3
    assert items["T_9_1"]["template_version_id"] == fixtures["template"].id
    assert items["T_9_2"]["authorable"] is False
    assert "YBT_<表编号>.sql" in items["T_9_2"]["reason"]
    assert items["T_NOFILE"]["authorable"] is False
    assert items["T_NOFILE"]["reason"] == "监管表不存在"


def test_author_creates_requirement_once_and_skips_covered_tables(snapshot_api):
    client, db, project, *_ = snapshot_api
    fixtures = _authoring_fixtures(db, project, 1)
    base = f"/projects/{project.id}/requirements"
    first = client.post(f"{base}/author-from-scripts", json={"table_codes": ["T_9_1"]})
    assert first.status_code == 201, first.text
    body = first.json()
    assert body["created_count"] == 1
    item = body["items"][0]
    assert item["created"] is True
    requirement = db.get(Requirement, item["requirement_id"])
    assert requirement is not None
    scope_fields = set(requirement.scope_json["field_ids"])
    assert scope_fields == {field.id for field in fixtures["fields"] if field.field_code in {"A090001", "SFJJGDM"}}

    again = client.post(f"{base}/author-from-scripts", json={"table_codes": ["T_9_1"]}).json()
    assert again["created_count"] == 0
    assert again["items"][0]["created"] is False
    assert "已有需求" in again["items"][0]["reason"]


def test_author_rejects_unknown_or_empty_selection(snapshot_api):
    client, db, project, *_ = snapshot_api
    _authoring_fixtures(db, project, 1)
    base = f"/projects/{project.id}/requirements"
    assert client.post(f"{base}/author-from-scripts", json={"table_codes": []}).status_code == 422
    assert client.post(f"{base}/author-from-scripts", json={"table_codes": [123]}).status_code == 422
    too_many = client.post(f"{base}/author-preview", json={"table_codes": [f"T_9_{i}" for i in range(11)]})
    assert too_many.status_code == 422
