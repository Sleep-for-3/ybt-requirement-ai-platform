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

#: Reporting-system names that must constrain retrieval when the question names
#: them explicitly. "一表通" is the local platform; EAST and 1104 are the two
#: upstream systems whose conversion rows otherwise look nearly identical.
SYSTEM_ALIASES: dict[str, tuple[str, ...]] = {
    "east": ("EAST", "east"),
    "1104": ("1104", "1104报表"),
    "ybt": ("一表通", "一表通制度"),
}

#: Sheet names of the conversion Q&A workbook, used to label a unit's system.
_SHEET_SYSTEMS: tuple[tuple[str, str], ...] = (
    ("EAST", "east"),
    ("1104", "1104"),
    ("一表通", "ybt"),
)

#: 1104 table codes are ``G`` + four digits (G0901/G0902…); the 一表通 table
#: codes are longer (G110001), so a bare four-digit ``G`` code names 1104 even
#: when the question only says "G0902 和一表通的差异".
_1104_TABLE_RE = re.compile(r"\bG\d{4}\b")

#: Data-item codes carry the reporting field identity (F250007, E010008,
#: G110001). The retriever can use them as structured signals instead of relying
#: on BM25/vector similarity alone.
_FIELD_CODE_RE = re.compile(r"\b(?:F\d{6}|E\d{6}|G\d{6})\b", re.IGNORECASE)

#: Phrases that explicitly ask for an older version. They must switch retrieval
#: to the historical branch and nudge superseded versions forward, otherwise a
#: question like "上一版规则是什么" returns the current version's text.
HISTORY_HINTS: tuple[str, ...] = (
    "上一版", "旧版", "老版本", "历史版本", "之前版本", "上一期", "旧规则", "原来版本",
)


def detect_history_intent(query: str) -> bool:
    text = query or ""
    return any(hint in text for hint in HISTORY_HINTS)


def extract_field_codes(query: str) -> set[str]:
    return {match.upper() for match in _FIELD_CODE_RE.findall(query or "")}


# 表号：一表通用 "8.13"，1104/EAST 用 "G01"/"S72"/"G0107"。数字部分宽松匹配，
# 只在单元原文里出现 "表号（主）：<code>" 时才真正加分，所以 "V2.0.0" 之类
# 不会被误当成表号。
_TABLE_CODE_RE = re.compile(r"\b(\d{1,2}\.\d{1,2}|[A-Z]\d{2,3}[A-Z]?)\b", re.IGNORECASE)


def extract_table_codes(query: str) -> set[str]:
    return {match.upper() for match in _TABLE_CODE_RE.findall(query or "")}


def detect_systems(query: str) -> set[str]:
    """Return the reporting systems explicitly named in ``query``.

    A question that names two systems ("EAST 和 1104 分别怎么转") returns both,
    so the caller can keep evidence from each side instead of hard-filtering to
    one. No alias means no constraint at all.
    """

    text = query or ""
    found: set[str] = set()
    for system, aliases in SYSTEM_ALIASES.items():
        if any(alias in text for alias in aliases):
            found.add(system)
    if _1104_TABLE_RE.search(text):
        found.add("1104")
    return found


def unit_system(sheet_name: str | None, content: str | None) -> str | None:
    """Label a knowledge unit with its reporting system.

    ``source_sheet_name`` is authoritative ("转EAST问答" / "转1104问答" /
    "一表通制度问答"); the question id prefix is the fallback for units that lost
    their sheet metadata during parsing.
    """

    sheet = str(sheet_name or "")
    for marker, system in _SHEET_SYSTEMS:
        if marker in sheet:
            return system
    head = str(content or "")[:160]
    if "EAST_" in head:
        return "east"
    if "1104_" in head:
        return "1104"
    if "YBZD_" in head:
        return "ybt"
    return None


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
    "HISTORY_HINTS",
    "INTENT_RULES",
    "INTENT_TYPES",
    "SYNONYM_GROUPS",
    "SYSTEM_ALIASES",
    "detect_history_intent",
    "detect_intent",
    "detect_systems",
    "expand_query",
    "extract_field_codes",
    "matched_scenarios",
    "unit_system",
]
