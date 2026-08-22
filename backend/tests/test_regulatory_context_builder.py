from __future__ import annotations

from copy import deepcopy
from datetime import UTC, date, datetime
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from app.models import (
    BusinessSystem,
    HistoricalCaliberImport,
    HistoricalCaliberItem,
    Institution,
    KnowledgeDocument,
    KnowledgeDocumentVersion,
    KnowledgeUnit,
    LineageEdge,
    LineageNode,
    MappingEvidenceReference,
    MartField,
    MartTable,
    MartToYbtMapping,
    ProductScenario,
    Project,
    RegulatoryKnowledgeItem,
    RetrievalLog,
    ScenarioBusinessMapping,
    ScenarioTechnicalLineage,
    ScriptFile,
    ScriptFileVersion,
    SemanticBinding,
    SemanticConcept,
    SemanticConceptVersion,
    SourceField,
    SourceTable,
    SourceToMartMapping,
    TargetField,
    TargetTable,
)
from app.schemas.regulatory_context import ContextMode, RegulatoryContext, RegulatoryContextRequest
from app.services.auth.dependencies import Principal
from app.services.auth.permission_service import PermissionService
from app.services.semantic import context_builder as context_builder_module
from app.services.semantic.context_authority import AuthorityRank, FactState, authority_for_source
from app.services.semantic.context_builder import RegulatoryContextBuilder
from app.services.embeddings.mock import MockEmbeddingService
from app.services.retrieval.hybrid_retriever import HybridRetriever
from app.services.retrieval.keyword_index import index_knowledge_unit
from app.services.vector.knowledge_record import build_knowledge_vector_record
from app.services.vector.mock import MockVectorStore


AS_OF = date(2026, 6, 30)
ACCEPTANCE_QUERY_BUDGET = 21
SPEC_LESS_REQUIREMENT_METADATA = (
    {"id": "CTX-01", "classification": "unclassified", "resolution": "unresolved"},
    {"id": "CTX-02", "classification": "unclassified", "resolution": "unresolved"},
    {"id": "CTX-03", "classification": "unclassified", "resolution": "unresolved"},
    {"id": "CTX-04", "classification": "unclassified", "resolution": "unresolved"},
)


def test_acceptance_context_build_returns_typed_project_scoped_date_effective_facts(
    db_session: Session,
) -> None:
    fixture = _seed_acceptance_target(db_session)
    project = _authorized_project(db_session, fixture["project_id"])
    request = RegulatoryContextRequest(
        project_id=project.id,
        target_table_id=fixture["target_table_id"],
        target_field_id=fixture["target_field_id"],
        as_of=AS_OF,
        reporting_period=" 2026   H1 ",
    )

    context = RegulatoryContextBuilder(db_session).build(
        request,
        authorized_project=project,
    )

    assert isinstance(context, RegulatoryContext)
    assert context.context_schema_version == "1.0"
    assert context.scope.project_id == project.id
    assert context.scope.institution_id == project.institution_id
    assert context.scope.as_of == AS_OF
    assert context.scope.reporting_period == "2026 H1"
    assert context.target.target_table_code == "2.3"
    assert context.target.target_table_name == "同业客户表"
    assert context.target.target_field_name == "客户统一编号"
    assert [fact.value.semantic_concept_version_id for fact in context.semantic] == [
        fixture["semantic_version_id"]
    ]
    assert context.semantic[0].effective_period.effective_from == date(2026, 1, 1)
    assert context.semantic[0].state is FactState.CONFIRMED
    assert context.metadata
    assert all(fact.authority is authority_for_source(fact.source_type) for fact in _all_facts(context))
    assert context.build_metadata.project_id == project.id
    assert context.build_metadata.input_scope.target_field_id == fixture["target_field_id"]


