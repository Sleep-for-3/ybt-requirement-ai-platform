r"""One-off patch: make the evidence-confirmation agent useful, not just strict.

Round 75.  ``evaluate_claim_support`` is a deterministic verifier: it only says
"supported" for a closed set of assertion kinds whose facts it can recompute from
script rules / runtime facts.  Real candidates (T_5_1 batches) mark every claim
support as ``unknown`` and use kind ``other``/``code_mapping`` for text that is
literally copied from the cited evidence unit, so the report was "unknown" for
100% of claims: correct but useless — a reviewer gets no signal about which
claims the retrieved evidence actually backs.

This patch adds a conservative *grounding* pass on top of the existing rules:

* only runs when the claim cites at least one evidence unit that is present in
  the fixed input;
* compares the claim against the cited evidence text with character bigram
  coverage (>= 0.75 by default) and refuses when the claim negates the evidence;
* supersedes only the "cannot verify" class of findings
  (``declared_support_unknown`` / ``assertion_not_verifiable`` /
  ``assertion_kind_unknown`` / ``claim_unverifiable_tokens`` / ``evidence_missing``)
  and records ``evidence_grounding_verified`` with the measured coverage;
* never overrides a conflict (rule/evidence/negation still win), and states in
  the finding message that this is a text-level check, not a semantic judgement.

Threshold is configurable through ``settings.claim_grounding_min_coverage`` so it
can be tuned against the A/B evaluation instead of being a magic number.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

NEW_HELPERS = '''# "无法确定性校验"这一类结论可以被证据原文的文本级核对取代；冲突永远不被取代。
_GROUNDING_SUPERSEDABLE = frozenset({
    "declared_support_unknown",
    "assertion_not_verifiable",
    "assertion_kind_unknown",
    "claim_unverifiable_tokens",
    "evidence_missing",
    "claim_without_support",
})
_GROUNDING_PUNCTUATION = re.compile(r"[\\s，。；：、！？,.;:!?（）()\\[\\]【】“”\\"'`]+")


def _normalize_for_grounding(value) -> str:
    return _GROUNDING_PUNCTUATION.sub("", str(value or "").lower())


def _grounding_coverage(claim_text: str, evidence_texts: list[str]) -> float:
    claim = _normalize_for_grounding(claim_text)
    if len(claim) < 8:
        return 0.0
    corpus = _normalize_for_grounding("\\n".join(evidence_texts))
    if not corpus:
        return 0.0
    shingles = [claim[index:index + 2] for index in range(len(claim) - 1)]
    if not shingles:
        return 0.0
    return sum(1 for shingle in shingles if shingle in corpus) / len(shingles)


def _grounding_threshold() -> float:
    try:
        from app.core.settings import get_settings

        value = getattr(get_settings(), "claim_grounding_min_coverage", None)
    except Exception:  # noqa: BLE001 - settings must never break verification
        value = None
    return float(value) if isinstance(value, (int, float)) else 0.75


def _supersede_with_grounding(lowered, text, cited_evidence, issues):
    """证据原文覆盖主张关键词时，把"无法校验"降级为"与证据原文一致"。

    这是文本级核对：它证明"这句话确实抄自召回到的证据"，不证明"这句话的业务
    结论正确"。因此 finding 里必须写清楚覆盖率和这一点，供人工复核时区分。
    """
    if not cited_evidence:
        return None
    candidates = {item[1] for item in issues.items}
    if not candidates & _GROUNDING_SUPERSEDABLE:
        return None
    texts = [str(unit.get("content") or "") for unit in cited_evidence if str(unit.get("content") or "").strip()]
    if not texts:
        return None
    threshold = _grounding_threshold()
    coverage = _grounding_coverage(text, texts)
    if coverage < threshold:
        return None
    if _negation_conflict(lowered, "\\n".join(texts).lower(), []):
        return None
    issues.items = [item for item in issues.items if item[1] not in _GROUNDING_SUPERSEDABLE]
    issues.support(
        "evidence_grounding_verified",
        f"主张关键片段与所引证据原文一致（字符二连覆盖 {coverage:.0%}）；这是文本级核对，"
        "不代表业务结论已经业务确认",
    )
    return {"coverage": round(coverage, 3), "threshold": threshold}
'''


def patch(relative: str, replacements: list[tuple[str, str]]) -> None:
    path = ROOT / relative
    with path.open("r", encoding="utf-8", newline="") as handle:
        raw = handle.read()
    text = raw.replace("\r\n", "\n")
    for old, new in replacements:
        if text.count(old) != 1:
            raise SystemExit(f"anchor missing/not unique in {relative}: {old[:120]!r}")
        text = text.replace(old, new)
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(text.replace("\n", "\r\n"))
    print(f"patched {relative}")


patch("app/services/requirement_claim_support.py", [
    (
        """    def unknown(self, code, message, refs=()):
        self.items.append((UNKNOWN, code, message))
        self.refs.extend(str(ref) for ref in refs if ref not in (None, ""))""",
        """    def unknown(self, code, message, refs=()):
        self.items.append((UNKNOWN, code, message))
        self.refs.extend(str(ref) for ref in refs if ref not in (None, ""))

    def support(self, code, message, refs=()):
        self.items.append((SUPPORTED, code, message))
        self.refs.extend(str(ref) for ref in refs if ref not in (None, ""))""",
    ),
    (
        """def _evaluate_claim(claim, index, sources):
    \"\"\"返回 (ClaimEvaluation, list[ClaimSupportFinding])。\"\"\"""",
        NEW_HELPERS + """

def _evaluate_claim(claim, index, sources):
    \"\"\"返回 (ClaimEvaluation, list[ClaimSupportFinding])。\"\"\"""",
    ),
    (
        """    status = CONFLICT if any(item[0] == CONFLICT for item in issues.items) else (
        UNKNOWN if issues.items else SUPPORTED)""",
        """    _supersede_with_grounding(lowered, text, cited_evidence, issues)
    status = CONFLICT if any(item[0] == CONFLICT for item in issues.items) else (
        UNKNOWN if any(item[0] == UNKNOWN for item in issues.items) else SUPPORTED)""",
    ),
])

print("done")
