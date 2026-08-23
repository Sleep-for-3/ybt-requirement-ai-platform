from __future__ import annotations

from datetime import UTC, date, datetime
import inspect

import pytest
from pydantic import ValidationError
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.models import (
    AuditLog,
    MartField,
    MartTable,
    MartToYbtMapping,
    ModelCallLog,
    ProductScenario,
    Project,
    ScenarioBusinessMapping,
    ScenarioTechnicalLineage,
    SourceToMartMapping,
    TargetField,
    TargetTable,
    User,
)
from app.schemas.regulatory_context import (
    ContextAttribute,
    ContextConflict,
    ContextFact,
    ContextMode,
    ContextOpenQuestion,
    ContextProvenance,
    MetadataContextValue,
)
from app.services.auth.dependencies import Principal
from app.services.auth.permission_service import PermissionService
from app.services.llm.prompt_runtime import PromptRuntime, prepare_model_input
from app.services.mapping.context_adapters import (
    MartToYbtContextAdapter,
    ScenarioBusinessContextAdapter,
    ScenarioTechnicalContextAdapter,
    SourceToMartContextAdapter,
    apply_generation_output_policy,
    audit_scenario_physical_coverage,
    build_physical_source_whitelist,
    redacted_generation_output_trace,
)
from app.services.mapping.generation_readiness import (
    evaluate_generation_readiness,
    merge_generation_questions,
)
from app.services.mapping import (
    mart_to_ybt_generator,
    scenario_draft_generator,
    source_to_mart_generator,
)
from app.services.mapping.generator_context import (
    GenerationActorError,
    build_generation_context,
    recover_queued_actor,
    resolve_generation_as_of,
    snapshot_mart_to_ybt_generation,
    snapshot_scenario_business_generation,
    snapshot_scenario_technical_generation,
    snapshot_source_to_mart_generation,
    validate_generation_actor,
)
from app.services.semantic.context_builder import RegulatoryContextBuilder
from app.services.semantic.context_authority import FactState, authority_for_source


AS_OF = date(2026, 6, 30)


@pytest.mark.parametrize(
    (
        "generator",
        "prompt_key",
        "output_contract",
        "permission",
        "task_lock",
    ),
    (
        (
            source_to_mart_generator.generate_source_to_mart_draft,
            "source_to_mart_mapping",
            "SourceToMartOutput",
            "technical.edit",
            "select(SourceToMartMapping)",
        ),
        (
            mart_to_ybt_generator.generate_mart_to_ybt_draft,
            "mart_to_ybt_mapping",
            "MartToYbtOutput",
            "technical.edit",
            "select(MartToYbtMapping)",
        ),
        (
            scenario_draft_generator.generate_business_draft,
            "scenario_business_mapping",
            "ScenarioBusinessOutput",
            "business.edit",
            "select(ScenarioBusinessMapping)",
        ),
        (
            scenario_draft_generator.generate_technical_draft,
            "scenario_technical_lineage",
            "ScenarioTechnicalOutput",
            "technical.edit",
            "select(ScenarioTechnicalLineage)",
        ),
    ),
)
def test_all_four_generators_share_one_context_seam_and_distinct_runtime_contracts(
    generator: object,
    prompt_key: str,
    output_contract: str,
    permission: str,
    task_lock: str,
) -> None:
    """Keep the four public contracts distinct behind one governed seam."""

    source = inspect.getsource(generator)

    assert source.count("build_generation_context(") == 1
    assert f'get_prompt_runtime(db, "{prompt_key}")' in source
    assert output_contract in source
    assert f'"{permission}"' in source

    context_build = source.index("build_generation_context(")
    model_call = source.index("execute_runtime_chat(", context_build)
    write_transaction = source.index("with db.begin():", model_call)
    actor_check = source.index("validate_generation_actor(db, actor)", write_transaction)
    permission_check = source.index("PermissionService(db, actor)", actor_check)
    project_lock = source.index("select(Project)", permission_check)
    local_task_lock = source.index(task_lock, project_lock)
    assert context_build < model_call < write_transaction
    assert actor_check < permission_check < project_lock < local_task_lock

    for forbidden in (
        "HybridRetriever",
        "MappingEvidenceReference",
        "CatalogColumn",
        "_source_candidates",
        "_evidence_text",
    ):
        assert forbidden not in source


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


