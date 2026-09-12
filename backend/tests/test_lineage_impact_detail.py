from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models import (
    BusinessSystem,
    ImpactAnalysis,
    Institution,
    LineageEdge,
    LineageNode,
    MappingEvidenceReference,
    MartField,
    MartTable,
    MartToYbtMapping,
    ProductScenario,
    Project,
    ScenarioBusinessMapping,
    ScenarioTechnicalLineage,
    ScriptChangeSet,
    ScriptFile,
    ScriptFileVersion,
    SourceField,
    SourceTable,
    SourceToMartMapping,
    TargetField,
    TargetTable,
    User,
)
from app.services.lineage.impact_view import ImpactDetailBuilder


def _seed(db: Session) -> dict[str, Any]:
    institution = Institution(institution_code="IMPACT-BANK", institution_name="影响分析测试机构")
    user = User(username="impact-detail-owner", status="active")
    db.add_all([institution, user])
    db.flush()
    project = Project(name="影响详情项目", institution_id=institution.id)
    other_project = Project(name="另一个项目", institution_id=institution.id)
    db.add_all([project, other_project])
    db.flush()

    system = BusinessSystem(project_id=project.id, system_code="ECIF", system_name="客户信息系统")
    db.add(system)
    db.flush()
    target_table = TargetTable(project_id=project.id, table_code="YBT_CUST", table_name="一表通客户表")
    mart_table = MartTable(project_id=project.id, table_code="MART_CUST", table_name="监管集市客户表")
    source_table = SourceTable(
        project_id=project.id, business_system_id=system.id, table_code="ECIF_CUSTOMER",
        table_name="客户主表", table_comment="客户主表",
    )
    scenario = ProductScenario(project_id=project.id, scenario_code="DEFAULT", scenario_name="默认场景")
    db.add_all([target_table, mart_table, source_table, scenario])
    db.flush()

    target = TargetField(
        project_id=project.id, target_table_id=target_table.id, field_code="E010007",
        field_name="证件类型", regulatory_description="客户证件类型",
    )
    mart = MartField(
        project_id=project.id, mart_table_id=mart_table.id, field_code="CERT_TYPE",
        field_name="证件类型", field_comment="证件类型",
    )
    source = SourceField(
        project_id=project.id, source_table_id=source_table.id, field_code="CERT_TYPE",
        field_name="证件类型", field_comment="证件类型代码",
    )
    uncommented = SourceField(
        project_id=project.id, source_table_id=source_table.id, field_code="X_FLAG",
        field_name="",
    )
    db.add_all([target, mart, source, uncommented])
    db.flush()

    business = ScenarioBusinessMapping(
        project_id=project.id, target_field_id=target.id, scenario_id=scenario.id,
        business_definition="证件类型业务口径", business_confirm_status="approved",
    )
    technical = ScenarioTechnicalLineage(
        project_id=project.id, target_field_id=target.id, scenario_id=scenario.id,
        processing_logic="直接取值", tech_confirm_status="approved",
    )
    source_mapping = SourceToMartMapping(
        project_id=project.id, mart_field_id=mart.id, mapping_status="approved",
        mapping_name="客户证件类型入集市", join_condition="c.CUST_ID = m.CUST_ID",
        filter_condition="c.STATUS = 'A'", business_rule="取最新一条",
    )
    ybt_mapping = MartToYbtMapping(
        project_id=project.id, target_field_id=target.id, mart_field_id=mart.id,
        mapping_status="approved", mapping_name="证件类型报送映射",
        join_condition="m.CUST_ID = t.CUST_ID", validation_rule="非空校验",
    )
    db.add_all([business, technical, source_mapping, ybt_mapping])

    script = ScriptFile(
        project_id=project.id, relative_path="etl/load_customer.sql",
        file_name="load_customer.sql", file_type="sql", current_version_no=2,
        logical_target_name="客户装载脚本",
    )
    db.add(script)
    db.flush()
    old_version = ScriptFileVersion(
        project_id=project.id, script_file_id=script.id, version_no=1,
        file_hash="a" * 64, normalized_hash="b" * 64, raw_content_storage_file_id=1,
        parse_status="parsed", git_commit_sha="oldsha", created_by=user.id,
    )
    new_version = ScriptFileVersion(
        project_id=project.id, script_file_id=script.id, version_no=2,
        file_hash="c" * 64, normalized_hash="d" * 64, raw_content_storage_file_id=2,
        parse_status="partially_parsed", git_commit_sha="newsha",
        warnings_json=["Statement 2 parse failed"], created_by=user.id,
    )
    db.add_all([old_version, new_version])
    db.flush()
    change_set = ScriptChangeSet(
        project_id=project.id, script_file_id=script.id,
        from_version_id=old_version.id, to_version_id=new_version.id,
        change_type="modified", status="completed",
        summary_json={"severity": "critical"}, created_by=user.id,
    )
    db.add(change_set)
    db.flush()

    source_node = LineageNode(
        project_id=project.id, node_type="column", logical_name="ECIF_CUSTOMER.CERT_TYPE",
        table_name="ECIF_CUSTOMER", column_name="CERT_TYPE", source_field_id=source.id,
        script_file_id=script.id, script_file_version_id=old_version.id, unresolved_flag=False,
    )
    target_node = LineageNode(
        project_id=project.id, node_type="column", logical_name="MART_CUST.CERT_TYPE",
        table_name="MART_CUST", column_name="CERT_TYPE", mart_field_id=mart.id,
        script_file_id=script.id, script_file_version_id=new_version.id, unresolved_flag=False,
    )
    db.add_all([source_node, target_node])
    db.flush()
    edge = LineageEdge(
        project_id=project.id, script_file_version_id=new_version.id,
        source_node_id=source_node.id, target_node_id=target_node.id,
        edge_type="derives_from", transformation_type="direct",
        join_condition="c.CUST_ID = m.CUST_ID", filter_condition="c.STATUS = 'A'",
        source_line_start=12, source_line_end=20, confidence_level="high",
        evidence_json={"statement_index": 1, "parser": "sqlglot"}, enabled=True,
    )
    db.add(edge)
    db.flush()

    db.add_all([
        MappingEvidenceReference(
            project_id=project.id, mapping_type="source_to_mart", mapping_id=source_mapping.id,
            evidence_type="source_field", evidence_id=source.id,
            source_name="客户主表", location_text="CERT_TYPE", evidence_summary="来源字段",
        ),
        MappingEvidenceReference(
            project_id=project.id, mapping_type="mart_to_ybt", mapping_id=ybt_mapping.id,
            evidence_type="mart_field", evidence_id=mart.id,
            source_name="监管集市客户表", location_text="CERT_TYPE", evidence_summary="集市字段",
        ),
    ])
    db.flush()

    impact = ImpactAnalysis(
        institution_id=institution.id, project_id=project.id, change_set_id=change_set.id,
        status="completed", severity="critical",
        affected_source_field_ids_json=[source.id, uncommented.id],
        affected_mart_field_ids_json=[mart.id],
        affected_target_field_ids_json=[target.id],
        affected_mapping_ids_json=[
            f"source_to_mart:{source_mapping.id}",
            f"mart_to_ybt:{ybt_mapping.id}",
            f"scenario_business:{business.id}",
            f"scenario_technical:{technical.id}",
            "mart_to_ybt:999999",
        ],
        affected_lineage_edge_ids_json=[edge.id],
        affected_requirement_ids_json=[target.id],
        summary_json={"script_file_id": script.id},
        open_questions_json=["请确认证件类型口径"],
    )
    db.add(impact)
    db.flush()
    return {
        "project": project,
        "other_project": other_project,
        "target": target,
        "mart": mart,
        "source": source,
        "uncommented": uncommented,
        "source_mapping": source_mapping,
        "ybt_mapping": ybt_mapping,
        "business": business,
        "technical": technical,
        "script": script,
        "old_version": old_version,
        "new_version": new_version,
        "edge": edge,
        "impact": impact,
    }


