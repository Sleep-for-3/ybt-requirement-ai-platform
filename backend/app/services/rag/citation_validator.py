from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.settings import get_settings
from app.models import KnowledgeUnit

from .citation_support import (
    CITATION_SUPPORT_PROMPT_KEY,
    CITATION_SUPPORT_SYSTEM_PROMPT,
    MAX_CLAIMS_PER_CALL,
    MAX_JUDGE_BATCHES,
    SUPPORTED,
    UNKEYED_VERDICT,
    UNKNOWN,
    UNSUPPORTED,
    claim_payloads,
    citation_evidence,
    run_judge,
    split_claims_all,
    tally_verdicts,
)

#: Answer-level verification verdicts. ``partially_supported`` is deliberately **not** a new
#: ``answer_status``: the answer status contract stays ``grounded`` / ``needs_confirmation`` /
#: ``degraded`` / ``error``, and the finer-grained fact lives here (see the B-package handoff).
VERIFIED = "verified"
PARTIALLY_SUPPORTED = "partially_supported"
UNSUPPORTED_VERIFICATION = "unsupported"
UNKNOWN_VERIFICATION = "unknown"
DEGRADED_VERIFICATION = "degraded"


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
        # --- claim-level denominators: an answer must never look "clean" because nothing was
        # --- judged; every number below is published so a consumer can compute coverage.
        "verification": UNKNOWN_VERIFICATION,
        "claims_total": 0,
        "claims_judged": 0,
        "claims_supported": 0,
        "claims_unsupported": 0,
        "claims_unknown": 0,
        "claims_unjudged": 0,
        "claim_coverage": 0.0,
        "coverage_truncated": False,
        "batch_count": 0,
        "claims": [],
        "supported_claims": [],
        "unsupported_claims": [],
        "unknown_claims": [],
        "uncovered_claims": [],
        # --- alignment diagnostics: nothing is silently dropped or double counted.
        "duplicate_verdict_ids": [],
        "dropped_verdict_ids": [],
        "unkeyed_verdict_count": 0,
        # --- citation-level denominators that exclude "no verdict" placeholders.
        "citation_judged": 0,
        "judged_citation_count": 0,
        "unreferenced_evidence_ids": [],
        "claim_judgement": None,
    }


def _ratio(part: int, whole: int) -> float:
    return round(part / whole, 4) if whole else 0.0


def _merge_citation_verdicts(
    citations: list[dict], verdicts: list[dict]
) -> tuple[list[dict], dict]:
    """Attach one verdict to every citation, aligned by ``citation_id`` **then by position**.

    Keyed verdicts always win. Verdicts without a usable key are assigned positionally to the
    citations still lacking a verdict — but **only when the count matches exactly**, which makes
    the assignment deterministic. A mismatch is ambiguous, so nothing is guessed: those verdicts
    are dropped and recorded, and the unanswered citations stay ``unknown``.
    """
    by_id: dict[str, dict] = {}
    duplicate_ids: list[str] = []
    dropped_ids: list[str] = []
    unkeyed: list[dict] = []
    for verdict in verdicts:
        citation_id = verdict.get("citation_id")
        if not citation_id:
            unkeyed.append(verdict)
            continue
        key = str(citation_id)
        if key in by_id:
            duplicate_ids.append(key)
            continue
        by_id[key] = verdict

    known_ids = {
        str(citation.get("citation_id") or f"citation-{index}")
        for index, citation in enumerate(citations)
    }
    for key in list(by_id):
        if key not in known_ids:
            dropped_ids.append(key)
            by_id.pop(key, None)

    unanswered = [key for key in known_ids if key not in by_id]
    if unkeyed and len(unkeyed) == len(unanswered) and unanswered:
        # Unambiguous: exactly one unkeyed verdict per citation still lacking a verdict.
        for key, verdict in zip(sorted(unanswered), unkeyed):
            by_id[key] = verdict
    elif unkeyed:
        # Ambiguous (or nothing to align to): never guess.
        dropped_ids.extend(UNKEYED_VERDICT for _ in unkeyed)

    merged: list[dict] = []
    for index, citation in enumerate(citations):
        citation_id = str(citation.get("citation_id") or f"citation-{index}")
        verdict = by_id.get(citation_id)
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
    return merged, {
        "duplicate_verdict_ids": duplicate_ids,
        "dropped_verdict_ids": dropped_ids,
        "unkeyed_verdict_count": len(unkeyed),
    }


