from sqlalchemy import event

from app.models import (
    MappingEvidenceReference,
    MartField,
    MartTable,
    MartToYbtMapping,
    ProductScenario,
    Project,
    ScenarioBusinessMapping,
    ScenarioTechnicalLineage,
    SourceToMartMapping,
    TargetField,
    TargetTable,
    User,
)
from app.services.requirement_workspace_projection import RequirementWorkspaceProjectionService


def test_workspace_projection_has_bounded_queries_and_defers_large_content(db_session) -> None:
    project = Project(name="工作区投影")
    db_session.add(project)
    db_session.flush()
    table = TargetTable(project_id=project.id, table_code="RPT", table_name="监管表")
    scenario = ProductScenario(project_id=project.id, scenario_code="BASE", scenario_name="基础场景", enabled=True)
    mart_table = MartTable(project_id=project.id, table_code="MART", table_name="监管集市表")
    db_session.add_all([table, scenario, mart_table])
    db_session.flush()
    mart_field = MartField(project_id=project.id, mart_table_id=mart_table.id, field_code="VALUE", field_name="值")
    db_session.add(mart_field)
    db_session.flush()

    large_final = "人工最终内容" * 1000
    for index in range(30):
        field = TargetField(project_id=project.id, target_table_id=table.id, field_code=f"F{index:03d}", field_name=f"字段{index}", required_flag=True, regulatory_refined_definition="监管定义" * 300)
        db_session.add(field)
        db_session.flush()
        business = ScenarioBusinessMapping(project_id=project.id, target_field_id=field.id, scenario_id=scenario.id, final_content=large_final, business_confirm_status="confirmed")
        lineage = ScenarioTechnicalLineage(project_id=project.id, target_field_id=field.id, scenario_id=scenario.id, final_content=large_final, tech_confirm_status="confirmed", source_system_name="核心系统")
        mart_mapping = MartToYbtMapping(project_id=project.id, target_field_id=field.id, mart_field_id=mart_field.id, final_content=large_final, mapping_status="approved")
        db_session.add_all([business, lineage, mart_mapping])
        db_session.flush()
        db_session.add(MappingEvidenceReference(project_id=project.id, mapping_type="scenario_business", mapping_id=business.id, evidence_type="manual_note", source_name="验收证据", quoted_content="证据全文" * 1000))
    project_id, table_id, scenario_id = project.id, table.id, scenario.id
    db_session.commit()

    statements: list[str] = []
    listener = lambda _conn, _cursor, statement, _parameters, _context, _executemany: statements.append(statement)
    event.listen(db_session.get_bind(), "before_cursor_execute", listener)
    try:
        projection = RequirementWorkspaceProjectionService(db_session).projection(project_id, table_id, scenario_id)
    finally:
        event.remove(db_session.get_bind(), "before_cursor_execute", listener)

    assert len(statements) <= 16
    assert projection["performance_budget"] == {
        "projection_version": "requirement-workspace-v1",
        "initial_api_request_budget": 1,
        "bounded_sql_query_budget": 16,
        "large_content_deferred": True,
    }
    assert len(projection["records"]) == 30
    assert projection["readiness_summary"]["evidence_count"] == 30
    serialized = str(projection)
    assert large_final not in serialized
    assert "证据全文" not in serialized
    assert len(projection["records"][0]["business"]["content_preview"]) == 320

    detail = RequirementWorkspaceProjectionService(db_session).field_detail(project_id, projection["records"][0]["field"]["id"], scenario_id)
    assert detail["business"]["final_content"] == large_final
    evidence = RequirementWorkspaceProjectionService(db_session).field_evidence(project_id, detail["field"]["id"], scenario_id)
    assert evidence[0]["quoted_content"].startswith("证据全文")


def test_workspace_projection_scopes_source_mappings_and_job_summaries(db_session) -> None:
    first = Project(name="主项目")
    second = Project(name="隔离项目")
    db_session.add_all([first, second])
    db_session.flush()
    table = TargetTable(project_id=first.id, table_code="RPT", table_name="监管表")
    scenario = ProductScenario(project_id=first.id, scenario_code="BASE", scenario_name="基础场景", enabled=True)
    mart_table = MartTable(project_id=first.id, table_code="MART", table_name="集市表")
    db_session.add_all([table, scenario, mart_table])
    db_session.flush()
    field = TargetField(project_id=first.id, target_table_id=table.id, field_code="F1", field_name="字段")
    mart_field = MartField(project_id=first.id, mart_table_id=mart_table.id, field_code="M1", field_name="集市字段")
    db_session.add_all([field, mart_field])
    db_session.flush()
    db_session.add(SourceToMartMapping(project_id=second.id, mart_field_id=mart_field.id, source_system_summary="不应泄露", final_content="secret"))
    from app.models import BackgroundJob
    user = User(username="projection-job-user", password_hash="test", status="active")
    db_session.add(user)
    db_session.flush()
    db_session.add(BackgroundJob(project_id=first.id, idempotency_key="projection-job", job_type="batch_ai_generation_business", created_by=user.id, result_summary_json={"processed": 1, "secret_payload": "must not leave projection"}))
    db_session.commit()

    projection = RequirementWorkspaceProjectionService(db_session).projection(first.id, table.id, scenario.id)
    record = projection["records"][0]
    assert record["source_mappings"] == {}
    assert "secret_payload" not in str(projection["recent_jobs"])


def test_workspace_projection_rejects_foreign_table_and_field(db_session) -> None:
    first = Project(name="项目一")
    second = Project(name="项目二")
    db_session.add_all([first, second])
    db_session.flush()
    foreign_table = TargetTable(project_id=second.id, table_code="FOREIGN", table_name="不可见表")
    db_session.add(foreign_table)
    db_session.flush()
    foreign_field = TargetField(project_id=second.id, target_table_id=foreign_table.id, field_code="SECRET", field_name="不可见字段")
    db_session.add(foreign_field)
    db_session.commit()

    service = RequirementWorkspaceProjectionService(db_session)
    try:
        service.projection(first.id, foreign_table.id, None)
        raise AssertionError("foreign table should be rejected")
    except LookupError:
        pass
    try:
        service.field_detail(first.id, foreign_field.id, None)
        raise AssertionError("foreign field should be rejected")
    except LookupError:
        pass
