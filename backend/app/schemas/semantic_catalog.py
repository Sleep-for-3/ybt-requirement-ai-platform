from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.semantic import ConceptType, EntityType, SemanticStatus


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
    has_relation: bool = False
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