def _align_claim_verdicts(
    batch_payloads: list[dict], verdicts: list[dict]
) -> tuple[list[dict], list[str], list[str]]:
    """Align claim verdicts by ``claim_id`` (never by position).

    A verdict may reference the claim by id (``claim-3``) or by quoting the claim text. Anything
    else — an unknown id, an unrelated text, or a verdict with no key at all — is dropped and
    recorded so it can neither misalign a claim nor inflate ``claims_judged``.
    """
    by_id: dict[str, dict] = {}
    by_text: dict[str, str] = {}
    duplicate_ids: list[str] = []
    dropped_ids: list[str] = []
    for payload in batch_payloads:
        by_text[payload["claim"]] = payload["claim_id"]

    for verdict in verdicts:
        claim_id = verdict.get("claim_id")
        if claim_id:
            key = str(claim_id)
            if key in by_id:
                duplicate_ids.append(key)
                continue
            by_id[key] = verdict
            continue
        claim_text = verdict.get("claim")
        if claim_text and str(claim_text) in by_text:
            key = by_text[str(claim_text)]
            if key in by_id:
                duplicate_ids.append(key)
                continue
            by_id[key] = verdict
            continue
        dropped_ids.append(UNKEYED_VERDICT)

    aligned: list[dict] = []
    for payload in batch_payloads:
        verdict = by_id.get(payload["claim_id"])
        if verdict is None:
            aligned.append(
                {
                    "claim_id": payload["claim_id"],
                    "claim": payload["claim"],
                    "verdict": UNKNOWN,
                    "reason": "judge_returned_no_verdict",
                    "judged": False,
                }
            )
            continue
        aligned.append(
            {
                "claim_id": payload["claim_id"],
                "claim": payload["claim"],
                "verdict": verdict.get("verdict", UNKNOWN),
                "reason": str(verdict.get("reason") or ""),
                "judged": True,
            }
        )
    return aligned, duplicate_ids, dropped_ids


def _claim_batches(claims: list[str]) -> tuple[list[list[str]], list[str]]:
    """Split claims into bounded batches; the tail beyond the budget is explicitly uncovered."""
    budget = MAX_CLAIMS_PER_CALL * MAX_JUDGE_BATCHES
    covered = claims[:budget]
    uncovered = claims[budget:]
    batches = [
        covered[index : index + MAX_CLAIMS_PER_CALL]
        for index in range(0, len(covered), MAX_CLAIMS_PER_CALL)
    ]
    return batches, uncovered


