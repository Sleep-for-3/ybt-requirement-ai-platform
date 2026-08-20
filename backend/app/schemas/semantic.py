from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


ConceptType = Literal["business_term", "metric", "dimension", "code_set", "business_rule", "regulatory_rule"]
SemanticStatus = Literal["draft", "ai_suggested", "confirmed", "rejected", "deprecated"]
ConfidenceLevel = Literal["low", "medium", "high"]
EntityType = Literal[
    "target_table", "target_field", "mart_table", "mart_field", "source_table", "source_field",
    "scenario", "knowledge_unit", "source_to_mart_mapping", "mart_to_ybt_mapping",
    "scenario_business_mapping", "scenario_technical_lineage",
]
RelationType = Literal[
    "is_a", "part_of", "uses", "derived_from", "classified_by", "identified_by",
    "reported_as", "governed_by", "related_to",
]


class OrmModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class SemanticConceptCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    concept_type: ConceptType
    concept_code: str = Field(min_length=1, max_length=150)
    concept_name: str = Field(min_length=1, max_length=255)
    definition: str | None = None
    description: str | None = None
    aliases_json: list[str] = Field(default_factory=list, max_length=100)
    business_domain: str | None = Field(default=None, max_length=200)
    owner_department: str | None = Field(default=None, max_length=200)
    status: Literal["draft", "ai_suggested"] = "draft"
    confidence_level: ConfidenceLevel = "medium"
    source_type: str = Field(default="manual", min_length=1, max_length=50)
    source_id: int | None = None

    @field_validator("concept_code", "concept_name")
    @classmethod
    def strip_required(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("value must not be blank")
        return stripped

    @field_validator("aliases_json")
    @classmethod
    def normalize_aliases(cls, values: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for value in values:
            alias = value.strip()
            key = alias.casefold()
            if alias and key not in seen:
                seen.add(key)
                result.append(alias)
        return result


class SemanticConceptUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    concept_code: str | None = Field(default=None, min_length=1, max_length=150)
    concept_name: str | None = Field(default=None, min_length=1, max_length=255)
    definition: str | None = None
    description: str | None = None
    aliases_json: list[str] | None = Field(default=None, max_length=100)
    business_domain: str | None = Field(default=None, max_length=200)
    owner_department: str | None = Field(default=None, max_length=200)
    confidence_level: ConfidenceLevel | None = None
    source_type: str | None = Field(default=None, min_length=1, max_length=50)
    source_id: int | None = None

    @field_validator("concept_code", "concept_name")
    @classmethod
    def strip_optional_required(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("value must not be blank")
        return stripped

    @field_validator("aliases_json")
    @classmethod
    def normalize_optional_aliases(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        result: list[str] = []
        seen: set[str] = set()
        for value in values:
            alias = value.strip()
            key = alias.casefold()
            if alias and key not in seen:
                seen.add(key)
                result.append(alias)
        return result


class SemanticConceptRead(OrmModel):
    id: int
    institution_id: int | None
    project_id: int
    concept_type: str
    concept_code: str
    concept_name: str
    definition: str | None
    description: str | None
    aliases_json: list[str]
    business_domain: str | None
    owner_department: str | None
    status: str
    confidence_level: str
    version: int
    source_type: str
    source_id: int | None
    created_by: str | None
    confirmed_by: str | None
    confirmed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class SemanticBindingCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    semantic_concept_id: int
    entity_type: EntityType
    entity_id: int
    binding_type: str = Field(default="describes", min_length=1, max_length=50)
    confidence_level: ConfidenceLevel = "medium"
    confidence_score: float | None = Field(default=None, ge=0, le=1)
    status: Literal["draft", "ai_suggested"] = "draft"
    source_type: str = Field(default="manual", min_length=1, max_length=50)
    source_id: int | None = None


class SemanticBindingUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    binding_type: str | None = Field(default=None, min_length=1, max_length=50)
    confidence_level: ConfidenceLevel | None = None
    confidence_score: float | None = Field(default=None, ge=0, le=1)
    source_type: str | None = Field(default=None, min_length=1, max_length=50)
    source_id: int | None = None


class SemanticBindingRead(OrmModel):
    id: int
    institution_id: int | None
    project_id: int
    semantic_concept_id: int
    entity_type: str
    entity_id: int
    binding_type: str
    confidence_level: str
    confidence_score: float | None
    status: str
    source_type: str
    source_id: int | None
    created_by: str | None
    confirmed_by: str | None
    confirmed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class SemanticRelationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_concept_id: int
    relation_type: RelationType
    target_concept_id: int
    confidence_level: ConfidenceLevel = "medium"
    confidence_score: float | None = Field(default=None, ge=0, le=1)
    status: Literal["draft", "ai_suggested"] = "draft"
    source_type: str = Field(default="manual", min_length=1, max_length=50)
    source_id: int | None = None


class SemanticRelationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    relation_type: RelationType | None = None
    confidence_level: ConfidenceLevel | None = None
    confidence_score: float | None = Field(default=None, ge=0, le=1)
    source_type: str | None = Field(default=None, min_length=1, max_length=50)
    source_id: int | None = None


class SemanticRelationRead(OrmModel):
    id: int
    institution_id: int | None
    project_id: int
    source_concept_id: int
    relation_type: str
    target_concept_id: int
    confidence_level: str
    confidence_score: float | None
    status: str
    source_type: str
    source_id: int | None
    created_by: str | None
    confirmed_by: str | None
    confirmed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class SemanticStatusTransition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: SemanticStatus
    comment: str | None = Field(default=None, max_length=1000)


class SemanticGraphNode(BaseModel):
    concept: SemanticConceptRead
    depth: int


class SemanticGraphEdge(BaseModel):
    relation: SemanticRelationRead
    direction: Literal["outgoing", "incoming"]


class SemanticGraphResponse(BaseModel):
    root_concept_id: int
    nodes: list[SemanticGraphNode]
    edges: list[SemanticGraphEdge]
    truncated: bool = False


class SemanticPathResponse(BaseModel):
    source_concept_id: int
    target_concept_id: int
    concept_ids: list[int]
    relation_ids: list[int]
    found: bool


class SemanticResolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entity_type: EntityType
    entity_id: int
    mode: Literal["trusted", "candidate"] = "trusted"
    query_code: str | None = None
    query_name: str | None = None
    comment: str | None = None
    limit: int = Field(default=10, ge=1, le=50)


class SemanticMatchEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    match_reason: str = Field(min_length=1, max_length=80)
    matched_field: str = Field(min_length=1, max_length=120)
    excerpt: str = Field(min_length=1, max_length=500)
    source_type: str = Field(min_length=1, max_length=100)
    source_id: int | None = None
    score: float = Field(ge=0, le=1)


class SemanticCandidateProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: int
    institution_id: int | None
    entity_type: EntityType
    entity_id: int
    semantic_concept_id: int
    resolver_rule: str = Field(min_length=1, max_length=120)
    source_type: str | None = Field(default=None, max_length=100)
    source_id: int | None = None
    source_ids: list[int] = Field(default_factory=list, max_length=8)
    evidence_ids: list[int] = Field(default_factory=list, max_length=8)
    retrieval_metadata: dict[str, str | int | float | bool | None] = Field(default_factory=dict, max_length=12)


class SemanticResolveCandidate(BaseModel):
    semantic_concept_id: int
    score: float
    match_reason: str
    evidence: list[SemanticMatchEvidence] = Field(default_factory=list, max_length=3)
    provenance: SemanticCandidateProvenance
    status: Literal["ai_suggested"] = "ai_suggested"


class SemanticResolveResponse(BaseModel):
    candidates: list[SemanticResolveCandidate]
