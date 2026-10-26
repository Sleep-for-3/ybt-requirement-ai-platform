r"""One-off patch: filter frozen evidence to the requested fields at projection time.

Round 75 follow-up.  The frozen ``script_basis.policy_snapshot`` stores the
evidence set of the whole requirement (126 units after field scoping).  Every
generation input deep-copied all of it, so even a single-field run carried the
whole evidence budget and could not fit the 128KB input limit.

The fix keeps the frozen text untouched (integrity is still validated against
the snapshot) and only narrows *which* frozen units enter this particular
projection: units whose ``target_field_code`` is outside the requested field
codes are omitted, and the omission is reported in ``limitations`` so the model
(and the reviewer) knows the projection is field-scoped.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def patch(relative: str, replacements: list[tuple[str, str]]) -> None:
    path = ROOT / relative
    with path.open("r", encoding="utf-8", newline="") as handle:
        raw = handle.read()
    text = raw.replace("\r\n", "\n")
    for old, new in replacements:
        if old not in text:
            raise SystemExit(f"anchor missing in {relative}:\n{old[:200]}")
        if text.count(old) != 1:
            raise SystemExit(f"anchor not unique in {relative}: {old[:80]}")
        text = text.replace(old, new)
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(text.replace("\n", "\r\n"))
    print(f"patched {relative}")


patch("app/services/mapping/requirement_input.py", [
    (
        """    from app.services.knowledge_eligibility import requirement_evidence, validate_frozen_requirement_evidence
    frozen_policy = (content.get("script_basis") or {}).get("policy_snapshot")
    if frozen_policy is not None:""",
        """    from app.services.knowledge_eligibility import requirement_evidence, validate_frozen_requirement_evidence
    bound_codes = sorted({str(record["field"].get("field_code") or "") for record in records} - {""})
    frozen_policy = (content.get("script_basis") or {}).get("policy_snapshot")
    if frozen_policy is not None:""",
    ),
    (
        """        validate_frozen_requirement_evidence(db, project_id, frozen_policy)
        evidence = deepcopy(frozen_policy["evidence"])
    else:
        bound_codes = sorted({str(record["field"].get("field_code") or "") for record in records} - {""})
        evidence = requirement_evidence(db, project_id, allowed["document_ids"], scope.get("scenario_id"),
            MAX_ROWS + 1, field_codes=bound_codes)""",
        """        validate_frozen_requirement_evidence(db, project_id, frozen_policy)
        evidence = deepcopy(frozen_policy["evidence"])
        # 固定快照保留整份证据以保证身份可复核；本次投影只送与所选字段相关的片段。
        evidence, dropped_frozen = _scope_frozen_evidence(db, evidence, bound_codes)
    else:
        dropped_frozen = 0
        evidence = requirement_evidence(db, project_id, allowed["document_ids"], scope.get("scenario_id"),
            MAX_ROWS + 1, field_codes=bound_codes)""",
    ),
    (
        """    if pinned_versions:
        # 版本钉扎是审计事实：候选生成用了哪个版本的证据必须可追溯，不能只看内容哈希。""",
        """    if dropped_frozen:
        result["limitations"].append(
            f"本次只送与所选字段相关的固定制度片段：从快照的 {dropped_frozen + len(evidence)} 条中排除 {dropped_frozen} 条"
            "（其他字段或通用条款之外的片段不参与本次生成；快照原文仍完整保留，可复核）。"
        )
    if pinned_versions:
        # 版本钉扎是审计事实：候选生成用了哪个版本的证据必须可追溯，不能只看内容哈希。""",
    ),
    (
        """def _documents_with_blocking_parse(db, project_id, document_ids):""",
        """def _scope_frozen_evidence(db, evidence, bound_codes):
    \"\"\"Narrow a frozen evidence list to the requested field codes.

    The frozen text is never rewritten: only units that clearly belong to another
    target field are omitted, and the count is reported so the projection is
    auditable.  Units without a field code are general clauses and always kept.
    \"\"\"
    if not evidence or not bound_codes:
        return evidence, 0
    from app.models import KnowledgeUnit
    ids = [item["unit_id"] for item in evidence if item.get("unit_id") is not None]
    codes = dict(db.execute(select(KnowledgeUnit.id, KnowledgeUnit.target_field_code)
        .where(KnowledgeUnit.id.in_(ids))).all())
    allowed = set(bound_codes)
    kept = [item for item in evidence
        if not codes.get(item.get("unit_id")) or codes.get(item.get("unit_id")) in allowed]
    return kept, len(evidence) - len(kept)


def _documents_with_blocking_parse(db, project_id, document_ids):""",
    ),
])

print("done")
