from collections import Counter
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Project, SemanticBinding, SemanticConcept
from app.schemas.semantic_catalog import (
    CatalogMode,
    SemanticCatalogEffectiveVersion,
    SemanticCatalogFacets,
    SemanticCatalogItem,
    SemanticCatalogPage,
)
from app.services.semantic.status_policy import SemanticVisibilityMode, statuses_for
from app.services.semantic.version_service import resolve_effective_versions


class SemanticCatalogQueryService:
    """Read-only projection over governed semantic source tables."""

    def __init__(self, db: Session, project: Project):
        self.db = db
        self.project = project

    def list_catalog(
        self,
        *,
        as_of: date,
        mode: CatalogMode = "candidate",
        query: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> SemanticCatalogPage:
        if mode == "audit":
            raise ValueError("Audit catalog mode is not available through the tracer")
        visibility = (
            SemanticVisibilityMode.TRUSTED
            if mode == "trusted"
            else SemanticVisibilityMode.CANDIDATE
        )
        statement = select(SemanticConcept).where(
            SemanticConcept.project_id == self.project.id,
            SemanticConcept.status.in_(statuses_for(visibility)),
        )
        if self.project.institution_id is None:
            statement = statement.where(SemanticConcept.institution_id.is_(None))
        else:
            statement = statement.where(
                SemanticConcept.institution_id == self.project.institution_id
            )
        if query and query.strip():
            pattern = f"%{query.strip()}%"
            statement = statement.where(
                SemanticConcept.concept_code.ilike(pattern)
                | SemanticConcept.concept_name.ilike(pattern)
            )

        total = int(
            self.db.scalar(select(func.count()).select_from(statement.subquery())) or 0
        )
        concepts = list(
            self.db.scalars(
                statement.order_by(SemanticConcept.id)
                .offset((page - 1) * page_size)
                .limit(page_size)
            ).all()
        )
        concept_ids = [concept.id for concept in concepts]
        effective = resolve_effective_versions(
            self.db,
            concept_ids,
            as_of,
            project_id=self.project.id,
        )
        binding_counts = self._confirmed_binding_counts(concept_ids)
        items = [
            self._item(concept, effective.get(concept.id), binding_counts)
            for concept in concepts
        ]
        return SemanticCatalogPage(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            as_of=as_of,
            mode=mode,
            facets=self._facets(items),
        )

    def _confirmed_binding_counts(self, concept_ids: list[int]) -> dict[int, int]:
        if not concept_ids:
            return {}
        rows = self.db.execute(
            select(
                SemanticBinding.semantic_concept_id,
                func.count(SemanticBinding.id),
            ).where(
                SemanticBinding.project_id == self.project.id,
                SemanticBinding.semantic_concept_id.in_(concept_ids),
                SemanticBinding.status == "confirmed",
            ).group_by(SemanticBinding.semantic_concept_id)
        ).all()
        return {int(concept_id): int(count) for concept_id, count in rows}

    @staticmethod
    def _item(concept, version, binding_counts: dict[int, int]) -> SemanticCatalogItem:
        effective_version = None
        if version is not None:
            effective_version = SemanticCatalogEffectiveVersion(
                id=version.id,
                version_no=version.version_no,
                concept_name=version.concept_name,
                definition=version.definition,
                aliases=list(version.aliases_json or []),
                business_domain=version.business_domain,
                owner_department=version.owner_department,
                status="confirmed",
                source_type=version.source_type,
                source_id=version.source_id,
                confirmed_by=version.confirmed_by,
                confirmed_at=version.confirmed_at,
                effective_from=version.effective_from,
                effective_to=version.effective_to,
                updated_at=version.updated_at,
            )
        return SemanticCatalogItem(
            id=concept.id,
            project_id=concept.project_id,
            concept_type=concept.concept_type,
            concept_code=concept.concept_code,
            concept_name=concept.concept_name,
            status=concept.status,
            business_domain=(
                version.business_domain if version is not None else concept.business_domain
            ),
            owner_department=(
                version.owner_department if version is not None else concept.owner_department
            ),
            effective_version=effective_version,
            related_asset_count=binding_counts.get(concept.id, 0),
            updated_at=concept.updated_at,
        )

    @staticmethod
    def _facets(items: list[SemanticCatalogItem]) -> SemanticCatalogFacets:
        return SemanticCatalogFacets(
            concept_types=dict(Counter(item.concept_type for item in items)),
            business_domains=dict(
                Counter(item.business_domain or "__uncategorized__" for item in items)
            ),
            owners=dict(Counter(item.owner_department or "__unowned__" for item in items)),
            statuses=dict(Counter(item.status for item in items)),
        )


__all__ = ["SemanticCatalogQueryService"]

