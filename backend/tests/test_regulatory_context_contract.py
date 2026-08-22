from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from app.schemas.regulatory_context import (
    CandidateContextValue,
    ContextAttribute,
    ContextBuildMetadata,
    ContextConflict,
    ContextEvidenceReference,
    ContextFact,
    ContextMode,
    ContextOpenQuestion,
    ContextProvenance,
    ContextScope,
    ContextTarget,
    EffectivePeriod,
    HistoricalContextValue,
    KnowledgeEvidenceContextValue,
    LineageContextValue,
    MappingContextValue,
    MetadataContextValue,
    QualityContextValue,
    RegulatoryContext,
    RegulatoryContextRequest,
    RegulatoryContextValue,
    SemanticContextValue,
)
from app.models import TargetField
from app.services.semantic.context_authority import (
    AuthorityRank,
    FactState,
    authority_for_source,
    compare_authority,
    is_confirmed_state,
)


SPECLESS_EDGE_PROBE_METADATA = tuple(
    {
        "requirement_id": requirement_id,
        "classification": "unclassified",
        "resolution_state": "unresolved",
    }
    for requirement_id in ("CTX-01", "CTX-02", "CTX-03", "CTX-04")
)


def _empty_context() -> RegulatoryContext:
    return RegulatoryContext(
        scope=ContextScope(
            project_id=7,
            institution_id=3,
            as_of=date(2026, 12, 31),
            reporting_period="2026 Q4",
            mode=ContextMode.TRUSTED,
        ),
        target=ContextTarget(
            target_table_id=23,
            target_field_id=47,
            target_table_code="2.3",
            target_table_name="同业客户表",
            target_field_code="CUST_UNIFIED_NO",
            target_field_name="客户统一编号",
        ),
        build_metadata=ContextBuildMetadata(
            built_at=datetime(2026, 12, 31, 8, 30, tzinfo=UTC),
            mode=ContextMode.TRUSTED,
            fact_count=0,
            conflict_count=0,
            open_question_count=0,
            source_count=0,
        ),
    )


def _semantic_fact(
    *,
    authority: AuthorityRank = AuthorityRank.SEMANTIC,
    state: FactState = FactState.CONFIRMED,
) -> ContextFact:
    evidence = ContextEvidenceReference(
        evidence_type="semantic_version",
        evidence_id=91,
        citation="SemanticConceptVersion 91",
        source_location="semantic_concept_versions/91",
    )
    effective_period = EffectivePeriod(
        effective_from=date(2026, 1, 1),
        effective_to=date(2026, 12, 31),
    )
    observed_at = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)
    provenance = ContextProvenance(
        project_id=7,
        institution_id=3,
        source_model="SemanticConceptVersion",
        source_type="semantic_concept_version",
        source_id=91,
        evidence_references=[evidence],
        version_no=2,
        effective_period=effective_period,
        observed_at=observed_at,
        retrieval_log_id=(401 if authority is AuthorityRank.RETRIEVED or state is FactState.RETRIEVED else None),
        confidentiality_level="internal",
    )
    return ContextFact(
        fact_type="semantic_definition",
        value=SemanticContextValue(
            semantic_concept_id=12,
            semantic_concept_version_id=91,
            concept_type="business_term",
            concept_code="CUST_UNIFIED_NO",
            concept_name="客户统一编号",
            definition="银行内唯一识别同一客户的稳定编号。",
            aliases=["统一客户号"],
        ),
        authority=authority,
        state=state,
        source_type="semantic_concept_version",
        source_id=91,
        evidence_references=[evidence],
        version_no=2,
        effective_period=effective_period,
        observed_at=observed_at,
        confidence=0.98,
        provenance=provenance,
    )


