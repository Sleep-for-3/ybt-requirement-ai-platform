from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.settings import get_settings
from app.models import KnowledgeUnit

from .citation_support import (
    CITATION_SUPPORT_PROMPT_KEY,
    CITATION_SUPPORT_SYSTEM_PROMPT,
    UNKNOWN,
    citation_evidence,
    run_judge,
    tally_verdicts,
)



def validate_citations(
    db: Session,
    citations: list[dict],
    *,
    project_id: int | None = None,
    institution_name: str | None = None,
) -> None:
    """Reject citations that do not resolve to visible, enabled knowledge units."""
    ids = {
        citation.get("knowledge_unit_id")
        for citation in citations
        if citation.get("knowledge_unit_id") is not None
    }
    if len(ids) != len(citations):
        raise ValueError("citation 缺少 knowledge_unit_id")
    if not ids:
        return

    units = {
        unit.id: unit
        for unit in db.scalars(
            select(KnowledgeUnit).where(
                KnowledgeUnit.id.in_(ids),
                KnowledgeUnit.enabled.is_(True),
            )
        ).all()
    }
    missing = ids - units.keys()
    if missing:
        raise ValueError(f"citation 对应的 KnowledgeUnit 不存在或已禁用: {sorted(missing)}")
    if project_id is None:
        return
    invisible = [
        unit.id
        for unit in units.values()
        if not (
            (unit.knowledge_scope == "global" and (unit.project_id == project_id or unit.confidentiality_level != "restricted"))
            or (unit.knowledge_scope in {"project", "institution"} and unit.project_id == project_id)
        )
    ]
    if invisible:
        raise ValueError(f"citation 对当前项目不可见: {sorted(invisible)}")


def _base_support_result(check: str, enabled: bool) -> dict:
    return {
        "enabled": enabled,
        "check": check,
        "judged": False,
        "citation_count": 0,
        "verdicts": [],
        "verdict_counts": {"supported": 0, "unsupported": 0, "unknown": 0},
        "supported_count": 0,
        "unsupported_count": 0,
        "unknown_count": 0,
        "judged_count": 0,
        "unsupported_ratio": 0.0,
        "degraded": False,
        "degraded_reason": None,
        "skip_reason": None,
        "model_profile_id": None,
        "provider_type": None,
        "model_name": None,
        "prompt_key": CITATION_SUPPORT_PROMPT_KEY,
    }


def _merge_citation_verdicts(citations: list[dict], verdicts: list[dict]) -> list[dict]:
    """Attach one verdict to every citation, aligned by citation_id then by position."""
    by_id: dict[str, dict] = {}
    unkeyed: list[dict] = []
    for verdict in verdicts:
        citation_id = verdict.get("citation_id")
        if citation_id:
            by_id.setdefault(str(citation_id), verdict)
        else:
            unkeyed.append(verdict)

    merged: list[dict] = []
    for index, citation in enumerate(citations):
        citation_id = str(citation.get("citation_id") or f"citation-{index}")
        verdict = by_id.get(citation_id)
        if verdict is None and index < len(unkeyed):
            verdict = unkeyed[index]
        if verdict is None:
            merged.append(
                {
                    "citation_id": citation_id,
                    "knowledge_unit_id": citation.get("knowledge_unit_id"),
                    "verdict": UNKNOWN,
                    "reason": "judge_returned_no_verdict",
                }
            )
            continue
        merged.append(
            {
                "citation_id": citation_id,
                "knowledge_unit_id": citation.get("knowledge_unit_id"),
                "verdict": verdict.get("verdict", UNKNOWN),
                "reason": str(verdict.get("reason") or ""),
            }
        )
    return merged


async def check_citation_support(
    db: Session,
    citations: list[dict],
    *,
    answer: str,
    project_id: int | None = None,
    confidentiality_levels: list[str] | None = None,
) -> dict:
    """Judge whether each citation's evidence entails the conclusion it is attached to.

    Controlled by ``settings.citation_support_check`` (default ``"off"``). When the switch is
    off this reports ``enabled=False`` and makes no model call, so the existing answer path is
    byte-for-byte unchanged. When it is ``"judge"`` each citation receives one of
    ``supported`` / ``unsupported`` / ``unknown`` plus a reason, and the result carries the
    overall unsupported ratio. An unavailable or misbehaving judge degrades to ``unknown`` and
    never raises.
    """
    check = str(getattr(get_settings(), "citation_support_check", "off") or "off")
    if check != "judge":
        return _base_support_result(check, False)

    result = _base_support_result(check, True)
    usable = [citation for citation in citations or [] if isinstance(citation, dict)]
    result["citation_count"] = len(usable)
    if not usable:
        result["skip_reason"] = "no_citations"
        return result

    answer_text = str(answer or "").strip()
    user_prompt = json.dumps(
        {"answer": answer_text, "citations": citation_evidence(usable)},
        ensure_ascii=False,
    )
    verdicts, facts, error_type = await run_judge(
        db,
        CITATION_SUPPORT_PROMPT_KEY,
        CITATION_SUPPORT_SYSTEM_PROMPT,
        user_prompt,
        confidentiality_levels=confidentiality_levels,
        project_id=project_id,
    )
    result.update(facts)
    result["verdicts"] = _merge_citation_verdicts(usable, verdicts)
    tallied = tally_verdicts(result["verdicts"])
    result["supported_count"] = tallied["supported_count"]
    result["unsupported_count"] = tallied["unsupported_count"]
    result["unknown_count"] = tallied["unknown_count"]
    result["judged_count"] = tallied["judged_count"]
    result["verdict_counts"] = {
        "supported": tallied["supported_count"],
        "unsupported": tallied["unsupported_count"],
        "unknown": tallied["unknown_count"],
    }
    result["unsupported_ratio"] = (
        round(tallied["unsupported_count"] / len(result["verdicts"]), 4)
        if result["verdicts"]
        else 0.0
    )
    if error_type:
        result["degraded"] = True
        result["degraded_reason"] = error_type
        return result
    result["judged"] = True
    return result

