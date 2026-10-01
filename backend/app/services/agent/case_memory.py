"""Retrieval-based decision / case memory.

Enterprise business experience accumulated **only** from human-confirmed
decisions and formal review outcomes.  This is explicitly not model training and
needs no embedding service:

* recording is refused unless the source is an approving human decision
  (``approve`` / ``edit_and_approve``) or a formal review outcome — a model
  suggestion (``llm_suggestion``, ``agent_inference``, ...) and a rejected /
  ``request_reanalysis`` decision can never become a case;
* retrieval (:func:`search_decision_cases`) is deterministic keyword/field
  matching — no model call, no embedding — and every hit is labelled
  ``source_type="historical_decision"`` with a ``similarity`` score;
* a case is **supporting context only**.  It may help rerank, recommend or
  explain, but it is never a regulatory basis
  (:func:`case_is_regulatory_basis` returns ``False`` unconditionally) — policy
  claims must come from ``regulatory_knowledge_items`` / ``requirements``.

Recording is idempotent: the same approved decision for the same subject and
effective window returns the existing row instead of appending a duplicate.
"""
from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AgentTask, DecisionCase, Project

# Only a human act may create experience.  A model/LLM suggestion is not a case.
CONFIDENCE_SOURCES: tuple[str, ...] = ("human_decision", "review_outcome")

# Retrieval labels.  A case is historical experience and must never be served as
# (or mistaken for) a policy requirement.
SOURCE_TYPE = "historical_decision"
POLICY_SOURCE_TYPE = "policy_requirement"
CASE_SOURCE_TYPES: tuple[str, ...] = (SOURCE_TYPE,)

DECISION_TYPE_FIELD_MAPPING = "field_mapping_decision"
DECISION_TYPE_POLICY_INTERPRETATION = "policy_interpretation_decision"
DECISION_TYPE_REQUIREMENT = "requirement_decision"
DECISION_TYPE_SQL_IMPACT = "sql_impact_decision"
DECISION_TYPE_SOURCE_SELECTION = "source_selection_decision"
# Registered types; a caller may name a new type and it is still recorded.
DECISION_TYPES: tuple[str, ...] = (
    DECISION_TYPE_FIELD_MAPPING,
    DECISION_TYPE_POLICY_INTERPRETATION,
    DECISION_TYPE_REQUIREMENT,
    DECISION_TYPE_SQL_IMPACT,
    DECISION_TYPE_SOURCE_SELECTION,
)

STATUS_ACTIVE = "active"
STATUS_ARCHIVED = "archived"
# Only active cases are retrievable: a retired case stays as history, never as advice.
SEARCHABLE_STATUSES: tuple[str, ...] = (STATUS_ACTIVE,)

# A case may only come from an approving human decision ...
APPROVING_DECISIONS: tuple[str, ...] = ("approve", "edit_and_approve")
# ... or a formal review outcome.
REVIEW_OUTCOME_DECISIONS: tuple[str, ...] = ("approved", "accepted", "passed", "signed_off", "confirmed")
# Decisions that explicitly refuse / send work back must never become experience.
REJECTED_DECISIONS: tuple[str, ...] = ("reject", "request_reanalysis")
ACCEPTED_DECISIONS: tuple[str, ...] = APPROVING_DECISIONS + REVIEW_OUTCOME_DECISIONS

DEFAULT_TOP_K = 10
MAX_TOP_K = 50
# Largest scanned candidate set for one query, so a lookup stays bounded.
MAX_SCAN = 500
# A hit this weak is noise ("rationale mentioned the same two characters").
MIN_HIT_WEIGHT = 0.30

_WORD = re.compile(r"[A-Za-z][A-Za-z0-9_]{1,40}|\d{2,}")
_CJK = re.compile(r"[\u4e00-\u9fff]")

# Where a query token may match, and how much that field is trusted.
_CASE_FIELDS: tuple[tuple[str, float, str], ...] = (
    ("decision", 1.0, "decision"),
    ("subject_id", 0.95, "subject_id"),
    ("decision_type", 0.9, "decision_type"),
    ("scenario_key", 0.85, "scenario_key"),
    ("subject_type", 0.7, "subject_type"),
    ("rationale", 0.6, "rationale"),
)


