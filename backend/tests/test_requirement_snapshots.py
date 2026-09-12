from datetime import date

from sqlalchemy import text

from app.models import (
    MartField,
    MartTable,
    MartToYbtMapping,
    ProductScenario,
    Project,
    ScenarioBusinessMapping,
    ScenarioTechnicalLineage,
    SourceToMartMapping,
    MappingVersion,
    SemanticBinding,
    SemanticConcept,
    SemanticConceptVersion,
    TargetField,
    TargetTable,
)
from app.api.requirement_workspace import create_requirement_snapshot
from app.schemas.requirement_snapshot import RequirementSnapshotCreate
from app.services.auth.dependencies import Principal
from app.services.auth.resource_guard import _permission
from app.services.requirement_snapshot import RequirementSnapshotService
from fastapi import Response


def _fixture(db_session):
    project = Project(name="结构化快照项目")
    db_session.add(project)
    db_session.flush()
    table = TargetTable(project_id=project.id, table_code="RPT_CUSTOMER", table_name="客户监管报表", description="监管报送目标表")
    scenario = ProductScenario(project_id=project.id, scenario_code="MONTHLY", scenario_name="月度报送", enabled=True)
    mart_table = MartTable(project_id=project.id, table_code="MART_CUSTOMER", table_name="客户监管集市", table_comment="集市客户主题")
    db_session.add_all([table, scenario, mart_table])
    db_session.flush()
    target = TargetField(
        project_id=project.id,
        target_table_id=table.id,
        field_code="CUSTOMER_ID",
        field_name="客户统一标识",
        field_type="VARCHAR",
        required_flag=True,
        regulatory_refined_definition="用于跨系统识别同一客户",
    )
    mart = MartField(
        project_id=project.id,
        mart_table_id=mart_table.id,
        field_code="CUST_ID",
        field_name="集市客户标识",
        field_type="VARCHAR",
        field_comment="监管集市中的客户标识",
    )
    db_session.add_all([target, mart])
    db_session.flush()
    business = ScenarioBusinessMapping(
        project_id=project.id,
        target_field_id=target.id,
        scenario_id=scenario.id,
        business_definition="按客户统一标识报送",
        final_content="取客户主数据中的统一标识",
        business_confirm_status="confirmed",
    )
    technical = ScenarioTechnicalLineage(
        project_id=project.id,
        target_field_id=target.id,
        scenario_id=scenario.id,
        source_system_name="客户信息系统",
        source_schema_name="ods",
        source_table_english_name="ODS_CUSTOMER",
        source_table_chinese_name="客户源表",
        source_field_english_name="CUST_ID",
        source_field_chinese_name="客户标识",
        processing_logic="直接取值",
        tech_confirm_status="confirmed",
        lineage_status="linked",
    )
    source = SourceToMartMapping(
        project_id=project.id,
        mart_field_id=mart.id,
        source_system_summary="客户信息系统",
        source_tables_summary="ODS_CUSTOMER",
        source_fields_summary="CUST_ID",
        join_condition="ODS_CUSTOMER.CUST_ID = CUSTOMER_MASTER.CUST_ID",
        filter_condition="is_deleted = 0",
        mapping_status="approved",
        final_content="取未删除客户记录",
    )
    mart_mapping = MartToYbtMapping(
        project_id=project.id,
        target_field_id=target.id,
        mart_field_id=mart.id,
        join_condition="MART_CUSTOMER.CUST_ID = CUSTOMER_MASTER.CUST_ID",
        mapping_status="approved",
        final_content="直接映射集市客户标识",
    )
    db_session.add_all([business, technical, source, mart_mapping])
    db_session.commit()
    return project, table, scenario, target, source, mart_mapping


