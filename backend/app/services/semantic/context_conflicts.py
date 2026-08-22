"""Deterministic RegulatoryContext gaps and contradictions.

This module transforms collected facts only.  It never creates PendingQuestion
rows or treats historical/retrieved material as an authoritative winner.
"""

from __future__ import annotations

from app.schemas.regulatory_context import ContextConflict, ContextOpenQuestion
from app.services.semantic.context_collectors import CollectedContext


MISSING_CONFIRMED_SEMANTIC_BINDING = "MISSING_CONFIRMED_SEMANTIC_BINDING"
MISSING_CONFIRMED_SEMANTIC_VERSION = "MISSING_CONFIRMED_SEMANTIC_VERSION"
MISSING_SOURCE_MAPPING = "MISSING_SOURCE_MAPPING"
MISSING_MART_TO_YBT_MAPPING = "MISSING_MART_TO_YBT_MAPPING"
MISSING_LINEAGE = "MISSING_LINEAGE"
STALE_LINEAGE = "STALE_LINEAGE"
MISSING_KNOWLEDGE = "MISSING_KNOWLEDGE"
MISSING_EVIDENCE = "MISSING_EVIDENCE"
HISTORICAL_ONLY_DEFINITION = "HISTORICAL_ONLY_DEFINITION"
CONFLICTING_AUTHORITATIVE_FACTS = "CONFLICTING_AUTHORITATIVE_FACTS"


def detect_conflicts(collected: CollectedContext) -> list[ContextConflict]:
    target_type, target_id = _target_identity(collected)
    conflicts: list[ContextConflict] = []
    for source_type, source_id in collected.signals.get("stale_lineage", []):
        conflicts.append(ContextConflict(
            code=STALE_LINEAGE,
            severity="warning",
            target_type=target_type,
            target_id=target_id,
            message="Persisted lineage status is stale and requires re-verification.",
            left_source_type=str(source_type),
            left_source_id=int(source_id),
        ))

    semantic_definitions = list(collected.signals.get("semantic_definitions", []))
    historical_definitions = list(collected.signals.get("historical_definitions", []))
    if historical_definitions and not semantic_definitions:
        source_type, source_id, _ = historical_definitions[0]
        conflicts.append(ContextConflict(
            code=HISTORICAL_ONLY_DEFINITION,
            severity="warning",
            target_type=target_type,
            target_id=target_id,
            message="Only a historical definition is available; it is not current authority.",
            left_source_type=str(source_type),
            left_source_id=int(source_id) if source_id is not None else None,
        ))

    for semantic_source, semantic_id, semantic_text in semantic_definitions:
        for historical_source, historical_id, historical_text in historical_definitions:
            if _normalized_claim(semantic_text) == _normalized_claim(historical_text):
                continue
            conflicts.append(ContextConflict(
                code=CONFLICTING_AUTHORITATIVE_FACTS,
                severity="error",
                target_type=target_type,
                target_id=target_id,
                message=(
                    "The current confirmed semantic definition contradicts a historical "
                    "caliber definition; no winner was selected."
                ),
                left_source_type=str(semantic_source),
                left_source_id=int(semantic_id) if semantic_id is not None else None,
                right_source_type=str(historical_source),
                right_source_id=int(historical_id) if historical_id is not None else None,
            ))
    return sorted(conflicts, key=lambda item: item.deterministic_sort_key())


def build_open_questions(collected: CollectedContext) -> list[ContextOpenQuestion]:
    target_type, target_id = _target_identity(collected)
    signals = collected.signals
    missing: list[tuple[str, str, str, str]] = []
    if not signals.get("has_semantic_binding"):
        missing.append((
            MISSING_CONFIRMED_SEMANTIC_BINDING,
            "semantic_binding",
            "high",
            "Which confirmed semantic binding governs this target?",
        ))
    if not signals.get("has_semantic_version"):
        missing.append((
            MISSING_CONFIRMED_SEMANTIC_VERSION,
            "semantic_version",
            "high",
            "Which confirmed semantic version is effective for the requested date?",
        ))
    if int(signals.get("source_mapping_count", 0)) == 0:
        missing.append((
            MISSING_SOURCE_MAPPING,
            "source_mapping",
            "high",
            "Which approved Source-to-Mart mapping supplies this target?",
        ))
    if int(signals.get("mart_mapping_count", 0)) == 0:
        missing.append((
            MISSING_MART_TO_YBT_MAPPING,
            "mart_to_ybt_mapping",
            "high",
            "Which approved Mart-to-YBT mapping supplies this target?",
        ))
    if int(signals.get("lineage_count", 0)) == 0:
        missing.append((
            MISSING_LINEAGE,
            "lineage",
            "high",
            "Which persisted lineage path supports this target?",
        ))
    if (
        int(signals.get("regulatory_knowledge_count", 0)) == 0
        and int(signals.get("retrieved_knowledge_count", 0)) == 0
    ):
        missing.append((
            MISSING_KNOWLEDGE,
            "knowledge",
            "medium",
            "Which visible regulatory or retrieved knowledge supports this target?",
        ))
    if (
        bool(signals.get("evidence_required"))
        and int(signals.get("supporting_evidence_count", 0)) == 0
    ):
        missing.append((
            MISSING_EVIDENCE,
            "evidence",
            "high",
            "Which source citation or mapping evidence supports the projected facts?",
        ))

    questions = [ContextOpenQuestion(
        question_code=code,
        question_type=question_type,
        priority=priority,
        target_type=target_type,
        target_id=target_id,
        question_text=text,
        assigned_role="domain_reviewer",
    ) for code, question_type, priority, text in missing]
    return sorted(questions, key=lambda item: item.deterministic_sort_key())


def _target_identity(collected: CollectedContext) -> tuple[str, int | None]:
    if collected.target.target_field_id is not None:
        return "target_field", collected.target.target_field_id
    if collected.target.target_table_id is not None:
        return "target_table", collected.target.target_table_id
    if collected.target.mart_field_id is not None:
        return "mart_field", collected.target.mart_field_id
    if collected.target.semantic_concept_id is not None:
        return "semantic_concept", collected.target.semantic_concept_id
    return "context_scope", None


def _normalized_claim(value: object | None) -> str:
    return "".join(str(value or "").casefold().split())


__all__ = [
    "CONFLICTING_AUTHORITATIVE_FACTS",
    "HISTORICAL_ONLY_DEFINITION",
    "MISSING_CONFIRMED_SEMANTIC_BINDING",
    "MISSING_CONFIRMED_SEMANTIC_VERSION",
    "MISSING_EVIDENCE",
    "MISSING_KNOWLEDGE",
    "MISSING_LINEAGE",
    "MISSING_MART_TO_YBT_MAPPING",
    "MISSING_SOURCE_MAPPING",
    "STALE_LINEAGE",
    "build_open_questions",
    "detect_conflicts",
]