def test_schema_version_normalized_scope_and_deterministic_json_round_trip() -> None:
    request = RegulatoryContextRequest(
        project_id=7,
        target_table_id=23,
        target_field_id=47,
        as_of=datetime(2026, 12, 31, 23, 59, tzinfo=UTC),
        reporting_period="  2026   Q4  ",
        mode="trusted",
    )
    assert request.as_of == date(2026, 12, 31)
    assert request.reporting_period == "2026 Q4"

    context = _empty_context()
    first = context.model_dump(mode="json")
    second = RegulatoryContext.model_validate_json(context.model_dump_json()).model_dump(mode="json")

    assert first == second
    assert first["context_schema_version"] == "1.0"
    assert list(first) == [
        "context_schema_version",
        "scope",
        "target",
        "scenario",
        "semantic",
        "regulatory",
        "metadata",
        "candidates",
        "mappings",
        "lineage",
        "knowledge_evidence",
        "historical",
        "quality",
        "conflicts",
        "open_questions",
        "build_metadata",
    ]
    assert first["scope"]["as_of"] == "2026-12-31"
    assert first["scope"]["reporting_period"] == "2026 Q4"
    assert first["scenario"] is None
    assert all(first[section] == [] for section in (
        "semantic",
        "regulatory",
        "metadata",
        "candidates",
        "mappings",
        "lineage",
        "knowledge_evidence",
        "historical",
        "quality",
        "conflicts",
        "open_questions",
    ))

    with pytest.raises(ValidationError):
        RegulatoryContextRequest(
            project_id=7,
            institution_id=999,
            as_of=date(2026, 12, 31),
        )


def test_fact_serializes_typed_value_authority_state_and_provenance_fields() -> None:
    fact = _semantic_fact()
    payload = fact.model_dump(mode="json")

    assert payload == {
        "fact_type": "semantic_definition",
        "value": {
            "kind": "semantic",
            "semantic_concept_id": 12,
            "semantic_concept_version_id": 91,
            "concept_type": "business_term",
            "concept_code": "CUST_UNIFIED_NO",
            "concept_name": "客户统一编号",
            "definition": "银行内唯一识别同一客户的稳定编号。",
            "aliases": ["统一客户号"],
            "business_domain": None,
        },
        "authority": "semantic",
        "state": "confirmed",
        "source_type": "semantic_concept_version",
        "source_id": 91,
        "evidence_references": [
            {
                "evidence_type": "semantic_version",
                "evidence_id": 91,
                "citation": "SemanticConceptVersion 91",
                "source_location": "semantic_concept_versions/91",
            }
        ],
        "version_no": 2,
        "effective_period": {
            "effective_from": "2026-01-01",
            "effective_to": "2026-12-31",
        },
        "observed_at": "2026-08-22T12:00:00Z",
        "confidence": 0.98,
        "provenance": {
            "project_id": 7,
            "institution_id": 3,
            "source_model": "SemanticConceptVersion",
            "source_type": "semantic_concept_version",
            "source_id": 91,
            "evidence_references": [
                {
                    "evidence_type": "semantic_version",
                    "evidence_id": 91,
                    "citation": "SemanticConceptVersion 91",
                    "source_location": "semantic_concept_versions/91",
                }
            ],
            "version_no": 2,
            "effective_period": {
                "effective_from": "2026-01-01",
                "effective_to": "2026-12-31",
            },
            "observed_at": "2026-08-22T12:00:00Z",
            "retrieval_log_id": None,
            "confidentiality_level": "internal",
        },
    }
    assert ContextFact.model_validate_json(fact.model_dump_json()) == fact


def test_authority_order_is_code_defined_without_mutating_fact_state() -> None:
    assert compare_authority(AuthorityRank.FORMAL, AuthorityRank.HUMAN_CONFIRMED) == 0
    expected_order = (
        AuthorityRank.HUMAN_CONFIRMED,
        AuthorityRank.REGULATORY,
        AuthorityRank.SEMANTIC,
        AuthorityRank.MAPPING,
        AuthorityRank.LINEAGE,
        AuthorityRank.METADATA,
        AuthorityRank.HISTORICAL,
        AuthorityRank.RETRIEVED,
        AuthorityRank.INFERRED,
    )
    for higher, lower in zip(expected_order, expected_order[1:]):
        assert compare_authority(higher, lower) == 1
        assert compare_authority(lower, higher) == -1
    assert authority_for_source("formal_regulation") is AuthorityRank.FORMAL
    assert authority_for_source("semantic_concept_version") is AuthorityRank.SEMANTIC
    assert authority_for_source("approved_mapping") is AuthorityRank.MAPPING
    assert authority_for_source("verified_lineage") is AuthorityRank.LINEAGE
    assert authority_for_source("retrieved_knowledge") is AuthorityRank.RETRIEVED
    assert authority_for_source("ai_inference") is AuthorityRank.INFERRED
    assert is_confirmed_state(FactState.CONFIRMED)
    assert not is_confirmed_state(FactState.RETRIEVED)

    retrieved = _semantic_fact(authority=AuthorityRank.RETRIEVED, state=FactState.RETRIEVED)
    assert retrieved.authority is AuthorityRank.RETRIEVED
    assert retrieved.state is FactState.RETRIEVED
    with pytest.raises(ValidationError):
        _semantic_fact(authority=AuthorityRank.RETRIEVED, state=FactState.CONFIRMED)


