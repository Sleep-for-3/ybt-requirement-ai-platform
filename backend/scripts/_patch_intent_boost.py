"""Patch: intent-aware boosts on top of query expansion (round 76 G2). CRLF safe."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(r"C:\Users\李儒伟\Desktop\ai-platform-dsh-20260930-150943 (2)\ai-platform\backend")
EDITS: list[tuple[Path, str, str, str]] = []


def add(path: Path, old: str, new: str, label: str) -> None:
    EDITS.append((path, old, new, label))


EXPANSION = ROOT / "app" / "services" / "retrieval" / "query_expansion.py"
RETRIEVER = ROOT / "app" / "services" / "retrieval" / "hybrid_retriever.py"
SETTINGS = ROOT / "app" / "core" / "settings.py"

add(
    EXPANSION,
    '__all__ = ["SYNONYM_GROUPS", "expand_query", "matched_scenarios"]\n',
    '''#: Question intent -> phrases that signal it, checked in order. The intent picks
#: the knowledge category that should answer the question (see INTENT_TYPES).
INTENT_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("processing", ("加工", "取数逻辑", "处理逻辑", "转换规则", "加工规则", "怎么算")),
    ("scenario", ("业务口径", "场景", "产品场景")),
    ("lineage", ("来源系统", "血缘", "溯源", "来源表", "上游")),
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
''',
    "expansion-intent",
)

add(
    RETRIEVER,
    "from .query_expansion import expand_query, matched_scenarios\n",
    "from .query_expansion import INTENT_TYPES, detect_intent, expand_query, matched_scenarios\n",
    "retriever-import-intent",
)

add(
    RETRIEVER,
    "        scenario_ids = {scenario_ids_by_name[name] for name in scenario_names}\n",
    "        scenario_ids = {scenario_ids_by_name[name] for name in scenario_names}\n"
    "        intent = detect_intent(query) if expansion_enabled else None\n",
    "retriever-intent",
)

add(
    RETRIEVER,
    '        scenario_boost = _setting_float(settings, "query_expansion_scenario_boost", 0.12)\n',
    '        scenario_boost = _setting_float(settings, "query_expansion_scenario_boost", 0.12)\n'
    '        intent_boost = _setting_float(settings, "query_intent_boost", 0.18)\n',
    "retriever-intent-boost",
)

add(
    RETRIEVER,
    """            scenario_hit = bool(scenario_ids) and unit.scenario_id in scenario_ids
            if scenario_hit:
                reasons.append("场景名匹配")
""",
    """            scenario_hit = bool(scenario_ids) and unit.scenario_id in scenario_ids
            if scenario_hit:
                reasons.append("场景名匹配")
            intent_hit = False
            if intent:
                preferred_type, marker = INTENT_TYPES[intent]
                if unit.knowledge_type == preferred_type and (
                    marker is None or marker in (unit.content or "")
                ):
                    intent_hit = True
                    reasons.append(f"意图匹配（{intent}）")
""",
    "retriever-intent-hit",
)

add(
    RETRIEVER,
    "            ranking_score = fused.get(unit_id, 0.0) + rule_boost + authority_bonus\n",
    "            ranking_score = (\n"
    "                fused.get(unit_id, 0.0)\n"
    "                + rule_boost\n"
    "                + authority_bonus\n"
    "                + (intent_boost if intent_hit else 0.0)\n"
    "            )\n",
    "retriever-ranking",
)

add(
    RETRIEVER,
    '                "scenario_hint": sorted(scenario_names),\n',
    '                "scenario_hint": sorted(scenario_names),\n'
    '                "intent": intent,\n',
    "retriever-log-intent",
)

add(
    SETTINGS,
    "    query_expansion_scenario_boost: float = 0.12\n",
    "    query_expansion_scenario_boost: float = 0.12\n"
    "    query_intent_boost: float = 0.18\n",
    "settings-intent",
)


def main() -> int:
    applied = 0
    for path, old, new, label in EDITS:
        raw = path.read_bytes().decode("utf-8")
        text = raw.replace("\r\n", "\n")
        count = text.count(old)
        if count == 0 and new in text:
            print(f"skip {label}")
            continue
        if count != 1:
            print(f"FAIL {label}: anchor count={count}")
            return 1
        text = text.replace(old, new, 1)
        path.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))
        print(f"ok {label}")
        applied += 1
    print(f"applied {applied}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
