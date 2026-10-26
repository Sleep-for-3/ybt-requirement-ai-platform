"""Patch: scenario-aware query expansion in the hybrid retriever (round 76 G2).

CRLF-safe: read bytes, normalise to \n, replace exact anchors, write back as \r\n.
Every anchor must match exactly once; otherwise the script exits non-zero.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(r"C:\Users\李儒伟\Desktop\ai-platform-dsh-20260930-150943 (2)\ai-platform\backend")

EDITS: list[tuple[Path, str, str, str]] = []


def _add(path: Path, old: str, new: str, label: str) -> None:
    EDITS.append((path, old, new, label))


# 1) imports
_add(
    ROOT / "app" / "services" / "retrieval" / "hybrid_retriever.py",
    "from .reranker import rerank_items\n",
    "from .query_expansion import expand_query, matched_scenarios\nfrom .reranker import rerank_items\n",
    "retriever-import",
)

# 2) scenarios + variants before tokenisation
_add(
    ROOT / "app" / "services" / "retrieval" / "hybrid_retriever.py",
    """        tokens = tokenize(
            " ".join(
                filter(
                    None,
                    [
                        query,
                        target.field_code if target else None,
                        target.field_name if target else None,
                        target.field_definition if target else None,
                    ],
                )
            ),
            expand_synonyms=True,
        )
""",
    """        expansion_enabled = bool(getattr(settings, "query_expansion_enabled", True))
        max_variants = max(1, _setting_int(settings, "query_expansion_max_variants", 3))
        variants = (
            expand_query(query, max_variants=max_variants)
            if expansion_enabled
            else [query]
        )
        if not variants:
            variants = [query]
        scenario_names: set[str] = set()
        if expansion_enabled:
            scenario_names = matched_scenarios(
                query,
                list(
                    self.db.scalars(
                        select(ProductScenario.scenario_name).where(
                            ProductScenario.project_id == project_id,
                            ProductScenario.enabled.is_(True),
                        )
                    ).all()
                ),
            )
        tokens = tokenize(
            " ".join(
                filter(
                    None,
                    [
                        " ".join(variants),
                        target.field_code if target else None,
                        target.field_name if target else None,
                        target.field_definition if target else None,
                    ],
                )
            ),
            expand_synonyms=True,
        )
""",
    "retriever-variants",
)

# 3) scenario boost definition next to authority boost
_add(
    ROOT / "app" / "services" / "retrieval" / "hybrid_retriever.py",
    '        authority_boost = _setting_float(settings, "retrieval_authority_boost", 0.15)\n',
    '        authority_boost = _setting_float(settings, "retrieval_authority_boost", 0.15)\n'
    '        scenario_boost = _setting_float(settings, "query_expansion_scenario_boost", 0.12)\n',
    "retriever-scenario-boost",
)

# 4) scenario hit inside the per-item loop
_add(
    ROOT / "app" / "services" / "retrieval" / "hybrid_retriever.py",
    """            rule_boost = 0.05 if reasons else 0.0
""",
    """            scenario_hit = bool(scenario_names) and unit.scenario_name in scenario_names
            if scenario_hit:
                reasons.append("场景名匹配")
            rule_boost = (0.05 if reasons else 0.0) + (
                scenario_boost if scenario_hit else 0.0
            )
""",
    "retriever-scenario-hit",
)

# 5) log filters
_add(
    ROOT / "app" / "services" / "retrieval" / "hybrid_retriever.py",
    '                "authority_boost": authority_boost,\n',
    '                "authority_boost": authority_boost,\n'
    '                "query_variant_count": len(variants),\n'
    '                "scenario_hint": sorted(scenario_names),\n',
    "retriever-log",
)

# 6) settings
_add(
    ROOT / "app" / "core" / "settings.py",
    '    retrieval_authority_boost: float = 0.15\n',
    '    retrieval_authority_boost: float = 0.15\n'
    '    query_expansion_enabled: bool = True\n'
    '    query_expansion_max_variants: int = 3\n'
    '    query_expansion_scenario_boost: float = 0.12\n',
    "settings-expansion",
)


def main() -> int:
    applied = 0
    for path, old, new, label in EDITS:
        raw = path.read_bytes().decode("utf-8")
        text = raw.replace("\r\n", "\n")
        count = text.count(old)
        if count == 0 and new in text:
            print(f"skip {label}（已存在）")
            continue
        if count != 1:
            print(f"FAIL {label}: anchor count={count} in {path}")
            return 1
        text = text.replace(old, new, 1)
        path.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))
        print(f"ok {label}")
        applied += 1
    print(f"applied {applied} edits")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