def test_spec_less_edge_metadata_is_planning_only_and_not_product_output() -> None:
    assert SPECLESS_EDGE_PROBE_METADATA == (
        {"requirement_id": "CTX-01", "classification": "unclassified", "resolution_state": "unresolved"},
        {"requirement_id": "CTX-02", "classification": "unclassified", "resolution_state": "unresolved"},
        {"requirement_id": "CTX-03", "classification": "unclassified", "resolution_state": "unresolved"},
        {"requirement_id": "CTX-04", "classification": "unclassified", "resolution_state": "unresolved"},
    )
    serialized = _empty_context().model_dump_json()
    assert _empty_context().open_questions == []
    assert all(record["requirement_id"] not in serialized for record in SPECLESS_EDGE_PROBE_METADATA)


def _fact_for_value(
    value,
    *,
    authority: AuthorityRank,
    state: FactState,
    source_type: str,
    source_id: int,
    project_id: int = 7,
    institution_id: int | None = 3,
    retrieval_log_id: int | None = None,
    confidentiality_level: str | None = None,
) -> ContextFact:
    value_kind = value.get("kind", "metadata") if isinstance(value, dict) else getattr(value, "kind", "metadata")
    evidence = ContextEvidenceReference(
        evidence_type=source_type,
        evidence_id=source_id,
        citation=f"{source_type}:{source_id}",
    )
    observed_at = datetime(2026, 8, 22, 13, 0, tzinfo=UTC)
    provenance = ContextProvenance(
        project_id=project_id,
        institution_id=institution_id,
        source_model="TestSource",
        source_type=source_type,
        source_id=source_id,
        evidence_references=[evidence],
        observed_at=observed_at,
        retrieval_log_id=retrieval_log_id,
        confidentiality_level=confidentiality_level,
    )
    return ContextFact(
        fact_type=f"{value_kind}_fact",
        value=value,
        authority=authority,
        state=state,
        source_type=source_type,
        source_id=source_id,
        evidence_references=[evidence],
        observed_at=observed_at,
        confidence=0.8,
        provenance=provenance,
    )


