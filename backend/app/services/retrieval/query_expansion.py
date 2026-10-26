"""Query expansion for knowledge retrieval (round 76 G2).

The retriever already expands *tokens* with a small banking vocabulary, but the
retrieval evaluation showed that two question families still rank poorly:

* ``processing`` questions ("这个字段的加工逻辑是什么") only match when the
  knowledge unit happens to use the exact same wording — a unit that writes
  "处理逻辑：直取" or "转换规则" is invisible to a query asking about "加工逻辑".
* ``scenario`` questions ("借记卡场景下这个字段的业务口径") need the scenario
  name in the query and, once matched, a nudge towards the units that belong to
  that scenario.

This module keeps the expansion deterministic and auditable: it only rewrites
the query into a bounded number of variants using a fixed synonym table and the
field codes / scenario names it can see. It never invents facts and it never
drops the original query — the original is always the first variant.
"""

from __future__ import annotations

import re

#: Each group is (canonical term, aliases). A query that contains *any* member of
#: a group gets the canonical term appended as an expansion variant, so units
#: written with a different alias still match through the keyword index.
SYNONYM_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("处理逻辑", ("处理逻辑", "加工逻辑", "取数逻辑", "转换规则", "加工规则", "加工方式", "计算逻辑")),
    ("来源系统", ("来源系统", "上游系统", "数据来源", "业务系统", "系统名称")),
    ("来源", ("来源表", "来源字段", "血缘", "溯源", "字段来源", "上游表")),
    ("场景", ("业务场景", "产品场景", "场景名称", "场景")),
    ("脚本规则", ("脚本规则", "规则明细", "跑批脚本", "脚本血缘")),
    ("业务口径", ("业务口径", "业务定义", "字段口径", "口径")),
    ("处理逻辑类型", ("直取", "加工", "聚合", "关联")),
)

#: Field codes look like ``E010001``; the few non-numeric codes used by the
#: survey template are listed explicitly so they are not lost.
_FIELD_CODE_RE = re.compile(r"\b(?:E\d{6}|E\d{4}|SFJJGDM|SFJJSSBM)\b", re.IGNORECASE)

#: Question words that carry no retrieval signal on their own.
_STOP_PREFIXES = ("请问", "请说明", "帮我看看", "这个字段", "该字段", "字段")


def expand_query(query: str, *, max_variants: int = 3) -> list[str]:
    """Return the original query plus at most ``max_variants - 1`` rewrites."""

    text = (query or "").strip()
    if not text:
        return [""]
    variants: list[str] = [text]
    lowered = text.lower()

    # 1) Synonym variants: append the canonical term so both spellings are indexed.
    for canonical, aliases in SYNONYM_GROUPS:
        if any(alias.lower() in lowered for alias in aliases) and canonical.lower() not in lowered:
            variants.append(f"{text} {canonical}")

    # 2) Field-code variant: keep the code but add the generic terms the units use.
    codes = _FIELD_CODE_RE.findall(text)
    if codes:
        variants.append(f"{text} 数据项 字段口径 {' '.join(dict.fromkeys(codes))}")

    # 3) Processing questions: make sure the "script rules" wording is present.
    if any(alias in text for alias in ("加工逻辑", "处理逻辑", "取数逻辑", "转换规则", "加工规则")):
        variants.append(f"{text} 脚本规则 处理逻辑类型")

    deduped: list[str] = []
    seen: set[str] = set()
    for variant in variants:
        key = variant.strip()
        if key and key not in seen:
            seen.add(key)
            deduped.append(key)
    return deduped[: max(1, max_variants)]


def matched_scenarios(query: str, scenario_names: list[str] | tuple[str, ...]) -> set[str]:
    """Return the scenario names explicitly mentioned in ``query``."""

    text = (query or "").strip()
    if not text:
        return set()
    hits: set[str] = set()
    for name in scenario_names:
        candidate = (name or "").strip()
        if candidate and candidate in text:
            hits.add(candidate)
    return hits


#: Question intent -> phrases that signal it, checked in order. The intent picks
#: the knowledge category that should answer the question (see INTENT_TYPES).
INTENT_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("processing", ("加工", "取数逻辑", "处理逻辑", "转换规则", "加工规则", "怎么算")),
    ("scenario", ("业务口径", "场景", "产品场景")),
    ("lineage", ("来源系统", "血缘", "溯源", "来源表", "上游", "来自哪里", "来自哪个", "来自")),
    ("regulatory", ("监管口径", "监管定义", "口径原文", "监管")),
)

#: Intent -> (preferred knowledge_type, required content marker or None).
INTENT_TYPES: dict[str, tuple[str, str | None]] = {
    "processing": ("technical_research", "处理逻辑"),
    "scenario": ("business_research", None),
    "lineage": ("technical_research", None),
    "regulatory": ("field_explanation", None),
}


def detect_intent(query: str) -> str | None:
    """Return the first matching question intent, or ``None``."""

    text = (query or "").strip()
    if not text:
        return None
    for intent, phrases in INTENT_RULES:
        if any(phrase in text for phrase in phrases):
            return intent
    return None


__all__ = [
    "INTENT_RULES",
    "INTENT_TYPES",
    "SYNONYM_GROUPS",
    "detect_intent",
    "expand_query",
    "matched_scenarios",
]
