"""Shared requirement candidate schema and frozen-input reference checks.

Pure validation only: callers authorize/build the context, then keep their
existing lease, concurrency and explicit human-adoption checks.
"""
from copy import deepcopy
from typing import Annotated, Literal

import re

from pydantic import BaseModel, ConfigDict, Field


_CHINESE_TEXT = re.compile(r"[\u4e00-\u9fff]")

ReferenceId = Annotated[int, Field(strict=True, gt=0)]

# 主张/支持记录的语义版本。校验器（requirement_claim_support）按该版本演进，
# 候选自行声明的版本与校验器不一致时不会被认证为“已支持”。
CLAIM_SUPPORT_VERSION = "claim-support-v1"

ClaimAssertionKind = Literal[
    "filter", "aggregation", "join_key", "as_of_date", "null_handling", "code_mapping",
    "runtime_fact", "other",
]
ClaimSupportSource = Literal["script_rule", "evidence", "physical_field", "runtime_fact"]
ClaimSupportStatus = Literal["supported", "conflict", "unknown"]


class ClaimSupport(BaseModel):
    """主张与某条固定事实（脚本规则/证据/物理字段）的关系记录。"""

    model_config = ConfigDict(extra="forbid")
    source: ClaimSupportSource
    ref_id: str = Field(min_length=1, max_length=200)
    status: ClaimSupportStatus = "unknown"
    method: str = Field(default="", max_length=200)
    method_version: str = Field(default="", max_length=100)
    detail: str = Field(default="", max_length=2000)
    # 主张声明的证据版本；为空表示未声明版本。
    ref_version: str = Field(default="", max_length=100)


class CandidateClaim(BaseModel):
    """候选正文中的一条可核验主张（供生成期校验与事后审计）。"""

    model_config = ConfigDict(extra="forbid")
    claim_id: str = Field(min_length=1, max_length=100)
    section: Literal["business", "lineage"]
    text: str = Field(min_length=1, max_length=5000)
    assertion_kind: ClaimAssertionKind
    support: list[ClaimSupport] = Field(default_factory=list, max_length=50)


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
    # 可选：旧候选没有 claims，仍必须通过本 schema（审计上记为“未执行主张校验”）。
    claims: list[CandidateClaim] = Field(default_factory=list, max_length=100)
    claim_support_version: str = Field(default=CLAIM_SUPPORT_VERSION, max_length=100)


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
    # 需求字段已固定的监管集市映射属于该字段自己的溯源证据（mapping_sources），
    # 不是"用户选定的资料范围"，但引用它对得上冻结内容，故允许；未映射的集市字段仍不可引用。
    allowed_physical.update(
        (item["kind"], item["table_id"], item["field_id"]) for item in context.get("mapping_sources", [])
    )
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

    final_content = (candidate.get("final_content") or "").strip()
    if not final_content:
        violations.append("候选未给出可交付的需求正文")
    elif not _CHINESE_TEXT.search(final_content):
        # 银行需求正文必须是中文业务描述。模型在格式修复路径上可能返回
        # schema 合法但语义空洞的占位文本，这类候选不能进入人工采用环节。
        violations.append("需求正文必须使用中文业务描述，当前候选未包含中文正文")

    from app.services.requirement_policy_comparison import NORMATIVE_CATEGORIES
    normative_ids = {u["unit_id"] for u in context.get("evidence", []) if u.get("source_category") in NORMATIVE_CATEGORIES}
    for comparison in candidate.get("policy_comparisons", []):
        if comparison["unit_id"] not in normative_ids or not set(comparison.get("rule_ids", [])) <= rule_ids:
            violations.append("AI 对照引用了范围外规则或非制度资料")
            break
        if comparison.get("status") == "conflict" and not (comparison.get("difference") or "").strip():
            violations.append("AI 冲突对照缺少差异说明")
            break

    # 语义支持校验：引用合法不等于正文被固定事实支持。无 claims 的历史候选
    # 返回 not_evaluated 且不产生新违规，保证向后兼容、不追改历史内容。
    # 只有"确定性冲突"（正文与固定事实矛盾）算生成期阻断；"无法判定"不阻断生成，
    # 由 seal_candidate 写成缺口，交给送审前的人工确认——否则模型如实说"无证据"
    # 反而被整条阻断，等于逼它虚构证据。
    from app.services.requirement_claim_support import evaluate_claim_support

    violations.extend(evaluate_claim_support(context, candidate).blocking_violations)
    return violations