def test_all_section_values_are_bounded_and_reject_orm_or_arbitrary_nested_data() -> None:
    semantic = _semantic_fact()
    regulatory = _fact_for_value(
        RegulatoryContextValue(
            regulatory_source_id=5,
            regulation_code="CBIRC-001",
            title="监管口径",
            requirement_text="客户统一编号必须稳定识别同一客户。",
            target_field_id=47,
        ),
        authority=AuthorityRank.REGULATORY,
        state=FactState.CONFIRMED,
        source_type="regulatory_knowledge_item",
        source_id=5,
    )
    metadata = _fact_for_value(
        MetadataContextValue(
            entity_type="target_field",
            entity_id=47,
            code="CUST_UNIFIED_NO",
            name="客户统一编号",
            attributes=[ContextAttribute(name="required", value=True)],
        ),
        authority=AuthorityRank.METADATA,
        state=FactState.OBSERVED,
        source_type="target_metadata",
        source_id=47,
    )
    candidate = _fact_for_value(
        CandidateContextValue(
            candidate_type="source_field",
            candidate_id=81,
            code="CUST_NO",
            name="客户号",
            match_reason="exact_code",
            score=0.92,
            rank_tier=2,
        ),
        authority=AuthorityRank.INFERRED,
        state=FactState.AI_SUGGESTED,
        source_type="ai_inference",
        source_id=81,
    )
    mapping = _fact_for_value(
        MappingContextValue(
            mapping_type="source_to_mart",
            mapping_id=101,
            source_entity_ids=[81],
            target_entity_ids=[61],
            mapping_status="approved",
            rule_text="trim(CUST_NO)",
        ),
        authority=AuthorityRank.MAPPING,
        state=FactState.APPROVED,
        source_type="approved_mapping",
        source_id=101,
    )
    lineage = _fact_for_value(
        LineageContextValue(
            lineage_edge_id=201,
            source_entity_type="source_field",
            source_entity_id=81,
            target_entity_type="mart_field",
            target_entity_id=61,
            transformation_rule="trim(CUST_NO)",
            lineage_status="verified",
            verified_at=datetime(2026, 8, 21, tzinfo=UTC),
        ),
        authority=AuthorityRank.LINEAGE,
        state=FactState.VERIFIED,
        source_type="verified_lineage",
        source_id=201,
    )
    knowledge = _fact_for_value(
        KnowledgeEvidenceContextValue(
            knowledge_unit_id=301,
            knowledge_type="regulatory_qa",
            title="监管答疑",
            excerpt="统一客户号采用行内客户主索引。",
            source_file_name="监管答疑.pdf",
            source_location="page:12",
            document_id=30,
            document_version_id=31,
            confidentiality_level="restricted",
            retrieval_score=0.99,
        ),
        authority=AuthorityRank.RETRIEVED,
        state=FactState.RETRIEVED,
        source_type="retrieved_knowledge",
        source_id=301,
        retrieval_log_id=401,
        confidentiality_level="restricted",
    )
    historical = _fact_for_value(
        HistoricalContextValue(
            historical_item_id=501,
            title="2025 历史口径",
            definition="历史上使用客户主键。",
            source_location="历史口径.xlsx!A2",
            content_hash="a" * 64,
            match_status="matched",
        ),
        authority=AuthorityRank.HISTORICAL,
        state=FactState.HISTORICAL,
        source_type="historical_caliber",
        source_id=501,
    )
    quality = _fact_for_value(
        QualityContextValue(
            quality_code="NOT_NULL",
            rule_type="not_null",
            description="客户统一编号不得为空。",
            severity="error",
            status="confirmed",
        ),
        authority=AuthorityRank.REGULATORY,
        state=FactState.CONFIRMED,
        source_type="regulatory",
        source_id=601,
    )

    context = RegulatoryContext(
        scope=_empty_context().scope,
        target=_empty_context().target,
        semantic=[semantic],
        regulatory=[regulatory],
        metadata=[metadata],
        candidates=[candidate],
        mappings=[mapping],
        lineage=[lineage],
        knowledge_evidence=[knowledge],
        historical=[historical],
        quality=[quality],
        build_metadata=ContextBuildMetadata(
            built_at=datetime(2026, 8, 22, 13, 1, tzinfo=UTC),
            mode=ContextMode.TRUSTED,
            fact_count=9,
            conflict_count=0,
            open_question_count=0,
            source_count=9,
        ),
    )
    first = context.model_dump(mode="json")
    second = context.model_dump(mode="json")
    assert first == second
    assert [first[name][0]["value"]["kind"] for name in (
        "semantic",
        "regulatory",
        "metadata",
        "candidates",
        "mappings",
        "lineage",
        "knowledge_evidence",
        "historical",
        "quality",
    )] == [
        "semantic",
        "regulatory",
        "metadata",
        "candidate",
        "mapping",
        "lineage",
        "knowledge_evidence",
        "historical",
        "quality",
    ]

    orm_field = TargetField(
        id=47,
        project_id=7,
        target_table_id=23,
        field_code="CUST_UNIFIED_NO",
        field_name="客户统一编号",
    )
    with pytest.raises(ValidationError):
        _fact_for_value(
            orm_field,
            authority=AuthorityRank.METADATA,
            state=FactState.OBSERVED,
            source_type="target_metadata",
            source_id=47,
        )
    with pytest.raises(ValidationError):
        _fact_for_value(
            {
                "kind": "metadata",
                "entity_type": "target_field",
                "entity_id": 47,
                "name": "客户统一编号",
                "orm_dump": {"password_hash": "must-not-leak"},
            },
            authority=AuthorityRank.METADATA,
            state=FactState.OBSERVED,
            source_type="target_metadata",
            source_id=47,
        )