def test_impact_detail_uses_business_names_and_exposes_rules(db_session: Session) -> None:
    seed = _seed(db_session)

    detail = ImpactDetailBuilder(db_session).build(seed["impact"], include_paths=False)

    source_assets = detail["assets"]["source_fields"]
    assert {item["display_name"] for item in source_assets} == {"证件类型", "X_FLAG"}
    commented = next(item for item in source_assets if item["technical_name"] == "CERT_TYPE")
    assert commented["display_name"] == "证件类型"
    assert commented["display_name_source"] == "business_name"
    assert commented["comment"] == "证件类型代码"
    assert commented["layer_code"] == "SOURCE"
    assert commented["layer_name"] == "源系统"
    assert commented["system_name"] == "客户信息系统"
    missing = next(item for item in source_assets if item["technical_name"] == "X_FLAG")
    assert missing["display_name_source"] == "technical_name"
    assert missing["label_quality"] == "missing"

    target_asset = detail["assets"]["target_fields"][0]
    assert target_asset["display_name"] == "证件类型"
    assert target_asset["entity_type"] == "target_field"

    mappings = {(item["mapping_type"], item["mapping_id"]): item for item in detail["mappings"]}
    source_mapping = mappings[("source_to_mart", seed["source_mapping"].id)]
    assert source_mapping["rules"]["join_condition"] == "c.CUST_ID = m.CUST_ID"
    assert source_mapping["rules"]["filter_condition"] == "c.STATUS = 'A'"
    assert source_mapping["target_assets"][0]["display_name"] == "证件类型"
    assert any(item["technical_name"] == "CERT_TYPE" for item in source_mapping["source_assets"])
    assert source_mapping["evidence_refs"][0]["evidence_type"] == "source_field"

    ybt_mapping = mappings[("mart_to_ybt", seed["ybt_mapping"].id)]
    assert ybt_mapping["display_name"] == "证件类型报送映射"
    assert ybt_mapping["rules"]["validation_rule"] == "非空校验"

    business_mapping = mappings[("scenario_business", seed["business"].id)]
    assert business_mapping["display_name"] == "证件类型业务口径"
    assert business_mapping["rules"]["business_definition"] == "证件类型业务口径"

    missing_mapping = mappings[("mart_to_ybt", 999999)]
    assert missing_mapping["status"] == "missing"
    assert missing_mapping["display_name"] == "映射已删除或不可见"


