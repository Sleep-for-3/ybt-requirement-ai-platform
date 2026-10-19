"""Evidence builders shared by every agent tool.

Rules encoded here (execution spec §E):

* Evidence is built through the *existing* ``SkillEvidence`` contract, never a
  parallel shape, so the agent cannot invent a looser citation format.
* Policy evidence must be a governed knowledge clause
  (``kind="policy_clause"`` / ``source_type="knowledge_clause"``); SQL scripts,
  historical mappings and model answers are facts, never policy.
* Anything without a reliable basis becomes a ``SkillGap`` instead of being
  silently completed.
"""
from __future__ import annotations

import re
from typing import Any

from app.models import AgentTask, Project
from app.schemas.ai_skill import EvidenceSource, SkillEvidence, SkillGap, SkillScope
from app.services.requirement_policy_comparison import NORMATIVE_CATEGORIES

CLAUSE_LOCATOR_PATTERN = re.compile(r"第[^\s]{1,20}条|\b\d+(?:\.\d+)+\b")
# A clause number the unit states itself: ``第三条 …`` at the start of a heading or
# sentence, or a dotted section number such as ``6.1``.
INSCRIBED_CLAUSE_PATTERN = re.compile(r"^(?:第[零一二三四五六七八九十百千\d]{1,12}条|\d+(?:\.\d+){1,4})(?![\d.])")
CONFIDENTIALITY_LEVELS = ("public", "internal", "confidential", "restricted")


def project_scope(task: AgentTask) -> SkillScope:
    """The skill scope of an agent task (always project-scoped)."""

    return SkillScope(
        scope_type="project",
        institution_id=task.institution_id,
        project_id=task.project_id,
    )


def confidentiality_of(project: Project) -> str:
    """Fail closed: an unknown project level is treated as ``restricted``."""

    value = (getattr(project, "confidentiality_level", None) or "").strip().lower()
    return value if value in CONFIDENTIALITY_LEVELS else "restricted"


def evidence(
    *,
    evidence_id: str,
    kind: str,
    value: Any,
    source_type: str,
    source_id: Any,
    locator: str | None,
    scope: SkillScope,
    confidentiality: str,
    source_version: Any = None,
) -> SkillEvidence:
    """Build one contract-valid evidence item (raises on an illegal shape)."""

    return SkillEvidence(
        id=str(evidence_id)[:255],
        kind=kind,
        value=value if value is not None else "",
        source=EvidenceSource(
            source_type=source_type,
            source_id=str(source_id)[:255],
            source_version=str(source_version if source_version is not None else "live")[:255],
            locator=(locator or "unspecified")[:255],
            scope=scope,
        ),
        confidentiality=confidentiality,
    )


def gap(code: str, message: str, source_ref: str | None = None) -> SkillGap:
    return SkillGap(code=code, message=message[:2000], source_ref=source_ref)


def clause_locator(hit: dict[str, Any]) -> str | None:
    for key in ("locator", "source_heading", "source_cell_range", "source_file_name"):
        raw = hit.get(key)
        if isinstance(raw, dict):
            raw = raw.get("heading") or raw.get("cell_range") or raw.get("page_no")
        if isinstance(raw, str) and raw.strip():
            return raw.strip()[:200]
        if isinstance(raw, (int, float)):
            return str(raw)
    return None


def clause_parentage(hit: dict[str, Any]) -> tuple[str | None, str | None, str | None]:
    """The chapter a cited clause sits under, as recorded at ingestion.

    Ingestion writes ``chapter_no`` / ``clause_no`` / ``chapter_heading`` next to the
    locator, so a citation of ``第五条`` can say it belongs to ``第二章 口径管理``.
    Nothing is reconstructed from prose here: a unit whose chapter was never recorded
    reports no chapter instead of guessing one from its neighbours.
    """

    locator = hit.get("locator")
    raw = locator if isinstance(locator, dict) else {}

    def text(value: Any) -> str | None:
        return value.strip()[:200] if isinstance(value, str) and value.strip() else None

    chapter_no = text(raw.get("chapter_no"))
    clause_no = text(raw.get("clause_no"))
    chapter_heading = text(raw.get("chapter_heading")) or text(hit.get("source_heading"))
    if chapter_no is None:
        return None, None, clause_no
    return chapter_no, chapter_heading, clause_no