def test_retrieved_provenance_requires_log_and_matching_confidentiality() -> None:
    value = KnowledgeEvidenceContextValue(
        knowledge_unit_id=301,
        knowledge_type="regulatory_qa",
        title="监管答疑",
        excerpt="统一客户号采用行内客户主索引。",
        confidentiality_level="restricted",
        retrieval_score=0.99,
    )
    fact = _fact_for_value(
        value,
        authority=AuthorityRank.RETRIEVED,
        state=FactState.RETRIEVED,
        source_type="retrieved_knowledge",
        source_id=301,
        retrieval_log_id=401,
        confidentiality_level="restricted",
    )
    payload = fact.model_dump(mode="json")
    assert payload["provenance"]["retrieval_log_id"] == 401
    assert payload["value"]["confidentiality_level"] == "restricted"
    assert payload["provenance"]["confidentiality_level"] == "restricted"

    with pytest.raises(ValidationError):
        _fact_for_value(
            value,
            authority=AuthorityRank.RETRIEVED,
            state=FactState.RETRIEVED,
            source_type="retrieved_knowledge",
            source_id=301,
            confidentiality_level="restricted",
        )
    with pytest.raises(ValidationError):
        _fact_for_value(
            value,
            authority=AuthorityRank.RETRIEVED,
            state=FactState.RETRIEVED,
            source_type="retrieved_knowledge",
            source_id=301,
            retrieval_log_id=401,
            confidentiality_level="internal",
        )


def test_inclusive_period_bounds_scope_and_deterministic_gap_ordering() -> None:
    inclusive = EffectivePeriod(effective_from="2026-12-31", effective_to="2026-12-31")
    assert inclusive.effective_from == inclusive.effective_to == date(2026, 12, 31)
    with pytest.raises(ValidationError):
        EffectivePeriod(effective_from="2027-01-01", effective_to="2026-12-31")
    with pytest.raises(ValidationError):
        RegulatoryContextRequest(project_id=7, as_of="not-a-date")
    with pytest.raises(ValidationError):
        RegulatoryContextRequest(project_id=7, as_of="2026-12-31", reporting_period="   ")
    with pytest.raises(ValidationError):
        RegulatoryContextRequest(project_id=7, as_of="2026-12-31", candidate_limit=101)
    with pytest.raises(ValidationError):
        MetadataContextValue(
            entity_type="target_field",
            entity_id=47,
            name="客户统一编号",
            attributes=[ContextAttribute(name=f"a{index}", value=index) for index in range(33)],
        )

    conflicts = [
        ContextConflict(
            code="Z_CONFLICT",
            severity="warning",
            target_type="target_field",
            target_id=47,
            message="后排序冲突",
        ),
        ContextConflict(
            code="A_CONFLICT",
            severity="error",
            target_type="target_field",
            target_id=47,
            message="先排序冲突",
        ),
    ]
    questions = [
        ContextOpenQuestion(
            question_code="Z_QUESTION",
            question_type="missing_evidence",
            target_type="target_field",
            target_id=47,
            question_text="后排序问题？",
        ),
        ContextOpenQuestion(
            question_code="A_QUESTION",
            question_type="missing_mapping",
            target_type="target_field",
            target_id=47,
            question_text="先排序问题？",
        ),
    ]
    ordered = RegulatoryContext(
        scope=_empty_context().scope,
        target=_empty_context().target,
        conflicts=conflicts,
        open_questions=questions,
        build_metadata=ContextBuildMetadata(
            built_at=datetime(2026, 8, 22, 13, 2, tzinfo=UTC),
            mode=ContextMode.TRUSTED,
            fact_count=0,
            conflict_count=2,
            open_question_count=2,
            source_count=0,
        ),
    )
    assert [item.code for item in ordered.conflicts] == ["A_CONFLICT", "Z_CONFLICT"]
    assert [item.question_code for item in ordered.open_questions] == ["A_QUESTION", "Z_QUESTION"]

    cross_project_payload = _semantic_fact().model_dump(mode="python")
    cross_project_payload["provenance"]["project_id"] = 8
    cross_project_fact = ContextFact.model_validate(cross_project_payload)
    with pytest.raises(ValidationError):
        RegulatoryContext(
            scope=_empty_context().scope,
            target=_empty_context().target,
            semantic=[cross_project_fact],
            build_metadata=ContextBuildMetadata(
                built_at=datetime(2026, 8, 22, 13, 3, tzinfo=UTC),
                mode=ContextMode.TRUSTED,
                fact_count=1,
                conflict_count=0,
                open_question_count=0,
                source_count=1,
            ),
        )