async def check_citation_support(
    db: Session,
    citations: list[dict],
    *,
    answer: str,
    claims: list[str] | None = None,
    referenced_unit_ids: list[int] | None = None,
    conflict_unit_ids: list[int] | None = None,
    project_id: int | None = None,
    confidentiality_levels: list[str] | None = None,
) -> dict:
    """Judge whether each citation's evidence entails the conclusion it is attached to.

    Controlled by ``settings.citation_support_check`` (default ``"off"``). When the switch is
    off this reports ``enabled=False`` and makes no model call, so the existing answer path is
    byte-for-byte unchanged. When it is ``"judge"`` the result carries:

    * one ``supported`` / ``unsupported`` / ``unknown`` verdict per citation;
    * one verdict per **claim** with stable ids, so a legal citation id never implies the claim
      it is attached to is actually supported;
    * explicit denominators (``claims_total`` / ``claims_judged`` / ``claims_unjudged`` /
      ``claim_coverage``) plus ``coverage_truncated`` when the per-answer judge budget was hit;
    * alignment diagnostics (``duplicate_verdict_ids`` / ``dropped_verdict_ids``).

    Claims are judged in bounded batches (``MAX_CLAIMS_PER_CALL`` per call, at most
    ``MAX_JUDGE_BATCHES`` calls) so a large answer cannot make one prompt unbounded; the tail
    beyond the budget is reported as uncovered instead of being silently cut off.
    An unavailable or misbehaving judge degrades to ``unknown`` and never raises.
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
    claim_list = [str(item).strip() for item in (claims or []) if str(item).strip()]
    if not claim_list:
        claim_list = split_claims_all(answer_text)
    result["claims_total"] = len(claim_list)
    if not claim_list:
        result["skip_reason"] = "no_claims"
        return result

    batches, uncovered = _claim_batches(claim_list)
    evidence = citation_evidence(usable)
    all_verdicts: list[dict] = []
    batch_payloads: list[dict] = []
    batch_count = 0
    error_type: str | None = None
    facts: dict = {}
    for index, batch in enumerate(batches):
        payloads = claim_payloads(batch)
        # Claim ids are only unique inside one answer, so a batched call keeps its own numbering
        # and its own `claims` list; citations are judged once, in the first batch, so a repeated
        # citation verdict can never be double counted.
        request = {
            "answer": answer_text,
            "claims": payloads,
            "citations": evidence if index == 0 else [],
        }
        batch_count += 1
        verdicts, batch_facts, error_type = await run_judge(
            db,
            CITATION_SUPPORT_PROMPT_KEY,
            CITATION_SUPPORT_SYSTEM_PROMPT,
            json.dumps(request, ensure_ascii=False),
            confidentiality_levels=confidentiality_levels,
            project_id=project_id,
        )
        facts = batch_facts or facts
        all_verdicts.extend(verdicts)
        batch_payloads.extend(payloads)
        if error_type:
            break

    result.update(facts)
    result["batch_count"] = batch_count
    result["verdicts"], citation_alignment = _merge_citation_verdicts(usable, all_verdicts)
    aligned_claims, duplicate_claim_ids, dropped_claim_ids = _align_claim_verdicts(
        batch_payloads, all_verdicts
    )
    result["claims"] = aligned_claims

    duplicates = citation_alignment["duplicate_verdict_ids"]
    dropped = citation_alignment["dropped_verdict_ids"]
    # 只有真正做了主张级判定时，主张对齐的丢弃才计入 dropped_verdict_ids。
    # 引用级回退下裁判本来就只给 citation_id，把那些 verdict 当作“被丢弃”会误导。
    if any(item["judged"] for item in aligned_claims):
        for dropped_id in dropped_claim_ids:
            if dropped_id != UNKEYED_VERDICT:
                dropped.append(dropped_id)
            elif dropped_id not in dropped:
                dropped.append(dropped_id)
    result["duplicate_verdict_ids"] = duplicates
    result["dropped_verdict_ids"] = dropped
    result["unkeyed_verdict_count"] = citation_alignment["unkeyed_verdict_count"]
    # 对齐之后再裁剪：裁判显式给过判定的引用、参与冲突的证据、以及答案实际引用的证据
    # 一律保留；只有“未获得判定且与本次结论无关”的召回证据不计入分母。
    if referenced_unit_ids is not None:
        kept_ids = {int(item) for item in referenced_unit_ids}
        kept_ids |= {int(item) for item in (conflict_unit_ids or [])}
        verdict_unkeyed_ids = {
            str(item.get("citation_id"))
            for item in all_verdicts
            if item.get("citation_id")
        }
        kept: list[dict] = []
        dropped_units: list = []
        for citation, verdict in zip(usable, result["verdicts"]):
            unit_id = citation.get("knowledge_unit_id")
            if (
                unit_id in kept_ids
                or str(verdict.get("citation_id")) in verdict_unkeyed_ids
            ):
                kept.append(verdict)
            else:
                dropped_units.append(unit_id)
        result["verdicts"] = kept
        # 分母必须同步到裁剪后的判定集，否则覆盖率会被无关召回证据稀释。
        usable = [
            citation for citation in usable
            if citation.get("knowledge_unit_id") in (
                {v.get("knowledge_unit_id") for v in kept} | kept_ids)
        ]
        result["unreferenced_evidence_ids"] = dropped_units
    result["judged_citation_count"] = len(result["verdicts"])
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

    judged_claims = [item for item in aligned_claims if item["judged"]]
    # The three verdict counts must be taken over **judged** claims only.  A claim the judge
    # never answered is *unjudged* -- it is already counted by ``claims_unjudged`` and by the
    # coverage ratio.  Counting it as ``unknown`` too made ``claims_unknown`` exceed
    # ``claims_judged`` on real data (observed 7 vs 5), which reads as a contradiction and
    # would let a reader believe the judge looked at more claims than it did.
    claim_tallied = tally_verdicts(judged_claims)
    result["claims_supported"] = claim_tallied["supported_count"]
    result["claims_unsupported"] = claim_tallied["unsupported_count"]
    result["claims_unknown"] = claim_tallied["unknown_count"]
    # 尾部超出单次判断预算时必须显式标记，不能截掉后仍声称全量通过。
    result["coverage_truncated"] = bool(uncovered)
    # 真正得到裁判回应的引用数：（unknown 不是“已判定”，不能被计入覆盖率分子）。
    genuinely_judged = sum(
        1 for item in result["verdicts"]
        if str(item.get("reason") or "") != "judge_returned_no_verdict"
    )
    result["citation_judged"] = genuinely_judged
    if judged_claims:
        # The judge scored individual claims: coverage is measured over the real claims.
        result["claim_judgement"] = "claim_level"
        result["claims_judged"] = len(judged_claims)
        result["claims_unjudged"] = len(claim_list) - len(judged_claims)
        result["claim_coverage"] = _ratio(len(judged_claims), len(claim_list))
        result["supported_claims"] = [
            item["claim"] for item in aligned_claims if item["verdict"] == SUPPORTED
        ]
        result["unsupported_claims"] = [
            item["claim"] for item in aligned_claims if item["verdict"] == UNSUPPORTED
        ]
        result["unknown_claims"] = [
            item["claim"]
            for item in aligned_claims
            if not item["judged"] or item["verdict"] == UNKNOWN
        ]
        claim_verdicts = (
            claim_tallied["supported_count"],
            claim_tallied["unsupported_count"],
            claim_tallied["unknown_count"],
        )
    else:
        # The judge answered only at citation level. That is still a real support judgement: a
        # conclusion whose every citation is entailed is supported. Coverage is then the share
        # of citations the judge actually scored, flagged so no consumer mistakes it for a
        # claim-level measurement (and so an unanswered citation still blocks ``verified``).
        result["claim_judgement"] = "citation_level"
        if error_type:
            # 裁判根本没跑成功：一条都没判定。绝不能把 unknown 当成“已判定”抬高覆盖率。
            result["claims_judged"] = 0
            result["claims_unjudged"] = len(claim_list)
            result["claim_coverage"] = 0.0
        else:
            judged_citations = result["citation_judged"]
            # Coverage is a *ratio*, so numerator and denominator must share one dimension.
            # ``citation_judged`` counts citations while ``len(claim_list)`` counts claims; using
            # them together produced ``claim_coverage`` above 1.0 on real data (observed 1.25 and
            # 2.5), which is not a coverage figure at all.  Because the judge answered at citation
            # level, the honest measurable quantity is citation coverage; claim-level judged
            # counts stay 0 (nothing was judged at that level) and the dimension field says so.
            cited_total = result.get("judged_citation_count") or len(result["verdicts"])
            citation_coverage = _ratio(judged_citations, cited_total)
            result["citation_coverage"] = citation_coverage
            result["claims_judged"] = 0
            result["claims_unjudged"] = len(claim_list)
            # ``claim_coverage`` must mean *claim* coverage, and in citation-level mode no claim
            # was scored: the judge answered about evidence.  Reporting citation coverage under
            # the claim name produced ``claims_judged=0`` next to ``claim_coverage=1.0`` -- a
            # contradiction a reader can only resolve by trusting the wrong number.  Claim
            # coverage is therefore 0.0 with an explicit denominator of 0; the citation ratio
            # travels separately on ``citation_coverage``.
            result["claim_coverage"] = 0.0
            result["claim_coverage_dimension"] = "citation_level"
            result["claim_coverage_numerator"] = 0
            result["claim_coverage_denominator"] = len(claim_list)
        # Citation-level verdicts say whether the *evidence* is entailed, not whether each
        # conclusion was independently checked.  Reporting every claim as supported (or every
        # claim as unsupported) under this mode contradicted ``claims_judged=0`` and let a
        # consumer count unjudged claims as verified.  Claim attribution therefore stays empty:
        # nothing was judged at claim level, so every claim is unknown here; the citation-level
        # verdicts remain visible on their own fields.
        result["supported_claims"] = []
        result["unsupported_claims"] = []
        result["unknown_claims"] = list(claim_list)
        claim_verdicts = (0, 0, len(claim_list))
    result["uncovered_claims"] = list(uncovered)
    result["verification"] = _verification(
        degraded=bool(error_type),
        claims_total=len(claim_list),
        claims_supported=claim_verdicts[0],
        claims_unsupported=claim_verdicts[1],
        claims_unknown=claim_verdicts[2],
        claim_coverage=result["claim_coverage"],
        coverage_truncated=result["coverage_truncated"],
        citation_unsupported=tallied["unsupported_count"],
        citation_unknown=(
            tallied["unknown_count"] if not error_type else 0),
        citation_judged=result["citation_judged"],
        claim_judgement=result.get("claim_judgement"),
    )
    if error_type:
        result["degraded"] = True
        result["degraded_reason"] = error_type
        return result
    result["judged"] = True
    return result


def _verification(
    *,
    degraded: bool,
    claims_total: int,
    claims_supported: int,
    claims_unsupported: int,
    claims_unknown: int,
    claim_coverage: float,
    coverage_truncated: bool,
    citation_unsupported: int,
    citation_unknown: int,
    citation_judged: int,
    claim_judgement: str | None = None,
) -> str:
    """Collapse the judge facts into one answer-level verdict.

    The rules are deliberately conservative: anything short of "every claim was judged and
    supported, and no citation contradicts it" is *not* ``verified``. In particular, zero
    ``unsupported`` counts combined with zero coverage stays ``unknown`` — an unjudged answer
    must never be presented as a clean pass — and a scored ``unknown`` claim is only partial
    support, never a verified one. A judge that failed outright is ``degraded`` even when every
    citation ended up as ``unknown``.
    """
    if degraded:
        return DEGRADED_VERIFICATION
    # 裁判一条都没真正回答（全部是“没有 verdict”）→ 未验证，而不是“部分支持”。
    if citation_judged <= 0 and claims_supported == 0 and claims_unsupported == 0:
        return UNKNOWN_VERIFICATION
    # A citation-level judgement cannot make any *claim* verified: the judge scored evidence,
    # not the statements built from it.  Reporting ``verified`` here would tell the reader that
    # every conclusion was checked when none was.  Claim coverage is 0 in this mode by
    # definition, so this branch must be decided *before* the generic zero-coverage rule.
    if claim_judgement == "citation_level":
        if citation_unsupported > 0 and citation_unsupported >= citation_judged - citation_unsupported:
            return UNSUPPORTED_VERIFICATION
        return PARTIALLY_SUPPORTED
    # No claim was ever scored and the judge said nothing either: unknown, not "clean".
    if claims_total <= 0 or claim_coverage <= 0.0:
        return UNKNOWN_VERIFICATION
    if claims_unsupported > 0 and claims_supported == 0 and citation_unsupported == 0:
        return UNSUPPORTED_VERIFICATION
    if claims_unsupported > 0 or citation_unsupported > 0 or claims_unknown > 0:
        return PARTIALLY_SUPPORTED
    if claim_coverage < 1.0 or coverage_truncated or citation_unknown > 0:
        return PARTIALLY_SUPPORTED
    return VERIFIED


def claim_support_summary(support: dict | None) -> dict:
    """Project the judge payload onto the fields the answer assembler needs.

    ``None`` (switch off / no judgement) is preserved as ``None`` so a disabled run keeps its
    original payload byte-for-byte and never claims semantic verification. Lists and counts are
    kept in distinct keys on purpose: a list must never be read as a denominator.
    """
    if not support or not isinstance(support, dict):
        return {
            "verification": None,
            "claim_judgement": None,
            "supported_claims": [],
            "unsupported_claims": [],
            "unknown_claims": [],
            "supported_count": 0,
            "unsupported_count": 0,
            "unknown_count": 0,
            "unjudged_count": 0,
            "coverage": 0.0,
        }
    return {
        "verification": support.get("verification"),
        "claim_judgement": support.get("claim_judgement"),
        "supported_claims": list(support.get("supported_claims") or []),
        "unsupported_claims": list(support.get("unsupported_claims") or []),
        "unknown_claims": list(support.get("unknown_claims") or []),
        "supported_count": int(support.get("claims_supported") or 0),
        "unsupported_count": int(support.get("claims_unsupported") or 0),
        "unknown_count": int(support.get("claims_unknown") or 0),
        "unjudged_count": int(support.get("claims_unjudged") or 0),
        "coverage": float(support.get("claim_coverage") or 0.0),
    }