def test_all_four_task_projections_are_distinct_and_mart_uses_approved_context_rule_only(
    db_session: Session,
) -> None:
    fixture = _seed_all_generator_tasks(db_session)
    project = fixture["project"]
    actor = Principal(None, "legacy-system", "Legacy", True)
    specifications = (
        (
            snapshot_source_to_mart_generation(fixture["source_task"], project),
            SourceToMartContextAdapter().project,
        ),
        (
            snapshot_mart_to_ybt_generation(fixture["mart_task"], project),
            MartToYbtContextAdapter().project,
        ),
        (
            snapshot_scenario_business_generation(fixture["business_task"], project),
            ScenarioBusinessContextAdapter().project,
        ),
        (
            snapshot_scenario_technical_generation(fixture["technical_task"], project),
            ScenarioTechnicalContextAdapter().project,
        ),
    )

    projections = [
        build_generation_context(
            db_session,
            snapshot=snapshot,
            actor=actor,
            authorized_project=project,
            explicit_as_of=AS_OF,
            adapter=adapter,
        ).projection
        for snapshot, adapter in specifications
    ]

    assert [projection.task_type for projection in projections] == [
        "source_to_mart",
        "mart_to_ybt",
        "scenario_business",
        "scenario_technical",
    ]
    assert len({projection.projection_hash for projection in projections}) == 4
    assert all(0 < len(projection.prompt_text) <= 6000 for projection in projections)
    mart_projection = projections[1]
    assert mart_projection.upstream_rule_summaries == ["APPROVED_CONTEXT_RULE"]
    assert "FORBIDDEN_DRAFT_FALLBACK" not in mart_projection.prompt_text
    assert "FORBIDDEN_DRAFT_FALLBACK" not in "\n".join(
        mart_projection.upstream_rule_summaries
    )
    assert "场景业务口径" in projections[2].prompt_text
    assert "场景技术溯源" in projections[3].prompt_text
    assert "__dict__" not in inspect.getsource(MartToYbtContextAdapter)
    assert "__dict__" not in inspect.getsource(ScenarioBusinessContextAdapter)
    assert "__dict__" not in inspect.getsource(ScenarioTechnicalContextAdapter)


def test_confidential_four_projection_matrix_denies_external_runtime_and_redacts_audit(
    db_session: Session,
) -> None:
    fixture = _seed_all_generator_tasks(db_session, suffix="CONFIDENTIAL")
    project = fixture["project"]
    project.confidentiality_level = "restricted"
    db_session.commit()
    actor = Principal(None, "legacy-system", "Legacy", True)
    specifications = (
        (
            snapshot_source_to_mart_generation(fixture["source_task"], project),
            SourceToMartContextAdapter().project,
        ),
        (
            snapshot_mart_to_ybt_generation(fixture["mart_task"], project),
            MartToYbtContextAdapter().project,
        ),
        (
            snapshot_scenario_business_generation(fixture["business_task"], project),
            ScenarioBusinessContextAdapter().project,
        ),
        (
            snapshot_scenario_technical_generation(fixture["technical_task"], project),
            ScenarioTechnicalContextAdapter().project,
        ),
    )
    projections = [
        build_generation_context(
            db_session,
            snapshot=snapshot,
            actor=actor,
            authorized_project=project,
            explicit_as_of=AS_OF,
            adapter=adapter,
        ).projection
        for snapshot, adapter in specifications
    ]
    runtime = PromptRuntime(
        prompt_key="qualification-external",
        version=1,
        system_prompt="qualification",
        user_template="{evidence}",
        model_profile_id=None,
        provider_type="openai-compatible",
        base_url="https://example.invalid/v1",
        model_name="qualification-only",
        api_key_env_name=None,
        local_only=False,
        config={},
    )
    raw_markers: list[str] = []

    for projection in projections:
        assert "restricted" in projection.confidentiality_levels
        marker = f"RAW_RESTRICTED_{projection.task_type.upper()}_BODY"
        raw_markers.append(marker)
        with pytest.raises(ValueError, match="restricted"):
            prepare_model_input(
                runtime,
                f"{projection.prompt_text}\n{marker}",
                projection.confidentiality_levels,
                db=db_session,
                project_id=project.id,
            )

    audits = db_session.scalars(
        select(AuditLog).where(
            AuditLog.project_id == project.id,
            AuditLog.action == "external_model_data_denied",
        )
    ).all()
    assert len(audits) == 4
    assert all(audit.result == "denied" for audit in audits)
    serialized_audits = str([
        (audit.before_summary_json, audit.after_summary_json)
        for audit in audits
    ])
    assert all(marker not in serialized_audits for marker in raw_markers)
    assert db_session.scalar(
        select(ModelCallLog.id).where(ModelCallLog.project_id == project.id)
    ) is None


