"""Human policy comparisons belong to immutable requirement content revisions."""
from copy import deepcopy
from datetime import datetime, timezone
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.services.requirement_revisions import append_revision, load_revision
from app.services.requirement_scope import content_digest

NORMATIVE_CATEGORIES = {"regulatory_formal", "regulatory_qa", "internal_policy"}
LEGACY_PENDING = "制度条款与脚本规则的逐条对照尚未人工确认"


class PolicyDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    unit_id: int = Field(gt=0)
    rule_ids: list[str] = Field(default_factory=list, max_length=2000)
    status: Literal["matched", "conflict", "missing_implementation", "pending"]
    rationale: str = Field(min_length=1, max_length=10000)
    difference: str = Field(default="", max_length=10000)


class ConfirmPolicyComparison(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_content_version: int = Field(gt=0)
    basis_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    decisions: list[PolicyDecision] = Field(min_length=1, max_length=500)


def basis_hash(basis):
    # Exclude derived gap labels; a comparison does not change the underlying facts.
    return content_digest({key: basis.get(key) for key in (
        "versions", "statements", "rules", "metadata", "template", "confirmation", "policy_snapshot")})


def normative_units(basis):
    return [u for u in basis.get("policy_snapshot", {}).get("evidence", [])
        if u.get("source_category") in NORMATIVE_CATEGORIES]


def comparison_issues(content):
    basis = content.get("script_basis")
    if not basis:
        return []
    units = normative_units(basis)
    rules = {r["rule_id"] for r in basis.get("rules", [])}
    saved = content.get("policy_comparisons", {})
    current = saved.get("basis_hash") == basis_hash(basis)
    decisions = saved.get("decisions", {}) if current else {}
    issues = []
    covered = set()
    def issue(code, message):
        issues.append({"code": f"scope:policy:{code}", "field_id": None, "message": message})
    if not units:
        issue("missing_basis", "缺少有效制度依据：技术材料和业务背景不能替代制度条款")
    for unit in units:
        row = decisions.get(str(unit["unit_id"]))
        if not row:
            issue(f"unit:{unit['unit_id']}", f"制度条款 {unit['unit_id']} 尚未人工对照")
            continue
        links = set(row.get("rule_ids", []))
        if (row.get("status") != "matched" or not links or not links <= rules
                or not str(row.get("rationale", "")).strip() or not row.get("confirmed_by")):
            labels = {"conflict": "与脚本存在差异", "missing_implementation": "缺少脚本实现", "pending": "仍待确认"}
            issue(f"unit:{unit['unit_id']}", f"制度条款 {unit['unit_id']} {labels.get(row.get('status'), '确认依据不完整')}")
        if links <= rules:
            covered.update(links)
    for rule_id in sorted(rules - covered):
        issue(f"rule:{rule_id}", f"脚本规则 {rule_id} 缺少已关联的制度依据")
    return issues


def comparison_view(content):
    basis = content.get("script_basis")
    if not basis:
        raise HTTPException(409, "请先固定脚本及制度依据")
    saved = content.get("policy_comparisons", {})
    digest = basis_hash(basis)
    return {"basis_hash": digest, "rules": deepcopy(basis["rules"]), "units": deepcopy(normative_units(basis)),
        "excluded_unit_count": len(basis["policy_snapshot"]["evidence"]) - len(normative_units(basis)),
        "decisions": deepcopy(saved.get("decisions", {})) if saved.get("basis_hash") == digest else {},
        "issues": comparison_issues(content)}


def sync_comparison_gaps(content):
    """Replace only derived comparison gaps, retaining parser and Mapping gaps."""
    content["gaps"] = [g for g in content.get("gaps", [])
        if not str(g.get("id", "")).startswith("scope:policy:")
        and not (str(g.get("id", "")).startswith("scope:script:") and g.get("message") == LEGACY_PENDING)]
    for issue in comparison_issues(content):
        content["gaps"].append({"id": issue["code"], "field_id": None, "origin": "analysis",
            "status": "open", "message": issue["message"]})
    content["assessment"] = "gaps" if content["gaps"] else "clear"


def confirm_comparison(db, requirement, payload, actor_id):
    previous = load_revision(db, requirement.project_id, requirement.id, payload.expected_content_version)
    if requirement.content_version != previous.content_version or previous.status != "draft":
        raise HTTPException(409, "只能在当前草稿版本确认制度对照")
    content = deepcopy(previous.content_json)
    view = comparison_view(content)
    if view["basis_hash"] != payload.basis_hash:
        raise HTTPException(409, "固定依据已变化，请重新加载制度对照")
    from app.services.knowledge_eligibility import validate_frozen_requirement_evidence
    validate_frozen_requirement_evidence(db, requirement.project_id, content["script_basis"]["policy_snapshot"])
    allowed_units = {u["unit_id"] for u in view["units"]}
    allowed_rules = {r["rule_id"] for r in view["rules"]}
    if len({d.unit_id for d in payload.decisions}) != len(payload.decisions):
        raise HTTPException(422, "同一条款不能重复提交")
    decisions = view["decisions"]
    for item in payload.decisions:
        if item.unit_id not in allowed_units or not set(item.rule_ids) <= allowed_rules:
            raise HTTPException(422, "条款或规则不在固定依据范围内，或资料不是制度依据")
        if not item.rationale.strip():
            raise HTTPException(422, "请填写人工核验理由")
        if item.status in {"matched", "conflict"} and not item.rule_ids:
            raise HTTPException(422, "匹配或冲突结论必须关联实现规则")
        if item.status in {"conflict", "missing_implementation"} and not item.difference.strip():
            raise HTTPException(422, "请说明实现差异或缺失内容")
        if item.status == "missing_implementation" and item.rule_ids:
            raise HTTPException(422, "缺少实现不能同时关联已有实现，请改为冲突或待确认")
        decisions[str(item.unit_id)] = {**item.model_dump(), "rule_ids": sorted(set(item.rule_ids)),
            "rationale": item.rationale.strip(), "difference": item.difference.strip(),
            "confirmed_by": actor_id, "confirmed_at": datetime.now(timezone.utc).isoformat(),
            "content_version": previous.content_version + 1}
    content["policy_comparisons"] = {"basis_hash": view["basis_hash"], "decisions": decisions}
    sync_comparison_gaps(content)
    return append_revision(db, requirement, content, previous.content_version, actor_id)


def ai_suggestions(db, project_id, requirement_id, content):
    """Read candidates independently; never overwrite a human decision."""
    from sqlalchemy import select
    from app.models import RequirementGenerationInput, RequirementGenerationItem
    expected = basis_hash(content["script_basis"])
    rows = db.execute(select(RequirementGenerationItem, RequirementGenerationInput).join(
        RequirementGenerationInput, RequirementGenerationInput.id == RequirementGenerationItem.input_id).where(
        RequirementGenerationInput.project_id == project_id,
        RequirementGenerationInput.requirement_id == requirement_id,
        RequirementGenerationItem.status == "completed").order_by(RequirementGenerationItem.id.desc()).limit(200))
    result = []
    for item, source in rows:
        frozen = source.input_json
        if frozen.get("content_version", 0) > content["requirement"].get("content_version", 0):
            continue
        basis = deepcopy(frozen.get("script_basis"))
        if item.decision == "rejected" or not basis or not item.candidate_json or not item.candidate_json.get("policy_comparisons"):
            continue
        if content_digest(frozen) != source.input_hash or content_digest(item.candidate_json) != item.candidate_hash:
            raise HTTPException(409, "制度对照候选完整性检查失败")
        basis["policy_snapshot"] = {"allowed": {"document_ids": frozen["allowed"]["document_ids"]},
            "requirement": {"scenario_id": frozen["requirement"].get("scenario_id")}, "evidence": frozen["evidence"]}
        if basis_hash(basis) != expected:
            continue
        result.append({"item_id": item.id, "test_provider": bool(item.candidate_json.get("runtime", {}).get("test_provider")),
            "comparisons": deepcopy(item.candidate_json["policy_comparisons"])})
    return result
