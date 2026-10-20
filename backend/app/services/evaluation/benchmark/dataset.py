"""Case schema, content hashing and the frozen dev/holdout split.

A benchmark case is deliberately *not* a ``RagEvaluationCase`` row: it must describe an
expected and a forbidden behaviour, carry its own provenance and belong to a group whose
rewrites may never straddle the dev/holdout boundary.  The runner maps it onto the real
service chain; nothing here writes to a business table.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Final

#: Bump when the digest inputs change so two dataset versions stay distinguishable.
DATASET_SCHEMA: Final = "overnight-benchmark-v1"

#: The six required families from the task book.  A corpus that does not cover every
#: family is reported as incomplete rather than silently scored on what it has.
FAMILIES: Final[tuple[str, ...]] = (
    "citation_not_supporting",      # ① 引用存在但不支撑结论
    "citation_support_boundary",    # ② 引用支撑判断边界
    "field_semantics",              # ③ 字段语义
    "rerank_long_context",          # ④ 重排与长上下文
    "version_and_scope",            # ⑤ 版本与作用域
    "agent_state_chain",            # ⑥ Agent 状态链
)

#: Families that the deterministic runner can execute through a real service entry point
#: in this environment.  ``agent_state_chain`` is executed through the pure state machine
#: (which is the real module the orchestrator uses), not through a live orchestrator run.
EXECUTABLE_FAMILIES: Final[tuple[str, ...]] = (
    "citation_not_supporting",
    "citation_support_boundary",
    "field_semantics",
    "version_and_scope",
    "agent_state_chain",
)


def dataset_digest(cases: list[dict]) -> str:
    """Content hash over the *observable* case fields, independent of dict order.

    Keys deliberately excluded from the digest: nothing.  A case edit must change the
    version, so a reported number can be tied to exactly the inputs that produced it.
    """
    material = json.dumps(_canonical(cases), sort_keys=True, ensure_ascii=False,
                          separators=(",", ":"))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def content_hash(value) -> str:
    """Digest any case-like value; order-independent for dict keys, order-sensitive for lists."""
    material = json.dumps(_canonical(value), sort_keys=True, ensure_ascii=False,
                          separators=(",", ":"))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _canonical(value):
    """Make a case tree JSON-representable and order-stable.

    ``expected`` may contain a ``set``/``frozenset`` (e.g. an accepted-status family); a
    digest over such a case must not depend on hash randomisation, so sets become sorted
    lists before serialisation.
    """
    if isinstance(value, dict):
        return {str(key): _canonical(item) for key, item in value.items()}
    if isinstance(value, (set, frozenset)):
        return sorted((_canonical(item) for item in value), key=lambda item: json.dumps(
            item, sort_keys=True, ensure_ascii=False))
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    return value


def _split_key(case: dict) -> tuple[str, str]:
    # Seeded groups share a seed_id; the group, not the individual rewrite, is split.
    return (str(case.get("seed_id") or case["case_id"]), str(case["case_id"]))


def split_cases(cases: list[dict]) -> dict[str, list[dict]]:
    """Deterministic ~80/20 dev/holdout split that never splits a seed group.

    Holdout membership is derived from the seed id, so adding a *new* seed
    group can move it between sides -- which is why the digest of each subset is
    reported next to the run and a holdout failure never edits an expectation.
    """
    groups: dict[str, list[dict]] = {}
    for case in cases:
        groups.setdefault(str(case.get("seed_id") or case["case_id"]), []).append(case)

    dev: list[dict] = []
    holdout: list[dict] = []
    for seed_id in sorted(groups):
        bucket = holdout if _in_holdout(seed_id) else dev
        bucket.extend(sorted(groups[seed_id], key=lambda item: str(item["case_id"])))
    return {"dev": dev, "holdout": holdout}


def _in_holdout(seed_id: str) -> bool:
    """Every fifth seed group is holdout; the rule is a pure function of the seed id."""
    digest = hashlib.sha256(seed_id.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % 5 == 0


def coverage(cases: list[dict]) -> dict[str, Any]:
    """Family/count coverage, including every missing family by name."""
    counts: dict[str, int] = {family: 0 for family in FAMILIES}
    for case in cases:
        family = case.get("family")
        if family in counts:
            counts[family] += 1
    missing = [family for family, count in counts.items() if count == 0]
    return {"total": len(cases), "by_family": counts, "missing_families": missing,
            "families_complete": not missing}


def validate_case(case: dict) -> list[str]:
    """Return the list of contract violations for one case (empty means valid)."""
    problems: list[str] = []
    for key in ("case_id", "family", "seed_id", "query", "expected", "forbidden",
                "scoring", "provenance", "synthetic"):
        if key not in case:
            problems.append(f"missing:{key}")
    if case.get("synthetic") is not True:
        problems.append("not_marked_synthetic")
    if case.get("family") not in FAMILIES:
        problems.append(f"unknown_family:{case.get('family')}")
    if not isinstance(case.get("expected"), dict) or not case.get("expected"):
        problems.append("expected_must_be_non_empty_object")
    if not isinstance(case.get("forbidden"), list) or not case.get("forbidden"):
        problems.append("forbidden_must_be_non_empty_list")
    if not isinstance(case.get("scoring"), dict) or not case.get("scoring"):
        problems.append("scoring_must_be_non_empty_object")
    provenance = case.get("provenance")
    if provenance not in {"synthetic", "synthetic_seeded"}:
        problems.append(f"unknown_provenance:{provenance}")
    return problems
