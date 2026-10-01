"""Subject resolution V2: resolve, ask, or refuse — never silently pick the first field.

V1 fell back to "the first target field of the project" whenever the objective did not
match anything, which in a real bank project quietly analyses an unrelated field. V2
returns one of three explicit outcomes:

``resolved``
    exactly one plausible subject (or one clearly ahead of the others): the plan runs.
``ambiguous``
    several plausible subjects: the agent must ask a human to choose.
``not_found``
    nothing plausible: the agent must ask for the subject instead of guessing.

Matching is deterministic and explainable (objective text → field code/name, table
name/code, script logical target). Every candidate carries its score and what it
matched on, so the workspace can show *why* the agent asked.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select

from app.models import Project, ScriptFile, TargetField, TargetTable

STATUS_RESOLVED = "resolved"
STATUS_AMBIGUOUS = "ambiguous"
STATUS_NOT_FOUND = "not_found"

# A token must match at least this share of a candidate text to count as a hit.
SCORE_FLOOR = 0.30
SCORE_EXACT = 1.0
# When several candidates are above the floor, the leader must be this far ahead.
SCORE_LEAD = 0.30
# A strong leader also wins on a relative margin (2x), which keeps genuinely
# specific matches resolvable when the runner-up only matched a short token.
SCORE_LEAD_RATIO = 2.0
MAX_CANDIDATES = 5
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9_]{1,40}|\d{2,}")


@dataclass(frozen=True)
class SubjectCandidate:
    target_field_id: int
    target_field_code: str
    target_field_name: str
    target_table_id: int | None
    score: float
    matched_on: str
    matched_token: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "target_field_id": self.target_field_id,
            "target_field_code": self.target_field_code,
            "target_field_name": self.target_field_name,
            "target_table_id": self.target_table_id,
            "score": round(self.score, 4),
            "matched_on": self.matched_on,
            "matched_token": self.matched_token,
        }


@dataclass(frozen=True)
class SubjectResolution:
    status: str
    subject: dict[str, Any] = field(default_factory=dict)
    candidates: tuple[SubjectCandidate, ...] = ()
    confidence: float = 0.0
    rationale: str = ""
    requirement: str = ""

    @property
    def resolved(self) -> bool:
        return self.status == STATUS_RESOLVED

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "confidence": round(self.confidence, 4),
            "rationale": self.rationale,
            "requirement": self.requirement,
            "candidates": [candidate.as_dict() for candidate in self.candidates],
        }

    def candidate_payload(self) -> list[dict[str, Any]]:
        return [candidate.as_dict() for candidate in self.candidates]


def objective_tokens(text: str) -> list[str]:
    """Deterministic tokens for Chinese + code-like objectives (no model involved)."""

    cleaned = (text or "").strip()
    tokens: list[str] = []
    for match in _WORD.finditer(cleaned):
        tokens.append(match.group(0))
    cjk = re.sub(r"[^\u4e00-\u9fff]", "", cleaned)
    for size in (4, 3, 2):
        for index in range(0, max(0, len(cjk) - size + 1)):
            tokens.append(cjk[index:index + size])
    seen: set[str] = set()
    ordered: list[str] = []
    for token in tokens:
        key = token.lower()
        if key and key not in seen:
            seen.add(key)
            ordered.append(token)
    return ordered


def _score(token: str, text: str, *, weight: float) -> float:
    if not token or not text:
        return 0.0
    lowered = text.lower()
    if lowered == token.lower():
        return SCORE_EXACT
    if token.lower() in lowered:
        # Longer matches are more specific: 6 characters saturate the score.
        return round(min(SCORE_EXACT, (len(token) / 6.0)) * weight, 4)
    return 0.0


def subject_candidates(db, project: Project, objective: str) -> list[SubjectCandidate]:
    """Rank this project's target fields against the objective (deterministic)."""

    tokens = objective_tokens(objective)
    fields = list(db.scalars(select(TargetField).where(TargetField.project_id == project.id)
                             .order_by(TargetField.id)).all())
    if not fields:
        return []
    tables = {table.id: table for table in db.scalars(
        select(TargetTable).where(TargetTable.project_id == project.id)).all()}
    scripts = list(db.scalars(select(ScriptFile).where(ScriptFile.project_id == project.id)).all())
    script_targets = {str(script.logical_target_name or "").upper() for script in scripts if script.logical_target_name}

    scored: dict[int, SubjectCandidate] = {}
    for target in fields:
        table = tables.get(target.target_table_id) if target.target_table_id else None
        best = SubjectCandidate(target.id, target.field_code, target.field_name,
                                target.target_table_id, 0.0, "none", "")
        for token in tokens:
            for text, weight, label in (
                (target.field_code, 1.0, "field_code"),
                (target.field_name, 1.0, "field_name"),
                ((table.table_name if table else ""), 0.7, "table_name"),
                ((table.table_code if table else ""), 0.9, "table_code"),
            ):
                value = _score(token, str(text or ""), weight=weight)
                if value > best.score:
                    best = SubjectCandidate(target.id, target.field_code, target.field_name,
                                            target.target_table_id, value, label, token)
        if str(target.field_code or "").upper() in script_targets and best.score < 0.5:
            # A script targets this field even though the objective did not name it.
            best = SubjectCandidate(target.id, target.field_code, target.field_name,
                                    target.target_table_id, 0.5, "script_target", target.field_code)
        if best.score >= SCORE_FLOOR:
            scored[target.id] = best
    return sorted(scored.values(), key=lambda item: (-item.score, item.target_field_id))[:MAX_CANDIDATES]