def test_impact_detail_script_versions_and_edge_evidence(db_session: Session) -> None:
    seed = _seed(db_session)

    detail = ImpactDetailBuilder(db_session).build(seed["impact"], include_paths=False)

    script = detail["script"]
    assert script["display_name"] == "客户装载脚本"
    assert script["technical_name"] == "etl/load_customer.sql"
    assert {item["role"] for item in script["versions"]} == {"before", "after"}
    after = next(item for item in script["versions"] if item["role"] == "after")
    assert after["parse_status"] == "partially_parsed"
    assert after["git_commit_sha"] == "newsha"
    assert after["warnings"] == ["Statement 2 parse failed"]

    edge = detail["affected_edges"][0]
    assert edge["join_condition"] == "c.CUST_ID = m.CUST_ID"
    assert edge["source_line_start"] == 12
    assert edge["source"]["display_name"] == "证件类型"
    assert edge["source"]["comment"] == "证件类型代码"
    assert edge["target"]["display_name"] == "证件类型"
    assert edge["evidence_refs"][0]["summary"] == {"statement_index": 1, "parser": "sqlglot"}

    assert detail["pending_confirmation"] is True
    assert detail["truncated"] is False


def test_impact_detail_ignores_cross_project_rows(db_session: Session) -> None:
    seed = _seed(db_session)
    foreign = Project(name="外部项目", institution_id=seed["impact"].institution_id)
    db_session.add(foreign)
    db_session.flush()
    foreign_table = MartTable(project_id=foreign.id, table_code="MART_F", table_name="外部集市表")
    db_session.add(foreign_table)
    db_session.flush()
    foreign_field = MartField(
        project_id=foreign.id, mart_table_id=foreign_table.id, field_code="F", field_name="外部字段",
    )
    db_session.add(foreign_field)
    db_session.flush()
    seed["impact"].affected_mart_field_ids_json = [seed["mart"].id, foreign_field.id]
    db_session.flush()

    detail = ImpactDetailBuilder(db_session).build(seed["impact"], include_paths=False)

    assert [item["id"] for item in detail["assets"]["mart_fields"]] == [seed["mart"].id]
    assert all(item["display_name"] != "外部字段" for item in detail["assets"]["mart_fields"])


def test_impact_detail_builds_bounded_upstream_paths(db_session: Session) -> None:
    seed = _seed(db_session)

    detail = ImpactDetailBuilder(db_session).build(seed["impact"], include_paths=True, max_paths=5)

    assert len(detail["paths"]) == 1
    group = detail["paths"][0]
    assert group["target_field_id"] == seed["target"].id
    assert group["display"]["display_name"] == "证件类型"
    assert detail["lineage_versions"]["current_published"] is None
    assert detail["lineage_versions"]["comparison_available"] is False
