"""Projection-only RegulatoryContext orchestration."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models import Project
from app.schemas.regulatory_context import (
    ContextBuildMetadata,
    ContextInputScope,
    ContextScope,
    RegulatoryContext,
    RegulatoryContextRequest,
)
from app.services.semantic.context_collectors import collect_base_context


SEMANTIC_POLICY_VERSION = "semantic-status-policy-v1"
AUTHORITY_POLICY_VERSION = "context-authority-v1"


class RegulatoryContextBuilder:
    """Build a typed context from existing governed facts without persisting it."""

    def __init__(self, db: Session):
        self.db = db

    def build(
        self,
        request: RegulatoryContextRequest,
        *,
        authorized_project: Project,
    ) -> RegulatoryContext:
        if int(request.project_id) != int(authorized_project.id):
            raise ValueError("request project_id does not match the authorized project")

        collected = collect_base_context(self.db, authorized_project, request)
        facts = collected.all_facts()
        retrieval_log_ids = sorted({
            fact.provenance.retrieval_log_id
            for fact in facts
            if fact.provenance.retrieval_log_id is not None
        })
        source_count = len({(fact.source_type, fact.source_id) for fact in facts})
        input_scope = ContextInputScope(
            reporting_period=request.reporting_period,
            mode=request.mode,
            target_table_id=collected.target.target_table_id,
            target_field_id=collected.target.target_field_id,
            mart_field_id=collected.target.mart_field_id,
            semantic_concept_id=collected.target.semantic_concept_id,
            scenario_id=(collected.scenario.scenario_id if collected.scenario is not None else None),
            candidate_limit=request.candidate_limit,
        )
        metadata = ContextBuildMetadata(
            built_at=datetime.now(UTC),
            project_id=authorized_project.id,
            as_of=request.as_of,
            input_scope=input_scope,
            semantic_policy_version=SEMANTIC_POLICY_VERSION,
            authority_policy_version=AUTHORITY_POLICY_VERSION,
            retrieval_log_ids=retrieval_log_ids,
            mode=request.mode,
            fact_count=len(facts),
            conflict_count=0,
            open_question_count=0,
            source_count=source_count,
            collector_names=collected.collector_names,
        )
        return RegulatoryContext(
            scope=ContextScope(
                project_id=authorized_project.id,
                institution_id=authorized_project.institution_id,
                as_of=request.as_of,
                reporting_period=request.reporting_period,
                mode=request.mode,
            ),
            target=collected.target,
            scenario=collected.scenario,
            semantic=collected.semantic,
            regulatory=collected.regulatory,
            metadata=collected.metadata,
            candidates=collected.candidates,
            mappings=collected.mappings,
            lineage=collected.lineage,
            knowledge_evidence=collected.knowledge_evidence,
            historical=collected.historical,
            quality=collected.quality,
            conflicts=[],
            open_questions=[],
            build_metadata=metadata,
        )


__all__ = ["RegulatoryContextBuilder"]
