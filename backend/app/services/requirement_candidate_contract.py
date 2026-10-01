"""Shared requirement candidate schema and frozen-input reference checks.

Pure validation only: callers authorize/build the context, then keep their
existing lease, concurrency and explicit human-adoption checks.
"""
from copy import deepcopy
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


ReferenceId = Annotated[int, Field(strict=True, gt=0)]


class PhysicalReference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["source", "mart"]
    table_id: ReferenceId
    field_id: ReferenceId


class PolicyComparisonCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    unit_id: ReferenceId
    rule_ids: list[str] = Field(min_length=1, max_length=100)
    status: Literal["matched", "conflict", "pending"]
    explanation: str = Field(min_length=1, max_length=5000)
    difference: str = Field(default="", max_length=5000)


class RequirementCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    business_definition: str = Field(default="", max_length=20000)
    processing_logic: str = Field(default="", max_length=20000)
    final_content: str = Field(max_length=20000)
    physical_references: list[PhysicalReference] = Field(default_factory=list, max_length=100)
    evidence_unit_ids: list[ReferenceId] = Field(default_factory=list, max_length=100)
    script_rule_ids: list[str] = Field(default_factory=list, max_length=100)
    policy_comparisons: list[PolicyComparisonCandidate] = Field(default_factory=list, max_length=100)
    gaps: list[str] = Field(default_factory=list, max_length=100)


def project_candidate_context(frozen: dict, field_id: int, section: str) -> dict:
    """Select exactly one authorized item without altering the frozen input.

    The caller still validates the persisted input hash and current permissions.
    A corrupt/stale queue item must not silently become a context with no target.
    """
    if section not in {"business", "lineage"} or section not in frozen.get("sections", []):
        raise ValueError("candidate section is outside frozen input")
    if type(field_id) is not int or field_id not in frozen.get("field_ids", []):
        raise ValueError("candidate field is outside frozen input")
    fields = [field for field in frozen.get("fields", []) if field.get("target", {}).get("id") == field_id]
    if len(fields) != 1:
        raise ValueError("candidate field must have exactly one frozen target")
    context = deepcopy(frozen)
    context["fields"] = deepcopy(fields)
    context["section"] = section
    return context


def check_candidate_compliance(context: dict, candidate: dict) -> list[str]:
    """Validate candidate against context boundaries and return actionable violation messages."""
    violations = []
    allowed_physical = {(item["kind"], item["table_id"], item["field_id"]) for item in context.get("physical_sources", [])}
    for ref in candidate.get("physical_references", []):
        ref_tuple = (ref.get("kind"), ref.get("table_id"), ref.get("field_id"))
        if ref_tuple not in allowed_physical:
            violations.append("生成结果引用了范围外的物理字段")
            break

    evidence_ids = {unit["unit_id"] for unit in context.get("evidence", [])}
    if not set(candidate.get("evidence_unit_ids", [])) <= evidence_ids:
        violations.append("候选引用了范围外证据")

    rule_ids = {rule["rule_id"] for rule in context.get("script_basis", {}).get("rules", [])}
    if not set(candidate.get("script_rule_ids", [])) <= rule_ids:
        violations.append("候选引用了范围外脚本规则")

    from app.services.requirement_policy_comparison import NORMATIVE_CATEGORIES
    normative_ids = {u["unit_id"] for u in context.get("evidence", []) if u.get("source_category") in NORMATIVE_CATEGORIES}
    for comparison in candidate.get("policy_comparisons", []):
        if comparison["unit_id"] not in normative_ids or not set(comparison.get("rule_ids", [])) <= rule_ids:
            violations.append("AI 对照引用了范围外规则或非制度资料")
            break
        if comparison.get("status") == "conflict" and not (comparison.get("difference") or "").strip():
            violations.append("AI 冲突对照缺少差异说明")
            break
    return violations


