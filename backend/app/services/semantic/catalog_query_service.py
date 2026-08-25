from collections import Counter, defaultdict
from datetime import date
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import (
    AuditLog, KnowledgeUnit, LineageEdge, LineageNode, MappingEvidenceReference,
    MartField, MartTable, MartToYbtMapping, PendingQuestion, ProductScenario,
    Project, ReviewTask, ScenarioBusinessMapping, ScenarioTechnicalLineage,
    SemanticBinding, SemanticConcept, SemanticConceptVersion, SemanticRelation,
    SourceField, SourceTable, SourceToMartMapping, TargetField, TargetTable,
)
from app.schemas.semantic import ConceptType, EntityType, SemanticStatus
from app.schemas.semantic_catalog import (
    BoundedRegionMetadata, CatalogMode, ReadableSemanticAssetReference,
    ReadableSemanticDetailReference, RestrictedSemanticAssetReference,
    RestrictedSemanticDetailReference, SemanticAssetReference,
    SemanticBindingChain, SemanticBindingProjection, SemanticBindingRegion,
    SemanticCatalogEffectiveVersion, SemanticCatalogFacets, SemanticCatalogItem,
    SemanticCatalogPage, SemanticCatalogReviewSummary, SemanticDetailConflictSource,
    SemanticDetailConflictSummary, SemanticDetailQuestionSummary,
    SemanticDetailReference, SemanticDetailRegionCapability,
    SemanticDetailReviewWorkflow, SemanticDetailShell, SemanticDetailVersion,
    SemanticEvidencePartition, SemanticEvidenceProjection, SemanticEvidenceRegion,
    SemanticGovernanceAuditEvent, SemanticGovernanceRegion, SemanticLineagePath,
    SemanticLineageRegion, SemanticRelationProjection, SemanticRelationRegion,
    SemanticVersionRegion,
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

_REGION_LIMIT = 100
_CHAIN_NODE_LIMIT = 13
_OPEN_QUESTION_STATUSES = ("open", "assigned", "answered")
_CANDIDATE_STATUSES = ("draft", "ai_suggested")
_AUDIT_STATUSES = ("rejected", "deprecated")
_MAPPING_TYPES = {
    "source_to_mart_mapping": "source_to_mart",
    "mart_to_ybt_mapping": "mart_to_ybt",
    "scenario_business_mapping": "scenario_business",
    "scenario_technical_lineage": "scenario_technical",
}


class SemanticCatalogQueryService:
    """Read-only projection over the governed semantic source tables."""

    def __init__(self, db: Session, project: Project, permissions: set[str]):
        self.db = db
        self.project = project
        self.permissions = permissions

    def get_detail_shell(
        self, concept_id: int, *, as_of: date, include_audit: bool = False
    ) -> SemanticDetailShell:
        concept = self._detail_concept(concept_id, include_audit=include_audit)
        effective = resolve_effective_versions(
            self.db, [concept.id], as_of, project_id=self.project.id,
            institution_id=self.project.institution_id,
        ).get(concept.id)
        candidates = list(self.db.scalars(select(SemanticConceptVersion).where(
            SemanticConceptVersion.project_id == self.project.id,
            SemanticConceptVersion.semantic_concept_id == concept.id,
            SemanticConceptVersion.status.in_(_CANDIDATE_STATUSES),
        ).order_by(
            SemanticConceptVersion.version_no,
            SemanticConceptVersion.id,
        ).limit(20)).all())
        questions = self._detail_questions(concept.id)
        return SemanticDetailShell(
            id=concept.id,
            project_id=concept.project_id,
            concept_type=concept.concept_type,
            concept_code=concept.concept_code,
            concept_name=concept.concept_name,
            lifecycle_status=concept.status,
            effective_as_of=as_of,
            effective_version=self._detail_version(effective) if effective is not None else None,
            candidate_versions=[self._detail_version(row) for row in candidates],
            review_workflow=self._detail_review(concept.id),
            open_questions=questions,
            conflicts=self._conflicts(questions),
            regions={
                "bindings": SemanticDetailRegionCapability(
                    temporal_scope="current_only", supports_audit=True, max_items=_REGION_LIMIT
                ),
                "relations": SemanticDetailRegionCapability(
                    temporal_scope="current_only", supports_audit=True, max_items=_REGION_LIMIT
                ),
                "evidence": SemanticDetailRegionCapability(
                    temporal_scope="current_only", supports_audit=True, max_items=_REGION_LIMIT
                ),
                "lineage": SemanticDetailRegionCapability(
                    temporal_scope="current_only", supports_audit=False, max_items=_REGION_LIMIT
                ),
                "governance": SemanticDetailRegionCapability(
                    temporal_scope="mixed", supports_audit=True, max_items=_REGION_LIMIT
                ),
                "versions": SemanticDetailRegionCapability(
                    temporal_scope="as_of", supports_audit=True, max_items=_REGION_LIMIT
                ),
            },
        )

    def get_bindings(
        self, concept_id: int, *, as_of: date, include_audit: bool = False
    ) -> SemanticBindingRegion:
        concept = self._detail_concept(concept_id, include_audit=include_audit)
        partitions, totals = self._partitioned_rows(
            SemanticBinding,
            SemanticBinding.project_id == self.project.id,
            SemanticBinding.semantic_concept_id == concept.id,
            include_audit=include_audit,
        )
        all_rows = [row for rows in partitions.values() for row in rows]
        references = self._detail_asset_references(all_rows, concept.id)

        def project(row: SemanticBinding) -> SemanticBindingProjection:
            return SemanticBindingProjection(
                id=row.id,
                binding_type=row.binding_type,
                confidence_level=row.confidence_level,
                confidence_score=row.confidence_score,
                status=row.status,
                source_type=row.source_type,
                source_id=row.source_id,
                confirmed_by=row.confirmed_by,
                confirmed_at=row.confirmed_at,
                target=references[row.id],
            )

        confirmed = [project(row) for row in partitions["confirmed"]]
        candidates = [project(row) for row in partitions["candidates"]]
        audit = [project(row) for row in partitions["audit"]]
        chain, chain_meta = self._binding_chain(concept, confirmed)
        return SemanticBindingRegion(
            concept_id=concept.id,
            as_of=as_of,
            current_only=True,
            confirmed=confirmed,
            candidates=candidates,
            audit=audit,
            confirmed_meta=self._meta(totals["confirmed"], confirmed),
            candidate_meta=self._meta(totals["candidates"], candidates),
            audit_meta=self._meta(totals["audit"], audit),
            chains=[chain] if chain is not None else [],
            chain_meta=chain_meta,
        )

    def get_relations(
        self, concept_id: int, *, as_of: date, include_audit: bool = False
    ) -> SemanticRelationRegion:
        concept = self._detail_concept(concept_id, include_audit=include_audit)
        partitions, _ = self._partitioned_rows(
            SemanticRelation,
            SemanticRelation.project_id == self.project.id,
            or_(
                SemanticRelation.source_concept_id == concept.id,
                SemanticRelation.target_concept_id == concept.id,
            ),
            include_audit=include_audit,
        )
        all_rows = [row for rows in partitions.values() for row in rows]
        related_ids = {
            row.target_concept_id if row.source_concept_id == concept.id else row.source_concept_id
            for row in all_rows
        }
        statement = select(SemanticConcept).where(
            SemanticConcept.project_id == self.project.id,
            SemanticConcept.id.in_(related_ids),
        )
        statement = self._institution_scope(statement, SemanticConcept)
        related = {row.id: row for row in self.db.scalars(statement).all()}

        def project(row: SemanticRelation) -> SemanticRelationProjection | None:
            outgoing = row.source_concept_id == concept.id
            related_id = row.target_concept_id if outgoing else row.source_concept_id
            target = related.get(related_id)
            if target is None or target.status in _AUDIT_STATUSES and row.status not in _AUDIT_STATUSES:
                return None
            if row.status == "confirmed" and target.status != "confirmed":
                return None
            return SemanticRelationProjection(
                id=row.id,
                direction="outgoing" if outgoing else "incoming",
                relation_type=row.relation_type,
                status=row.status,
                confidence_level=row.confidence_level,
                confidence_score=row.confidence_score,
                source_type=row.source_type,
                source_id=row.source_id,
                related_concept=ReadableSemanticDetailReference(
                    entity_type="semantic_concept",
                    entity_id=target.id,
                    display_name=target.concept_name,
                    display_code=target.concept_code,
                    href=f"/semantics/{target.id}",
                ),
            )

        projected = {
            name: [item for row in rows if (item := project(row)) is not None]
            for name, rows in partitions.items()
        }
        return SemanticRelationRegion(
            concept_id=concept.id,
            as_of=as_of,
            current_only=True,
            confirmed=projected["confirmed"],
            candidates=projected["candidates"],
            audit=projected["audit"],
            confirmed_meta=self._meta(len(projected["confirmed"]), projected["confirmed"]),
            candidate_meta=self._meta(len(projected["candidates"]), projected["candidates"]),
            audit_meta=self._meta(len(projected["audit"]), projected["audit"]),
        )

    def get_evidence(
        self, concept_id: int, *, as_of: date, include_audit: bool = False
    ) -> SemanticEvidenceRegion:
        concept = self._detail_concept(concept_id, include_audit=include_audit)
        partitions, _ = self._partitioned_rows(
            SemanticBinding,
            SemanticBinding.project_id == self.project.id,
            SemanticBinding.semantic_concept_id == concept.id,
            include_audit=include_audit,
        )
        projected = {
            name: self._evidence_partition(rows, concept.id)
            for name, rows in partitions.items()
        }
        return SemanticEvidenceRegion(
            concept_id=concept.id,
            as_of=as_of,
            current_only=True,
            confirmed=projected["confirmed"],
            candidates=projected["candidates"],
            audit=projected["audit"],
        )

    def get_lineage(self, concept_id: int, *, as_of: date) -> SemanticLineageRegion:
        concept = self._detail_concept(concept_id, include_audit=False)
        bindings = list(self.db.scalars(select(SemanticBinding).where(
            SemanticBinding.project_id == self.project.id,
            SemanticBinding.semantic_concept_id == concept.id,
            SemanticBinding.status == "confirmed",
            SemanticBinding.entity_type.in_((
                "target_table", "target_field", "mart_table", "mart_field",
                "source_table", "source_field",
            )),
        ).order_by(SemanticBinding.id).limit(_REGION_LIMIT)).all())
        node_conditions = []
        column_by_entity = {
            "target_table": LineageNode.target_table_id,
            "target_field": LineageNode.target_field_id,
            "mart_table": LineageNode.mart_table_id,
            "mart_field": LineageNode.mart_field_id,
            "source_table": LineageNode.source_table_id,
            "source_field": LineageNode.source_field_id,
        }
        for entity_type, column in column_by_entity.items():
            ids = [row.entity_id for row in bindings if row.entity_type == entity_type]
            if ids:
                node_conditions.append(column.in_(ids))
        nodes: list[LineageNode] = []
        if node_conditions:
            node_statement = select(LineageNode).where(
                LineageNode.project_id == self.project.id,
                or_(*node_conditions),
            )
            node_statement = self._institution_scope(node_statement, LineageNode)
            nodes = list(self.db.scalars(
                node_statement.order_by(LineageNode.id).limit(_REGION_LIMIT)
            ).all())
        node_by_id = {row.id: row for row in nodes}
        node_references = self._lineage_node_references(nodes, concept.id)
        edges: list[LineageEdge] = []
        if node_by_id:
            node_ids = list(node_by_id)
            edges = list(self.db.scalars(select(LineageEdge).where(
                LineageEdge.project_id == self.project.id,
                LineageEdge.enabled.is_(True),
                LineageEdge.source_node_id.in_(node_ids),
                LineageEdge.target_node_id.in_(node_ids),
            ).order_by(LineageEdge.id).limit(_REGION_LIMIT)).all())
        verified: list[SemanticLineagePath] = []
        candidates: list[SemanticLineagePath] = []
        for edge in edges:
            source = node_by_id.get(edge.source_node_id)
            target = node_by_id.get(edge.target_node_id)
            if source is None or target is None:
                continue
            is_verified = not source.unresolved_flag and not target.unresolved_flag
            item = SemanticLineagePath(
                id=edge.id,
                status="verified" if is_verified else "unresolved",
                source=node_references[source.id],
                target=node_references[target.id],
                relation=edge.edge_type,
                transformation=edge.transformation_expression,
                evidence=[],
            )
            (verified if is_verified else candidates).append(item)
        return SemanticLineageRegion(
            concept_id=concept.id,
            as_of=as_of,
            current_only=True,
            verified=verified,
            candidates=candidates,
            audit=[],
            verified_meta=self._meta(len(verified), verified),
            candidate_meta=self._meta(len(candidates), candidates),
            audit_meta=self._meta(0, []),
        )

    def get_governance(
        self, concept_id: int, *, as_of: date, include_audit: bool = False
    ) -> SemanticGovernanceRegion:
        concept = self._detail_concept(concept_id, include_audit=include_audit)
        questions = self._detail_questions(concept.id)
        events: list[SemanticGovernanceAuditEvent] = []
        total_events = 0
        if include_audit:
            event_statement = select(AuditLog).where(
                AuditLog.project_id == self.project.id,
                AuditLog.resource_type == "semantic_concept",
                AuditLog.resource_id == str(concept.id),
            )
            total_events = int(self.db.scalar(select(func.count()).select_from(
                event_statement.subquery()
            )) or 0)
            rows = list(self.db.scalars(event_statement.order_by(
                AuditLog.created_at.desc(), AuditLog.id.desc()
            ).limit(_REGION_LIMIT)).all())
            for row in rows:
                after = dict(row.after_summary_json or {})
                before = dict(row.before_summary_json or {})
                status = after.get("status") or before.get("status")
                if status not in {"draft", "ai_suggested", "confirmed", "rejected", "deprecated"}:
                    status = None
                events.append(SemanticGovernanceAuditEvent(
                    id=row.id,
                    event_type=row.action,
                    status=status,
                    summary=row.action.replace("_", " "),
                    actor=str(row.actor_user_id) if row.actor_user_id is not None else None,
                    occurred_at=row.created_at,
                ))
        return SemanticGovernanceRegion(
            concept_id=concept.id,
            as_of=as_of,
            current_only=True,
            lifecycle_status=concept.status,
            review_workflow=self._detail_review(concept.id),
            open_questions=questions,
            conflicts=self._conflicts(questions),
            audit_events=events,
            audit_meta=self._meta(total_events, events),
        )

    def get_versions(
        self, concept_id: int, *, as_of: date, include_audit: bool = False
    ) -> SemanticVersionRegion:
        concept = self._detail_concept(concept_id, include_audit=include_audit)
        partitions, totals = self._partitioned_rows(
            SemanticConceptVersion,
            SemanticConceptVersion.project_id == self.project.id,
            SemanticConceptVersion.semantic_concept_id == concept.id,
            include_audit=include_audit,
            order_by=(
                SemanticConceptVersion.effective_from,
                SemanticConceptVersion.version_no,
                SemanticConceptVersion.id,
            ),
        )
        effective = resolve_effective_versions(
            self.db, [concept.id], as_of, project_id=self.project.id,
            institution_id=self.project.institution_id,
        ).get(concept.id)
        current = resolve_effective_versions(
            self.db, [concept.id], date.today(), project_id=self.project.id,
            institution_id=self.project.institution_id,
        ).get(concept.id)
        projected = {
            name: [self._detail_version(row) for row in rows]
            for name, rows in partitions.items()
        }
        return SemanticVersionRegion(
            concept_id=concept.id,
            as_of=as_of,
            effective_version_id=effective.id if effective is not None else None,
            current_effective_version_id=current.id if current is not None else None,
            confirmed=projected["confirmed"],
            candidates=projected["candidates"],
            audit=projected["audit"],
            confirmed_meta=self._meta(totals["confirmed"], projected["confirmed"]),
            candidate_meta=self._meta(totals["candidates"], projected["candidates"]),
            audit_meta=self._meta(totals["audit"], projected["audit"]),
        )

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
            self.db, concept_ids, as_of, project_id=self.project.id,
            institution_id=self.project.institution_id,
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

    def _detail_concept(
        self, concept_id: int, *, include_audit: bool
    ) -> SemanticConcept:
        statuses = set(statuses_for(SemanticVisibilityMode.CANDIDATE))
        if include_audit:
            statuses.update(_AUDIT_STATUSES)
        statement = select(SemanticConcept).where(
            SemanticConcept.project_id == self.project.id,
            SemanticConcept.id == concept_id,
            SemanticConcept.status.in_(sorted(statuses)),
        )
        statement = self._institution_scope(statement, SemanticConcept)
        concept = self.db.scalar(statement)
        if concept is None:
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail="SemanticConcept not found")
        return concept

    def _institution_scope(self, statement: Any, model: type[Any]) -> Any:
        if not hasattr(model, "institution_id"):
            return statement
        if self.project.institution_id is None:
            return statement.where(model.institution_id.is_(None))
        return statement.where(model.institution_id == self.project.institution_id)

    def _partitioned_rows(
        self,
        model: type[Any],
        *conditions: Any,
        include_audit: bool,
        order_by: tuple[Any, ...] | None = None,
    ) -> tuple[dict[str, list[Any]], dict[str, int]]:
        count_rows = self.db.execute(select(
            model.status, func.count(model.id)
        ).where(*conditions).group_by(model.status)).all()
        status_counts = {str(status): int(count) for status, count in count_rows}
        groups = {
            "confirmed": ("confirmed",),
            "candidates": _CANDIDATE_STATUSES,
            "audit": _AUDIT_STATUSES if include_audit else (),
        }
        rows: dict[str, list[Any]] = {}
        totals: dict[str, int] = {}
        stable_order = order_by or (model.id,)
        for name, group_statuses in groups.items():
            totals[name] = sum(status_counts.get(status, 0) for status in group_statuses)
            if not group_statuses:
                rows[name] = []
                continue
            rows[name] = list(self.db.scalars(select(model).where(
                *conditions,
                model.status.in_(group_statuses),
            ).order_by(*stable_order).limit(_REGION_LIMIT)).all())
        return rows, totals

    @staticmethod
    def _meta(total: int, items: list[Any]) -> BoundedRegionMetadata:
        return BoundedRegionMetadata(
            total=total,
            returned=len(items),
            limit=_REGION_LIMIT,
        )

    @staticmethod
    def _detail_version(version: SemanticConceptVersion) -> SemanticDetailVersion:
        scalar_provenance = {
            str(key): value
            for key, value in dict(version.provenance_json or {}).items()
            if value is None or isinstance(value, (str, int, float, bool))
        }
        return SemanticDetailVersion(
            id=version.id,
            version_no=version.version_no,
            concept_name=version.concept_name,
            definition=version.definition,
            description=version.description,
            aliases=list(version.aliases_json or []),
            business_domain=version.business_domain,
            owner_department=version.owner_department,
            provenance=scalar_provenance,
            status=version.status,
            confidence_level=version.confidence_level,
            source_type=version.source_type,
            source_id=version.source_id,
            created_by=version.created_by,
            confirmed_by=version.confirmed_by,
            confirmed_at=version.confirmed_at,
            effective_from=version.effective_from,
            effective_to=version.effective_to,
            created_at=version.created_at,
            updated_at=version.updated_at,
        )

    def _detail_review(self, concept_id: int) -> SemanticDetailReviewWorkflow:
        tasks = list(self.db.scalars(select(ReviewTask).where(
            ReviewTask.project_id == self.project.id,
            ReviewTask.target_type == "semantic_concept",
            ReviewTask.target_id == concept_id,
            ReviewTask.status.in_(("pending", "claimed")),
        ).order_by(ReviewTask.created_at, ReviewTask.id).limit(20)).all())
        if not tasks:
            return SemanticDetailReviewWorkflow()
        task = tasks[0]
        return SemanticDetailReviewWorkflow(
            pending=True,
            pending_count=len(tasks),
            task_id=task.id,
            status=task.status,
            current_step=task.step_key,
            assigned_role=task.assignee_role,
            assigned_user_id=task.assignee_user_id,
            due_at=task.due_at,
            href=f"/tasks/{task.id}?from=semantics&semanticConceptId={concept_id}",
        )

    def _detail_questions(self, concept_id: int) -> list[SemanticDetailQuestionSummary]:
        rows = list(self.db.scalars(select(PendingQuestion).where(
            PendingQuestion.project_id == self.project.id,
            PendingQuestion.source_type == "semantic_concept",
            PendingQuestion.source_id == concept_id,
            PendingQuestion.question_status.in_(_OPEN_QUESTION_STATUSES),
        ).order_by(PendingQuestion.priority.desc(), PendingQuestion.id).limit(_REGION_LIMIT)).all())
        return [SemanticDetailQuestionSummary(
            id=row.id,
            question_type=row.question_type,
            question_text=row.question_text,
            question_status=row.question_status,
            priority=row.priority,
            source_type=row.source_type,
            source_id=row.source_id,
            review_href=f"/review-tasks?from=semantics&semanticConceptId={concept_id}",
        ) for row in rows]

    @staticmethod
    def _conflicts(
        questions: list[SemanticDetailQuestionSummary],
    ) -> list[SemanticDetailConflictSummary]:
        return [SemanticDetailConflictSummary(
            conflict_key=f"question:{question.id}",
            summary=question.question_text,
            sources=[SemanticDetailConflictSource(
                source_type=question.source_type or "pending_question",
                source_id=question.source_id,
                summary=question.question_text,
                authority="high" if question.priority == "high" else None,
            )],
            review_href=question.review_href,
        ) for question in questions if "conflict" in question.question_type.casefold()]

    def _detail_asset_references(
        self, bindings: list[SemanticBinding], concept_id: int
    ) -> dict[int, SemanticDetailReference]:
        readable_ids: dict[EntityType, set[int]] = defaultdict(set)
        for binding in bindings:
            entity_type: EntityType = binding.entity_type
            if _ENTITY_PERMISSION[entity_type] in self.permissions:
                readable_ids[entity_type].add(binding.entity_id)

        entities: dict[tuple[EntityType, int], Any] = {}
        for entity_type, entity_ids in readable_ids.items():
            model = _ENTITY_MODEL[entity_type]
            statement = select(model).where(
                model.project_id == self.project.id,
                model.id.in_(entity_ids),
            )
            entities.update({
                (entity_type, row.id): row for row in self.db.scalars(statement).all()
            })

        result: dict[int, SemanticDetailReference] = {}
        for binding in bindings:
            entity_type: EntityType = binding.entity_type
            entity = entities.get((entity_type, binding.entity_id))
            if entity is None:
                result[binding.id] = RestrictedSemanticDetailReference(
                    entity_type=entity_type
                )
                continue
            name, code, href = self._describe_detail_asset(
                entity_type, entity, concept_id
            )
            result[binding.id] = ReadableSemanticDetailReference(
                entity_type=entity_type,
                entity_id=entity.id,
                display_name=name[:255],
                display_code=code,
                href=href,
            )
        return result

    @staticmethod
    def _describe_detail_asset(
        entity_type: EntityType, entity: Any, concept_id: int
    ) -> tuple[str, str | None, str | None]:
        suffix = f"from=semantics&semanticConceptId={concept_id}"
        if entity_type == "target_table":
            return entity.table_name, entity.table_code, f"/fields?targetTableId={entity.id}&{suffix}"
        if entity_type == "target_field":
            return entity.field_name, entity.field_code, f"/fields/{entity.id}/scenarios?{suffix}"
        if entity_type == "mart_table":
            return entity.table_name, entity.table_code, f"/mart?martTableId={entity.id}&{suffix}"
        if entity_type == "mart_field":
            return entity.field_name, entity.field_code, f"/mart?martFieldId={entity.id}&{suffix}"
        if entity_type == "source_table":
            return entity.table_name, entity.table_code, f"/catalog?sourceTableId={entity.id}&{suffix}"
        if entity_type == "source_field":
            return entity.field_name, entity.field_code, f"/catalog?sourceFieldId={entity.id}&{suffix}"
        if entity_type == "scenario":
            return entity.scenario_name, entity.scenario_code, None
        if entity_type == "knowledge_unit":
            return (
                entity.title or entity.source_file_name,
                None,
                f"/knowledge/documents/{entity.document_id}?unitId={entity.id}&{suffix}",
            )
        if entity_type in {"source_to_mart_mapping", "mart_to_ybt_mapping"}:
            name = entity.mapping_name or entity_type.replace("_", " ")
            return name, None, f"/mart?mappingType={_MAPPING_TYPES[entity_type]}&mappingId={entity.id}&{suffix}"
        if entity_type == "scenario_business_mapping":
            return entity.business_definition or "scenario business mapping", None, None
        name = (
            entity.source_field_chinese_name or entity.source_table_chinese_name
            or entity.source_field_english_name or entity.source_table_english_name
            or "scenario technical lineage"
        )
        return name, None, f"/lineage?scenarioTechnicalLineageId={entity.id}&{suffix}"

    def _binding_chain(
        self,
        concept: SemanticConcept,
        confirmed: list[SemanticBindingProjection],
    ) -> tuple[SemanticBindingChain | None, BoundedRegionMetadata]:
        if not confirmed:
            return None, BoundedRegionMetadata(total=0, returned=0, limit=_CHAIN_NODE_LIMIT)
        groups: dict[str, list[SemanticDetailReference]] = {
            "targets": [], "marts": [], "sources": []
        }
        seen: set[tuple[str, int | None]] = set()
        for item in confirmed:
            family = (
                "targets" if item.target.entity_type.startswith("target_") else
                "marts" if item.target.entity_type.startswith("mart_") else
                "sources" if item.target.entity_type.startswith("source_") else None
            )
            if family is None:
                continue
            key = (item.target.entity_type, getattr(item.target, "entity_id", None))
            if key not in seen:
                seen.add(key)
                groups[family].append(item.target)
        total = 1 + sum(len(items) for items in groups.values())
        chain = SemanticBindingChain(
            concept=ReadableSemanticDetailReference(
                entity_type="semantic_concept",
                entity_id=concept.id,
                display_name=concept.concept_name,
                display_code=concept.concept_code,
                href=f"/semantics/{concept.id}",
            ),
            targets=groups["targets"][:4],
            marts=groups["marts"][:4],
            sources=groups["sources"][:4],
        )
        returned = 1 + len(chain.targets) + len(chain.marts) + len(chain.sources)
        return chain, BoundedRegionMetadata(
            total=total,
            returned=returned,
            limit=_CHAIN_NODE_LIMIT,
        )

    def _evidence_partition(
        self, bindings: list[SemanticBinding], concept_id: int
    ) -> SemanticEvidencePartition:
        knowledge_bindings = {
            row.entity_id: row for row in bindings if row.entity_type == "knowledge_unit"
        }
        knowledge_rows: list[KnowledgeUnit] = []
        if knowledge_bindings:
            knowledge_rows = list(self.db.scalars(select(KnowledgeUnit).where(
                KnowledgeUnit.project_id == self.project.id,
                KnowledgeUnit.id.in_(knowledge_bindings),
                KnowledgeUnit.enabled.is_(True),
                KnowledgeUnit.confidentiality_level != "restricted",
            ).order_by(KnowledgeUnit.id).limit(_REGION_LIMIT)).all())
        knowledge = [SemanticEvidenceProjection(
            id=row.id,
            evidence_type=row.knowledge_type,
            title=row.title or row.source_file_name,
            location=row.source_heading or row.source_sheet_name,
            excerpt=row.content,
            authority="confirmed" if knowledge_bindings[row.id].status == "confirmed" else "candidate",
            status=knowledge_bindings[row.id].status,
            observed_at=row.updated_at,
            reference=ReadableSemanticDetailReference(
                entity_type="knowledge_unit",
                entity_id=row.id,
                display_name=row.title or row.source_file_name,
                href=(
                    f"/knowledge/documents/{row.document_id}?unitId={row.id}"
                    f"&from=semantics&semanticConceptId={concept_id}"
                ),
            ),
        ) for row in knowledge_rows]

        mapping_bindings = {
            (_MAPPING_TYPES[row.entity_type], row.entity_id): row
            for row in bindings if row.entity_type in _MAPPING_TYPES
        }
        evidence_rows: list[MappingEvidenceReference] = []
        if mapping_bindings:
            evidence_rows = list(self.db.scalars(select(MappingEvidenceReference).where(
                MappingEvidenceReference.project_id == self.project.id,
                or_(*[
                    (MappingEvidenceReference.mapping_type == mapping_type)
                    & (MappingEvidenceReference.mapping_id == mapping_id)
                    for mapping_type, mapping_id in mapping_bindings
                ]),
            ).order_by(MappingEvidenceReference.id).limit(_REGION_LIMIT)).all())
        evidence = []
        for row in evidence_rows:
            binding = mapping_bindings.get((row.mapping_type, row.mapping_id))
            if binding is None:
                continue
            evidence.append(SemanticEvidenceProjection(
                id=row.id,
                evidence_type=row.evidence_type,
                title=row.source_name,
                location=row.location_text,
                excerpt=row.quoted_content or row.evidence_summary,
                authority="confirmed" if binding.status == "confirmed" else "candidate",
                status=binding.status,
                observed_at=row.created_at,
                reference=None,
            ))
        return SemanticEvidencePartition(
            evidence=evidence,
            knowledge=knowledge,
            evidence_meta=self._meta(len(evidence), evidence),
            knowledge_meta=self._meta(len(knowledge), knowledge),
        )

    def _lineage_node_references(
        self, nodes: list[LineageNode], concept_id: int
    ) -> dict[int, SemanticDetailReference]:
        entity_attrs = (
            ("target_table", "target_table_id"),
            ("target_field", "target_field_id"),
            ("mart_table", "mart_table_id"),
            ("mart_field", "mart_field_id"),
            ("source_table", "source_table_id"),
            ("source_field", "source_field_id"),
        )
        entity_ids: dict[EntityType, set[int]] = defaultdict(set)
        node_entities: dict[int, tuple[EntityType, int]] = {}
        for node in nodes:
            for entity_type, attr in entity_attrs:
                entity_id = getattr(node, attr)
                if entity_id is not None:
                    node_entities[node.id] = (entity_type, entity_id)
                    if _ENTITY_PERMISSION[entity_type] in self.permissions:
                        entity_ids[entity_type].add(entity_id)
                    break
        entities: dict[tuple[EntityType, int], Any] = {}
        for entity_type, ids in entity_ids.items():
            model = _ENTITY_MODEL[entity_type]
            rows = self.db.scalars(select(model).where(
                model.project_id == self.project.id,
                model.id.in_(ids),
            )).all()
            entities.update({(entity_type, row.id): row for row in rows})
        result: dict[int, SemanticDetailReference] = {}
        for node in nodes:
            node_entity = node_entities.get(node.id)
            if node_entity is None:
                result[node.id] = ReadableSemanticDetailReference(
                    entity_type="lineage",
                    entity_id=node.id,
                    display_name=node.logical_name[:255],
                    href=(
                        f"/lineage?nodeId={node.id}&from=semantics"
                        f"&semanticConceptId={concept_id}"
                    ),
                )
                continue
            entity_type, entity_id = node_entity
            entity = entities.get((entity_type, entity_id))
            if entity is None:
                result[node.id] = RestrictedSemanticDetailReference(
                    entity_type=entity_type
                )
                continue
            name, code, href = self._describe_detail_asset(
                entity_type, entity, concept_id
            )
            result[node.id] = ReadableSemanticDetailReference(
                entity_type=entity_type,
                entity_id=entity.id,
                display_name=name,
                display_code=code,
                href=href,
            )
        return result

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
            PendingQuestion.question_status.in_(_OPEN_QUESTION_STATUSES),
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
