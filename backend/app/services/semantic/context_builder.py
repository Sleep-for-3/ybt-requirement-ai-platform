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
from app.services.semantic.context_collectors import CollectedContext, collect_base_context
from app.services.semantic.context_conflicts import build_open_questions, detect_conflicts


SEMANTIC_POLICY_VERSION = "semantic-status-policy-v1"
AUTHORITY_POLICY_VERSION = "context-authority-v1"
FACT_SECTION_LIMIT = 500
GLOBAL_FACT_LIMIT = 1000
CONFLICT_LIMIT = 200
OPEN_QUESTION_LIMIT = 200
TRUNCATION_WARNING = (
    "Regulatory context output was deterministically truncated to Contract limits."
)
FACT_SECTION_NAMES = (
    "semantic",
    "regulatory",
    "metadata",
    "candidates",
    "mappings",
    "lineage",
    "knowledge_evidence",
    "historical",
    "quality",
)


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
        truncated = _apply_fact_budgets(collected)
        facts = collected.all_facts()
        all_conflicts = detect_conflicts(collected)
        all_open_questions = build_open_questions(collected)
        conflicts = all_conflicts[:CONFLICT_LIMIT]
        open_questions = all_open_questions[:OPEN_QUESTION_LIMIT]
        truncated = truncated or len(conflicts) < len(all_conflicts)
        truncated = truncated or len(open_questions) < len(all_open_questions)
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
            conflict_count=len(conflicts),
            open_question_count=len(open_questions),
            source_count=source_count,
            collector_names=collected.collector_names,
            warnings=_bounded_warnings(collected.warnings, truncated=truncated),
            truncated=truncated,
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
            conflicts=conflicts,
            open_questions=open_questions,
            build_metadata=metadata,
        )


def _apply_fact_budgets(collected: CollectedContext) -> bool:
    """Apply Contract section and global budgets in stable schema order."""

    truncated = bool(getattr(collected, "truncated", False))
    remaining = GLOBAL_FACT_LIMIT
    for section_name in FACT_SECTION_NAMES:
        facts = list(getattr(collected, section_name))
        emitted = facts[:min(FACT_SECTION_LIMIT, remaining)]
        if len(emitted) < len(facts):
            truncated = True
        setattr(collected, section_name, emitted)
        remaining -= len(emitted)
    return truncated


def _bounded_warnings(warnings: list[str], *, truncated: bool) -> list[str]:
    result: list[str] = []
    for warning in warnings:
        normalized = str(warning).strip()
        if normalized and normalized not in result:
            result.append(normalized[:500])
        if len(result) == 50:
            break
    if truncated and TRUNCATION_WARNING not in result:
        if len(result) == 50:
            result[-1] = TRUNCATION_WARNING
        else:
            result.append(TRUNCATION_WARNING)
    return result


__all__ = ["RegulatoryContextBuilder"]
