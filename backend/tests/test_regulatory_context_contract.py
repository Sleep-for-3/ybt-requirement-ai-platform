from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from app.schemas.regulatory_context import (
    ContextBuildMetadata,
    ContextEvidenceReference,
    ContextFact,
    ContextMode,
    ContextProvenance,
    ContextScope,
    ContextTarget,
    EffectivePeriod,
    RegulatoryContext,
    RegulatoryContextRequest,
    SemanticContextValue,
)
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
