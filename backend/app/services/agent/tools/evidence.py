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

CLAUSE_LOCATOR_PATTERN = re.compile(r"第[^\s]{1,20}条|\b\d+(?:\.\d+)+\b")
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


def policy_clause_evidence(
    hit: dict[str, Any], *, scope: SkillScope, confidentiality: str
) -> tuple[SkillEvidence | None, SkillGap | None]:
    """Turn a retrieval hit into governed policy evidence, or explain why not."""

    unit_id = hit.get("knowledge_unit_id") or hit.get("chunk_id")
    document_version_id = hit.get("document_version_id")
    if unit_id is None or document_version_id is None:
        return None, gap("missing_basis", "检索命中缺少知识单元标识，不能作为监管依据。")
    locator = clause_locator(hit)
    if not locator or not CLAUSE_LOCATOR_PATTERN.search(locator):
        return None, gap(
            "clause_locator_missing",
            f"知识单元 {unit_id} 缺少可引用的条款定位，不能作为监管依据。",
            source_ref=f"knowledge-unit:{unit_id}",
        )
    item = evidence(
        evidence_id=f"knowledge:{document_version_id}:unit:{unit_id}",
        kind="policy_clause",
        value={
            "title": hit.get("title") or hit.get("source_heading"),
            "excerpt": (hit.get("content") or "")[:1000],
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