def test_snapshot_is_deterministic_and_idempotent(db_session):
    project, table, scenario, target, source, mart_mapping = _fixture(db_session)
    service = RequirementSnapshotService(db_session)

    first, first_idempotent = service.create(
        project_id=project.id,
        target_table_id=table.id,
        scenario_id=scenario.id,
        created_by=None,
        change_note="首次冻结",
    )
    db_session.commit()
    second, second_idempotent = service.create(
        project_id=project.id,
        target_table_id=table.id,
        scenario_id=scenario.id,
        created_by=None,
    )

    assert first_idempotent is False
    assert second_idempotent is True
    assert second.id == first.id
    assert first.snapshot_no == 1
    assert first.requirement_version == "req-1"
    assert len(first.content_hash) == 64
    assert first.content_snapshot_json["schema_version"] == "structured-requirement-v1"
    plan = first.content_snapshot_json["field_plans"][0]
    assert plan["target"]["display_name"] == "客户统一标识"
    assert plan["target"]["technical_name"] == "CUSTOMER_ID"
    assert plan["join_plans"][0]["raw_condition"]
    assert plan["join_plans"][0]["structured"] is False
    assert plan["join_plans"][0]["review_required"] is True
    assert plan["source_sources"][0]["resolution_status"] == "summary_only"


def test_snapshot_change_creates_new_version_without_mutating_old(db_session):
    project, table, scenario, _target, source, _mart_mapping = _fixture(db_session)
    service = RequirementSnapshotService(db_session)
    old, _ = service.create(project_id=project.id, target_table_id=table.id, scenario_id=scenario.id, created_by=None)
    db_session.commit()

    source.filter_condition = "is_deleted = 0 AND status = 'ACTIVE'"
    db_session.commit()
    new, idempotent = service.create(project_id=project.id, target_table_id=table.id, scenario_id=scenario.id, created_by=None)

    assert idempotent is False
    assert new.id != old.id
    assert new.snapshot_no == 2
    assert new.content_hash != old.content_hash
    assert old.content_snapshot_json["field_plans"][0]["source_sources"][0]["rules"]["rules"]["filter_condition"] == "is_deleted = 0"
    assert new.content_snapshot_json["field_plans"][0]["source_sources"][0]["rules"]["rules"]["filter_condition"] == "is_deleted = 0 AND status = 'ACTIVE'"


def test_snapshot_rejects_foreign_scope(db_session):
    project, table, scenario, _target, _source, _mart_mapping = _fixture(db_session)
    foreign = Project(name="其他项目")
    db_session.add(foreign)
    db_session.flush()
    foreign_table = TargetTable(project_id=foreign.id, table_code="FOREIGN", table_name="其他表")
    db_session.add(foreign_table)
    db_session.commit()

    service = RequirementSnapshotService(db_session)
    try:
        service.create(project_id=project.id, target_table_id=foreign_table.id, scenario_id=scenario.id, created_by=None)
        raise AssertionError("foreign table should be rejected")
    except LookupError as exc:
        assert "does not belong" in str(exc)


def test_snapshot_api_is_idempotent_and_audited(db_session):
    project, table, scenario, _target, _source, _mart_mapping = _fixture(db_session)
    principal = Principal(None, "legacy-system", "Legacy development mode", True)
    payload = RequirementSnapshotCreate(target_table_id=table.id, scenario_id=scenario.id, change_note="API 冻结")

    first_response = Response()
    first = create_requirement_snapshot(project.id, payload, principal, first_response, db_session)
    second_response = Response()
    second = create_requirement_snapshot(project.id, payload, principal, second_response, db_session)

    assert first_response.status_code == 201
    assert second_response.status_code == 200
    assert first["idempotent"] is False
    assert second["idempotent"] is True
    assert second["id"] == first["id"]
    audit_rows = db_session.execute(
        text("SELECT COUNT(*) FROM audit_logs WHERE project_id = :project_id AND action = :action"),
        {"project_id": project.id, "action": "create_requirement_snapshot"},
    ).scalar_one()
    assert audit_rows == 1


def test_snapshot_routes_use_existing_deliverable_permissions():
    assert _permission("POST", "/api/projects/1/requirement-workspace/snapshots") == "deliverable.generate"
    assert _permission("GET", "/api/projects/1/requirement-workspace/snapshots") == "deliverable.view"
    assert _permission("GET", "/api/projects/1/requirement-workspace/snapshots/2") == "deliverable.view"


