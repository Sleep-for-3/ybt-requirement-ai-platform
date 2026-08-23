from __future__ import annotations

from datetime import UTC, date, datetime
import inspect

import pytest
from pydantic import ValidationError
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.models import MartField, MartTable, Project, SourceToMartMapping, User
from app.schemas.regulatory_context import (
    ContextAttribute,
    ContextConflict,
    ContextFact,
    ContextMode,
    ContextProvenance,
    MetadataContextValue,
)
from app.services.auth.dependencies import Principal
from app.services.auth.permission_service import PermissionService
from app.services.mapping.context_adapters import (
    SourceToMartContextAdapter,
    audit_scenario_physical_coverage,
    build_physical_source_whitelist,
)
from app.services.mapping.generation_readiness import evaluate_generation_readiness
from app.services.mapping.generator_context import (
    GenerationActorError,
    build_generation_context,
    recover_queued_actor,
    resolve_generation_as_of,
    snapshot_source_to_mart_generation,
    validate_generation_actor,
)
from app.services.semantic.context_builder import RegulatoryContextBuilder
from app.services.semantic.context_authority import FactState, authority_for_source


AS_OF = date(2026, 6, 30)


def test_source_to_mart_tracer_builds_one_candidate_context_and_bounded_projection(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _seed_source_to_mart_task(db_session)
    actor = Principal(
        fixture["user"].id,
        fixture["user"].username,
        fixture["user"].display_name,
        False,
    )
    authorized_project = PermissionService(
        db_session,
        Principal(None, "legacy-system", "Legacy", True),
    ).require_project_permission(fixture["project"].id, "project.view")
    snapshot = snapshot_source_to_mart_generation(
        fixture["mapping"],
        authorized_project,
    )
    original_build = RegulatoryContextBuilder.build
    builder_requests = []

    def counted_build(self, request, *, authorized_project):
        builder_requests.append(request)
        return original_build(self, request, authorized_project=authorized_project)

    monkeypatch.setattr(RegulatoryContextBuilder, "build", counted_build)

    envelope = build_generation_context(
        db_session,
        snapshot=snapshot,
        actor=actor,
        authorized_project=authorized_project,
        explicit_as_of=AS_OF,
        adapter=SourceToMartContextAdapter().project,
    )

    assert len(builder_requests) == 1
    assert builder_requests[0].mode is ContextMode.CANDIDATE
    assert builder_requests[0].project_id == authorized_project.id
    assert builder_requests[0].mart_field_id == fixture["mapping"].mart_field_id
    assert envelope.actor == actor
    assert envelope.context.scope.mode is ContextMode.CANDIDATE
    assert envelope.projection.task_type == "source_to_mart"
    assert 0 < len(envelope.projection.prompt_text) <= 6000
    assert envelope.trace.resolved_as_of == AS_OF
    assert envelope.trace.as_of_source == "explicit"
    assert envelope.trace.context_schema_version == "1.0"
    assert envelope.trace.context_built_at == envelope.context.build_metadata.built_at
    assert "with_for_update" not in inspect.getsource(build_generation_context)


def test_builder_failure_propagates_before_adapter_or_legacy_fallback_and_preserves_snapshot(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _seed_source_to_mart_task(db_session, suffix="FAIL")
    actor = Principal(
        fixture["user"].id,
        fixture["user"].username,
        fixture["user"].display_name,
        False,
    )
    snapshot = snapshot_source_to_mart_generation(
        fixture["mapping"],
        fixture["project"],
    )
    before = snapshot.model_dump(mode="json")
    adapter_calls = 0

    def fail_build(*args: object, **kwargs: object):
        raise RuntimeError("context construction failed")

    def adapter(*args: object, **kwargs: object):
        nonlocal adapter_calls
        adapter_calls += 1
        raise AssertionError("adapter must not run after builder failure")

    monkeypatch.setattr(RegulatoryContextBuilder, "build", fail_build)

    with pytest.raises(RuntimeError, match="context construction failed"):
        build_generation_context(
            db_session,
            snapshot=snapshot,
            actor=actor,
            authorized_project=fixture["project"],
            explicit_as_of=AS_OF,
            adapter=adapter,
        )

    assert adapter_calls == 0
    assert snapshot.model_dump(mode="json") == before
    source = inspect.getsource(build_generation_context)
    assert "HybridRetriever" not in source
    assert "MappingEvidenceReference" not in source
    assert "fallback" not in source.casefold()


def test_as_of_resolution_prefers_explicit_then_injected_current_business_date() -> None:
    ignored_created_at = datetime(1999, 1, 1, tzinfo=UTC)
    ignored_reporting_label = "2025 年末"

    explicit = resolve_generation_as_of(
        AS_OF,
        task_created_at=ignored_created_at,
        reporting_label=ignored_reporting_label,
        today_provider=lambda: date(2099, 12, 31),
    )
    current = resolve_generation_as_of(
        None,
        task_created_at=ignored_created_at,
        reporting_label=ignored_reporting_label,
        today_provider=lambda: date(2026, 8, 23),
    )

    assert explicit.as_of == AS_OF
    assert explicit.source == "explicit"
    assert current.as_of == date(2026, 8, 23)
    assert current.source == "current_business_date"


def test_source_to_mart_readiness_treats_own_mapping_gap_as_non_blocking_but_blocks_core_conflict(
    db_session: Session,
) -> None:
    fixture = _seed_source_to_mart_task(db_session, suffix="READINESS")
    actor = Principal(
        fixture["user"].id,
        fixture["user"].username,
        fixture["user"].display_name,
        False,
    )
    snapshot = snapshot_source_to_mart_generation(
        fixture["mapping"],
        fixture["project"],
    )
    envelope = build_generation_context(
        db_session,
        snapshot=snapshot,
        actor=actor,
        authorized_project=fixture["project"],
        explicit_as_of=AS_OF,
        adapter=SourceToMartContextAdapter().project,
    )

    readiness = envelope.projection.readiness
    assert readiness.can_generate is True
    assert readiness.confidence_cap == "low"
    assert "MISSING_SOURCE_MAPPING" not in readiness.blocking_reasons
    assert "MISSING_SOURCE_MAPPING" in readiness.warnings

    conflicted = envelope.context.model_copy(deep=True)
    conflicted.conflicts.append(ContextConflict(
        code="CONFLICTING_AUTHORITATIVE_FACTS",
        severity="error",
        target_type="mart_field",
        target_id=fixture["mapping"].mart_field_id,
        message="Two authoritative rules conflict.",
        resolution_state="unresolved",
    ))
    blocked = evaluate_generation_readiness(conflicted, "source_to_mart")

    assert blocked.can_generate is False
    assert blocked.blocking_reasons == ["CONFLICTING_AUTHORITATIVE_FACTS"]


def test_physical_catalog_whitelist_and_coverage_audit_are_exact_and_zero_sql(
    db_session: Session,
) -> None:
    fixture = _seed_source_to_mart_task(db_session, suffix="PHYSICAL")
    snapshot = snapshot_source_to_mart_generation(
        fixture["mapping"],
        fixture["project"],
    )
    envelope = build_generation_context(
        db_session,
        snapshot=snapshot,
        actor=Principal(None, "legacy-system", "Legacy", True),
        authorized_project=fixture["project"],
        explicit_as_of=AS_OF,
        adapter=SourceToMartContextAdapter().project,
    )
    observed_at = datetime(2026, 6, 30, tzinfo=UTC)
    catalog_fact = ContextFact(
        fact_type="catalog_column_metadata",
        value=MetadataContextValue(
            entity_type="catalog_column",
            entity_id=7001,
            code="BANK_DB.ODS.CUSTOMER.CUST_UNIFIED_NO",
            name="CUST_UNIFIED_NO",
            attributes=[
                ContextAttribute(name="database_name", value=" BANK_DB "),
                ContextAttribute(name="schema_name", value="ODS"),
                ContextAttribute(name="table_name", value="Customer"),
                ContextAttribute(name="column_name", value="Cust_Unified_No"),
            ],
        ),
        authority=authority_for_source("source_metadata"),
        state=FactState.OBSERVED,
        source_type="source_metadata",
        source_id=7001,
        observed_at=observed_at,
        confidence=1.0,
        provenance=ContextProvenance(
            project_id=fixture["project"].id,
            institution_id=fixture["project"].institution_id,
            source_model="CatalogColumn",
            source_type="source_metadata",
            source_id=7001,
            observed_at=observed_at,
            confidentiality_level=fixture["project"].confidentiality_level,
        ),
    )
    enriched = envelope.context.model_copy(
        update={"metadata": [*envelope.context.metadata, catalog_fact]},
    )
    engine = db_session.get_bind()
    statement_count = 0

    def before_cursor_execute(*args: object, **kwargs: object) -> None:
        nonlocal statement_count
        statement_count += 1

    event.listen(engine, "before_cursor_execute", before_cursor_execute)
    try:
        whitelist = build_physical_source_whitelist(enriched)
        complete = audit_scenario_physical_coverage(enriched)
        missing = audit_scenario_physical_coverage(envelope.context)
    finally:
        event.remove(engine, "before_cursor_execute", before_cursor_execute)

    assert statement_count == 0
    assert whitelist == (("bank_db", "ods", "customer", "cust_unified_no"),)
    assert complete.allowlisted_sources == whitelist
    assert complete.warning is None
    assert complete.open_question is None
    assert complete.confidence_cap == "high"
    assert missing.allowlisted_sources == ()
    assert missing.warning == "PHYSICAL_SOURCE_EVIDENCE_MISSING"
    assert missing.open_question == (
        "请确认来源数据库、模式、表和字段，并提供 CatalogColumn 证据或已验证血缘。"
    )
    assert missing.confidence_cap == "low"


def test_source_to_mart_snapshot_is_explicit_frozen_and_actor_identity_fails_closed(
    db_session: Session,
) -> None:
    fixture = _seed_source_to_mart_task(db_session, suffix="ACTOR")
    mapping = fixture["mapping"]
    project = fixture["project"]
    actor = Principal(
        fixture["user"].id,
        fixture["user"].username,
        fixture["user"].display_name,
        False,
    )
    snapshot = snapshot_source_to_mart_generation(mapping, project)

    assert snapshot.project.model_dump() == {
        "id": project.id,
        "institution_id": project.institution_id,
        "project_status": project.project_status,
        "confidentiality_level": project.confidentiality_level,
        "governance_workflow_enabled": project.governance_workflow_enabled,
        "updated_at": project.updated_at.isoformat(),
    }
    assert set(type(snapshot.task).model_fields) == {
        "id",
        "project_id",
        "mart_field_id",
        "mapping_name",
        "mapping_status",
        "source_system_summary",
        "source_tables_summary",
        "source_fields_summary",
        "business_rule",
        "filter_condition",
        "join_condition",
        "priority_rule",
        "merge_rule",
        "code_mapping_rule",
        "null_handling_rule",
        "exception_rule",
        "quality_check_rule",
        "open_questions",
        "ai_generated_content",
        "final_content",
        "confidence_level",
        "created_by",
        "reviewed_by",
        "reviewed_at",
        "lineage_status",
        "lineage_last_verified_at",
        "lineage_change_set_id",
        "updated_at",
    }
    with pytest.raises(ValidationError):
        snapshot.task.mapping_status = "approved"

    assert validate_generation_actor(db_session, actor) is actor
    with pytest.raises(GenerationActorError, match="positive user_id"):
        validate_generation_actor(db_session, Principal(0, "zero", None, False))
    with pytest.raises(GenerationActorError, match="active User"):
        validate_generation_actor(db_session, Principal(999999, "missing", None, False))

    disabled = User(username=f"disabled-{mapping.id}", display_name="Disabled", status="disabled")
    db_session.add(disabled)
    db_session.commit()
    with pytest.raises(GenerationActorError, match="active User"):
        validate_generation_actor(
            db_session,
            Principal(disabled.id, disabled.username, disabled.display_name, False),
        )
    with pytest.raises(GenerationActorError, match="positive persisted user id"):
        recover_queued_actor(db_session, None)
    with pytest.raises(GenerationActorError, match="positive persisted user id"):
        recover_queued_actor(db_session, 0)

    recovered = recover_queued_actor(db_session, fixture["user"].id)
    assert recovered == Principal(
        fixture["user"].id,
        fixture["user"].username,
        fixture["user"].display_name,
        False,
    )
    assert validate_generation_actor(
        db_session,
        Principal(None, "legacy-system", "Legacy", True),
    ).is_legacy_system is True


def _seed_source_to_mart_task(
    db: Session,
    *,
    suffix: str = "BASE",
) -> dict[str, object]:
    user = User(
        username=f"generator-user-{suffix.casefold()}",
        display_name=f"Generator User {suffix}",
        status="active",
    )
    project = Project(
        name=f"Generator Context {suffix}",
        project_status="active",
        confidentiality_level="internal",
        governance_workflow_enabled=True,
    )
    db.add_all([user, project])
    db.flush()
    mart_table = MartTable(
        project_id=project.id,
        table_code=f"MART_{suffix}",
        table_name=f"监管集市 {suffix}",
        database_name="dw",
        schema_name="mart",
        physical_table_name=f"mart_{suffix.casefold()}",
    )
    db.add(mart_table)
    db.flush()
    mart_field = MartField(
        project_id=project.id,
        mart_table_id=mart_table.id,
        field_code=f"FIELD_{suffix}",
        field_name=f"监管字段 {suffix}",
        field_type="varchar(64)",
        field_comment="统一监管字段",
        physical_column_name=f"field_{suffix.casefold()}",
    )
    db.add(mart_field)
    db.flush()
    mapping = SourceToMartMapping(
        project_id=project.id,
        mart_field_id=mart_field.id,
        mapping_name=f"Source to mart {suffix}",
        mapping_status="draft",
        source_system_summary="核心系统",
        source_tables_summary="客户主表",
        source_fields_summary="客户统一编号",
        business_rule="按客户统一编号映射",
        filter_condition="有效标志=1",
        join_condition="无",
        priority_rule="主记录优先",
        merge_rule="去重",
        code_mapping_rule="原值",
        null_handling_rule="待确认",
        exception_rule="进入异常队列",
        quality_check_rule="非空",
        open_questions="人工问题保持原样",
        ai_generated_content="旧 AI 草稿",
        final_content="人工最终内容",
        confidence_level="medium",
        created_by=user.username,
        lineage_status="not_linked",
    )
    db.add(mapping)
    db.commit()
    db.refresh(user)
    db.refresh(project)
    db.refresh(mapping)
    return {
        "user": user,
        "project": project,
        "mart_table": mart_table,
        "mart_field": mart_field,
        "mapping": mapping,
    }
