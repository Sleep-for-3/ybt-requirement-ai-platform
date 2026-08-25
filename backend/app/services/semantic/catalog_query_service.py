from collections import Counter, defaultdict
from datetime import date
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import (
    KnowledgeUnit, MartField, MartTable, MartToYbtMapping, PendingQuestion,
    ProductScenario, Project, ReviewTask, ScenarioBusinessMapping,
    ScenarioTechnicalLineage, SemanticBinding, SemanticConcept, SemanticRelation,
    SourceField, SourceTable, SourceToMartMapping, TargetField, TargetTable,
)
from app.schemas.semantic import ConceptType, EntityType, SemanticStatus
from app.schemas.semantic_catalog import (
    CatalogMode, ReadableSemanticAssetReference, RestrictedSemanticAssetReference,
    SemanticAssetReference, SemanticCatalogEffectiveVersion, SemanticCatalogFacets,
    SemanticCatalogItem, SemanticCatalogPage, SemanticCatalogReviewSummary,
)
from app.services.semantic.status_policy import (
    SemanticVisibilityMode, audit_only_statuses, statuses_for,
)
from app.services.semantic.version_service import resolve_effective_versions


_ENTITY_PERMISSION: dict[EntityType, str] = {
    "target_table": "catalog.search", "target_field": "catalog.search",
    "mart_table": "catalog.search", "mart_field": "catalog.search",
    "source_table": "catalog.search", "source_field": "catalog.search",
    "scenario": "project.view", "knowledge_unit": "knowledge.search",
    "source_to_mart_mapping": "project.view", "mart_to_ybt_mapping": "project.view",
    "scenario_business_mapping": "project.view",
    "scenario_technical_lineage": "lineage.view",
}

_ENTITY_MODEL: dict[EntityType, type[Any]] = {
    "target_table": TargetTable, "target_field": TargetField,
    "mart_table": MartTable, "mart_field": MartField,
    "source_table": SourceTable, "source_field": SourceField,
    "scenario": ProductScenario, "knowledge_unit": KnowledgeUnit,
    "source_to_mart_mapping": SourceToMartMapping,
    "mart_to_ybt_mapping": MartToYbtMapping,
    "scenario_business_mapping": ScenarioBusinessMapping,
    "scenario_technical_lineage": ScenarioTechnicalLineage,
}