def inscribed_clause_locator(hit: dict[str, Any]) -> str | None:
    """The clause number the unit itself states (``第三条 …`` / ``6.1 …``).

    A locator taken from a spreadsheet cell range or a bare file name cannot be
    cited as a regulatory clause, but the clause number written into the unit's
    own heading or text is an exact, checkable reference to that clause.  This is
    deliberately narrower than searching arbitrary prose: the number has to sit at
    the start of the heading or sentence and be carried by text the unit owns.
    """

    candidates: list[str] = []
    heading = hit.get("source_heading")
    title = hit.get("title")
    for value in (heading, title):
        if isinstance(value, str) and value.strip():
            candidates.append(value.strip()[:200])
    for key in ("content", "normalized_content"):
        body = hit.get(key)
        if not isinstance(body, str):
            continue
        for line in body.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            candidates.append(stripped[:200])
            if len(candidates) > 12:
                break
    for candidate in candidates:
        match = INSCRIBED_CLAUSE_PATTERN.match(candidate)
        if match:
            return match.group(0).strip()[:200]
    return None

def policy_clause_evidence(
    hit: dict[str, Any], *, scope: SkillScope, confidentiality: str
) -> tuple[SkillEvidence | None, SkillGap | None]:
    """Turn a retrieval hit into governed policy evidence, or explain why not."""

    # Same normative-source rule the requirement and lineage paths already use: a
    # data-item definition, business material or model answer can never become a
    # regulatory basis just because its text looks clause-shaped.
    if hit.get("source_category") not in NORMATIVE_CATEGORIES:
        return None, None
    unit_id = hit.get("knowledge_unit_id") or hit.get("chunk_id")
    document_version_id = hit.get("document_version_id")
    if unit_id is None or document_version_id is None:
        return None, gap("missing_basis", "检索命中缺少知识单元标识，不能作为监管依据。")
    locator = clause_locator(hit)
    # Chapter/clause parentage travels with the cited clause: a citation of ``第五条``
    # that cannot say it belongs to ``第二章`` breaks cross-clause reasoning.
    chapter_no, chapter_heading, clause_no = clause_parentage(hit)
    if not locator or not CLAUSE_LOCATOR_PATTERN.search(locator):
        # The container locator (a spreadsheet cell range, a bare file name) is not a
        # citable clause, but the clause number the unit itself states is one.  Only
        # fall back to it when it is a *clause* number: a dotted section number or a
        # ``第N条`` heading, matched at the start of text the unit owns.
        inscribed = inscribed_clause_locator(hit)
        if inscribed:
            locator = inscribed
        else:
            return None, gap(
                "clause_locator_missing",
                f"知识单元 {unit_id} 缺少可引用的条款定位，不能作为监管依据。",
                source_ref=f"knowledge-unit:{unit_id}",
            )
    # Chapter parentage is only real when the cited locator *is* a clause; a file
    # name or a cell range can never acquire a chapter by adjacency.
    if locator != clause_no and CLAUSE_LOCATOR_PATTERN.fullmatch(locator or "") is None:
        chapter_no = chapter_heading = None
    item = evidence(
        evidence_id=f"knowledge:{document_version_id}:unit:{unit_id}",
        kind="policy_clause",
        value={
            "title": hit.get("title") or hit.get("source_heading"),
            "excerpt": (hit.get("content") or "")[:1000],
            "chapter_no": chapter_no,
            "chapter_heading": chapter_heading,
            "clause_no": clause_no,
            "authority_rank": hit.get("authority_rank"),
            "publisher": hit.get("publisher"),
            "regulatory_version": hit.get("regulatory_version"),
            "effective_at": hit.get("effective_at"),
        },
        source_type="knowledge_clause",
        source_id=unit_id,
        source_version=hit.get("content_hash") or document_version_id,
        locator=locator,
        scope=scope,
        confidentiality=confidentiality,
    )
    return item, None


def knowledge_evidence(hit: dict[str, Any], *, scope: SkillScope, confidentiality: str) -> SkillEvidence | None:
    """Non-normative retrieval material: usable as a fact, never as policy."""

    unit_id = hit.get("knowledge_unit_id") or hit.get("chunk_id")
    if unit_id is None:
        return None
    return evidence(
        evidence_id=f"knowledge-unit:{unit_id}",
        kind="knowledge_evidence",
        value={"title": hit.get("title"), "excerpt": (hit.get("content") or "")[:1000]},
        source_type="knowledge_unit",
        source_id=unit_id,
        source_version=hit.get("content_hash") or hit.get("document_version_id"),
        locator=clause_locator(hit),
        scope=scope,
        confidentiality=confidentiality,
    )