def test_question_merge_preserves_human_bytes_and_is_stable_deduplicated_and_idempotent() -> None:
    human = "人工问题 B\r\n人工问题 A  "
    context_questions = [
        ContextOpenQuestion(
            question_code="CTX_Z",
            question_type="governance",
            priority="medium",
            target_type="target_field",
            target_id=8,
            question_text="请确认业务负责人",
        ),
        ContextOpenQuestion(
            question_code="CTX_A",
            question_type="physical_source",
            priority="high",
            target_type="target_field",
            target_id=8,
            question_text="Schema Required",
        ),
    ]

    merged = merge_generation_questions(
        human,
        context_questions,
        ["schema\u00a0required", "Model only question", "MODEL ONLY\u3000QUESTION", "人工问题 a"],
    )

    assert merged.text.startswith(human)
    assert merged.text == (
        human
        + "\n[CTX:CTX_A] Schema Required"
        + "\n[CTX:CTX_Z] 请确认业务负责人"
        + "\n[AI] Model only question"
    )
    assert merged.appended_context_codes == ["CTX_A", "CTX_Z"]
    assert merged.appended_model_count == 1
    repeated = merge_generation_questions(
        merged.text,
        context_questions,
        ["Schema Required", "model only question"],
    )
    assert repeated.text == merged.text
    assert repeated.appended_context_codes == []
    assert repeated.appended_model_count == 0


def test_sparse_output_policy_caps_confidence_and_omits_unknown_physical_and_governance_fields(
    db_session: Session,
) -> None:
    fixture = _seed_all_generator_tasks(db_session, suffix="SAFE_OUTPUT")
    project = fixture["project"]
    snapshot = snapshot_scenario_technical_generation(
        fixture["technical_task"],
        project,
    )
    projection = build_generation_context(
        db_session,
        snapshot=snapshot,
        actor=Principal(None, "legacy-system", "Legacy", True),
        authorized_project=project,
        explicit_as_of=AS_OF,
        adapter=ScenarioTechnicalContextAdapter().project,
    ).projection
    proposed = {
        "source_database_name": "UNKNOWN_DB",
        "source_schema_name": "UNKNOWN_SCHEMA",
        "source_table_english_name": "UNKNOWN_TABLE",
        "source_field_english_name": "UNKNOWN_FIELD",
        "processing_logic": "SECRET_PROCESSING remains non-physical",
        "confidence_level": "high",
        "open_questions": ["Model-only safety question"],
        "tech_confirm_status": "confirmed",
        "final_content": "must never become authoritative",
    }

    safe = apply_generation_output_policy(
        projection,
        proposed,
        existing_human_questions="人工原始问题",
    )

    assert safe.output_fields["processing_logic"] == "SECRET_PROCESSING remains non-physical"
    assert not {
        "source_database_name",
        "source_schema_name",
        "source_table_english_name",
        "source_field_english_name",
        "tech_confirm_status",
        "final_content",
    } & safe.output_fields.keys()
    assert safe.confidence_level == "low"
    assert safe.pending_confirmation is True
    assert "[CTX:PHYSICAL_SOURCE_EVIDENCE_MISSING]" in safe.merged_questions.text
    assert "[AI] Model-only safety question" in safe.merged_questions.text
    assert "UNKNOWN_DB" not in safe.merged_questions.text

    allowlisted = apply_generation_output_policy(
        projection,
        proposed,
        physical_whitelist=((
            "unknown_db",
            "unknown_schema",
            "unknown_table",
            "unknown_field",
        ),),
    )
    assert allowlisted.output_fields["source_database_name"] == "UNKNOWN_DB"
    assert allowlisted.output_fields["source_field_english_name"] == "UNKNOWN_FIELD"

    unchanged = apply_generation_output_policy(
        projection,
        {
            "source_database_name": "LEGACY_DB",
            "source_schema_name": "LEGACY_SCHEMA",
            "source_table_english_name": "LEGACY_TABLE",
            "source_field_english_name": "LEGACY_FIELD",
            "processing_logic": "unchanged physical tuple",
            "confidence_level": "high",
        },
    )
    assert unchanged.output_fields["source_database_name"] == "LEGACY_DB"
    assert unchanged.output_fields["source_field_english_name"] == "LEGACY_FIELD"
    trace_json = redacted_generation_output_trace(safe).model_dump_json()
    assert "SECRET_PROCESSING" not in trace_json
    assert "UNKNOWN_DB" not in trace_json
    assert "must never become authoritative" not in trace_json


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


