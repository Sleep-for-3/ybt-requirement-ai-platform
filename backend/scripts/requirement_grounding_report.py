"""字段级"有据可查率"报告（只读）。

回答一个比"非空率"更硬的问题：需求正文里的字段口径，有多少条主张能被
**本次生成输入里实际引用的证据**支撑？

口径（写进输出的 ``denominator``，避免事后争论）：

* 只统计 ``decision == "adopted"`` 且 ``status == "completed"`` 的候选（同一字段/分区取最新一条）；
* 每条候选的主张用**当前代码**重放 ``evaluate_claim_support``（含 M3 的证据接地）；
* ``supported / unknown / conflict`` 按主张计数；
* 分母同时给出两种：``all_fields``（全部目标字段）与 ``fields_with_candidate``（有采纳候选的字段）。

除了主张级统计，还会统计需求内容里 ``evidence_type == "knowledge_unit"`` 的字段数，
把"有映射证据"和"有知识证据"区分开（前者只证明脚本变更集，不证明监管口径）。

用法::

    python scripts/requirement_grounding_report.py --requirement-id 30

输出：``backend/scripts/out/retrieval/grounding_req<id>.json`` 与同名 ``.md``。
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models import Requirement, RequirementGenerationInput, RequirementGenerationItem
from app.services.requirement_claim_support import evaluate_claim_support
from app.services.requirement_scope import document_content

HERE = Path(__file__).resolve().parent
OUT = HERE / "out" / "retrieval"


def _latest_adopted_items(db, requirement_id: int) -> dict[tuple[int, str], RequirementGenerationItem]:
    rows = db.scalars(
        select(RequirementGenerationItem)
        .join(RequirementGenerationInput, RequirementGenerationInput.id == RequirementGenerationItem.input_id)
        .where(
            RequirementGenerationInput.requirement_id == requirement_id,
            RequirementGenerationItem.status == "completed",
            RequirementGenerationItem.decision == "adopted",
            RequirementGenerationItem.candidate_json.is_not(None),
        )
        .order_by(RequirementGenerationItem.id)
    ).all()
    latest: dict[tuple[int, str], RequirementGenerationItem] = {}
    for row in rows:
        latest[(row.field_id, row.section)] = row
    return latest


def _input_payload(db, input_id: int) -> dict:
    """重放用的完整生成上下文（与 worker 调用 `evaluate_claim_support` 时一致）。"""
    generation_input = db.get(RequirementGenerationInput, input_id)
    if generation_input is None:
        return {}
    return dict(generation_input.input_json or {})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requirement-id", type=int, default=30)
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    db = SessionLocal()
    requirement = db.get(Requirement, args.requirement_id)
    if requirement is None:
        raise SystemExit(f"requirement {args.requirement_id} not found")
    content = document_content(db, requirement)
    fields = content.get("fields") or []
    latest = _latest_adopted_items(db, requirement.id)

    per_field: list[dict] = []
    claim_counts: Counter = Counter()
    knowledge_evidence_fields = 0
    for record in fields:
        field = record.get("field") or {}
        field_id = int(field.get("id") or 0)
        code = field.get("field_code")
        name = field.get("field_name")
        evidence = record.get("evidence") or []
        knowledge_refs = [item for item in evidence if str(item.get("evidence_type") or "") == "knowledge_unit"]
        business = record.get("business") or {}
        manual_text = str(business.get("final_content") or business.get("business_definition") or "").strip()
        ai_text = str(business.get("ai_generated_content") or "").strip()
        ai_draft_only = bool(ai_text) and not manual_text
        if knowledge_refs:
            knowledge_evidence_fields += 1
        sections: dict[str, dict] = {}
        for section in ("business", "lineage"):
            item = latest.get((field_id, section))
            if item is None:
                sections[section] = {"has_candidate": False}
                continue
            candidate = item.candidate_json or {}
            claims = candidate.get("claims") or []
            if not claims:
                sections[section] = {"has_candidate": True, "claims": 0, "item_id": item.id}
                continue
            context = _input_payload(db, item.input_id) or {
                "evidence": [],
                "script_basis": {"rules": [], "condition_texts": {}, "metadata": []},
            }
            context["section"] = section
            report = evaluate_claim_support(context, {"claims": claims})
            statuses = Counter(evaluation.status for evaluation in report.evaluations)
            claim_counts.update(statuses)
            sections[section] = {
                "has_candidate": True,
                "item_id": item.id,
                "candidate_hash": item.candidate_hash,
                "adopted_content_version": item.adopted_content_version,
                "claims": report.claim_count,
                "supported": statuses.get("supported", 0),
                "unknown": statuses.get("unknown", 0),
                "conflict": statuses.get("conflict", 0),
                "codes": sorted({code for evaluation in report.evaluations for code in evaluation.codes}),
            }
        supported = sum(int(part.get("supported") or 0) for part in sections.values())
        total = sum(int(part.get("claims") or 0) for part in sections.values())
        per_field.append({
            "field_id": field_id,
            "field_code": code,
            "field_name": name,
            "knowledge_evidence_refs": len(knowledge_refs),
            "ai_draft_only": ai_draft_only,
            "sections": sections,
            "claims": total,
            "supported": supported,
            "supported_ratio": round(supported / total, 4) if total else None,
        })

    total_claims = sum(item["claims"] for item in per_field)
    total_supported = sum(item["supported"] for item in per_field)
    covered = [item for item in per_field if item["claims"]]
    grounded_fields = [item for item in per_field if item["supported"]]
    report = {
        "requirement": {"id": requirement.id, "content_version": requirement.content_version,
                        "version": requirement.version,
                        "target_table_code": (content.get("requirement") or {}).get("target_table_code"),
                        "target_table_id": (content.get("target_table") or {}).get("id")},
        "denominator": {
            "definition": (
                "分母=目标字段数（all_fields）或有采纳候选的字段数（fields_with_candidate）；"
                "主张只统计 adopted+completed 候选，且用当前代码重放 evidence grounding"
            ),
            "all_fields": len(per_field),
            "fields_with_candidate": len(covered),
            "fields_with_supported_claim": len(grounded_fields),
            "fields_with_knowledge_evidence": knowledge_evidence_fields,
        },
        "claims": {
            "total": total_claims,
            "supported": total_supported,
            "unknown": claim_counts.get("unknown", 0),
            "conflict": claim_counts.get("conflict", 0),
            "supported_ratio": round(total_supported / total_claims, 4) if total_claims else None,
        },
        "coverage": {
            "all_fields": round(len(grounded_fields) / len(per_field), 4) if per_field else None,
            "fields_with_candidate": round(len(grounded_fields) / len(covered), 4) if covered else None,
        },
        "per_field": per_field,
    }
    gate_threshold = 0.7
    coverage_all = report["coverage"]["all_fields"] or 0.0
    ai_draft_fields = [item["field_code"] for item in per_field if item.get("ai_draft_only")]
    no_candidate_fields = [item["field_code"] for item in per_field if not any(part.get("has_candidate") for part in item["sections"].values())]
    reasons: list[str] = []
    if coverage_all < gate_threshold:
        reasons.append(
            f"字段级有据可查率 {coverage_all:.0%} 低于阈值 {gate_threshold:.0%}：{len(per_field) - len(grounded_fields)} 个字段还没有被证据支撑的主张"
        )
    if ai_draft_fields:
        reasons.append(f"{len(ai_draft_fields)} 个字段的正文只有 AI 草稿（导出时带“（AI 生成草稿，待业务确认）”前缀）：{'、'.join(ai_draft_fields)}")
    if no_candidate_fields:
        reasons.append(f"{len(no_candidate_fields)} 个字段还没有采纳候选：{'、'.join(no_candidate_fields)}")
    report["quality_gate"] = {
        "threshold": gate_threshold,
        "verdict": "pass" if not reasons else "mark",
        "coverage_all_fields": coverage_all,
        "ai_draft_fields": ai_draft_fields,
        "fields_without_candidate": no_candidate_fields,
        "reasons": reasons,
    }

    output = Path(args.output) if args.output else OUT / f"grounding_req{requirement.id}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        f"# 字段级有据可查率（requirement {requirement.id} / content v{requirement.content_version}）",
        "",
        f"- 分母：全部字段 {len(per_field)}；有采纳候选 {len(covered)}；有知识证据 {knowledge_evidence_fields}",
        f"- 主张：{total_claims} 条 → supported {total_supported} / unknown {claim_counts.get('unknown', 0)} / conflict {claim_counts.get('conflict', 0)}",
        f"- 字段级覆盖：全部字段 {report['coverage']['all_fields']}；有候选字段 {report['coverage']['fields_with_candidate']}",
        f"- 导出质量门：{report['quality_gate']['verdict']}（阈值 {gate_threshold:.0%}）",
        *[f"  - {reason}" for reason in reasons],
        "",
        "| 字段 | 名称 | 主张 | supported | 知识证据 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for item in per_field:
        lines.append(
            f"| {item['field_code']} | {item['field_name']} | {item['claims']} | {item['supported']} | {item['knowledge_evidence_refs']} |"
        )
    output.with_suffix(".md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({
        "denominator": report["denominator"],
        "claims": report["claims"],
        "coverage": report["coverage"],
        "quality_gate": report["quality_gate"],
        "output": str(output),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
