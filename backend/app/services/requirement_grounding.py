"""字段级"有据可查率"与导出软门禁。

口径与 ``scripts/requirement_grounding_report.py`` 一致，但下沉到服务层：让
"冻结并导出"和"统一导出"在返回文件之前就能算出这份文档有多少字段的正文被
**本次生成输入里实际引用的证据**支撑，并把结论作为**软门禁**标记出来。

软门禁（``gate=mark``）只标记、不阻断：

* 结论写进响应头 ``X-Requirement-Quality-Gate``（pass/mark/unknown）与
  ``X-Requirement-Grounding-Coverage``；
* 原因条数写进 ``X-Requirement-Grounding-Reason-Count``，完整原因进审计
  ``after.quality_gate``；
* 统计本身失败时给 ``verdict="unknown"`` 并写明原因，绝不因为"算不出来"挡住导出。

口径（写进 ``denominator.definition``，避免事后争论）：只统计
``decision == "adopted"`` 且 ``status == "completed"`` 的候选（同一字段/分区取
最新一条），每条候选的主张用**当前代码**重放 ``evaluate_claim_support``（含证据
接地）；分母同时给出 ``all_fields``（全部目标字段）与 ``fields_with_candidate``。
"""

from __future__ import annotations

from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.settings import get_settings
from app.models import Requirement, RequirementGenerationInput, RequirementGenerationItem
from app.services.requirement_claim_support import evaluate_claim_support
from app.services.requirement_scope import document_content

GATE_MODE = "mark"
DEFAULT_THRESHOLD = 0.7

DENOMINATOR_DEFINITION = (
    "分母=目标字段数（all_fields）或有采纳候选的字段数（fields_with_candidate）；"
    "主张只统计 adopted+completed 候选，且用当前代码重放 evidence grounding"
)


def latest_adopted_items(db: Session, requirement_id: int) -> dict[tuple[int, str], RequirementGenerationItem]:
    """同一 (field_id, section) 只留最新一条 adopted+completed 候选。"""

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


def input_payload(db: Session, input_id: int) -> dict:
    """重放用的完整生成上下文（与 worker 调用 ``evaluate_claim_support`` 时一致）。"""

    generation_input = db.get(RequirementGenerationInput, input_id)
    if generation_input is None:
        return {}
    return dict(generation_input.input_json or {})


def grounding_summary(db: Session, requirement: Requirement, content: dict | None = None) -> dict:
    """统计字段级有据可查率；返回结构可直接落盘做报告。"""

    content = content if content is not None else document_content(db, requirement)
    fields = content.get("fields") or []
    latest = latest_adopted_items(db, requirement.id)

    per_field: list[dict] = []
    claim_counts: Counter = Counter()
    knowledge_evidence_fields = 0
    for record in fields:
        field = record.get("field") or {}
        field_id = int(field.get("id") or 0)
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
            context = input_payload(db, item.input_id) or {
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
            "field_code": field.get("field_code"),
            "field_name": field.get("field_name"),
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
    return {
        "requirement": {
            "id": requirement.id,
            "content_version": requirement.content_version,
            "version": requirement.version,
            "target_table_code": (content.get("requirement") or {}).get("target_table_code"),
            "target_table_id": (content.get("target_table") or {}).get("id"),
        },
        "denominator": {
            "definition": DENOMINATOR_DEFINITION,
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


def quality_gate(summary: dict | None, *, threshold: float | None = None) -> dict:
    """把统计结果翻译成软门禁结论；没有阈值通过就标 mark，不抛错。"""

    settings = get_settings()
    effective_threshold = threshold
    if effective_threshold is None:
        effective_threshold = float(getattr(settings, "grounding_gate_threshold", DEFAULT_THRESHOLD))
    enabled = bool(getattr(settings, "grounding_gate_enabled", True))
    if summary is None:
        return {
            "mode": GATE_MODE,
            "enabled": enabled,
            "threshold": effective_threshold,
            "verdict": "unknown",
            "coverage_all_fields": None,
            "reasons": ["未能读取字段口径，无法统计有据可查率"],
            "ai_draft_fields": [],
            "fields_without_candidate": [],
            "fields_without_support": [],
        }
    per_field = summary.get("per_field") or []
    coverage_all = float((summary.get("coverage") or {}).get("all_fields") or 0.0)
    ai_draft_fields = [item.get("field_code") for item in per_field if item.get("ai_draft_only")]
    no_candidate_fields = [
        item.get("field_code") for item in per_field
        if not any(part.get("has_candidate") for part in (item.get("sections") or {}).values())
    ]
    without_support = [item.get("field_code") for item in per_field if not item.get("supported")]
    reasons: list[str] = []
    if coverage_all < effective_threshold:
        reasons.append(
            f"字段级有据可查率 {coverage_all:.0%} 低于阈值 {effective_threshold:.0%}："
            f"{len(without_support)} 个字段还没有被证据支撑的主张"
        )
    if ai_draft_fields:
        reasons.append(
            f"{len(ai_draft_fields)} 个字段的正文只有 AI 草稿（导出时带“（AI 生成草稿，待业务确认）”前缀）："
            f"{'、'.join(str(code) for code in ai_draft_fields)}"
        )
    if no_candidate_fields:
        reasons.append(
            f"{len(no_candidate_fields)} 个字段还没有采纳候选：{'、'.join(str(code) for code in no_candidate_fields)}"
        )
    return {
        "mode": GATE_MODE,
        "enabled": enabled,
        "threshold": effective_threshold,
        "verdict": "pass" if not reasons else "mark",
        "coverage_all_fields": coverage_all,
        "reasons": reasons,
        "ai_draft_fields": ai_draft_fields,
        "fields_without_candidate": no_candidate_fields,
        "fields_without_support": without_support,
    }


def gate_headers(gate: dict | None) -> dict[str, str]:
    """响应头只放短结论；完整原因进审计，避免头部过长。"""

    if not gate:
        return {}
    coverage = gate.get("coverage_all_fields")
    return {
        "X-Requirement-Quality-Gate": str(gate.get("verdict") or "unknown"),
        "X-Requirement-Grounding-Coverage": f"{float(coverage):.4f}" if coverage is not None else "unknown",
        "X-Requirement-Grounding-Reason-Count": str(len(gate.get("reasons") or [])),
    }