def _seed_all_generator_tasks(
    db: Session,
    *,
    suffix: str = "ALL",
) -> dict[str, object]:
    base = _seed_source_to_mart_task(db, suffix=suffix)
    project = base["project"]
    mart_field = base["mart_field"]
    source_task = base["mapping"]
    source_task.mapping_status = "draft"
    source_task.final_content = "FORBIDDEN_DRAFT_FALLBACK"
    source_task.ai_generated_content = "FORBIDDEN_DRAFT_AI"
    approved_source = SourceToMartMapping(
        project_id=project.id,
        mart_field_id=mart_field.id,
        mapping_name=f"Approved upstream {suffix}",
        mapping_status="approved",
        business_rule="APPROVED_BUSINESS_RULE_SHOULD_NOT_WIN",
        final_content="APPROVED_CONTEXT_RULE",
        confidence_level="high",
        lineage_status="verified",
        lineage_last_verified_at=datetime(2026, 5, 1, tzinfo=UTC),
    )
    target_table = TargetTable(
        project_id=project.id,
        table_code=f"YBT_{suffix}",
        table_name=f"一表通表 {suffix}",
        description="监管报送目标表",
    )
    db.add_all([approved_source, target_table])
    db.flush()
    target_field = TargetField(
        project_id=project.id,
        target_table_id=target_table.id,
        field_code=f"TARGET_{suffix}",
        field_name=f"目标字段 {suffix}",
        field_type="VARCHAR(64)",
        required_flag=True,
        field_definition="监管目标字段定义",
    )
    scenario = ProductScenario(
        project_id=project.id,
        scenario_code=f"SCENARIO_{suffix}",
        scenario_name=f"监管场景 {suffix}",
        scenario_type="regulatory_reporting",
        enabled=True,
    )
    db.add_all([target_field, scenario])
    db.flush()
    mart_task = MartToYbtMapping(
        project_id=project.id,
        target_field_id=target_field.id,
        mart_field_id=mart_field.id,
        mapping_name=f"Mart to YBT {suffix}",
        mapping_status="draft",
        business_rule="人工 Mart-to-YBT 规则",
        open_questions="人工 Mart 问题",
        confidence_level="medium",
        lineage_status="not_linked",
    )
    business_task = ScenarioBusinessMapping(
        project_id=project.id,
        target_field_id=target_field.id,
        scenario_id=scenario.id,
        business_definition="人工场景业务定义",
        business_confirm_status="draft",
        open_questions="人工业务问题",
        confidence_level="medium",
    )
    db.add_all([mart_task, business_task])
    db.flush()
    technical_task = ScenarioTechnicalLineage(
        project_id=project.id,
        target_field_id=target_field.id,
        scenario_id=scenario.id,
        business_mapping_id=business_task.id,
        source_system_name="LEGACY_SYSTEM",
        source_database_name="LEGACY_DB",
        source_schema_name="LEGACY_SCHEMA",
        source_table_english_name="LEGACY_TABLE",
        source_field_english_name="LEGACY_FIELD",
        processing_logic="人工处理逻辑",
        tech_confirm_status="draft",
        open_questions="人工技术问题",
        confidence_level="medium",
        lineage_status="not_linked",
    )
    db.add(technical_task)
    db.commit()
    for value in (
        project,
        source_task,
        approved_source,
        mart_task,
        business_task,
        technical_task,
    ):
        db.refresh(value)
    return {
        **base,
        "project": project,
        "source_task": source_task,
        "approved_source": approved_source,
        "target_table": target_table,
        "target_field": target_field,
        "scenario": scenario,
        "mart_task": mart_task,
        "business_task": business_task,
        "technical_task": technical_task,
    }