def test_snapshot_hash_includes_mapping_fact_fields_and_uses_highest_mapping_version(db_session):
    project, table, scenario, _target, _source, mart_mapping = _fixture(db_session)
    db_session.add_all([
        MappingVersion(
            project_id=project.id,
            mapping_type="mart_to_ybt",
            mapping_id=mart_mapping.id,
            version_no=1,
            content_snapshot="v1",
        ),
        MappingVersion(
            project_id=project.id,
            mapping_type="mart_to_ybt",
            mapping_id=mart_mapping.id,
            version_no=3,
            content_snapshot="v3",
        ),
    ])
    db_session.commit()

    service = RequirementSnapshotService(db_session)
    first, _ = service.create(project_id=project.id, target_table_id=table.id, scenario_id=scenario.id, created_by=None)
    mart_plan = first.content_snapshot_json["field_plans"][0]["mart_sources"][0]
    assert mart_plan["version"]["version_no"] == 3
    assert mart_plan["final_content"] == "直接映射集市客户标识"

    mart_mapping.final_content = "改为按客户主键取集市记录"
    db_session.commit()
    second, idempotent = service.create(project_id=project.id, target_table_id=table.id, scenario_id=scenario.id, created_by=None)
    assert idempotent is False
    assert second.content_hash != first.content_hash
    assert second.content_snapshot_json["field_plans"][0]["mart_sources"][0]["final_content"] == "改为按客户主键取集市记录"


def test_snapshot_contains_read_only_semantic_references(db_session):
    project, table, scenario, target, _source, _mart_mapping = _fixture(db_session)
    concept = SemanticConcept(
        project_id=project.id,
        concept_type="business_term",
        concept_code="CUSTOMER_ID",
        concept_name="客户统一标识",
        status="confirmed",
        version=1,
    )
    db_session.add(concept)
    db_session.flush()
    db_session.add_all([
        SemanticConceptVersion(
            project_id=project.id,
            semantic_concept_id=concept.id,
            version_no=1,
            concept_name="客户统一标识",
            status="confirmed",
            effective_from=date(2026, 1, 1),
        ),
        SemanticBinding(
            project_id=project.id,
            semantic_concept_id=concept.id,
            entity_type="target_field",
            entity_id=target.id,
            binding_type="describes",
            status="confirmed",
        ),
    ])
    db_session.commit()

    snapshot, _ = RequirementSnapshotService(db_session).create(
        project_id=project.id,
        target_table_id=table.id,
        scenario_id=scenario.id,
        created_by=None,
    )
    refs = snapshot.content_snapshot_json["semantic_references"]
    assert refs["read_only"] is True
    assert refs["bindings"][0]["semantic_concept_id"] == concept.id
    assert refs["concepts"][0]["concept_name"] == "客户统一标识"
    assert refs["versions"][0]["version_no"] == 1


def test_snapshot_redacts_sensitive_values_before_persistence(db_session):
    project, table, scenario, _target, source, _mart_mapping = _fixture(db_session)
    source.filter_condition = "email = 'alice@example.com' AND password=secret123 AND phone=13800138000"
    db_session.commit()

    snapshot, _ = RequirementSnapshotService(db_session).create(
        project_id=project.id,
        target_table_id=table.id,
        scenario_id=scenario.id,
        created_by=None,
    )
    payload = str(snapshot.content_snapshot_json)
    assert "alice@example.com" not in payload
    assert "secret123" not in payload
    assert "13800138000" not in payload
    assert "[邮件]" in payload
    assert "[密钥]" in payload
    assert "[手机号]" in payload


def test_snapshot_null_scenario_scope_is_stable_and_non_null(db_session):
    project = Project(name="无场景快照项目")
    db_session.add(project)
    db_session.flush()
    table = TargetTable(project_id=project.id, table_code="NO_SCENARIO", table_name="无场景目标表")
    db_session.add(table)
    db_session.commit()

    service = RequirementSnapshotService(db_session)
    first, first_idempotent = service.create(project_id=project.id, target_table_id=table.id, scenario_id=None, created_by=None)
    db_session.commit()
    second, second_idempotent = service.create(project_id=project.id, target_table_id=table.id, scenario_id=None, created_by=None)
    assert first_idempotent is False
    assert second_idempotent is True
    assert second.id == first.id
    assert first.scope_key.endswith("scenario:0")
