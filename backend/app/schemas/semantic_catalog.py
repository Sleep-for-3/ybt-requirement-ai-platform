from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.semantic import (
    ConceptType,
    ConfidenceLevel,
    EntityType,
    RelationType,
    SemanticStatus,
)


CatalogMode = Literal["trusted", "candidate", "audit"]


class StrictCatalogModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SemanticCatalogEffectiveVersion(StrictCatalogModel):
    id: int
    version_no: int
    concept_name: str
    definition: str | None
    aliases: list[str] = Field(default_factory=list, max_length=100)
    business_domain: str | None
    owner_department: str | None
    status: Literal["confirmed"]
    source_type: str
    source_id: int | None
    confirmed_by: str | None
    confirmed_at: datetime | None
    effective_from: date
    effective_to: date | None
    updated_at: datetime


class SemanticCatalogReviewSummary(StrictCatalogModel):
    pending: bool = False
    pending_count: int = Field(default=0, ge=0)
    task_id: int | None = None
    status: str | None = None
    current_step: str | None = None


class ReadableSemanticAssetReference(StrictCatalogModel):
    entity_type: EntityType
    restricted: Literal[False] = False
    entity_id: int
    display_name: str = Field(min_length=1, max_length=255)
    display_code: str | None = Field(default=None, max_length=150)
    href: str | None = Field(default=None, max_length=1000)


class RestrictedSemanticAssetReference(StrictCatalogModel):
    entity_type: EntityType
    restricted: Literal[True] = True


SemanticAssetReference = Annotated[
    ReadableSemanticAssetReference | RestrictedSemanticAssetReference,
    Field(discriminator="restricted"),
]


class SemanticCatalogItem(StrictCatalogModel):
    id: int
    project_id: int
    concept_type: ConceptType
    concept_code: str
    concept_name: str
    status: SemanticStatus
    business_domain: str | None
    owner_department: str | None
    effective_version: SemanticCatalogEffectiveVersion | None = None
    related_asset_count: int = Field(default=0, ge=0)
    related_assets: list[SemanticAssetReference] = Field(default_factory=list)
    has_relation: bool = False
    open_question_count: int = Field(default=0, ge=0)
    review: SemanticCatalogReviewSummary = Field(default_factory=SemanticCatalogReviewSummary)
    updated_at: datetime


class SemanticCatalogFacets(StrictCatalogModel):
    concept_types: dict[str, int] = Field(default_factory=dict)
    business_domains: dict[str, int] = Field(default_factory=dict)
    owners: dict[str, int] = Field(default_factory=dict)
    statuses: dict[str, int] = Field(default_factory=dict)


class SemanticCatalogPage(StrictCatalogModel):
    items: list[SemanticCatalogItem]
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    as_of: date
    mode: CatalogMode
    facets: SemanticCatalogFacets = Field(default_factory=SemanticCatalogFacets)


SemanticDetailRegionName = Literal[
    "bindings", "relations", "evidence", "lineage", "governance", "versions"
]
SemanticTemporalScope = Literal["as_of", "current_only", "mixed"]
SemanticQuestionStatus = Literal[
    "open", "assigned", "answered", "accepted", "rejected", "closed"
]
SemanticDetailReferenceType = Literal[
    "target_table", "target_field", "mart_table", "mart_field",
    "source_table", "source_field", "scenario", "knowledge_unit",
    "source_to_mart_mapping", "mart_to_ybt_mapping",
    "scenario_business_mapping", "scenario_technical_lineage",
    "semantic_concept", "review_task", "evidence", "lineage",
]


class BoundedRegionMetadata(StrictCatalogModel):
    total: int = Field(ge=0)
    returned: int = Field(ge=0)
    limit: int = Field(ge=1, le=500)
    overflow: int = Field(default=0, ge=0)
    truncated: bool = False

    @model_validator(mode="after")
    def derive_bounds(self) -> "BoundedRegionMetadata":
        if self.returned > self.total:
            raise ValueError("returned must not exceed total")
        if self.returned > self.limit:
            raise ValueError("returned must not exceed limit")
        expected_overflow = self.total - self.returned
        if self.overflow not in (0, expected_overflow):
            raise ValueError("overflow must equal total minus returned")
        if self.truncated not in (False, expected_overflow > 0):
            raise ValueError("truncated must reflect overflow")
        self.overflow = expected_overflow
        self.truncated = expected_overflow > 0
        return self


class ReadableSemanticDetailReference(StrictCatalogModel):
    entity_type: SemanticDetailReferenceType
    restricted: Literal[False] = False
    entity_id: int = Field(gt=0)
    display_name: str = Field(min_length=1, max_length=255)
    display_code: str | None = Field(default=None, max_length=150)
    href: str | None = Field(default=None, max_length=1000)


class RestrictedSemanticDetailReference(StrictCatalogModel):
    entity_type: SemanticDetailReferenceType
    restricted: Literal[True] = True


SemanticDetailReference = Annotated[
    ReadableSemanticDetailReference | RestrictedSemanticDetailReference,
    Field(discriminator="restricted"),
]