class CaseMemoryError(ValueError):
    """A decision case was requested from a source that may not create one."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def decision_tokens(text: str | None) -> list[str]:
    """Deterministic tokens for Chinese + code-like queries (no model involved)."""

    cleaned = str(text or "").strip()
    tokens: list[str] = [match.group(0) for match in _WORD.finditer(cleaned)]
    cjk = "".join(_CJK.findall(cleaned))
    for size in (4, 3, 2):
        for index in range(0, max(0, len(cjk) - size + 1)):
            tokens.append(cjk[index:index + size])
    seen: set[str] = set()
    ordered: list[str] = []
    for token in tokens:
        key = token.casefold()
        if key and key not in seen:
            seen.add(key)
            ordered.append(token)
    return ordered


def _as_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _lookup(source: Any, *keys: str) -> Any:
    """Read the first present key/attribute of a dict-like or ORM-ish record."""

    if source is None:
        return None
    for key in keys:
        if isinstance(source, Mapping):
            if source.get(key) is not None:
                return source[key]
        else:
            value = getattr(source, key, None)
            if value is not None:
                return value
    return None


def _decision_verb(decision_record: Any) -> str | None:
    verb = _lookup(decision_record, "decision", "outcome", "result")
    if verb is None:
        return None
    text = str(verb).strip().lower()
    return text or None


def _json_list(values: Sequence[Any] | None) -> list[Any]:
    if values is None:
        return []
    if isinstance(values, (str, bytes, Mapping)):
        return [values]
    return [item for item in values]


def _project_scope(db: Session, *, project: Any, task: Any, step: Any) -> tuple[int | None, int | None]:
    """Resolve (project_id, institution_id) from whichever scope the caller has."""

    if project is not None:
        project_id = _as_int(getattr(project, "id", None))
        institution_id = _as_int(getattr(project, "institution_id", None))
        if project_id is None:
            # A bare project id was passed instead of the ORM row.
            project_id = _as_int(project)
            row = db.get(Project, project_id) if project_id else None
            institution_id = _as_int(getattr(row, "institution_id", None))
        return project_id, institution_id
    if task is None and step is not None:
        task = db.get(AgentTask, _as_int(getattr(step, "task_id", None)))
    if task is not None:
        project_id = _as_int(getattr(task, "project_id", None))
        institution_id = _as_int(getattr(task, "institution_id", None))
        if institution_id is None and project_id:
            row = db.get(Project, project_id)
            institution_id = _as_int(getattr(row, "institution_id", None))
        return project_id, institution_id
    return None, None


def _identity_query(
    *,
    project_id: int,
    decision_type: str,
    subject_type: str | None,
    subject_id: str | None,
    decision: str,
    approved_by: int | None,
    effective_from: Any,
):
    """Select the row that would be duplicated by this exact recording."""

    def _eq(column, value):
        return column.is_(None) if value is None else column == value

    return (
        select(DecisionCase)
        .where(
            _eq(DecisionCase.project_id, project_id),
            _eq(DecisionCase.decision_type, decision_type),
            _eq(DecisionCase.subject_type, subject_type),
            _eq(DecisionCase.subject_id, subject_id),
            _eq(DecisionCase.decision, decision),
            _eq(DecisionCase.approved_by, approved_by),
            _eq(DecisionCase.effective_from, effective_from),
        )
        .order_by(DecisionCase.id)
        .limit(1)
    )


def record_decision_case(
    db: Session,
    *,
    task: Any = None,
    step: Any = None,
    decision_record: Any = None,
    project: Any = None,
    decision_type: str,
    decision: str,
    rationale: str | None = None,
    subject_type: str | None = None,
    subject_id: str | None = None,
    evidence_refs: Sequence[Any] = (),
    regulatory_refs: Sequence[Any] = (),
    related: Any = None,
    approved_by: int | None = None,
    confidence_source: str,
    effective_from: Any = None,
    effective_to: Any = None,
    scenario_key: str | None = None,
) -> DecisionCase:
    """Record one human-confirmed decision as retrievable experience.

    Refused (``CaseMemoryError``) when ``confidence_source`` is not a human
    source, when the bound ``decision_record`` is a rejection /
    ``request_reanalysis``, or when no approving human act can be identified.
    Recording the same (project, decision_type, subject_type, subject_id,
    decision, approved_by, effective_from) twice returns the existing row.
    """

    source = str(confidence_source or "").strip().lower()
    if source not in CONFIDENCE_SOURCES:
        raise CaseMemoryError(
            "unsupported_confidence_source",
            "只有人工确认的决定（%s）才能写入案例记忆；模型建议（%s）不构成经验。"
            % (" / ".join(CONFIDENCE_SOURCES), confidence_source),
        )

    verb = _decision_verb(decision_record)
    if verb is not None and verb not in ACCEPTED_DECISIONS + REJECTED_DECISIONS:
        raise CaseMemoryError("unsupported_decision", f"未知的人工决定：{verb}")
    if verb in REJECTED_DECISIONS:
        raise CaseMemoryError(
            "not_an_approving_decision",
            f"被拒绝/退回重分析的决定（{verb}）不能作为案例记忆。",
        )

    approver = _as_int(approved_by) or _as_int(_lookup(decision_record, "decided_by", "approved_by"))
    if verb is None and approver is None:
        raise CaseMemoryError(
            "missing_human_approval",
            "案例记忆必须来自明确的人工批准或正式评审结论。",
        )

    decision_text = str(decision or "").strip()
    if not decision_text:
        raise CaseMemoryError("empty_decision", "决定内容不能为空。")
    type_key = str(decision_type or "").strip()
    if not type_key:
        raise CaseMemoryError("missing_decision_type", "decision_type 不能为空。")

    project_id, institution_id = _project_scope(db, project=project, task=task, step=step)
    if project_id is None:
        raise CaseMemoryError("missing_project_scope", "案例记忆必须归属到项目。")

    existing = db.scalar(_identity_query(
        project_id=project_id,
        decision_type=type_key,
        subject_type=subject_type or None,
        subject_id=str(subject_id) if subject_id is not None else None,
        decision=decision_text,
        approved_by=approver,
        effective_from=effective_from,
    ))
    if existing is not None:
        return existing

    case = DecisionCase(
        institution_id=institution_id,
        project_id=project_id,
        scenario_key=scenario_key or getattr(task, "scenario_key", None),
        subject_type=subject_type or None,
        subject_id=str(subject_id) if subject_id is not None else None,
        decision_type=type_key,
        decision=decision_text,
        rationale=rationale,
        evidence_refs_json=_json_list(evidence_refs),
        regulatory_refs_json=_json_list(regulatory_refs),
        related_mapping_id=_as_int(_lookup(related, "mapping_id", "related_mapping_id")),
        related_requirement_id=_as_int(_lookup(related, "requirement_id", "related_requirement_id")),
        related_script_id=_as_int(_lookup(related, "script_id", "related_script_id")),
        created_by=approver or _as_int(getattr(task, "created_by", None)),
        approved_by=approver,
        confidence_source=source,
        effective_from=effective_from,
        effective_to=effective_to,
        status=STATUS_ACTIVE,
    )
    db.add(case)
    db.commit()
    db.refresh(case)
    return case


def case_is_regulatory_basis(case: Any) -> bool:
    """Always ``False``: a historical decision is supporting context, not policy.

    Decision / case memory records what humans decided before.  It can help rank
    candidates, recommend an option or explain a rationale, but it is not a
    regulatory source: a citation must point at a ``regulatory_knowledge_items``
    row or a ``requirements`` row.  Callers that must refuse to cite a policy
    basis should gate on this function instead of trusting the payload label.
    """

    return False


def _token_score(token: str, text: str, weight: float) -> float:
    if not token or not text:
        return 0.0
    lowered = text.casefold()
    needle = token.casefold()
    if lowered.strip() == needle:
        return weight
    if needle in lowered:
        # Longer matches are more specific: six characters saturate the score.
        return round(min(1.0, len(token) / 6.0) * weight, 4)
    return 0.0


def _score_case(case: DecisionCase, tokens: Sequence[str]) -> tuple[float, list[str], str]:
    """Deterministic similarity of one case against the query tokens."""

    if not tokens:
        return 1.0, [], ""
    best_weight = 0.0
    best_field = ""
    matched_tokens: dict[str, None] = {}
    matched_fields: dict[str, None] = {}
    for token in tokens:
        for field, weight, label in _CASE_FIELDS:
            value = _token_score(token, str(getattr(case, field, None) or ""), weight)
            if value > 0.0:
                matched_tokens[token] = None
                matched_fields[label] = None
                if value > best_weight:
                    best_weight, best_field = value, label
    if best_weight < MIN_HIT_WEIGHT:
        return 0.0, [], ""
    coverage = len(matched_tokens) / len(tokens)
    similarity = round(min(1.0, 0.7 * best_weight + 0.3 * coverage), 4)
    return similarity, sorted(matched_fields), best_field


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def case_payload(
    case: DecisionCase,
    *,
    similarity: float = 1.0,
    matched_fields: Sequence[str] = (),
    matched_on: str = "",
) -> dict[str, Any]:
    """Serializable retrieval hit.  ``source_type`` is always historical."""

    return {
        "id": case.id,
        "source_type": SOURCE_TYPE,
        "confidence_source": case.confidence_source,
        "institution_id": case.institution_id,
        "project_id": case.project_id,
        "scenario_key": case.scenario_key,
        "subject_type": case.subject_type,
        "subject_id": case.subject_id,
        "decision_type": case.decision_type,
        "decision": case.decision,
        "rationale": case.rationale,
        "evidence_refs": list(case.evidence_refs_json or []),
        "regulatory_refs": list(case.regulatory_refs_json or []),
        "related_mapping_id": case.related_mapping_id,
        "related_requirement_id": case.related_requirement_id,
        "related_script_id": case.related_script_id,
        "approved_by": case.approved_by,
        "effective_from": _iso(case.effective_from),
        "effective_to": _iso(case.effective_to),
        "status": case.status,
        "embedding_version": case.embedding_version,
        "created_at": _iso(case.created_at),
        "updated_at": _iso(case.updated_at),
        "similarity": similarity,
        "score": similarity,
        "matched_fields": list(matched_fields),
        "matched_on": matched_on,
        # Useful for retrieval / reranking / rationale only.
        "regulatory_basis": case_is_regulatory_basis(case),
    }


def search_decision_cases(
    db: Session,
    *,
    project: Any,
    query: str | None = None,
    subject_type: str | None = None,
    subject_id: Any = None,
    scenario_key: str | None = None,
    decision_type: str | None = None,
    top_k: int = DEFAULT_TOP_K,
    at: Any = None,
) -> list[dict[str, Any]]:
    """Retrieve historical cases for one project (deterministic, no model call).

    Filters are exact field matches; ``query`` adds keyword similarity over the
    decision text, subject, scenario, type and rationale.  Only active cases are
    returned, and ``at`` restricts results to cases whose
    ``effective_from`` / ``effective_to`` window covers that moment (without
    ``at`` the window is not applied).  Every hit carries
    ``source_type="historical_decision"`` plus ``similarity`` / ``score`` and is
    never labelled ``policy_requirement``.
    """

    project_id = _as_int(getattr(project, "id", None))
    if project_id is None:
        project_id = _as_int(project)
    if project_id is None:
        raise CaseMemoryError("missing_project_scope", "检索案例记忆必须指定项目。")

    limit = DEFAULT_TOP_K if top_k is None else _as_int(top_k)
    if limit is None or limit <= 0:
        return []
    limit = min(limit, MAX_TOP_K)

    tokens = decision_tokens(query) if query else []

    statement = select(DecisionCase).where(
        DecisionCase.project_id == project_id,
        DecisionCase.status.in_(SEARCHABLE_STATUSES),
    )
    if decision_type:
        statement = statement.where(DecisionCase.decision_type == str(decision_type))
    if scenario_key:
        statement = statement.where(DecisionCase.scenario_key == str(scenario_key))
    if subject_type:
        statement = statement.where(DecisionCase.subject_type == str(subject_type))
    if subject_id is not None:
        statement = statement.where(DecisionCase.subject_id == str(subject_id))
    if at is not None:
        # A case is in force when it started and before it was superseded.
        statement = statement.where(
            (DecisionCase.effective_from.is_(None)) | (DecisionCase.effective_from <= at),
            (DecisionCase.effective_to.is_(None)) | (DecisionCase.effective_to >= at),
        )

    scan_limit = limit if not tokens else min(max(limit * 10, 50), MAX_SCAN)
    rows = list(db.scalars(statement.order_by(DecisionCase.id.desc()).limit(scan_limit)).all())

    hits: list[dict[str, Any]] = []
    for case in rows:
        similarity, matched_fields, matched_on = _score_case(case, tokens)
        if tokens and similarity <= 0.0:
            continue
        hits.append(case_payload(
            case,
            similarity=similarity,
            matched_fields=matched_fields,
            matched_on=matched_on,
        ))
    # Deterministic: best match first, then most recently recorded.
    hits.sort(key=lambda item: (-item["similarity"], -item["id"]))
    return hits[:limit]
