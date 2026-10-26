r"""One-off patch: scope generation evidence and script rules to the selected fields.

Background (round 75): after M1 seeded 166 knowledge units, preparing a T_5_1
generation input failed with "输入字节：请求 410135 字节，上限 128000 字节".

Measured composition of the projection (in-process, content v5):

    evidence        296304 bytes (157 units x ~3.5KB, all units of the bound docs)
    script_basis     85136 bytes (rules 40542 + template 32733)
    fields           22245 bytes

The projection deliberately refuses to truncate, so the only correct fix is to
stop sending facts that cannot apply to the selected fields:

* evidence is filtered to units whose ``target_field_code`` is one of the bound
  field codes (units without a field code stay: they are general clauses);
* script rules are filtered to rules whose target column is a bound column
  (rules without a target column stay: they state table-level facts).

Both filters are recorded in the projection audit (``projection``/limitations)
so the omission is visible instead of silent.
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


patch("app/services/knowledge_eligibility.py", [
    (
        "def selected_requirement_units(db, project_id, document_ids, scenario_id=None, limit=501):",
        "def selected_requirement_units(db, project_id, document_ids, scenario_id=None, limit=501, field_codes=None):",
    ),
    (
        """    if scenario_id:
        query = query.where(or_(KnowledgeUnit.scenario_id.is_(None), KnowledgeUnit.scenario_id == scenario_id))
""",
        """    if scenario_id:
        query = query.where(or_(KnowledgeUnit.scenario_id.is_(None), KnowledgeUnit.scenario_id == scenario_id))
    # 字段级证据：选了 18 个字段就只送这 18 个字段的制度片段。之前的实现把选定资料里的
    # 全部单元都送进模型，语料一补齐就撑爆 128KB 输入预算（真实报错：请求 410135 字节）。
    # 没有字段代码的单元是通用条款，仍然保留；过滤结果写进 projection 审计可查。
    if field_codes:
        codes = sorted({str(code) for code in field_codes if code})
        query = query.where(
            or_(
                KnowledgeUnit.target_field_code.is_(None),
                KnowledgeUnit.target_field_code == "",
                KnowledgeUnit.target_field_code.in_(codes),
            )
        )
""",
    ),
    (
        "def requirement_evidence(db, project_id, document_ids, scenario_id=None, limit=501):",
        "def requirement_evidence(db, project_id, document_ids, scenario_id=None, limit=501, field_codes=None):",
    ),
    (
        """        for unit, document, version in selected_requirement_units(db, project_id, document_ids, scenario_id, limit)]""",
        """        for unit, document, version in selected_requirement_units(
            db, project_id, document_ids, scenario_id, limit, field_codes=field_codes)]""",
    ),
    (
        """    rows = selected_requirement_units(db, project_id, snapshot["allowed"]["document_ids"],
        snapshot.get("requirement", {}).get("scenario_id"))""",
        """    rows = selected_requirement_units(db, project_id, snapshot["allowed"]["document_ids"],
        snapshot.get("requirement", {}).get("scenario_id"), field_codes=snapshot.get("field_codes"))""",
    ),
])

patch("app/services/requirement_script_basis.py", [
    (
        """    from app.services.knowledge_eligibility import requirement_evidence
    evidence = requirement_evidence(db, requirement.project_id, requirement.scope_json.get("document_ids", []),
        requirement.scope_json.get("scenario_id"))""",
        """    from app.services.knowledge_eligibility import requirement_evidence
    from app.models import TargetField
    bound_codes = sorted({str(code) for code in db.scalars(select(TargetField.field_code).where(
        TargetField.project_id == requirement.project_id, TargetField.id.in_(field_ids))) if code})
    evidence = requirement_evidence(db, requirement.project_id, requirement.scope_json.get("document_ids", []),
        requirement.scope_json.get("scenario_id"), field_codes=bound_codes)""",
    ),
    (
        """    basis["policy_snapshot"] = {"allowed": {"document_ids": sorted(set(requirement.scope_json.get("document_ids", [])))},
        "requirement": {"scenario_id": requirement.scope_json.get("scenario_id")}, "evidence": evidence}""",
        """    basis["policy_snapshot"] = {"allowed": {"document_ids": sorted(set(requirement.scope_json.get("document_ids", [])))},
        "requirement": {"scenario_id": requirement.scope_json.get("scenario_id")},
        "field_codes": bound_codes, "evidence": evidence}""",
    ),
])

patch("app/services/mapping/requirement_input.py", [
    (
        """        evidence = requirement_evidence(db, project_id, allowed["document_ids"], scope.get("scenario_id"), MAX_ROWS + 1)""",
        """        bound_codes = sorted({str(record["field"].get("field_code") or "") for record in records} - {""})
        evidence = requirement_evidence(db, project_id, allowed["document_ids"], scope.get("scenario_id"),
            MAX_ROWS + 1, field_codes=bound_codes)""",
    ),
    (
        """    pool: dict[str, str] = {}
    rules = []
    truncated = 0
    for rule in basis.get("rules") or []:
        source = rule.get("source") or {}
        target = rule.get("target") or {}""",
        """    pool: dict[str, str] = {}
    rules = []
    truncated = 0
    omitted_rules = 0
    for rule in basis.get("rules") or []:
        source = rule.get("source") or {}
        target = rule.get("target") or {}
        target_column = str(target.get("column_name") or "")
        if bound_codes and target_column and target_column not in bound_codes:
            # 目标列不在本次确认的字段范围内：这条规则不影响本次生成，送进去只会挤占预算。
            omitted_rules += 1
            continue""",
    ),
    (
        """        "bound_columns": sorted(bound_codes),
        "rule_count": len(rules),""",
        """        "bound_columns": sorted(bound_codes),
        "omitted_unbound_rule_count": omitted_rules,
        "rule_count": len(rules),""",
    ),
])

print("done")