class SemanticDetailRegionCapability(StrictCatalogModel):
    temporal_scope: SemanticTemporalScope
    supports_audit: bool = False
    max_items: int = Field(default=100, ge=1, le=500)


class SemanticDetailReviewWorkflow(StrictCatalogModel):
    pending: bool = False
    pending_count: int = Field(default=0, ge=0)
    task_id: int | None = Field(default=None, gt=0)
    status: str | None = Field(default=None, max_length=50)
    current_step: str | None = Field(default=None, max_length=100)
    assigned_role: str | None = Field(default=None, max_length=100)
    assigned_user_id: int | None = Field(default=None, gt=0)
    due_at: datetime | None = None
    href: str | None = Field(default=None, max_length=1000)


class SemanticDetailVersion(StrictCatalogModel):
    id: int = Field(gt=0)
    version_no: int = Field(ge=1)
    concept_name: str = Field(min_length=1, max_length=255)
    definition: str | None = Field(default=None, max_length=12000)
    description: str | None = Field(default=None, max_length=12000)
    aliases: list[str] = Field(default_factory=list, max_length=100)
    business_domain: str | None = Field(default=None, max_length=200)
    owner_department: str | None = Field(default=None, max_length=200)
    provenance: dict[str, str | int | float | bool | None] = Field(
        default_factory=dict, max_length=12
    )
    status: SemanticStatus
    confidence_level: ConfidenceLevel
    source_type: str = Field(min_length=1, max_length=50)
    source_id: int | None = Field(default=None, gt=0)
    created_by: str | None = Field(default=None, max_length=100)
    confirmed_by: str | None = Field(default=None, max_length=100)
    confirmed_at: datetime | None = None
    effective_from: date
    effective_to: date | None = None
    created_at: datetime
    updated_at: datetime


class SemanticDetailQuestionSummary(StrictCatalogModel):
    id: int = Field(gt=0)
    question_type: str = Field(min_length=1, max_length=50)
    question_text: str = Field(min_length=1, max_length=2000)
    question_status: SemanticQuestionStatus
    priority: Literal["low", "medium", "high"]
    source_type: str | None = Field(default=None, max_length=50)
    source_id: int | None = Field(default=None, gt=0)
    review_href: str | None = Field(default=None, max_length=1000)


class SemanticDetailConflictSource(StrictCatalogModel):
    source_type: str = Field(min_length=1, max_length=100)
    source_id: int | None = Field(default=None, gt=0)
    summary: str = Field(min_length=1, max_length=1000)
    authority: str | None = Field(default=None, max_length=100)


class SemanticDetailConflictSummary(StrictCatalogModel):
    conflict_key: str = Field(min_length=1, max_length=100)
    summary: str = Field(min_length=1, max_length=2000)
    sources: list[SemanticDetailConflictSource] = Field(default_factory=list, max_length=20)
    winner: None = None
    review_href: str | None = Field(default=None, max_length=1000)


class SemanticDetailShell(StrictCatalogModel):
    id: int = Field(gt=0)
    project_id: int = Field(gt=0)
    concept_type: ConceptType
    concept_code: str = Field(min_length=1, max_length=150)
    concept_name: str = Field(min_length=1, max_length=255)
    lifecycle_status: SemanticStatus
    effective_as_of: date
    effective_version: SemanticDetailVersion | None = None
    candidate_versions: list[SemanticDetailVersion] = Field(default_factory=list, max_length=20)
    review_workflow: SemanticDetailReviewWorkflow = Field(
        default_factory=SemanticDetailReviewWorkflow
    )
    open_questions: list[SemanticDetailQuestionSummary] = Field(default_factory=list, max_length=100)
    conflicts: list[SemanticDetailConflictSummary] = Field(default_factory=list, max_length=20)
    regions: dict[SemanticDetailRegionName, SemanticDetailRegionCapability]


class SemanticBindingProjection(StrictCatalogModel):
    id: int = Field(gt=0)
    binding_type: str = Field(min_length=1, max_length=50)
    confidence_level: ConfidenceLevel
    confidence_score: float | None = Field(default=None, ge=0, le=1)
    status: SemanticStatus
    source_type: str = Field(min_length=1, max_length=50)
    source_id: int | None = Field(default=None, gt=0)
    confirmed_by: str | None = Field(default=None, max_length=100)
    confirmed_at: datetime | None = None
    target: SemanticDetailReference


class SemanticBindingChain(StrictCatalogModel):
    concept: SemanticDetailReference
    targets: list[SemanticDetailReference] = Field(default_factory=list, max_length=4)
    marts: list[SemanticDetailReference] = Field(default_factory=list, max_length=4)
    sources: list[SemanticDetailReference] = Field(default_factory=list, max_length=4)