def resolve_subject_v2(db, project: Project, objective: str) -> SubjectResolution:
    """Resolve the objective's subject (or state exactly why it cannot be resolved)."""

    requirement = (
        "请人工选择目标字段后再继续：Agent 不会默认使用项目中的第一个字段。"
    )
    candidates = subject_candidates(db, project, objective)
    if not candidates:
        return SubjectResolution(
            status=STATUS_NOT_FOUND, confidence=0.0,
            rationale="目标中没有可与本项目目标字段/表/脚本匹配的名称或编码。",
            requirement=requirement,
        )
    leader = candidates[0]
    if len(candidates) == 1:
        return SubjectResolution(status=STATUS_RESOLVED, subject=_subject_of(leader), confidence=_confidence(leader),
                                 candidates=tuple(candidates),
                                 rationale=f"唯一候选：{leader.target_field_name}（{leader.matched_on}）")
    runner_up = candidates[1]
    if leader.score >= SCORE_EXACT or (leader.score - runner_up.score) >= SCORE_LEAD \
            or (leader.score >= 0.5 and leader.score >= SCORE_LEAD_RATIO * runner_up.score):
        return SubjectResolution(status=STATUS_RESOLVED, subject=_subject_of(leader), confidence=_confidence(leader),
                                 candidates=tuple(candidates),
                                 rationale=(f"最佳候选明显领先：{leader.target_field_name}"
                                            f"（{leader.score:.2f} vs {runner_up.score:.2f}）"))
    return SubjectResolution(
        status=STATUS_AMBIGUOUS, confidence=_confidence(leader), candidates=tuple(candidates),
        rationale=(f"{len(candidates)} 个候选字段分值接近（{leader.target_field_name} "
                   f"{leader.score:.2f} / {runner_up.target_field_name} {runner_up.score:.2f}），需要人工选择。"),
        requirement=requirement,
    )


def _subject_of(candidate: SubjectCandidate) -> dict[str, Any]:
    return {
        "target_field_id": candidate.target_field_id,
        "target_field_code": candidate.target_field_code,
        "target_field_name": candidate.target_field_name,
        "target_table_id": candidate.target_table_id,
        "resolution": "objective_match",
        "matched_on": candidate.matched_on,
    }


def _confidence(candidate: SubjectCandidate) -> float:
    return round(min(0.95, 0.4 + candidate.score), 4)
