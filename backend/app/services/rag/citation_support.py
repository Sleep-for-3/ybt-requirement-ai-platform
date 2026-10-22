"""Self-built citation-support and faithfulness judge engine.

This module ports the *idea* of RefChecker-style entailment checking (judge whether an
extracted claim is entailed by its cited evidence) with an in-house implementation:

* no vendored third-party code, no new dependency, no network access of its own;
* every model call goes through the existing LLM gateway
  (``get_prompt_runtime`` / ``get_runtime_llm_service`` / ``prepare_model_input``), so the
  data-classification guard and the configured model profile keep applying;
* every failure path degrades to ``unknown`` (or a ``degraded`` flag) and never raises, so
  an unavailable or misbehaving judge can never break answer generation or evaluation.

Callers keep their existing contracts: :func:`app.services.rag.citation_validator.validate_citations`
is untouched, and the judge results are reported as *additional* metadata only.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from sqlalchemy.orm import Session

from app.core.settings import get_settings
from app.services.llm import prompt_runtime

logger = logging.getLogger("app.rag.citation_support")

# Dedicated prompt keys. ``get_prompt_runtime`` falls back to ``default_system_prompt`` when no
# PromptTemplateVersion row exists, so no prompt-template row is required for these keys.
CITATION_SUPPORT_PROMPT_KEY = "citation_support_check"
FAITHFULNESS_PROMPT_KEY = "rag_faithfulness_judge"

SUPPORTED = "supported"
UNSUPPORTED = "unsupported"
UNKNOWN = "unknown"

#: Accepted spellings of the three verdicts, including the Chinese labels an in-house model
#: is likely to answer with. Anything unrecognised becomes ``unknown``.
VERDICT_ALIASES = {
    "supported": SUPPORTED,
    "support": SUPPORTED,
    "entailed": SUPPORTED,
    "entailment": SUPPORTED,
    "entails": SUPPORTED,
    "yes": SUPPORTED,
    "true": SUPPORTED,
    "支持": SUPPORTED,
    "有依据": SUPPORTED,
    "蕴含": SUPPORTED,
    "unsupported": UNSUPPORTED,
    "not_supported": UNSUPPORTED,
    "notsupported": UNSUPPORTED,
    "contradicted": UNSUPPORTED,
    "contradiction": UNSUPPORTED,
    "refuted": UNSUPPORTED,
    "no": UNSUPPORTED,
    "false": UNSUPPORTED,
    "不支持": UNSUPPORTED,
    "无依据": UNSUPPORTED,
    "矛盾": UNSUPPORTED,
    "unknown": UNKNOWN,
    "uncertain": UNKNOWN,
    "unclear": UNKNOWN,
    "nei": UNKNOWN,
    "not_enough_info": UNKNOWN,
    "insufficient": UNKNOWN,
    "不确定": UNKNOWN,
    "未知": UNKNOWN,
    "无法判断": UNKNOWN,
    "无从判断": UNKNOWN,
}

#: Candidate container keys a judge payload may nest its verdict list under.
VERDICT_CONTAINER_KEYS = ("verdicts", "results", "judgements", "judgments", "claims", "items")

#: Hard cap for one claim batch. A single judge call never sees more than this many claims, so a
#: slow model cannot stall the answer on an unbounded prompt.
MAX_CLAIMS_PER_CALL = 20
#: Backwards-compatible alias: the historical single-call cap.
MAX_CLAIMS = MAX_CLAIMS_PER_CALL
#: How many claim batches one answer may spend. 3 x 20 = 60 claims are covered; anything beyond
#: that is reported as *explicitly uncovered* rather than silently cut off.
MAX_JUDGE_BATCHES = 3
MAX_QUOTE_CHARS = 1200
MAX_PROVENANCE_CHARS = 200
MAX_REASON_CHARS = 300
#: Marker used when a verdict carries no usable key (neither claim_id nor citation_id).
UNKEYED_VERDICT = "<unkeyed>"

CITATION_SUPPORT_SYSTEM_PROMPT = (
    "你是银行一表通知识问答的引用蕴含校验裁判（[AI_SKILL_CITATION_SUPPORT_V2]）。"
    "输入包含 answer、claims（claim_id 与原子断言）、citations（citation_id、引文、来源或版本）。"
    "请完成三件事："
    "1) 对每条引用判断它是否支持 claims 中至少一条原子断言：supported=至少蕴含一条；"
    "unsupported=与断言矛盾或完全不涉及；unknown=证据不足、只有培训/PPT/二手转述、或无法判断。"
    "2) 对每条原子断言判断所有引用合起来是否支持它，取值同上；断言只被覆盖了一部分条件时，"
    "该断言不得判 supported，应判 unsupported 或 unknown。"
    "3) 若两条及以上正式来源对同一主张给出互相矛盾的表述，必须列入 conflicts（citation_ids "
    "至少两条）并说明 conflict_type：version（版本差异）/ scope（适用范围差异）/ "
    "contradiction（真实矛盾）；禁止静默合并互相矛盾的结论。"
    "判定规则："
    "1) 只有正式制度原文或正式条款可以判 supported；培训材料、PPT 转述、二手摘要、"
    "未给原始出处的综述，即使内容看似吻合也一律判 unknown；"
    "2) 引文的版本、生效日期、适用范围与结论不一致时判 unsupported；"
    "3) 引文与断言字面相近但口径范围不同（如表内/表外、含/不含）判 unsupported。"
    "只允许输出 JSON，格式为 "
    '{"verdicts": [{"citation_id": "<引用编号>", "verdict": "supported|unsupported|unknown", '
    '"supported_claim_ids": ["<claim-1>"], "reason": "<不超过50字的理由>"}], '
    '"claims": [{"claim_id": "<claim-1>", "verdict": "supported|unsupported|unknown", '
    '"reason": "<不超过50字的理由>"}], '
    '"conflicts": [{"claim_id": "<claim-1>", "citation_ids": ["<引用编号>", "<引用编号>"], '
    '"conflict_type": "version|scope|contradiction", "reason": "<不超过50字的理由>"}]}。'
    "证据不足以判断时输出 unknown，不得推测，不得输出任何额外文字。"
)

FAITHFULNESS_SYSTEM_PROMPT = (
    "你是银行一表通知识问答的忠实性裁判（[AI_SKILL_FAITHFULNESS_V1]）。"
    "对每一条断言，判断它是否能由给定的引用证据支持。"
    "只允许输出 JSON，格式为 "
    '{"claims": [{"claim": "<断言原文或序号>", "verdict": "supported|unsupported|unknown", '
    '"reason": "<不超过50字的理由>"}]}。'
    "证据不足以判断时输出 unknown，不得推测，不得输出任何额外文字。"
)


def normalize_verdict(value: Any) -> str:
    """Map an arbitrary judge verdict spelling onto supported/unsupported/unknown."""
    if not isinstance(value, str):
        return UNKNOWN
    key = value.strip().lower().replace("-", "_").replace(" ", "_")
    if not key:
        return UNKNOWN
    return VERDICT_ALIASES.get(key, UNKNOWN)


def _reason(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()[:MAX_REASON_CHARS]


def _raw_verdict_items(payload: Any) -> list[dict]:
    """Collect every candidate verdict item from a judge payload.

    ``[AI_SKILL_CITATION_SUPPORT_V2]`` asks for *two* lists (``verdicts`` per citation and
    ``claims`` per claim). The V1 shape nested a single list under one of
    :data:`VERDICT_CONTAINER_KEYS`; both are accepted so older prompts keep working.
    """
    if isinstance(payload, str):
        return []
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    items: list[dict] = []
    seen_containers = False
    for key in VERDICT_CONTAINER_KEYS:
        candidate = payload.get(key)
        if isinstance(candidate, list):
            seen_containers = True
            items.extend(item for item in candidate if isinstance(item, dict))
        elif isinstance(candidate, dict):
            seen_containers = True
            items.append(candidate)
    if not seen_containers:
        items.append(payload)
    return items


def parse_judge_verdicts(payload: Any) -> list[dict]:
    """Normalise a judge payload into ``[{"verdict": ..., "reason": ..., ...}, ...]``.

    Accepts a bare list, a dict nesting the list under one of
    :data:`VERDICT_CONTAINER_KEYS`, or a single verdict object. Unparseable input yields an
    empty list (the caller then degrades to unknown) — this function never raises.

    Each item is tagged with ``dimension``: ``citation`` (keyed by citation_id),
    ``claim`` (keyed by claim_id only) or ``pair`` (both). Without the tag a claim-only
    verdict could be paired positionally with an unanswered citation.
    """
    verdicts: list[dict] = []
    for item in _raw_verdict_items(payload):
        verdict = {
            "verdict": normalize_verdict(item.get("verdict") or item.get("label") or item.get("result")),
            "reason": _reason(item.get("reason") or item.get("rationale")),
        }
        for source_key in ("citation_id", "citation_ref", "ref", "id"):
            if item.get(source_key) not in (None, ""):
                verdict["citation_id"] = str(item[source_key])
                break
        for source_key in ("claim", "claim_text", "statement"):
            if item.get(source_key) not in (None, ""):
                verdict["claim"] = str(item[source_key])
                break
        if item.get("claim_id") not in (None, ""):
            verdict["claim_id"] = str(item["claim_id"])
        supported_claims = item.get("supported_claim_ids") or item.get("supported_claims")
        if isinstance(supported_claims, list):
            verdict["supported_claim_ids"] = [str(value) for value in supported_claims if value]
        conflicts = item.get("conflicts")
        if isinstance(conflicts, list) and conflicts:
            verdict["conflicts"] = conflicts
        if item.get("knowledge_unit_id") is not None:
            verdict["knowledge_unit_id"] = item["knowledge_unit_id"]
        has_citation = "citation_id" in verdict
        has_claim = "claim_id" in verdict or "claim" in verdict
        verdict["dimension"] = "pair" if has_citation and has_claim else ("citation" if has_citation else ("claim" if has_claim else "unknown"))
        verdicts.append(verdict)
    return verdicts


def parse_judge_conflicts(payload: Any) -> list[dict]:
    """Pull the raw ``conflicts`` list out of a judge payload (normalisation happens later)."""
    if isinstance(payload, dict):
        candidate = payload.get("conflicts") or payload.get("conflict")
        if isinstance(candidate, list):
            return [item for item in candidate if isinstance(item, dict)]
        return []
    raw: list[dict] = []
    for item in _raw_verdict_items(payload):
        candidate = item.get("conflicts")
        if isinstance(candidate, list):
            raw.extend(entry for entry in candidate if isinstance(entry, dict))
    return raw

def tally_verdicts(verdicts: list[dict]) -> dict:
    """Count supported/unsupported/unknown verdicts."""
    supported = sum(1 for item in verdicts if item.get("verdict") == SUPPORTED)
    unsupported = sum(1 for item in verdicts if item.get("verdict") == UNSUPPORTED)
    unknown = sum(1 for item in verdicts if item.get("verdict") == UNKNOWN)
    return {
        "supported_count": supported,
        "unsupported_count": unsupported,
        "unknown_count": unknown,
        "judged_count": supported + unsupported + unknown,
    }


def _ratio(part: int, whole: int) -> float:
    return round(part / whole, 4) if whole else 0.0


def split_claims(text: str) -> list[str]:
    """Split an answer into atomic claims when the caller supplied none."""
    if not text:
        return []
    parts = (part.strip() for part in re.split(r"[。；;\n]+", str(text)))
    return [part for part in parts if part][:MAX_CLAIMS]



_COMPOUND_MARKER = re.compile(r"(?:条件|口径|范围|包括|包含|分别为|分别|如下|以下)\s*[:：]")
_ENUMERATION_SPLIT = re.compile(r"[、，,]")
MAX_COMPOUND_ITEMS = 8


def _expand_compound_claim(sentence: str) -> list[str]:
    """Split a "subject + enumerated conditions" sentence into atomic claims.

    A regulator sentence such as ``报送范围包括：表内贷款、表外担保、贴现。`` carries three
    independent conditions. Judging it as one claim lets a single citation that only covers
    ``表内贷款`` look like full support — exactly the C08 defect. Splitting keeps coverage
    honest: 1/3 covered is partial support, not "verified".
    """
    match = _COMPOUND_MARKER.search(sentence)
    if match is None:
        return [sentence]
    head = sentence[: match.start()].strip()
    tail = sentence[match.end():].rstrip("。；;.!！ ").strip()
    items = [item.strip() for item in _ENUMERATION_SPLIT.split(tail) if item.strip()]
    if len(items) < 2 or len(items) > MAX_COMPOUND_ITEMS:
        return [sentence]
    # 只有一项带冒号的普通句子（如「说明：xxx」之外的描述）不应被拆碎
    if not head:
        return [sentence]
    return [f"{head}：{item}。" for item in items]


def split_claims_all(text: str) -> list[str]:
    """Split a whole answer into atomic claims **without truncation**.

    The caller needs the real total to publish a coverage denominator: silently keeping the
    first N claims is exactly the defect where an answer looks fully verified while its tail was
    never judged. Punctuation is preserved so a supported claim can be shown verbatim.
    Enumerated compound conclusions are expanded into one claim per condition.
    """
    if not text:
        return []
    parts = (part.strip() for part in re.split(r"(?<=[。；;])", str(text)))
    claims: list[str] = []
    for part in parts:
        if not part:
            continue
        claims.extend(_expand_compound_claim(part))
    return claims


def claim_payloads(claims: list[str]) -> list[dict]:
    """Give every claim a stable id so verdicts can never be aligned by position."""
    return [
        {"claim_id": f"claim-{index + 1}", "claim": str(text)}
        for index, text in enumerate(claims)
    ]


def citation_evidence(citations: Any) -> list[dict]:
    """Project citations onto the minimal evidence payload handed to the judge.

    Provenance travels with the quote: a judge that only sees text cannot tell a
    regulation article from a training deck, or a v2 quote from the v1 the snapshot
    froze. Those are exactly the citation-trust decisions the product needs, so the
    whitelisted metadata is included when the caller supplied it (bounded, so a long
    field cannot grow the prompt without limit).
    """
    evidence: list[dict] = []
    for index, citation in enumerate(citations or []):
        if not isinstance(citation, dict):
            continue
        entry = {
            "citation_id": str(citation.get("citation_id") or f"citation-{index}"),
            "label": str(citation.get("label") or ""),
            "quoted_content": str(citation.get("quoted_content") or "")[:MAX_QUOTE_CHARS],
        }
        for source_key, target_key in (
            ("source_name", "source_name"),
            ("title", "source_name"),
            ("location_text", "location_text"),
            ("locator", "location_text"),
            ("version", "version"),
            ("effective_date", "effective_date"),
            ("published_at", "published_at"),
        ):
            if target_key in entry:
                continue
            value = citation.get(source_key)
            if isinstance(value, str):
                value = value.strip()
            if value not in (None, ""):
                entry[target_key] = str(value)[:MAX_PROVENANCE_CHARS]
        if citation.get("knowledge_unit_id") is not None:
            entry["knowledge_unit_id"] = citation["knowledge_unit_id"]
        evidence.append(entry)
    return evidence


async def run_judge(
    db: Session,
    prompt_key: str,
    system_prompt: str,
    user_prompt: str,
    *,
    confidentiality_levels: list[str] | None = None,
    project_id: int | None = None,
) -> tuple[list[dict], dict, str | None]:
    """Run one judge call through the LLM gateway.

    Returns ``(verdicts, model_facts, error_type)``. ``error_type`` is ``None`` on a completed
    call (even when the model returned nothing parseable) and otherwise carries the gateway's
    error type so the caller can report a graceful degradation. This helper never raises and
    never writes ModelCallLog rows or commits — judge results stay side-effect free.
    """
    verdicts, _conflicts, facts, error_type = await run_judge_with_conflicts(
        db,
        prompt_key,
        system_prompt,
        user_prompt,
        confidentiality_levels=confidentiality_levels,
        project_id=project_id,
    )
    return verdicts, facts, error_type


async def run_judge_with_conflicts(
    db: Session,
    prompt_key: str,
    system_prompt: str,
    user_prompt: str,
    *,
    confidentiality_levels: list[str] | None = None,
    project_id: int | None = None,
) -> tuple[list[dict], list[dict], dict, str | None]:
    """Same as :func:`run_judge` but also returns the raw ``conflicts`` the judge reported."""
    facts: dict[str, Any] = {
        "model_profile_id": None,
        "provider_type": None,
        "model_name": None,
    }
    try:
        runtime = prompt_runtime.get_prompt_runtime(db, prompt_key)
        facts = {
            "model_profile_id": runtime.model_profile_id,
            "provider_type": runtime.provider_type,
            "model_name": runtime.model_name,
        }
        service = prompt_runtime.get_runtime_llm_service(runtime)
        guarded_input = prompt_runtime.prepare_model_input(
            runtime,
            user_prompt,
            list(confidentiality_levels or ["internal"]),
            db=db,
            project_id=project_id,
        )
        payload = await service.chat_json(system_prompt, guarded_input)
        return parse_judge_verdicts(payload), parse_judge_conflicts(payload), facts, None
    except prompt_runtime.LLMRuntimeError as exc:
        error_type = exc.error_type
    except Exception as exc:  # noqa: BLE001 - the judge must never break the caller
        error_type = getattr(exc, "error_type", None) or type(exc).__name__
    logger.warning(
        "judge call unavailable prompt_key=%s project_id=%s error_type=%s",
        prompt_key,
        project_id,
        error_type,
    )
    return [], [], facts, error_type


def _base_result(enabled: bool, prompt_key: str) -> dict:
    return {
        "enabled": enabled,
        "judged": False,
        "verdicts": [],
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
        "prompt_key": prompt_key,
    }


async def judge_faithfulness(
    db: Session,
    *,
    answer: str,
    citations: Any = None,
    claims: Any = None,
    project_id: int | None = None,
    confidentiality_levels: list[str] | None = None,
) -> dict:
    """Judge whether an answer's claims are supported by its cited evidence.

    Controlled by ``settings.ragas_judge_enabled`` (default ``False``): when the switch is off
    this returns immediately with ``enabled=False`` and makes no model call, so existing
    evaluation output is untouched. ``faithfulness`` is ``supported / (supported + unsupported)``
    over the judged claims; ``unsupported_ratio`` is ``unsupported / claims_total``.
    """
    settings = get_settings()
    enabled = bool(getattr(settings, "ragas_judge_enabled", False))
    result = _base_result(enabled, FAITHFULNESS_PROMPT_KEY)
    result["claims_total"] = 0
    result["answer_judged"] = False
    if not enabled:
        result["skip_reason"] = "judge_disabled"
        return result

    answer_text = str(answer or "").strip()
    if not answer_text:
        result["skip_reason"] = "empty_answer"
        return result

    claim_list = [str(item).strip() for item in (claims or []) if str(item).strip()]
    if not claim_list:
        claim_list = split_claims(answer_text)
    claim_list = claim_list[:MAX_CLAIMS]
    if not claim_list:
        result["skip_reason"] = "no_claims"
        return result
    result["claims_total"] = len(claim_list)
    user_prompt = json.dumps(
        {
            "answer": answer_text,
            "claims": claim_list,
            "citations": citation_evidence(citations),
        },
        ensure_ascii=False,
    )
    verdicts, facts, error_type = await run_judge(
        db,
        FAITHFULNESS_PROMPT_KEY,
        FAITHFULNESS_SYSTEM_PROMPT,
        user_prompt,
        confidentiality_levels=confidentiality_levels,
        project_id=project_id,
    )
    result.update(facts)
    if error_type:
        result["degraded"] = True
        result["degraded_reason"] = error_type
        return result

    tallied = tally_verdicts(verdicts)
    if not tallied["judged_count"]:
        result["degraded"] = True
        result["degraded_reason"] = "invalid_judgement"
        return result

    result.update(tallied)
    result["verdicts"] = verdicts
    result["judged"] = True
    result["answer_judged"] = True
    decisive = tallied["supported_count"] + tallied["unsupported_count"]
    result["faithfulness"] = _ratio(tallied["supported_count"], decisive)
    result["unsupported_ratio"] = _ratio(tallied["unsupported_count"], len(claim_list))
    return result