class SemanticBindingRegion(StrictCatalogModel):
    concept_id: int = Field(gt=0)
    as_of: date
    current_only: bool = True
    confirmed: list[SemanticBindingProjection] = Field(default_factory=list, max_length=100)
    candidates: list[SemanticBindingProjection] = Field(default_factory=list, max_length=100)
    audit: list[SemanticBindingProjection] = Field(default_factory=list, max_length=100)
    confirmed_meta: BoundedRegionMetadata
    candidate_meta: BoundedRegionMetadata
    audit_meta: BoundedRegionMetadata
    chains: list[SemanticBindingChain] = Field(default_factory=list, max_length=13)
    chain_meta: BoundedRegionMetadata


class SemanticRelationProjection(StrictCatalogModel):
    id: int = Field(gt=0)
    direction: Literal["incoming", "outgoing"]
    relation_type: RelationType
    status: SemanticStatus
    confidence_level: ConfidenceLevel
    confidence_score: float | None = Field(default=None, ge=0, le=1)
    source_type: str = Field(min_length=1, max_length=50)
    source_id: int | None = Field(default=None, gt=0)
    related_concept: SemanticDetailReference


class SemanticRelationRegion(StrictCatalogModel):
    concept_id: int = Field(gt=0)
    as_of: date
    current_only: bool = True
    confirmed: list[SemanticRelationProjection] = Field(default_factory=list, max_length=100)
    candidates: list[SemanticRelationProjection] = Field(default_factory=list, max_length=100)
    audit: list[SemanticRelationProjection] = Field(default_factory=list, max_length=100)
    confirmed_meta: BoundedRegionMetadata
    candidate_meta: BoundedRegionMetadata
    audit_meta: BoundedRegionMetadata


class SemanticEvidenceProjection(StrictCatalogModel):
    id: int = Field(gt=0)
    evidence_type: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=500)
    location: str | None = Field(default=None, max_length=500)
    excerpt: str | None = Field(default=None, max_length=4000)
    authority: str | None = Field(default=None, max_length=100)
    status: SemanticStatus
    observed_at: datetime | None = None
    reference: SemanticDetailReference | None = None


class SemanticEvidencePartition(StrictCatalogModel):
    evidence: list[SemanticEvidenceProjection] = Field(default_factory=list, max_length=100)
    knowledge: list[SemanticEvidenceProjection] = Field(default_factory=list, max_length=100)
    evidence_meta: BoundedRegionMetadata
    knowledge_meta: BoundedRegionMetadata


class SemanticEvidenceRegion(StrictCatalogModel):
    concept_id: int = Field(gt=0)
    as_of: date
    current_only: bool = True
    confirmed: SemanticEvidencePartition
    candidates: SemanticEvidencePartition
    audit: SemanticEvidencePartition


class SemanticLineagePath(StrictCatalogModel):
    id: int = Field(gt=0)
    status: Literal["verified", "stale", "unresolved"]
    source: SemanticDetailReference
    target: SemanticDetailReference
    relation: str = Field(min_length=1, max_length=100)
    transformation: str | None = Field(default=None, max_length=4000)
    evidence: list[SemanticDetailReference] = Field(default_factory=list, max_length=20)


class SemanticLineageRegion(StrictCatalogModel):
    concept_id: int = Field(gt=0)
    as_of: date
    current_only: bool = True
    verified: list[SemanticLineagePath] = Field(default_factory=list, max_length=100)
    candidates: list[SemanticLineagePath] = Field(default_factory=list, max_length=100)
    audit: list[SemanticLineagePath] = Field(default_factory=list, max_length=100)
    verified_meta: BoundedRegionMetadata
    candidate_meta: BoundedRegionMetadata
    audit_meta: BoundedRegionMetadata


class SemanticGovernanceAuditEvent(StrictCatalogModel):
    id: int = Field(gt=0)
    event_type: str = Field(min_length=1, max_length=100)
    status: SemanticStatus | None = None
    summary: str = Field(min_length=1, max_length=2000)
    actor: str | None = Field(default=None, max_length=100)
    occurred_at: datetime
    non_current: Literal[True] = True


class SemanticGovernanceRegion(StrictCatalogModel):
    concept_id: int = Field(gt=0)
    as_of: date
    current_only: bool = True
    lifecycle_status: SemanticStatus
    review_workflow: SemanticDetailReviewWorkflow
    open_questions: list[SemanticDetailQuestionSummary] = Field(default_factory=list, max_length=100)
    conflicts: list[SemanticDetailConflictSummary] = Field(default_factory=list, max_length=20)
    audit_events: list[SemanticGovernanceAuditEvent] = Field(default_factory=list, max_length=100)
    audit_meta: BoundedRegionMetadata


class SemanticVersionRegion(StrictCatalogModel):
    concept_id: int = Field(gt=0)
    as_of: date
    current_only: bool = False
    effective_version_id: int | None = Field(default=None, gt=0)
    current_effective_version_id: int | None = Field(default=None, gt=0)
    confirmed: list[SemanticDetailVersion] = Field(default_factory=list, max_length=100)
    candidates: list[SemanticDetailVersion] = Field(default_factory=list, max_length=100)
    audit: list[SemanticDetailVersion] = Field(default_factory=list, max_length=100)
    confirmed_meta: BoundedRegionMetadata
    candidate_meta: BoundedRegionMetadata
    audit_meta: BoundedRegionMetadata
