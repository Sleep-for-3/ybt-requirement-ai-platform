"""Strict, versioned wire contract for RegulatoryContext projections.

The contract deliberately models compact values and references rather than ORM
rows or arbitrary JSON.  It is projection-only: no schema in this module is a
persistence model, cache record, or mutable source of regulatory truth.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from app.services.semantic.context_authority import AuthorityRank, FactState, authority_for_source


Code50 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]
Code80 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
Code120 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Code150 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=150)]
Code500 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
Text500 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
Text1000 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
Text2000 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
Text4000 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
Text12000 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=12000)]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ContextMode(str, Enum):
    TRUSTED = "trusted"
    CANDIDATE = "candidate"


def normalize_context_date(value: date | datetime | str) -> date:
    """Normalize a date-like input to the inclusive business calendar date."""

    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raw = str(value).strip()
    if not raw:
        raise ValueError("as_of must not be blank")
    try:
        if "T" in raw or " " in raw:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError("as_of must be a valid ISO date or datetime") from exc


def normalize_reporting_period(value: str | None) -> str | None:
    """Trim and bound a reporting label without inferring or persisting dates."""

    if value is None:
        return None
    normalized = " ".join(str(value).split())
    if not normalized:
        raise ValueError("reporting_period must not be blank")
    if len(normalized) > 120:
        raise ValueError("reporting_period must contain at most 120 characters")
    return normalized


def _require_aware_datetime(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone")
    return value


class EffectivePeriod(_StrictModel):
    """Inclusive business-date interval."""

    effective_from: date
    effective_to: date | None = None

    @field_validator("effective_from", "effective_to", mode="before")
    @classmethod
    def normalize_dates(cls, value: date | datetime | str | None):
        return None if value is None else normalize_context_date(value)

    @model_validator(mode="after")
    def validate_interval(self) -> "EffectivePeriod":
        if self.effective_to is not None and self.effective_to < self.effective_from:
            raise ValueError("effective_to must be on or after effective_from")
        return self


class ContextEvidenceReference(_StrictModel):
    evidence_type: Code80
    evidence_id: int | None = Field(default=None, gt=0)
    citation: Text1000 | None = None
    source_location: Text1000 | None = None

    @model_validator(mode="after")
    def require_reference(self) -> "ContextEvidenceReference":
        if self.evidence_id is None and self.citation is None and self.source_location is None:
            raise ValueError("an evidence reference requires an id, citation, or source location")
        return self


class ContextProvenance(_StrictModel):
    project_id: int = Field(gt=0)
    institution_id: int | None = Field(default=None, gt=0)
    source_model: Code120
    source_type: Code120
    source_id: int | None = Field(default=None, gt=0)
    evidence_references: list[ContextEvidenceReference] = Field(default_factory=list, max_length=50)
    version_no: int | None = Field(default=None, gt=0)
    effective_period: EffectivePeriod | None = None
    observed_at: datetime
    retrieval_log_id: int | None = Field(default=None, gt=0)
    confidentiality_level: Code50 | None = None

    @field_validator("observed_at")
    @classmethod
    def validate_observed_at(cls, value: datetime) -> datetime:
        return _require_aware_datetime(value, "observed_at")


class ContextAttribute(_StrictModel):
    name: Code120
    value: Text2000 | int | float | bool | None


class SemanticContextValue(_StrictModel):
    kind: Literal["semantic"] = "semantic"
    semantic_concept_id: int = Field(gt=0)
    semantic_concept_version_id: int | None = Field(default=None, gt=0)
    concept_type: Code50
    concept_code: Code150
    concept_name: Code500
    definition: Text12000 | None = None
    aliases: list[Code500] = Field(default_factory=list, max_length=100)
    business_domain: Code500 | None = None

    @field_validator("aliases")
    @classmethod
    def normalize_aliases(cls, values: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for raw in values:
            alias = raw.strip()
            key = alias.casefold()
            if alias and key not in seen:
                seen.add(key)
                result.append(alias)
        return result


class RegulatoryContextValue(_StrictModel):
    kind: Literal["regulatory"] = "regulatory"
    regulatory_source_id: int | None = Field(default=None, gt=0)
    regulation_code: Code150 | None = None
    title: Code500
    requirement_text: Text12000
    article_reference: Code500 | None = None
    target_field_id: int | None = Field(default=None, gt=0)


class MetadataContextValue(_StrictModel):
    kind: Literal["metadata"] = "metadata"
    entity_type: Code80
    entity_id: int = Field(gt=0)
    code: Code500 | None = None
    name: Code500 | None = None
    description: Text4000 | None = None
    attributes: list[ContextAttribute] = Field(default_factory=list, max_length=32)

    @model_validator(mode="after")
    def require_descriptor(self) -> "MetadataContextValue":
        if self.code is None and self.name is None and self.description is None and not self.attributes:
            raise ValueError("metadata value requires a code, name, description, or attribute")
        return self


class CandidateContextValue(_StrictModel):
    kind: Literal["candidate"] = "candidate"
    candidate_type: Code80
    candidate_id: int = Field(gt=0)
    code: Code500 | None = None
    name: Code500 | None = None
    match_reason: Text500
    score: float = Field(ge=0, le=1)
    rank_tier: int = Field(ge=1, le=100)
    evidence_excerpt: Text1000 | None = None


class MappingContextValue(_StrictModel):
    kind: Literal["mapping"] = "mapping"
    mapping_type: Literal[
        "source_to_mart",
        "mart_to_ybt",
        "scenario_business",
        "scenario_technical",
    ]
    mapping_id: int = Field(gt=0)
    mapping_name: Code500 | None = None
    source_entity_ids: list[int] = Field(default_factory=list, max_length=100)
    target_entity_ids: list[int] = Field(default_factory=list, max_length=100)
    rule_text: Text12000 | None = None
    mapping_status: Code50
    lineage_status: Code50 | None = None

    @field_validator("source_entity_ids", "target_entity_ids")
    @classmethod
    def positive_entity_ids(cls, values: list[int]) -> list[int]:
        if any(value <= 0 for value in values):
            raise ValueError("mapping entity ids must be positive")
        return values


class LineageContextValue(_StrictModel):
    kind: Literal["lineage"] = "lineage"
    lineage_edge_id: int | None = Field(default=None, gt=0)
    source_entity_type: Code80
    source_entity_id: int = Field(gt=0)
    target_entity_type: Code80
    target_entity_id: int = Field(gt=0)
    transformation_rule: Text12000 | None = None
    lineage_status: Code50
    verified_at: datetime | None = None

    @field_validator("verified_at")
    @classmethod
    def validate_verified_at(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _require_aware_datetime(value, "verified_at")


class KnowledgeEvidenceContextValue(_StrictModel):
    kind: Literal["knowledge_evidence"] = "knowledge_evidence"
    knowledge_unit_id: int | None = Field(default=None, gt=0)
    evidence_reference_id: int | None = Field(default=None, gt=0)
    knowledge_type: Code80
    title: Code500 | None = None
    excerpt: Text4000 | None = None
    source_file_name: Code500 | None = None
    source_location: Text1000 | None = None
    document_id: int | None = Field(default=None, gt=0)
    document_version_id: int | None = Field(default=None, gt=0)
    confidentiality_level: Code50
    retrieval_score: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def require_source_identity(self) -> "KnowledgeEvidenceContextValue":
        if self.knowledge_unit_id is None and self.evidence_reference_id is None:
            raise ValueError("knowledge/evidence value requires a knowledge or evidence id")
        return self


class HistoricalContextValue(_StrictModel):
    kind: Literal["historical"] = "historical"
    historical_item_id: int = Field(gt=0)
    title: Code500 | None = None
    definition: Text12000 | None = None
    source_location: Text1000
    content_hash: Code150 | None = None
    match_status: Literal["matched", "ambiguous", "unmatched"]


class QualityContextValue(_StrictModel):
    kind: Literal["quality"] = "quality"
    quality_code: Code120
    rule_type: Code80
    description: Text4000
    expression: Text4000 | None = None
    severity: Literal["info", "warning", "error"] = "warning"
    status: Code50


ContextStructuredValue = Annotated[
    SemanticContextValue
    | RegulatoryContextValue
    | MetadataContextValue
    | CandidateContextValue
    | MappingContextValue
    | LineageContextValue
    | KnowledgeEvidenceContextValue
    | HistoricalContextValue
    | QualityContextValue,
    Field(discriminator="kind"),
]


class ContextFact(_StrictModel):
    fact_type: Code120
    value: ContextStructuredValue
    authority: AuthorityRank
    state: FactState
    source_type: Code120
    source_id: int | None = Field(default=None, gt=0)
    evidence_references: list[ContextEvidenceReference] = Field(default_factory=list, max_length=50)
    version_no: int | None = Field(default=None, gt=0)
    effective_period: EffectivePeriod | None = None
    observed_at: datetime
    confidence: float = Field(ge=0, le=1)
    provenance: ContextProvenance

    @field_validator("observed_at")
    @classmethod
    def validate_observed_at(cls, value: datetime) -> datetime:
        return _require_aware_datetime(value, "observed_at")

    @model_validator(mode="after")
    def validate_state_and_provenance(self) -> "ContextFact":
        trusted_states = {FactState.CONFIRMED, FactState.APPROVED, FactState.VERIFIED}
        if self.authority in {AuthorityRank.RETRIEVED, AuthorityRank.INFERRED} and self.state in trusted_states:
            raise ValueError("retrieved or inferred facts cannot use trusted states")
        if self.state is FactState.RETRIEVED and self.authority is not AuthorityRank.RETRIEVED:
            raise ValueError("retrieved state requires retrieved authority")
        if self.state is FactState.INFERRED and self.authority is not AuthorityRank.INFERRED:
            raise ValueError("inferred state requires inferred authority")
        if (
            self.authority is AuthorityRank.RETRIEVED or self.state is FactState.RETRIEVED
        ) and self.provenance.retrieval_log_id is None:
            raise ValueError("retrieved facts require provenance.retrieval_log_id")
        if isinstance(self.value, KnowledgeEvidenceContextValue):
            if self.provenance.confidentiality_level != self.value.confidentiality_level:
                raise ValueError(
                    "knowledge/evidence confidentiality must match provenance.confidentiality_level"
                )

        mirrored = (
            ("source_type", self.source_type, self.provenance.source_type),
            ("source_id", self.source_id, self.provenance.source_id),
            ("evidence_references", self.evidence_references, self.provenance.evidence_references),
            ("version_no", self.version_no, self.provenance.version_no),
            ("effective_period", self.effective_period, self.provenance.effective_period),
            ("observed_at", self.observed_at, self.provenance.observed_at),
        )
        for field_name, fact_value, provenance_value in mirrored:
            if fact_value != provenance_value:
                raise ValueError(f"{field_name} must match provenance.{field_name}")

        try:
            expected_authority = authority_for_source(self.source_type)
        except ValueError as exc:
            raise ValueError(f"unknown context source_type: {self.source_type}") from exc
        if self.authority is not expected_authority:
            raise ValueError(
                "authority must match source_type policy: "
                f"{self.source_type} requires {expected_authority.value}"
            )
        return self


class ContextScope(_StrictModel):
    project_id: int = Field(gt=0)
    institution_id: int | None = Field(default=None, gt=0)
    as_of: date
    reporting_period: Code120 | None = None
    mode: ContextMode = ContextMode.TRUSTED

    @field_validator("as_of", mode="before")
    @classmethod
    def normalize_as_of(cls, value: date | datetime | str) -> date:
        return normalize_context_date(value)

    @field_validator("reporting_period", mode="before")
    @classmethod
    def normalize_period(cls, value: str | None) -> str | None:
        return normalize_reporting_period(value)


class ContextTarget(_StrictModel):
    target_table_id: int | None = Field(default=None, gt=0)
    target_field_id: int | None = Field(default=None, gt=0)
    mart_field_id: int | None = Field(default=None, gt=0)
    semantic_concept_id: int | None = Field(default=None, gt=0)
    target_table_code: Code500 | None = None
    target_table_name: Code500 | None = None
    target_field_code: Code500 | None = None
    target_field_name: Code500 | None = None


class ContextScenario(_StrictModel):
    scenario_id: int = Field(gt=0)
    scenario_code: Code150 | None = None
    scenario_name: Code500 | None = None
    scenario_type: Code80 | None = None


class ContextInputScope(_StrictModel):
    """Typed caller-controlled inputs recorded for reproducible context builds."""

    reporting_period: Code120 | None = None
    mode: ContextMode
    target_table_id: int | None = Field(default=None, gt=0)
    target_field_id: int | None = Field(default=None, gt=0)
    mart_field_id: int | None = Field(default=None, gt=0)
    semantic_concept_id: int | None = Field(default=None, gt=0)
    scenario_id: int | None = Field(default=None, gt=0)

    @field_validator("reporting_period", mode="before")
    @classmethod
    def normalize_period(cls, value: str | None) -> str | None:
        return normalize_reporting_period(value)


class ContextConflict(_StrictModel):
    code: Code120
    severity: Literal["info", "warning", "error"]
    target_type: Code80
    target_id: int | None = Field(default=None, gt=0)
    message: Text2000
    left_source_type: Code120 | None = None
    left_source_id: int | None = Field(default=None, gt=0)
    right_source_type: Code120 | None = None
    right_source_id: int | None = Field(default=None, gt=0)
    resolution_state: Literal["unresolved", "resolved"] = "unresolved"

    def deterministic_sort_key(self) -> tuple[str, str, int, str, int, str, int]:
        return (
            self.code,
            self.target_type,
            self.target_id or 0,
            self.left_source_type or "",
            self.left_source_id or 0,
            self.right_source_type or "",
            self.right_source_id or 0,
        )


class ContextOpenQuestion(_StrictModel):
    question_code: Code120
    question_type: Code80
    priority: Literal["low", "medium", "high"] = "medium"
    target_type: Code80
    target_id: int | None = Field(default=None, gt=0)
    question_text: Text2000
    evidence_references: list[ContextEvidenceReference] = Field(default_factory=list, max_length=50)
    assigned_role: Code80 | None = None
    resolution_state: Literal["open", "answered", "dismissed"] = "open"

    def deterministic_sort_key(self) -> tuple[str, str, int, str, str]:
        return (
            self.question_code,
            self.target_type,
            self.target_id or 0,
            self.priority,
            self.question_text,
        )


class ContextBuildMetadata(_StrictModel):
    context_version: Literal["1.0"] = "1.0"
    builder_version: Literal["1.0"] = "1.0"
    built_at: datetime
    project_id: int = Field(gt=0)
    as_of: date
    input_scope: ContextInputScope
    semantic_policy_version: Code120
    authority_policy_version: Code120
    retrieval_log_ids: list[int] = Field(default_factory=list, max_length=100)
    mode: ContextMode
    fact_count: int = Field(ge=0, le=10000)
    conflict_count: int = Field(ge=0, le=1000)
    open_question_count: int = Field(ge=0, le=1000)
    source_count: int = Field(ge=0, le=10000)
    collector_names: list[Code120] = Field(default_factory=list, max_length=32)
    warnings: list[Text500] = Field(default_factory=list, max_length=50)
    truncated: bool = False

    @field_validator("built_at")
    @classmethod
    def validate_built_at(cls, value: datetime) -> datetime:
        return _require_aware_datetime(value, "built_at")

    @field_validator("as_of", mode="before")
    @classmethod
    def normalize_as_of(cls, value: date | datetime | str) -> date:
        return normalize_context_date(value)

    @field_validator("retrieval_log_ids")
    @classmethod
    def normalize_retrieval_log_ids(cls, value: list[int]) -> list[int]:
        if any(retrieval_log_id <= 0 for retrieval_log_id in value):
            raise ValueError("retrieval_log_ids must contain only positive integers")
        return sorted(set(value))


class RegulatoryContext(_StrictModel):
    context_schema_version: Literal["1.0"] = "1.0"
    scope: ContextScope
    target: ContextTarget = Field(default_factory=ContextTarget)
    scenario: ContextScenario | None = None
    semantic: list[ContextFact] = Field(default_factory=list, max_length=500)
    regulatory: list[ContextFact] = Field(default_factory=list, max_length=500)
    metadata: list[ContextFact] = Field(default_factory=list, max_length=500)
    candidates: list[ContextFact] = Field(default_factory=list, max_length=500)
    mappings: list[ContextFact] = Field(default_factory=list, max_length=500)
    lineage: list[ContextFact] = Field(default_factory=list, max_length=500)
    knowledge_evidence: list[ContextFact] = Field(default_factory=list, max_length=500)
    historical: list[ContextFact] = Field(default_factory=list, max_length=500)
    quality: list[ContextFact] = Field(default_factory=list, max_length=500)
    conflicts: list[ContextConflict] = Field(default_factory=list, max_length=200)
    open_questions: list[ContextOpenQuestion] = Field(default_factory=list, max_length=200)
    build_metadata: ContextBuildMetadata

    @model_validator(mode="after")
    def validate_sections_and_scope(self) -> "RegulatoryContext":
        sections = (
            ("semantic", self.semantic, "semantic"),
            ("regulatory", self.regulatory, "regulatory"),
            ("metadata", self.metadata, "metadata"),
            ("candidates", self.candidates, "candidate"),
            ("mappings", self.mappings, "mapping"),
            ("lineage", self.lineage, "lineage"),
            ("knowledge_evidence", self.knowledge_evidence, "knowledge_evidence"),
            ("historical", self.historical, "historical"),
            ("quality", self.quality, "quality"),
        )
        all_facts: list[ContextFact] = []
        for section_name, facts, expected_kind in sections:
            for fact in facts:
                if fact.value.kind != expected_kind:
                    raise ValueError(f"{section_name} facts require value.kind={expected_kind}")
                if fact.provenance.project_id != self.scope.project_id:
                    raise ValueError("fact provenance project_id must match context scope")
                allowed_institutions = {None, self.scope.institution_id}
                if fact.provenance.institution_id not in allowed_institutions:
                    raise ValueError("fact provenance institution_id must match context scope")
            all_facts.extend(facts)

        if len(all_facts) > 1000:
            raise ValueError("RegulatoryContext contains more than 1000 facts")
        if self.build_metadata.context_version != self.context_schema_version:
            raise ValueError("build_metadata.context_version must match context_schema_version")
        if self.build_metadata.project_id != self.scope.project_id:
            raise ValueError("build_metadata.project_id must match scope.project_id")
        if self.build_metadata.as_of != self.scope.as_of:
            raise ValueError("build_metadata.as_of must match scope.as_of")

        input_scope = self.build_metadata.input_scope
        input_scope_bindings = (
            ("reporting_period", input_scope.reporting_period, self.scope.reporting_period),
            ("mode", input_scope.mode, self.scope.mode),
            ("target_table_id", input_scope.target_table_id, self.target.target_table_id),
            ("target_field_id", input_scope.target_field_id, self.target.target_field_id),
            ("mart_field_id", input_scope.mart_field_id, self.target.mart_field_id),
            (
                "semantic_concept_id",
                input_scope.semantic_concept_id,
                self.target.semantic_concept_id,
            ),
            (
                "scenario_id",
                input_scope.scenario_id,
                self.scenario.scenario_id if self.scenario is not None else None,
            ),
        )
        for field_name, metadata_value, context_value in input_scope_bindings:
            if metadata_value != context_value:
                raise ValueError(
                    f"build_metadata.input_scope.{field_name} must match context {field_name}"
                )

        if self.scope.mode is not self.build_metadata.mode:
            raise ValueError("build metadata mode must match context scope mode")
        if self.build_metadata.fact_count != len(all_facts):
            raise ValueError("build metadata fact_count does not match section facts")
        if self.build_metadata.conflict_count != len(self.conflicts):
            raise ValueError("build metadata conflict_count does not match conflicts")
        if self.build_metadata.open_question_count != len(self.open_questions):
            raise ValueError("build metadata open_question_count does not match open_questions")

        actual_retrieval_log_ids = sorted(
            {
                fact.provenance.retrieval_log_id
                for fact in all_facts
                if fact.provenance.retrieval_log_id is not None
            }
        )
        if self.build_metadata.retrieval_log_ids != actual_retrieval_log_ids:
            raise ValueError(
                "build_metadata.retrieval_log_ids must match fact provenance retrieval_log_ids"
            )

        self.conflicts = sorted(self.conflicts, key=lambda item: item.deterministic_sort_key())
        self.open_questions = sorted(self.open_questions, key=lambda item: item.deterministic_sort_key())
        return self


class RegulatoryContextRequest(_StrictModel):
    """Caller-controlled build inputs; institution ownership is output-derived."""

    project_id: int = Field(gt=0)
    target_table_id: int | None = Field(default=None, gt=0)
    target_field_id: int | None = Field(default=None, gt=0)
    scenario_id: int | None = Field(default=None, gt=0)
    mart_field_id: int | None = Field(default=None, gt=0)
    semantic_concept_id: int | None = Field(default=None, gt=0)
    as_of: date
    reporting_period: Code120 | None = None
    mode: ContextMode = ContextMode.TRUSTED
    candidate_limit: int = Field(default=50, ge=1, le=100)

    @field_validator("as_of", mode="before")
    @classmethod
    def normalize_as_of(cls, value: date | datetime | str) -> date:
        return normalize_context_date(value)

    @field_validator("reporting_period", mode="before")
    @classmethod
    def normalize_period(cls, value: str | None) -> str | None:
        return normalize_reporting_period(value)


__all__ = [
    "CandidateContextValue",
    "ContextAttribute",
    "ContextBuildMetadata",
    "ContextConflict",
    "ContextEvidenceReference",
    "ContextFact",
    "ContextMode",
    "ContextOpenQuestion",
    "ContextProvenance",
    "ContextScenario",
    "ContextScope",
    "ContextStructuredValue",
    "ContextTarget",
    "EffectivePeriod",
    "HistoricalContextValue",
    "KnowledgeEvidenceContextValue",
    "LineageContextValue",
    "MappingContextValue",
    "MetadataContextValue",
    "QualityContextValue",
    "RegulatoryContext",
    "RegulatoryContextRequest",
    "RegulatoryContextValue",
    "SemanticContextValue",
    "normalize_context_date",
    "normalize_reporting_period",
]