class SemanticCatalogQueryService:
    """Read-only projection over the governed semantic source tables."""

    def __init__(self, db: Session, project: Project, permissions: set[str]):
        self.db = db
        self.project = project
        self.permissions = permissions

    def list_catalog(
        self, *, as_of: date, mode: CatalogMode = "candidate",
        query: str | None = None,
        concept_types: list[ConceptType] | None = None,
        domains: list[str] | None = None,
        owners: list[str] | None = None,
        statuses: list[SemanticStatus] | None = None,
        has_binding: bool | None = None,
        has_relation: bool | None = None,
        pending_review: bool | None = None,
        page: int = 1, page_size: int = 50,
    ) -> SemanticCatalogPage:
        allowed_statuses = self._statuses_for_mode(mode)
        if statuses and not set(statuses).issubset(allowed_statuses):
            raise ValueError(f"Status filter is not visible in {mode} mode")

        statement = select(SemanticConcept).where(
            SemanticConcept.project_id == self.project.id,
            SemanticConcept.status.in_(allowed_statuses),
        )
        if self.project.institution_id is None:
            statement = statement.where(SemanticConcept.institution_id.is_(None))
        else:
            statement = statement.where(
                SemanticConcept.institution_id == self.project.institution_id
            )
        concepts = list(self.db.scalars(statement).all())
        concept_ids = [concept.id for concept in concepts]

        effective = resolve_effective_versions(
            self.db, concept_ids, as_of, project_id=self.project.id
        )
        bindings = self._confirmed_bindings(concept_ids)
        binding_counts = Counter(binding.semantic_concept_id for binding in bindings)
        relation_ids = self._confirmed_relation_ids(concept_ids)
        reviews = self._review_summaries(concept_ids)
        question_counts = self._open_question_counts(concept_ids)

        filtered = [
            concept for concept in concepts
            if self._matches(
                concept, effective.get(concept.id), query=query,
                concept_types=concept_types, domains=domains, owners=owners,
                statuses=statuses, has_binding=has_binding,
                has_relation=has_relation, pending_review=pending_review,
                binding_counts=binding_counts, relation_ids=relation_ids,
                reviews=reviews,
            )
        ]
        filtered.sort(
            key=lambda concept: self._sort_key(concept, effective.get(concept.id))
        )
        total = len(filtered)
        page_concepts = filtered[(page - 1) * page_size : page * page_size]
        page_ids = {concept.id for concept in page_concepts}
        asset_refs = self._asset_references([
            binding for binding in bindings
            if binding.semantic_concept_id in page_ids
        ])
        all_items = [
            self._item(
                concept, effective.get(concept.id), binding_counts, relation_ids,
                reviews, question_counts, asset_refs,
            )
            for concept in filtered
        ]
        item_by_id = {item.id: item for item in all_items}
        return SemanticCatalogPage(
            items=[item_by_id[concept.id] for concept in page_concepts],
            total=total, page=page, page_size=page_size, as_of=as_of, mode=mode,
            facets=self._facets(all_items),
        )

    @staticmethod
    def _statuses_for_mode(mode: CatalogMode) -> tuple[str, ...]:
        if mode == "audit":
            return audit_only_statuses()
        visibility = (
            SemanticVisibilityMode.TRUSTED
            if mode == "trusted" else SemanticVisibilityMode.CANDIDATE
        )
        return statuses_for(visibility)

    def _confirmed_bindings(self, concept_ids: list[int]) -> list[SemanticBinding]:
        if not concept_ids:
            return []
        return list(self.db.scalars(select(SemanticBinding).where(
            SemanticBinding.project_id == self.project.id,
            SemanticBinding.semantic_concept_id.in_(concept_ids),
            SemanticBinding.status == "confirmed",
        )).all())

    def _confirmed_relation_ids(self, concept_ids: list[int]) -> set[int]:
        if not concept_ids:
            return set()
        rows = self.db.execute(select(
            SemanticRelation.source_concept_id, SemanticRelation.target_concept_id,
        ).where(
            SemanticRelation.project_id == self.project.id,
            SemanticRelation.status == "confirmed",
            or_(
                SemanticRelation.source_concept_id.in_(concept_ids),
                SemanticRelation.target_concept_id.in_(concept_ids),
            ),
        )).all()
        visible_ids = set(concept_ids)
        return {
            concept_id for source_id, target_id in rows
            for concept_id in (int(source_id), int(target_id))
            if concept_id in visible_ids
        }

    def _review_summaries(
        self, concept_ids: list[int]
    ) -> dict[int, SemanticCatalogReviewSummary]:
        if not concept_ids:
            return {}
        tasks = list(self.db.scalars(select(ReviewTask).where(
            ReviewTask.project_id == self.project.id,
            ReviewTask.target_type == "semantic_concept",
            ReviewTask.target_id.in_(concept_ids),
            ReviewTask.status.in_(("pending", "claimed")),
        ).order_by(ReviewTask.target_id, ReviewTask.created_at, ReviewTask.id)).all())
        grouped: dict[int, list[ReviewTask]] = defaultdict(list)
        for task in tasks:
            grouped[task.target_id].append(task)
        return {
            concept_id: SemanticCatalogReviewSummary(
                pending=True, pending_count=len(concept_tasks),
                task_id=concept_tasks[0].id, status=concept_tasks[0].status,
                current_step=concept_tasks[0].step_key,
            )
            for concept_id, concept_tasks in grouped.items()
        }

    def _open_question_counts(self, concept_ids: list[int]) -> Counter[int]:
        if not concept_ids:
            return Counter()
        rows = self.db.execute(select(PendingQuestion.source_id).where(
            PendingQuestion.project_id == self.project.id,
            PendingQuestion.source_type == "semantic_concept",
            PendingQuestion.source_id.in_(concept_ids),
            PendingQuestion.question_status == "open",
        )).all()
        return Counter(int(source_id) for (source_id,) in rows if source_id is not None)

    @staticmethod
    def _matches(
        concept: SemanticConcept, version: Any, *, query: str | None,
        concept_types: list[ConceptType] | None, domains: list[str] | None,
        owners: list[str] | None, statuses: list[SemanticStatus] | None,
        has_binding: bool | None, has_relation: bool | None,
        pending_review: bool | None, binding_counts: Counter[int],
        relation_ids: set[int],
        reviews: dict[int, SemanticCatalogReviewSummary],
    ) -> bool:
        business_domain = version.business_domain if version is not None else concept.business_domain
        owner = version.owner_department if version is not None else concept.owner_department
        if concept_types and concept.concept_type not in concept_types:
            return False
        if domains and business_domain not in domains:
            return False
        if owners and owner not in owners:
            return False
        if statuses and concept.status not in statuses:
            return False
        if has_binding is not None and bool(binding_counts[concept.id]) != has_binding:
            return False
        if has_relation is not None and (concept.id in relation_ids) != has_relation:
            return False
        if pending_review is not None and (concept.id in reviews) != pending_review:
            return False
        if query and query.strip():
            needle = query.strip().casefold()
            aliases = list(concept.aliases_json or [])
            if version is not None:
                aliases.extend(version.aliases_json or [])
            haystack = [concept.concept_code, concept.concept_name, *aliases,
                        version.definition if version is not None else concept.definition]
            if not any(needle in str(value).casefold() for value in haystack if value):
                return False
        return True

    @staticmethod
    def _sort_key(concept: SemanticConcept, version: Any) -> tuple[Any, ...]:
        business_domain = version.business_domain if version is not None else concept.business_domain
        return (
            business_domain is None or not business_domain.strip(),
            (business_domain or "").casefold(), concept.concept_code.casefold(),
            concept.concept_name.casefold(), concept.id,
        )

    def _asset_references(
        self, bindings: list[SemanticBinding]
    ) -> dict[int, list[SemanticAssetReference]]:
        result: dict[int, list[SemanticAssetReference]] = defaultdict(list)
        readable_ids: dict[EntityType, set[int]] = defaultdict(set)
        for binding in bindings:
            entity_type: EntityType = binding.entity_type
            if _ENTITY_PERMISSION[entity_type] in self.permissions:
                readable_ids[entity_type].add(binding.entity_id)

        entities: dict[tuple[EntityType, int], Any] = {}
        for entity_type, entity_ids in readable_ids.items():
            model = _ENTITY_MODEL[entity_type]
            rows = self.db.scalars(select(model).where(
                model.project_id == self.project.id,
                model.id.in_(entity_ids),
            )).all()
            entities.update({(entity_type, row.id): row for row in rows})

        for binding in sorted(bindings, key=lambda row: (row.semantic_concept_id, row.id)):
            entity_type: EntityType = binding.entity_type
            entity = entities.get((entity_type, binding.entity_id))
            if entity is None:
                reference: SemanticAssetReference = RestrictedSemanticAssetReference(
                    entity_type=entity_type
                )
            else:
                name, code, href = self._describe_asset(entity_type, entity)
                reference = ReadableSemanticAssetReference(
                    entity_type=entity_type, entity_id=entity.id,
                    display_name=name[:255], display_code=code, href=href,
                )
            result[binding.semantic_concept_id].append(reference)
        return result

    @staticmethod
    def _describe_asset(entity_type: EntityType, entity: Any) -> tuple[str, str | None, str | None]:
        if entity_type.endswith("_table"):
            return entity.table_name, entity.table_code, None
        if entity_type.endswith("_field"):
            return entity.field_name, entity.field_code, None
        if entity_type == "scenario":
            return entity.scenario_name, entity.scenario_code, None
        if entity_type == "knowledge_unit":
            return entity.title or entity.source_file_name, None, None
        if entity_type in {"source_to_mart_mapping", "mart_to_ybt_mapping"}:
            return entity.mapping_name or entity_type.replace("_", " "), None, None
        if entity_type == "scenario_business_mapping":
            return entity.business_definition or "scenario business mapping", None, None
        return (
            entity.source_field_chinese_name or entity.source_table_chinese_name
            or entity.source_field_english_name or entity.source_table_english_name
            or "scenario technical lineage", None, "/lineage",
        )

    @staticmethod
    def _item(
        concept: SemanticConcept, version: Any, binding_counts: Counter[int],
        relation_ids: set[int],
        reviews: dict[int, SemanticCatalogReviewSummary],
        question_counts: Counter[int],
        asset_refs: dict[int, list[SemanticAssetReference]],
    ) -> SemanticCatalogItem:
        effective_version = None
        if version is not None:
            effective_version = SemanticCatalogEffectiveVersion(
                id=version.id, version_no=version.version_no,
                concept_name=version.concept_name, definition=version.definition,
                aliases=list(version.aliases_json or []),
                business_domain=version.business_domain,
                owner_department=version.owner_department, status="confirmed",
                source_type=version.source_type, source_id=version.source_id,
                confirmed_by=version.confirmed_by, confirmed_at=version.confirmed_at,
                effective_from=version.effective_from, effective_to=version.effective_to,
                updated_at=version.updated_at,
            )
        return SemanticCatalogItem(
            id=concept.id, project_id=concept.project_id,
            concept_type=concept.concept_type, concept_code=concept.concept_code,
            concept_name=concept.concept_name, status=concept.status,
            business_domain=version.business_domain if version is not None else concept.business_domain,
            owner_department=version.owner_department if version is not None else concept.owner_department,
            effective_version=effective_version,
            related_asset_count=binding_counts[concept.id],
            related_assets=asset_refs.get(concept.id, []),
            has_relation=concept.id in relation_ids,
            open_question_count=question_counts[concept.id],
            review=reviews.get(concept.id, SemanticCatalogReviewSummary()),
            updated_at=concept.updated_at,
        )

    @staticmethod
    def _facets(items: list[SemanticCatalogItem]) -> SemanticCatalogFacets:
        return SemanticCatalogFacets(
            concept_types=dict(sorted(Counter(item.concept_type for item in items).items())),
            business_domains=dict(sorted(Counter(
                item.business_domain or "__uncategorized__" for item in items
            ).items())),
            owners=dict(sorted(Counter(
                item.owner_department or "__unowned__" for item in items
            ).items())),
            statuses=dict(sorted(Counter(item.status for item in items).items())),
        )


__all__ = ["SemanticCatalogQueryService"]