def test_authorized_project_mismatch_is_rejected_before_collectors(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _seed_acceptance_target(db_session)
    other = _seed_project(db_session, "CTX_BANK_B", "隔离银行 B", "隔离项目 B")
    authorized_project = _authorized_project(db_session, fixture["project_id"])
    collector_called = False

    def fail_if_called(*args: object, **kwargs: object) -> object:
        nonlocal collector_called
        collector_called = True
        raise AssertionError("collector must not run for mismatched project scope")

    monkeypatch.setattr(context_builder_module, "collect_base_context", fail_if_called)

    with pytest.raises(ValueError, match="authorized project"):
        RegulatoryContextBuilder(db_session).build(
            RegulatoryContextRequest(project_id=other.id, as_of=AS_OF),
            authorized_project=authorized_project,
        )

    assert collector_called is False


def test_projection_only_build_preserves_authoritative_rows(db_session: Session) -> None:
    fixture = _seed_acceptance_target(db_session)
    project = _authorized_project(db_session, fixture["project_id"])
    request = RegulatoryContextRequest(
        project_id=project.id,
        target_field_id=fixture["target_field_id"],
        as_of=AS_OF,
    )
    before = _authoritative_snapshot(db_session, project.id)

    RegulatoryContextBuilder(db_session).build(request, authorized_project=project)

    assert _authoritative_snapshot(db_session, project.id) == before


def test_repeat_builds_preserve_domain_content_and_validate_volatile_metadata(
    db_session: Session,
) -> None:
    fixture = _seed_acceptance_target(db_session)
    project = _authorized_project(db_session, fixture["project_id"])
    request = RegulatoryContextRequest(
        project_id=project.id,
        target_table_id=fixture["target_table_id"],
        target_field_id=fixture["target_field_id"],
        semantic_concept_id=fixture["semantic_concept_id"],
        as_of=AS_OF,
        mode=ContextMode.TRUSTED,
    )
    builder = RegulatoryContextBuilder(db_session)

    first = builder.build(request, authorized_project=project)
    second = builder.build(request, authorized_project=project)

    assert _stable_projection(first) == _stable_projection(second)
    for context in (first, second):
        assert context.build_metadata.built_at.tzinfo is not None
        assert context.build_metadata.built_at.utcoffset() is not None
        assert context.build_metadata.retrieval_log_ids == []
        assert context.conflicts == sorted(
            context.conflicts,
            key=lambda item: item.deterministic_sort_key(),
        )
        assert context.open_questions == sorted(
            context.open_questions,
            key=lambda item: item.deterministic_sort_key(),
        )


def test_mapping_lineage_evidence_history_and_knowledge_families_are_aggregated(
    db_session: Session,
) -> None:
    fixture = _seed_populated_context(db_session, suffix="A")
    context = _build_context(db_session, fixture)

    assert {fact.value.mapping_type for fact in context.mappings} == {
        "source_to_mart",
        "mart_to_ybt",
        "scenario_business",
        "scenario_technical",
    }
    assert {
        "SourceToMartMapping",
        "MartToYbtMapping",
        "ScenarioTechnicalLineage",
        "LineageEdge",
    } <= {fact.provenance.source_model for fact in context.lineage}
    assert any(fact.value.evidence_reference_id for fact in context.knowledge_evidence)
    assert any(fact.value.knowledge_unit_id for fact in context.knowledge_evidence)
    assert {fact.source_type for fact in context.regulatory} == {"regulatory_knowledge_item"}
    assert {fact.source_type for fact in context.historical} == {"historical_caliber"}
    assert all(fact.evidence_references for fact in context.mappings)
    assert context.build_metadata.retrieval_log_ids


def test_missing_stale_history_knowledge_evidence_and_conflict_codes_are_deterministic(
    db_session: Session,
) -> None:
    gap = _seed_gap_context(db_session, suffix="GAP")
    gap_context = _build_context(db_session, gap)

    stale = _seed_acceptance_target(db_session, suffix="STALE")
    stale_project = db_session.get(Project, stale["project_id"])
    stale_mart_table = MartTable(
        project_id=stale_project.id,
        table_code="MART_STALE",
        table_name="过期集市表",
    )
    db_session.add(stale_mart_table)
    db_session.flush()
    stale_mart_field = MartField(
        project_id=stale_project.id,
        mart_table_id=stale_mart_table.id,
        field_code="STALE_FIELD",
        field_name="过期字段",
    )
    db_session.add(stale_mart_field)
    db_session.flush()
    db_session.add(SourceToMartMapping(
        project_id=stale_project.id,
        mart_field_id=stale_mart_field.id,
        mapping_name="过期来源映射",
        mapping_status="approved",
        final_content="过期来源口径",
        lineage_status="stale",
        lineage_last_verified_at=datetime(2020, 1, 1, tzinfo=UTC),
    ))
    db_session.commit()
    stale["mart_field_id"] = stale_mart_field.id
    stale_context = _build_context(db_session, stale)

    conflict = _seed_populated_context(db_session, suffix="CONFLICT")
    historical = db_session.get(HistoricalCaliberItem, conflict["historical_item_id"])
    historical.business_content = "与当前确认语义完全矛盾的历史定义"
    db_session.commit()
    conflict_context = _build_context(db_session, conflict)

    emitted_codes = {
        *(item.question_code for item in gap_context.open_questions),
        *(item.code for item in gap_context.conflicts),
        *(item.question_code for item in stale_context.open_questions),
        *(item.code for item in stale_context.conflicts),
        *(item.question_code for item in conflict_context.open_questions),
        *(item.code for item in conflict_context.conflicts),
    }
    assert {
        "MISSING_CONFIRMED_SEMANTIC_BINDING",
        "MISSING_CONFIRMED_SEMANTIC_VERSION",
        "MISSING_SOURCE_MAPPING",
        "MISSING_MART_TO_YBT_MAPPING",
        "MISSING_LINEAGE",
        "STALE_LINEAGE",
        "MISSING_KNOWLEDGE",
        "MISSING_EVIDENCE",
        "HISTORICAL_ONLY_DEFINITION",
        "CONFLICTING_AUTHORITATIVE_FACTS",
    } <= emitted_codes
    for context in (gap_context, stale_context, conflict_context):
        assert context.conflicts == sorted(context.conflicts, key=lambda item: item.deterministic_sort_key())
        assert context.open_questions == sorted(
            context.open_questions,
            key=lambda item: item.deterministic_sort_key(),
        )


def test_source_type_authority_and_knowledge_scope_are_contract_driven(
    db_session: Session,
) -> None:
    fixture = _seed_populated_context(db_session, suffix="SCOPE")
    project = db_session.get(Project, fixture["project_id"])
    other = _seed_project(db_session, "CTX_SCOPE_OTHER", "其他银行", "其他隔离项目")
    db_session.add(RegulatoryKnowledgeItem(
        project_id=other.id,
        knowledge_type="regulatory_qa",
        target_field_code="CUST_UNIFIED_NO",
        target_field_name="客户统一编号",
        regulatory_reply="CROSS_PROJECT_REGULATORY_SECRET",
        source_document_name="cross-project-secret.docx",
    ))
    _seed_knowledge_unit(
        db_session,
        owner_project=other,
        scope="global",
        institution_name=None,
        content="客户统一编号 GLOBAL_VISIBLE_KNOWLEDGE",
        confidentiality="public",
        suffix="GLOBAL",
    )
    _seed_knowledge_unit(
        db_session,
        owner_project=other,
        scope="institution",
        institution_name=project.bank_name,
        content="客户统一编号 INSTITUTION_VISIBLE_KNOWLEDGE",
        confidentiality="confidential",
        suffix="INSTITUTION_VISIBLE",
    )
    _seed_knowledge_unit(
        db_session,
        owner_project=other,
        scope="institution",
        institution_name="其他银行",
        content="客户统一编号 INSTITUTION_HIDDEN_SECRET",
        confidentiality="restricted",
        suffix="INSTITUTION_HIDDEN",
    )
    _seed_knowledge_unit(
        db_session,
        owner_project=other,
        scope="project",
        institution_name=None,
        content="客户统一编号 OTHER_PROJECT_HIDDEN_SECRET",
        confidentiality="restricted",
        suffix="PROJECT_HIDDEN",
    )
    db_session.commit()

    context = _build_context(db_session, fixture)
    payload = json.dumps(context.model_dump(mode="json"), ensure_ascii=False)
    regulatory_fact = context.regulatory[0]
    retrieved = [fact for fact in context.knowledge_evidence if fact.source_type == "retrieved_knowledge"]

    assert all(fact.authority is authority_for_source(fact.source_type) for fact in _all_facts(context))
    assert regulatory_fact.state is FactState.UNVERIFIED
    assert regulatory_fact.source_type == "regulatory_knowledge_item"
    assert "CROSS_PROJECT_REGULATORY_SECRET" not in payload
    assert "GLOBAL_VISIBLE_KNOWLEDGE" in payload
    assert "INSTITUTION_VISIBLE_KNOWLEDGE" not in payload
    assert "INSTITUTION_HIDDEN_SECRET" not in payload
    assert "OTHER_PROJECT_HIDDEN_SECRET" not in payload
    assert retrieved
    for fact in retrieved:
        assert fact.state is FactState.RETRIEVED
        assert fact.provenance.retrieval_log_id in context.build_metadata.retrieval_log_ids
        assert fact.provenance.confidentiality_level == fact.value.confidentiality_level
        assert fact.value.source_file_name
    assert {
        db_session.get(RetrievalLog, log_id).project_id
        for log_id in context.build_metadata.retrieval_log_ids
    } == {project.id}


def test_sensitive_knowledge_does_not_cross_same_name_institution_boundary(
    db_session: Session,
) -> None:
    fixture = _seed_acceptance_target(db_session, suffix="SAME_NAME_SCOPE")
    project = db_session.get(Project, fixture["project_id"])
    other = _seed_project(
        db_session,
        "CTX_SAME_NAME_OTHER",
        project.bank_name,
        "同名但不同机构项目",
    )
    own_unit = _seed_knowledge_unit(
        db_session,
        owner_project=project,
        scope="institution",
        institution_name=project.bank_name,
        content="客户统一编号 OWN_INSTITUTION_VISIBLE",
        confidentiality="restricted",
        suffix="OWN_INSTITUTION",
    )
    foreign_institution = _seed_knowledge_unit(
        db_session,
        owner_project=other,
        scope="institution",
        institution_name=project.bank_name,
        content="客户统一编号 CROSS_TENANT_INSTITUTION_SECRET",
        confidentiality="confidential",
        suffix="FOREIGN_INSTITUTION",
    )
    foreign_restricted = _seed_knowledge_unit(
        db_session,
        owner_project=other,
        scope="global",
        institution_name=None,
        content="客户统一编号 CROSS_TENANT_RESTRICTED_SECRET",
        confidentiality="restricted",
        suffix="FOREIGN_RESTRICTED",
    )
    db_session.commit()

    context = _build_context(db_session, fixture)
    payload = json.dumps(context.model_dump(mode="json"), ensure_ascii=False)
    retrieved_ids = {
        int(fact.source_id)
        for fact in context.knowledge_evidence
        if fact.source_type == "retrieved_knowledge"
    }
    logged_ids = {
        int(unit_id)
        for log_id in context.build_metadata.retrieval_log_ids
        for unit_id in db_session.get(RetrievalLog, log_id).result_ids_json
    }

    assert own_unit.id in retrieved_ids
    assert foreign_institution.id not in retrieved_ids | logged_ids
    assert foreign_restricted.id not in retrieved_ids | logged_ids
    assert "OWN_INSTITUTION_VISIBLE" in payload
    assert "CROSS_TENANT_INSTITUTION_SECRET" not in payload
    assert "CROSS_TENANT_RESTRICTED_SECRET" not in payload
    for fact in context.knowledge_evidence:
        if fact.source_type != "retrieved_knowledge":
            continue
        unit = db_session.get(KnowledgeUnit, fact.source_id)
        owner = db_session.get(Project, unit.project_id)
        if unit.knowledge_scope == "institution" or unit.confidentiality_level == "restricted":
            assert unit.project_id == project.id
            assert fact.provenance.project_id == owner.id == project.id
            assert fact.provenance.institution_id == owner.institution_id == project.institution_id


def test_raw_lineage_verification_uses_only_real_model_predicates(
    db_session: Session,
) -> None:
    fixture = _seed_acceptance_target(db_session)
    project = db_session.get(Project, fixture["project_id"])
    verified_id = _seed_raw_lineage_case(
        db_session,
        project,
        fixture["target_field_id"],
        suffix="VERIFIED",
        created_at=datetime(2000, 1, 1, tzinfo=UTC),
    )
    non_verified_ids = {
        _seed_raw_lineage_case(
            db_session, project, fixture["target_field_id"], suffix="DISABLED_EDGE", edge_enabled=False
        ),
        _seed_raw_lineage_case(
            db_session, project, fixture["target_field_id"], suffix="SOURCE_UNRESOLVED", source_resolved=False
        ),
        _seed_raw_lineage_case(
            db_session, project, fixture["target_field_id"], suffix="TARGET_UNRESOLVED", target_resolved=False
        ),
        _seed_raw_lineage_case(
            db_session, project, fixture["target_field_id"], suffix="MEDIUM", confidence="medium"
        ),
        _seed_raw_lineage_case(
            db_session, project, fixture["target_field_id"], suffix="SCRIPT_DISABLED", script_enabled=False
        ),
        _seed_raw_lineage_case(
            db_session, project, fixture["target_field_id"], suffix="OLD_VERSION", current_version_no=2
        ),
    }
    db_session.commit()

    context = _build_context(db_session, fixture)
    raw_facts = {
        fact.source_id: fact
        for fact in context.lineage
        if fact.provenance.source_model == "LineageEdge"
    }

    assert raw_facts[verified_id].source_type == "verified_lineage"
    assert raw_facts[verified_id].state is FactState.VERIFIED
    assert all(raw_facts[edge_id].state is not FactState.VERIFIED for edge_id in non_verified_ids)
    assert set(raw_facts) == {verified_id, *non_verified_ids}


def test_mapping_and_scenario_lineage_use_persisted_status_fields(
    db_session: Session,
) -> None:
    fixture = _seed_acceptance_target(db_session)
    project = db_session.get(Project, fixture["project_id"])
    mart_table = MartTable(project_id=project.id, table_code="MART_STATUS", table_name="状态集市")
    db_session.add(mart_table)
    db_session.flush()
    mart_field = MartField(
        project_id=project.id,
        mart_table_id=mart_table.id,
        field_code="STATUS_FIELD",
        field_name="状态字段",
    )
    scenario = ProductScenario(
        project_id=project.id,
        scenario_code="STATUS_SCENE",
        scenario_name="状态场景",
        enabled=True,
    )
    linked_scenario = ProductScenario(
        project_id=project.id,
        scenario_code="LINKED_SCENE",
        scenario_name="仅链接状态场景",
        enabled=True,
    )
    db_session.add_all([mart_field, scenario, linked_scenario])
    db_session.flush()
    verified_at = datetime(2026, 4, 1, tzinfo=UTC)
    source_verified = SourceToMartMapping(
        project_id=project.id,
        mart_field_id=mart_field.id,
        mapping_status="approved",
        final_content="已验证来源口径",
        lineage_status="verified",
        lineage_last_verified_at=verified_at,
    )
    source_stale = SourceToMartMapping(
        project_id=project.id,
        mart_field_id=mart_field.id,
        mapping_status="approved",
        final_content="过期来源口径",
        lineage_status="stale",
        lineage_last_verified_at=verified_at,
    )
    mart_verified_without_timestamp = MartToYbtMapping(
        project_id=project.id,
        target_field_id=fixture["target_field_id"],
        mart_field_id=mart_field.id,
        mapping_status="approved",
        final_content="缺时间戳目标口径",
        lineage_status="verified",
        lineage_last_verified_at=None,
    )
    business = ScenarioBusinessMapping(
        project_id=project.id,
        target_field_id=fixture["target_field_id"],
        scenario_id=scenario.id,
        business_definition="已确认业务场景口径",
        final_content="已确认业务场景口径",
        business_confirm_status="confirmed",
        business_confirm_at=verified_at,
    )
    technical_verified = ScenarioTechnicalLineage(
        project_id=project.id,
        target_field_id=fixture["target_field_id"],
        scenario_id=scenario.id,
        business_mapping_id=None,
        processing_logic="已核验场景技术口径",
        final_content="已核验场景技术口径",
        tech_confirm_status="confirmed",
        tech_confirm_at=verified_at,
        lineage_status="verified",
        lineage_last_verified_at=verified_at,
    )
    technical_linked = ScenarioTechnicalLineage(
        project_id=project.id,
        target_field_id=fixture["target_field_id"],
        scenario_id=linked_scenario.id,
        processing_logic="仅链接场景技术口径",
        final_content="仅链接场景技术口径",
        tech_confirm_status="confirmed",
        lineage_status="linked",
        lineage_last_verified_at=verified_at,
    )
    db_session.add_all([
        source_verified,
        source_stale,
        mart_verified_without_timestamp,
        business,
        technical_verified,
        technical_linked,
    ])
    db_session.commit()
    fixture.update({"mart_field_id": mart_field.id, "scenario_id": scenario.id})

    context = _build_context(db_session, fixture)
    linked_fixture = dict(fixture, scenario_id=linked_scenario.id)
    linked_context = _build_context(db_session, linked_fixture)
    mapping_by_source = {
        (fact.provenance.source_model, fact.source_id): fact
        for fact in [*context.mappings, *linked_context.mappings]
    }
    lineage_by_source = {
        (fact.provenance.source_model, fact.source_id): fact
        for fact in [*context.lineage, *linked_context.lineage]
        if fact.provenance.source_model != "LineageEdge"
    }

    assert mapping_by_source[("SourceToMartMapping", source_verified.id)].state is FactState.APPROVED
    assert mapping_by_source[("SourceToMartMapping", source_stale.id)].state is FactState.APPROVED
    assert mapping_by_source[("ScenarioBusinessMapping", business.id)].state is FactState.CONFIRMED
    assert mapping_by_source[("ScenarioTechnicalLineage", technical_linked.id)].state is FactState.CONFIRMED
    assert lineage_by_source[("SourceToMartMapping", source_verified.id)].state is FactState.VERIFIED
    assert lineage_by_source[("SourceToMartMapping", source_stale.id)].state is not FactState.VERIFIED
    assert lineage_by_source[("MartToYbtMapping", mart_verified_without_timestamp.id)].state is not FactState.VERIFIED
    assert lineage_by_source[("ScenarioTechnicalLineage", technical_verified.id)].state is FactState.VERIFIED
    assert lineage_by_source[("ScenarioTechnicalLineage", technical_linked.id)].state is not FactState.VERIFIED
    assert all(key[0] != "ScenarioBusinessMapping" for key in lineage_by_source)
    assert "STALE_LINEAGE" in {item.code for item in context.conflicts}


@pytest.mark.parametrize(
    ("mapping_family", "status"),
    [
        (mapping_family, status)
        for mapping_family in (
            "source_to_mart",
            "mart_to_ybt",
            "scenario_business",
            "scenario_technical",
        )
        for status in ("draft", "ai_suggested", "rejected", "deprecated")
    ],
)
def test_mapping_lifecycle_never_promotes_audit_rows_or_candidates_to_trusted(
    db_session: Session,
    mapping_family: str,
    status: str,
) -> None:
    fixture = _seed_populated_context(
        db_session,
        suffix=f"STATUS_{mapping_family}_{status}",
    )
    model, fixture_key, status_field = {
        "source_to_mart": (SourceToMartMapping, "source_mapping_id", "mapping_status"),
        "mart_to_ybt": (MartToYbtMapping, "mart_mapping_id", "mapping_status"),
        "scenario_business": (
            ScenarioBusinessMapping,
            "business_mapping_id",
            "business_confirm_status",
        ),
        "scenario_technical": (
            ScenarioTechnicalLineage,
            "technical_mapping_id",
            "tech_confirm_status",
        ),
    }[mapping_family]
    row = db_session.get(model, fixture[fixture_key])
    setattr(row, status_field, status)
    db_session.commit()

    trusted = _build_context(db_session, fixture)
    assert not any(
        fact.provenance.source_model == model.__name__
        and fact.provenance.source_id == row.id
        for fact in _all_facts(trusted)
    )

    candidate = _build_context(
        db_session,
        fixture,
        mode=ContextMode.CANDIDATE,
        candidate_limit=100,
    )
    matches = [
        fact
        for fact in candidate.candidates
        if fact.value.candidate_type == mapping_family
        and fact.value.candidate_id == row.id
    ]
    assert not any(
        fact.provenance.source_model == model.__name__
        and fact.provenance.source_id == row.id
        for fact in [
            *candidate.mappings,
            *candidate.lineage,
            *candidate.knowledge_evidence,
        ]
    )
    if status in {"rejected", "deprecated"}:
        assert matches == []
    else:
        assert len(matches) == 1
        assert matches[0].state is (
            FactState.DRAFT if status == "draft" else FactState.AI_SUGGESTED
        )
        assert status in matches[0].value.match_reason


def test_two_project_two_institution_isolation_preserves_authoritative_rows(
    db_session: Session,
) -> None:
    fixture = _seed_populated_context(db_session, suffix="ISOLATION_A")
    other = _seed_populated_context(db_session, suffix="ISOLATION_B_SECRET")
    project = db_session.get(Project, fixture["project_id"])
    before = _expanded_authoritative_snapshot(db_session)

    context = _build_context(db_session, fixture)
    payload = json.dumps(context.model_dump(mode="json"), ensure_ascii=False)

    assert context.scope.project_id == project.id
    assert context.scope.institution_id == project.institution_id
    assert all(fact.provenance.project_id == project.id for fact in _all_facts(context))
    assert all(
        fact.provenance.institution_id in {None, project.institution_id}
        for fact in _all_facts(context)
    )
    assert "ISOLATION_B_SECRET" not in payload
    assert _expanded_authoritative_snapshot(db_session) == before
    assert other["project_id"] != fixture["project_id"]


def test_candidate_ranking_uses_explicit_tiers_and_caps_only_after_full_sort(
    db_session: Session,
) -> None:
    fixture = _seed_candidate_context(db_session)
    expected_tiers = fixture.pop("candidate_tiers")

    full = _build_context(
        db_session,
        fixture,
        mode=ContextMode.CANDIDATE,
        candidate_limit=100,
    )
    source_and_mart = [
        fact for fact in full.candidates
        if fact.value.candidate_type in {"source_field", "mart_field"}
    ]
    actual_tiers = {
        (fact.value.candidate_type, fact.value.candidate_id): fact.value.rank_tier
        for fact in source_and_mart
    }

    assert actual_tiers == expected_tiers
    assert {fact.value.rank_tier for fact in source_and_mart} == set(range(1, 8))
    assert [
        (fact.value.rank_tier, fact.value.candidate_type, fact.value.candidate_id)
        for fact in source_and_mart
    ] == sorted(
        (
            fact.value.rank_tier,
            fact.value.candidate_type,
            fact.value.candidate_id,
        )
        for fact in source_and_mart
    )

    capped = _build_context(
        db_session,
        fixture,
        mode=ContextMode.CANDIDATE,
        candidate_limit=3,
    )
    assert [
        (fact.value.candidate_type, fact.value.candidate_id)
        for fact in capped.candidates
    ] == [
        (fact.value.candidate_type, fact.value.candidate_id)
        for fact in full.candidates[:3]
    ]


def test_spec_less_records_remain_test_metadata_and_never_enter_runtime_output(
    db_session: Session,
) -> None:
    fixture = _seed_populated_context(db_session, suffix="SPEC_LESS")
    context = _build_context(
        db_session,
        fixture,
        mode=ContextMode.CANDIDATE,
    )
    serialized = json.dumps(context.model_dump(mode="json"), ensure_ascii=False)

    assert len(SPEC_LESS_REQUIREMENT_METADATA) == 4
    assert {item["id"] for item in SPEC_LESS_REQUIREMENT_METADATA} == {
        "CTX-01",
        "CTX-02",
        "CTX-03",
        "CTX-04",
    }
    assert all(
        item["classification"] == "unclassified" and item["resolution"] == "unresolved"
        for item in SPEC_LESS_REQUIREMENT_METADATA
    )
    assert all(item["id"] not in serialized for item in SPEC_LESS_REQUIREMENT_METADATA)
    assert all(
        question.question_code not in {item["id"] for item in SPEC_LESS_REQUIREMENT_METADATA}
        for question in context.open_questions
    )
    trusted_states = {FactState.CONFIRMED, FactState.APPROVED, FactState.VERIFIED}
    assert all(
        fact.state not in trusted_states
        for fact in _all_facts(context)
        if fact.authority in {AuthorityRank.RETRIEVED, AuthorityRank.INFERRED}
    )


def test_query_count_is_measured_bounded_and_retriever_get_boundary_is_qualified(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _seed_populated_context(db_session, suffix="QUERY_COUNT")
    engine = db_session.get_bind()

    def measured_build() -> tuple[int, RegulatoryContext]:
        db_session.expire_all()
        project = _authorized_project(db_session, fixture["project_id"])
        request = _request_for_fixture(fixture)
        statement_count = 0

        def before_cursor_execute(*args: object) -> None:
            nonlocal statement_count
            statement_count += 1

        event.listen(engine, "before_cursor_execute", before_cursor_execute)
        try:
            context = RegulatoryContextBuilder(db_session).build(
                request,
                authorized_project=project,
            )
        finally:
            event.remove(engine, "before_cursor_execute", before_cursor_execute)
        return statement_count, context

    baseline_count, baseline = measured_build()
    project = db_session.get(Project, fixture["project_id"])
    for index in range(6):
        db_session.add(SourceToMartMapping(
            project_id=project.id,
            mart_field_id=fixture["mart_field_id"],
            mapping_name=f"等价来源映射 {index}",
            mapping_status="draft",
            final_content=f"等价来源映射内容 {index}",
            lineage_status="linked",
        ))
        _seed_raw_lineage_case(
            db_session,
            project,
            fixture["target_field_id"],
            suffix=f"QUERY_GROWTH_{index}",
        )
        _seed_knowledge_unit(
            db_session,
            owner_project=project,
            scope="project",
            institution_name=None,
            content=f"客户统一编号 CUST_UNIFIED_NO 等价知识 {index}",
            confidentiality="internal",
            suffix=f"QUERY_GROWTH_{index}",
            scenario_id=fixture["scenario_id"],
        )
    db_session.commit()
    authoritative_before_growth_build = _expanded_authoritative_snapshot(db_session)
    growth_count, growth = measured_build()

    assert baseline_count == ACCEPTANCE_QUERY_BUDGET
    assert growth_count <= ACCEPTANCE_QUERY_BUDGET
    assert growth.build_metadata.fact_count > baseline.build_metadata.fact_count
    assert _expanded_authoritative_snapshot(db_session) == authoritative_before_growth_build

    original_get = db_session.get
    knowledge_gets: list[int] = []

    def tracked_get(entity: object, identifier: object, *args: object, **kwargs: object):
        if entity is KnowledgeUnit:
            knowledge_gets.append(int(identifier))
        return original_get(entity, identifier, *args, **kwargs)

    monkeypatch.setattr(db_session, "get", tracked_get)
    _build_context(db_session, fixture)
    assert knowledge_gets == []

    unit = original_get(KnowledgeUnit, fixture["knowledge_unit_id"])
    embedding = MockEmbeddingService()
    vector_store = MockVectorStore()
    vector_store.upsert([build_knowledge_vector_record(unit, embedding.embed_query(unit.content))])
    settings = SimpleNamespace(
        keyword_top_k=500,
        vector_top_k=30,
        hybrid_keyword_weight=0.55,
        hybrid_vector_weight=0.45,
        vector_store_provider="mock",
    )
    monkeypatch.setattr(
        "app.services.retrieval.hybrid_retriever.get_settings",
        lambda: settings,
    )
    monkeypatch.setattr(
        "app.services.retrieval.hybrid_retriever.get_embedding_service",
        lambda: embedding,
    )
    monkeypatch.setattr(
        "app.services.retrieval.hybrid_retriever.get_vector_store",
        lambda *args: vector_store,
    )
    knowledge_gets.clear()
    HybridRetriever(db_session).search(
        fixture["project_id"],
        "客户统一编号",
        target_field_id=fixture["target_field_id"],
        scenario_id=fixture["scenario_id"],
        top_k=5,
        retrieval_mode="vector_only",
    )
    assert knowledge_gets == [fixture["knowledge_unit_id"]]


def test_confidential_deterministic_builds_normalize_only_valid_volatile_metadata(
    db_session: Session,
) -> None:
    fixture = _seed_populated_context(db_session, suffix="DETERMINISTIC")

    first = _build_context(db_session, fixture)
    second = _build_context(db_session, fixture)

    assert _stable_projection(first) == _stable_projection(second)
    assert first.build_metadata.retrieval_log_ids != second.build_metadata.retrieval_log_ids
    for context in (first, second):
        assert context.build_metadata.built_at.tzinfo is not None
        assert context.build_metadata.built_at.utcoffset() is not None
        expected_log_ids = sorted({
            fact.provenance.retrieval_log_id
            for fact in _all_facts(context)
            if fact.provenance.retrieval_log_id is not None
        })
        assert context.build_metadata.retrieval_log_ids == expected_log_ids
        assert all(
            db_session.get(RetrievalLog, log_id).project_id == fixture["project_id"]
            for log_id in expected_log_ids
        )
        retrieved = [
            fact for fact in context.knowledge_evidence
            if fact.source_type == "retrieved_knowledge"
        ]
        assert retrieved
        assert all(
            fact.source_id == fact.provenance.source_id == fact.value.knowledge_unit_id
            for fact in retrieved
        )
        assert all(
            fact.provenance.confidentiality_level == fact.value.confidentiality_level
            for fact in retrieved
        )


def _seed_acceptance_target(db: Session, *, suffix: str = "A") -> dict[str, int]:
    project = _seed_project(
        db,
        f"CTX_BANK_{suffix}",
        f"隔离银行 {suffix}",
        f"监管上下文项目 {suffix}",
    )
    target_table = TargetTable(
        project_id=project.id,
        table_code="2.3",
        table_name="同业客户表",
        description="同业客户监管报送表",
    )
    db.add(target_table)
    db.flush()
    target_field = TargetField(
        project_id=project.id,
        target_table_id=target_table.id,
        field_code="CUST_UNIFIED_NO",
        field_name="客户统一编号",
        field_type="VARCHAR(64)",
        required_flag=True,
        field_definition="全行范围内唯一识别同业客户的编号",
        regulatory_description="报送同业客户唯一标识",
    )
    concept = SemanticConcept(
        project_id=project.id,
        institution_id=project.institution_id,
        concept_type="business_term",
        concept_code="CUST_UNIFIED_NO",
        concept_name="客户统一编号",
        definition="全行客户唯一标识",
        status="confirmed",
        confidence_level="high",
        confirmed_by="reviewer",
        confirmed_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    db.add_all([target_field, concept])
    db.flush()
    version = SemanticConceptVersion(
        semantic_concept_id=concept.id,
        project_id=project.id,
        institution_id=project.institution_id,
        version_no=1,
        concept_name="客户统一编号",
        definition="全行客户唯一标识",
        aliases_json=["统一客户号"],
        status="confirmed",
        confidence_level="high",
        confirmed_by="reviewer",
        confirmed_at=datetime(2026, 1, 1, tzinfo=UTC),
        effective_from=date(2026, 1, 1),
        effective_to=date(2026, 12, 31),
    )
    binding = SemanticBinding(
        project_id=project.id,
        institution_id=project.institution_id,
        semantic_concept_id=concept.id,
        entity_type="target_field",
        entity_id=target_field.id,
        binding_type="represents",
        confidence_level="high",
        confidence_score=1.0,
        status="confirmed",
        confirmed_by="reviewer",
        confirmed_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    db.add_all([version, binding])
    db.commit()
    return {
        "project_id": project.id,
        "target_table_id": target_table.id,
        "target_field_id": target_field.id,
        "semantic_concept_id": concept.id,
        "semantic_version_id": version.id,
    }


def _seed_populated_context(db: Session, *, suffix: str) -> dict[str, int]:
    fixture = _seed_acceptance_target(db, suffix=suffix)
    project = db.get(Project, fixture["project_id"])
    target_field = db.get(TargetField, fixture["target_field_id"])
    target_table = db.get(TargetTable, fixture["target_table_id"])
    marker = suffix.upper()
    mart_table = MartTable(
        project_id=project.id,
        table_code=f"MART_{marker}",
        table_name=f"监管集市表 {marker}",
    )
    scenario = ProductScenario(
        project_id=project.id,
        scenario_code=f"SCENARIO_{marker}",
        scenario_name=f"监管场景 {marker}",
        scenario_type="regulatory_reporting",
        enabled=True,
    )
    db.add_all([mart_table, scenario])
    db.flush()
    mart_field = MartField(
        project_id=project.id,
        mart_table_id=mart_table.id,
        field_code=target_field.field_code,
        field_name=f"集市客户统一编号 {marker}",
        field_type="VARCHAR(64)",
        description=f"集市客户统一标识 {marker}",
    )
    db.add(mart_field)
    db.flush()
    verified_at = datetime(2026, 5, 1, tzinfo=UTC)
    source_mapping = SourceToMartMapping(
        project_id=project.id,
        mart_field_id=mart_field.id,
        mapping_name=f"来源到集市 {marker}",
        mapping_status="approved",
        business_rule="取客户主数据统一编号",
        final_content="来源系统客户编号映射到集市客户统一编号",
        confidence_level="high",
        lineage_status="verified",
        lineage_last_verified_at=verified_at,
    )
    mart_mapping = MartToYbtMapping(
        project_id=project.id,
        target_field_id=target_field.id,
        mart_field_id=mart_field.id,
        mapping_name=f"集市到一表通 {marker}",
        mapping_status="approved",
        business_rule="直接报送统一编号",
        final_content="集市客户统一编号直接报送",
        confidence_level="high",
        lineage_status="verified",
        lineage_last_verified_at=verified_at,
    )
    business_mapping = ScenarioBusinessMapping(
        project_id=project.id,
        target_field_id=target_field.id,
        scenario_id=scenario.id,
        business_definition="客户唯一编号在监管场景下保持全行唯一",
        final_content="客户唯一编号在监管场景下保持全行唯一",
        business_confirm_status="confirmed",
        business_confirm_at=verified_at,
        confidence_level="high",
    )
    technical_mapping = ScenarioTechnicalLineage(
        project_id=project.id,
        target_field_id=target_field.id,
        scenario_id=scenario.id,
        source_system_name=f"ECIF_{marker}",
        source_database_name="BANK_DB",
        source_schema_name="ODS",
        source_table_english_name="CUSTOMER",
        source_field_english_name="CUST_UNIFIED_NO",
        processing_logic="直接映射客户统一编号",
        final_content="ODS.CUSTOMER.CUST_UNIFIED_NO",
        tech_confirm_status="confirmed",
        tech_confirm_at=verified_at,
        confidence_level="high",
        lineage_status="verified",
        lineage_last_verified_at=verified_at,
    )
    db.add_all([source_mapping, mart_mapping, business_mapping, technical_mapping])
    db.flush()
    for mapping_type, mapping in (
        ("source_to_mart", source_mapping),
        ("mart_to_ybt", mart_mapping),
        ("scenario_business", business_mapping),
        ("scenario_technical", technical_mapping),
    ):
        db.add(MappingEvidenceReference(
            project_id=project.id,
            mapping_type=mapping_type,
            mapping_id=mapping.id,
            evidence_type="manual_note",
            source_name=f"治理评审记录 {marker}",
            location_text=f"review/{marker}/{mapping_type}",
            quoted_content="映射已由业务与技术共同核验",
            evidence_summary="人工核验映射来源和转换规则",
        ))
    raw_lineage_id = _seed_raw_lineage_case(
        db,
        project,
        target_field.id,
        suffix=f"POPULATED_{marker}",
    )
    regulatory = RegulatoryKnowledgeItem(
        project_id=project.id,
        knowledge_type="regulatory_qa",
        target_table_code=target_table.table_code,
        target_field_code=target_field.field_code,
        target_field_name=target_field.field_name,
        scenario_id=scenario.id,
        question_text="客户统一编号如何填报",
        regulatory_reply="客户统一编号应在全行范围唯一",
        source_document_name=f"监管答疑_{marker}.docx",
        source_sheet_name="答疑",
        source_cell_range="A2:B2",
    )
    db.add(regulatory)
    knowledge_unit = _seed_knowledge_unit(
        db,
        owner_project=project,
        scope="project",
        institution_name=None,
        content=f"客户统一编号 CUST_UNIFIED_NO 来源字段规则 {marker}",
        confidentiality="confidential",
        suffix=f"PROJECT_{marker}",
        scenario_id=scenario.id,
    )
    historical_import = HistoricalCaliberImport(
        institution_id=project.institution_id,
        project_id=project.id,
        stored_file_id=1,
        import_name=f"历史口径 {marker}",
        document_type="full_package",
        status="parsed",
    )
    db.add(historical_import)
    db.flush()
    historical = HistoricalCaliberItem(
        project_id=project.id,
        historical_import_id=historical_import.id,
        target_table_code=target_table.table_code,
        target_field_code=target_field.field_code,
        target_field_name=target_field.field_name,
        scenario_name=scenario.scenario_name,
        business_content="全行客户唯一标识",
        technical_content="历史来源 ODS.CUSTOMER.CUST_UNIFIED_NO",
        source_system_name=f"ECIF_{marker}",
        source_table_name="CUSTOMER",
        source_field_name="CUST_UNIFIED_NO",
        source_sheet_name="历史口径",
        source_cell_range="A2:Z2",
        content_hash=(marker.lower() + "0" * 64)[:64],
        match_status="matched",
        matched_target_field_id=target_field.id,
        matched_scenario_id=scenario.id,
    )
    db.add(historical)
    db.commit()
    fixture.update({
        "mart_field_id": mart_field.id,
        "scenario_id": scenario.id,
        "source_mapping_id": source_mapping.id,
        "mart_mapping_id": mart_mapping.id,
        "business_mapping_id": business_mapping.id,
        "technical_mapping_id": technical_mapping.id,
        "raw_lineage_id": raw_lineage_id,
        "regulatory_item_id": regulatory.id,
        "knowledge_unit_id": knowledge_unit.id,
        "historical_item_id": historical.id,
    })
    return fixture


def _seed_candidate_context(db: Session) -> dict:
    fixture = _seed_populated_context(db, suffix="CANDIDATE")
    project = db.get(Project, fixture["project_id"])
    system = BusinessSystem(
        project_id=project.id,
        system_code="CANDIDATE_SYS",
        system_name="候选来源系统",
        enabled=True,
    )
    db.add(system)
    db.flush()
    source_table = SourceTable(
        project_id=project.id,
        business_system_id=system.id,
        table_code="CANDIDATE_TABLE",
        table_name="候选来源表",
    )
    db.add(source_table)
    db.flush()

    def source_field(code: str, name: str, comment: str | None = None) -> SourceField:
        row = SourceField(
            project_id=project.id,
            source_table_id=source_table.id,
            field_code=code,
            field_name=name,
            field_comment=comment,
        )
        db.add(row)
        db.flush()
        return row

    bound = source_field("BOUND_ONLY", "绑定候选")
    exact = source_field("CUST_UNIFIED_NO", "代码精确候选")
    semantic_evidence = source_field("SEMANTIC_EVIDENCE_ONLY", "语义证据候选")
    metadata_keyword = source_field(
        "METADATA_ONLY",
        "元数据候选",
        "客户唯一标识补充来源",
    )
    historical = source_field("HISTORY_ONLY", "历史候选")
    lineage = source_field("LINEAGE_ONLY", "血缘候选")
    retrieval = source_field("RETRIEVAL_ONLY", "检索候选")
    db.add(SemanticBinding(
        project_id=project.id,
        institution_id=project.institution_id,
        semantic_concept_id=fixture["semantic_concept_id"],
        entity_type="source_field",
        entity_id=bound.id,
        binding_type="represents",
        confidence_level="high",
        confidence_score=1.0,
        status="confirmed",
        confirmed_by="candidate-reviewer",
        confirmed_at=datetime(2026, 1, 1, tzinfo=UTC),
    ))
    db.add(MappingEvidenceReference(
        project_id=project.id,
        mapping_type="source_to_mart",
        mapping_id=fixture["source_mapping_id"],
        evidence_type="source_field",
        evidence_id=semantic_evidence.id,
        source_name="候选字段语义评审",
        location_text="candidate/source-field",
        evidence_summary="字段被映射证据引用",
    ))
    historical_item = db.get(HistoricalCaliberItem, fixture["historical_item_id"])
    historical_item.source_field_name = historical.field_code
    lineage_edge = _seed_raw_lineage_case(
        db,
        project,
        fixture["target_field_id"],
        suffix="CANDIDATE_NEIGHBOR",
    )
    edge = db.get(LineageEdge, lineage_edge)
    db.get(LineageNode, edge.source_node_id).source_field_id = lineage.id
    _seed_knowledge_unit(
        db,
        owner_project=project,
        scope="project",
        institution_name=None,
        content="客户统一编号 CUST_UNIFIED_NO 检索证据 RETRIEVAL_ONLY",
        confidentiality="internal",
        suffix="CANDIDATE_RETRIEVAL",
        scenario_id=fixture["scenario_id"],
    )
    db.commit()
    fixture["candidate_tiers"] = {
        ("mart_field", fixture["mart_field_id"]): 1,
        ("source_field", bound.id): 1,
        ("source_field", exact.id): 2,
        ("source_field", semantic_evidence.id): 3,
        ("source_field", metadata_keyword.id): 4,
        ("source_field", historical.id): 5,
        ("source_field", lineage.id): 6,
        ("source_field", retrieval.id): 7,
    }
    return fixture


def _seed_gap_context(db: Session, *, suffix: str) -> dict[str, int]:
    project = _seed_project(db, f"CTX_{suffix}", f"缺口银行 {suffix}", f"缺口项目 {suffix}")
    target_table = TargetTable(
        project_id=project.id,
        table_code=f"GAP_TABLE_{suffix}",
        table_name=f"缺口报表 {suffix}",
    )
    db.add(target_table)
    db.flush()
    target_field = TargetField(
        project_id=project.id,
        target_table_id=target_table.id,
        field_code=f"GAP_FIELD_{suffix}",
        field_name=f"缺口字段 {suffix}",
        field_definition="当前未形成确认语义",
    )
    db.add(target_field)
    db.flush()
    historical_import = HistoricalCaliberImport(
        institution_id=project.institution_id,
        project_id=project.id,
        stored_file_id=1,
        import_name=f"仅历史口径 {suffix}",
        document_type="business_traceability",
        status="parsed",
    )
    db.add(historical_import)
    db.flush()
    historical = HistoricalCaliberItem(
        project_id=project.id,
        historical_import_id=historical_import.id,
        target_table_code=target_table.table_code,
        target_field_code=target_field.field_code,
        target_field_name=target_field.field_name,
        business_content="仅有历史定义",
        source_sheet_name="历史",
        source_cell_range="A1:B2",
        content_hash=(suffix.lower() + "f" * 64)[:64],
        match_status="matched",
        matched_target_field_id=target_field.id,
    )
    db.add(historical)
    db.commit()
    return {
        "project_id": project.id,
        "target_table_id": target_table.id,
        "target_field_id": target_field.id,
        "historical_item_id": historical.id,
    }


def _seed_knowledge_unit(
    db: Session,
    *,
    owner_project: Project,
    scope: str,
    institution_name: str | None,
    content: str,
    confidentiality: str,
    suffix: str,
    scenario_id: int | None = None,
) -> KnowledgeUnit:
    document = KnowledgeDocument(
        project_id=owner_project.id,
        file_name=f"knowledge_{suffix}.md",
        file_type="md",
        source_type="upload",
        storage_path=f"knowledge/{suffix}.md",
        knowledge_type="manual_note",
        knowledge_scope=scope,
        institution_name=institution_name,
        document_status="indexed",
        confidentiality_level=confidentiality,
        current_version_no=1,
    )
    db.add(document)
    db.flush()
    version = KnowledgeDocumentVersion(
        project_id=owner_project.id,
        document_id=document.id,
        version_no=1,
        file_name=document.file_name,
        storage_path=document.storage_path,
        file_hash=(suffix.lower() + "d" * 64)[:64],
        parse_status="parsed",
    )
    db.add(version)
    db.flush()
    unit = KnowledgeUnit(
        project_id=owner_project.id,
        document_id=document.id,
        document_version_id=version.id,
        knowledge_type="manual_note",
        knowledge_scope=scope,
        institution_name=institution_name,
        unit_type="paragraph",
        title=f"客户统一编号知识 {suffix}",
        content=content,
        normalized_content=content.lower(),
        source_file_name=document.file_name,
        source_sheet_name="知识页",
        source_cell_range="A1:B3",
        target_table_code="2.3",
        target_field_code="CUST_UNIFIED_NO",
        target_field_name="客户统一编号",
        scenario_id=scenario_id,
        confidentiality_level=confidentiality,
        enabled=True,
        content_hash=(suffix.lower() + "c" * 64)[:64],
    )
    db.add(unit)
    db.flush()
    index_knowledge_unit(db, unit)
    return unit


def _seed_raw_lineage_case(
    db: Session,
    project: Project,
    target_field_id: int,
    *,
    suffix: str,
    edge_enabled: bool = True,
    source_resolved: bool = True,
    target_resolved: bool = True,
    confidence: str = "high",
    script_enabled: bool = True,
    current_version_no: int = 1,
    created_at: datetime | None = None,
) -> int:
    script = ScriptFile(
        institution_id=project.institution_id,
        project_id=project.id,
        relative_path=f"etl/{suffix}.sql",
        file_name=f"{suffix}.sql",
        file_type="sql",
        logical_target_name="CUST_UNIFIED_NO",
        enabled=script_enabled,
        current_version_no=current_version_no,
    )
    db.add(script)
    db.flush()
    version = ScriptFileVersion(
        project_id=project.id,
        script_file_id=script.id,
        version_no=1,
        file_hash=(suffix.lower() + "1" * 64)[:64],
        normalized_hash=(suffix.lower() + "2" * 64)[:64],
        raw_content_storage_file_id=1,
        parse_status="parsed",
    )
    db.add(version)
    db.flush()
    source = LineageNode(
        institution_id=project.institution_id,
        project_id=project.id,
        node_type="source_field",
        logical_name=f"ODS.CUSTOMER.{suffix}",
        schema_name="ODS",
        table_name="CUSTOMER",
        column_name=suffix,
        unresolved_flag=not source_resolved,
    )
    target = LineageNode(
        institution_id=project.institution_id,
        project_id=project.id,
        node_type="target_field",
        logical_name=f"YBT.CUST_UNIFIED_NO.{suffix}",
        table_name="2.3",
        column_name="CUST_UNIFIED_NO",
        target_field_id=target_field_id,
        unresolved_flag=not target_resolved,
    )
    db.add_all([source, target])
    db.flush()
    edge = LineageEdge(
        institution_id=project.institution_id,
        project_id=project.id,
        script_file_version_id=version.id,
        source_node_id=source.id,
        target_node_id=target.id,
        edge_type="column_lineage",
        transformation_type="direct",
        transformation_expression=f"{suffix}_EXPR",
        confidence_level=confidence,
        enabled=edge_enabled,
        created_at=created_at,
        updated_at=created_at,
    )
    db.add(edge)
    db.flush()
    return edge.id


def _request_for_fixture(
    fixture: dict,
    *,
    mode: ContextMode = ContextMode.TRUSTED,
    candidate_limit: int = 50,
) -> RegulatoryContextRequest:
    return RegulatoryContextRequest(
        project_id=fixture["project_id"],
        target_table_id=fixture.get("target_table_id"),
        target_field_id=fixture.get("target_field_id"),
        mart_field_id=fixture.get("mart_field_id"),
        semantic_concept_id=fixture.get("semantic_concept_id"),
        scenario_id=fixture.get("scenario_id"),
        as_of=AS_OF,
        mode=mode,
        candidate_limit=candidate_limit,
    )


def _build_context(
    db: Session,
    fixture: dict,
    *,
    mode: ContextMode = ContextMode.TRUSTED,
    candidate_limit: int = 50,
) -> RegulatoryContext:
    project = _authorized_project(db, fixture["project_id"])
    return RegulatoryContextBuilder(db).build(
        _request_for_fixture(
            fixture,
            mode=mode,
            candidate_limit=candidate_limit,
        ),
        authorized_project=project,
    )


def _seed_project(db: Session, code: str, bank_name: str, project_name: str) -> Project:
    institution = Institution(institution_code=code, institution_name=bank_name)
    db.add(institution)
    db.flush()
    project = Project(
        name=project_name,
        bank_name=bank_name,
        institution_id=institution.id,
    )
    db.add(project)
    db.flush()
    return project


def _authorized_project(db: Session, project_id: int) -> Project:
    principal = Principal(None, "legacy-system", "Legacy development mode", True)
    return PermissionService(db, principal).require_project_permission(project_id, "project.view")


def _all_facts(context: RegulatoryContext) -> list:
    return [
        *context.semantic,
        *context.regulatory,
        *context.metadata,
        *context.candidates,
        *context.mappings,
        *context.lineage,
        *context.knowledge_evidence,
        *context.historical,
        *context.quality,
    ]


def _authoritative_snapshot(db: Session, project_id: int) -> tuple[tuple[str, int], ...]:
    models = (TargetField, SemanticConcept, SemanticConceptVersion, SemanticBinding)
    return tuple(
        (model.__tablename__, int(db.scalar(select(func.count()).select_from(model).where(model.project_id == project_id))))
        for model in models
    )


def _expanded_authoritative_snapshot(db: Session) -> tuple[tuple[str, tuple], ...]:
    specifications = (
        (SemanticConcept, ("status", "confirmed_at", "updated_at")),
        (SemanticConceptVersion, ("status", "effective_from", "effective_to", "updated_at")),
        (SemanticBinding, ("status", "confirmed_at", "updated_at")),
        (SourceToMartMapping, ("mapping_status", "lineage_status", "lineage_last_verified_at", "updated_at")),
        (MartToYbtMapping, ("mapping_status", "lineage_status", "lineage_last_verified_at", "updated_at")),
        (ScenarioBusinessMapping, ("business_confirm_status", "business_confirm_at", "updated_at")),
        (ScenarioTechnicalLineage, ("tech_confirm_status", "lineage_status", "lineage_last_verified_at", "updated_at")),
        (RegulatoryKnowledgeItem, ("updated_at",)),
        (HistoricalCaliberItem, ("match_status", "created_at")),
    )
    snapshot: list[tuple[str, tuple]] = []
    for model, attributes in specifications:
        rows = list(db.scalars(select(model).order_by(model.id)).all())
        snapshot.append((
            model.__tablename__,
            tuple(
                (row.id, row.project_id, *(getattr(row, attribute) for attribute in attributes))
                for row in rows
            ),
        ))
    return tuple(snapshot)


def _stable_projection(context: RegulatoryContext) -> dict:
    payload = deepcopy(context.model_dump(mode="json"))
    payload["build_metadata"]["built_at"] = "<volatile-built-at>"
    payload["build_metadata"]["retrieval_log_ids"] = ["<volatile-retrieval-log-id>"] * len(
        payload["build_metadata"]["retrieval_log_ids"]
    )
    for section in (
        "semantic",
        "regulatory",
        "metadata",
        "candidates",
        "mappings",
        "lineage",
        "knowledge_evidence",
        "historical",
        "quality",
    ):
        for fact in payload[section]:
            if fact["provenance"]["retrieval_log_id"] is not None:
                fact["provenance"]["retrieval_log_id"] = "<volatile-retrieval-log-id>"
    return payload
