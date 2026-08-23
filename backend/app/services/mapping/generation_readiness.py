"""Deterministic, task-aware readiness and confidence policy for generators."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.schemas.regulatory_context import RegulatoryContext
from app.services.semantic.context_conflicts import (
    CONFLICTING_AUTHORITATIVE_FACTS,
    HISTORICAL_ONLY_DEFINITION,
    MISSING_CONFIRMED_SEMANTIC_BINDING,
    MISSING_CONFIRMED_SEMANTIC_VERSION,
    MISSING_EVIDENCE,
    MISSING_KNOWLEDGE,
    MISSING_LINEAGE,
    MISSING_MART_TO_YBT_MAPPING,
    MISSING_SOURCE_MAPPING,
    STALE_LINEAGE,
)


GenerationTaskType = Literal[
    "source_to_mart",
    "mart_to_ybt",
    "scenario_business",
    "scenario_technical",
]
ConfidenceLevel = Literal["low", "medium", "high"]

_CONFIDENCE_ORDER: dict[ConfidenceLevel, int] = {
    "low": 0,
    "medium": 1,
    "high": 2,
}
_SPARSE_CONTEXT_CODES = {
    HISTORICAL_ONLY_DEFINITION,
    MISSING_CONFIRMED_SEMANTIC_BINDING,
    MISSING_CONFIRMED_SEMANTIC_VERSION,
    MISSING_EVIDENCE,
    MISSING_KNOWLEDGE,
    MISSING_LINEAGE,
    MISSING_MART_TO_YBT_MAPPING,
    MISSING_SOURCE_MAPPING,
}


class GenerationReadiness(BaseModel):
    """Strict internal policy result evaluated before model execution."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    can_generate: bool
    confidence_cap: ConfidenceLevel
    blocking_reasons: list[str]
    warnings: list[str]


class MergedGenerationQuestions(BaseModel):
    """Stable text merge result; existing human bytes are always the prefix."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str
    appended_context_codes: list[str]
    appended_model_count: int


def evaluate_generation_readiness(
    context: RegulatoryContext,
    task_type: GenerationTaskType,
    *,
    scope_matches: bool = True,
    governance_allowed: bool = True,
) -> GenerationReadiness:
    """Evaluate typed Context state without issuing I/O or asking the model to decide."""

    blocking: set[str] = set()
    warnings: set[str] = set()

    if not scope_matches:
        blocking.add("GENERATION_SCOPE_MISMATCH")
    if not governance_allowed:
        blocking.add("GENERATION_GOVERNANCE_PROHIBITED")

    for conflict in context.conflicts:
        if conflict.resolution_state == "resolved":
            continue
        if (
            conflict.code == CONFLICTING_AUTHORITATIVE_FACTS
            and conflict.severity == "error"
        ):
            blocking.add(CONFLICTING_AUTHORITATIVE_FACTS)
        else:
            warnings.add(conflict.code)

    question_codes = {
        question.question_code
        for question in context.open_questions
        if question.resolution_state == "open"
    }
    warnings.update(question_codes)

    # These gaps describe the work performed by their matching generator. They
    # remain visible warnings but never block the generator that can fill them.
    if task_type == "source_to_mart":
        blocking.discard(MISSING_SOURCE_MAPPING)
    if task_type == "mart_to_ybt":
        blocking.discard(MISSING_MART_TO_YBT_MAPPING)

    if blocking:
        confidence_cap: ConfidenceLevel = "low"
    elif question_codes & _SPARSE_CONTEXT_CODES:
        confidence_cap = "low"
    elif warnings or any(
        conflict.code == STALE_LINEAGE for conflict in context.conflicts
    ):
        confidence_cap = "medium"
    else:
        confidence_cap = "high"

    return GenerationReadiness(
        can_generate=not blocking,
        confidence_cap=confidence_cap,
        blocking_reasons=sorted(blocking),
        warnings=sorted(warnings),
    )


def normalize_confidence(value: object) -> ConfidenceLevel:
    normalized = str(value or "").strip().casefold()
    if normalized in _CONFIDENCE_ORDER:
        return normalized  # type: ignore[return-value]
    return "low"


def apply_confidence_cap(
    value: object,
    cap: ConfidenceLevel,
) -> ConfidenceLevel:
    normalized = normalize_confidence(value)
    return min((normalized, cap), key=_CONFIDENCE_ORDER.__getitem__)


def merge_generation_questions(
    existing_human_text: str | None,
    context_questions: Sequence[object],
    model_questions: object,
) -> MergedGenerationQuestions:
    """Append governed/model questions without rewriting the human segment."""

    existing = existing_human_text or ""
    seen = {
        key
        for line in existing.splitlines()
        if (key := _normalized_question_key(line))
    }
    additions: list[str] = []
    appended_context_codes: list[str] = []
    context_rows = sorted(
        (
            (
                str(getattr(question, "question_code", "")).strip(),
                str(getattr(question, "question_text", "")).strip(),
                str(getattr(question, "target_type", "")),
                int(getattr(question, "target_id", 0) or 0),
                str(getattr(question, "priority", "")),
                str(getattr(question, "resolution_state", "open")),
            )
            for question in context_questions
        ),
        key=lambda item: (item[0], item[2], item[3], item[4], item[1]),
    )
    for code, question_text, _, _, _, resolution_state in context_rows:
        if not code or not question_text or resolution_state != "open":
            continue
        key = _normalized_question_key(question_text)
        if not key or key in seen:
            continue
        seen.add(key)
        additions.append(f"[CTX:{code}] {question_text}")
        appended_context_codes.append(code)

    if isinstance(model_questions, str):
        model_values: Sequence[object] = [model_questions]
    elif isinstance(model_questions, (list, tuple)):
        model_values = model_questions
    else:
        model_values = []
    appended_model_count = 0
    for value in model_values:
        if not isinstance(value, str):
            continue
        question_text = value.strip()
        key = _normalized_question_key(question_text)
        if not key or key in seen:
            continue
        seen.add(key)
        additions.append(f"[AI] {question_text}")
        appended_model_count += 1

    if not additions:
        merged_text = existing
    elif not existing:
        merged_text = "\n".join(additions)
    elif existing.endswith(("\n", "\r")):
        merged_text = existing + "\n".join(additions)
    else:
        merged_text = existing + "\n" + "\n".join(additions)
    return MergedGenerationQuestions(
        text=merged_text,
        appended_context_codes=appended_context_codes,
        appended_model_count=appended_model_count,
    )


_QUESTION_MARKER = re.compile(r"^\[(?:CTX:[^\]]+|AI)\]\s*", re.IGNORECASE)


def _normalized_question_key(value: str) -> str:
    without_marker = _QUESTION_MARKER.sub("", value.strip())
    normalized = unicodedata.normalize("NFKC", without_marker)
    return " ".join(normalized.split()).casefold()


__all__ = [
    "ConfidenceLevel",
    "GenerationReadiness",
    "GenerationTaskType",
    "MergedGenerationQuestions",
    "apply_confidence_cap",
    "evaluate_generation_readiness",
    "merge_generation_questions",
    "normalize_confidence",
]
