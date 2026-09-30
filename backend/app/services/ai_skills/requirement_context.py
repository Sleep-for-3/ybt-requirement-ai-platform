"""Fixed requirement projection shared by Skill execution and replay validation.

This pure adapter does not authorize input. Its caller must recheck the persisted
input hash, actor permissions and frozen knowledge eligibility before execution.
"""
from copy import deepcopy

from app.schemas.ai_skill import EvidenceSource, SkillEvidence, SkillGap, SkillInputEnvelope, SkillScope
from app.services.llm.execution_metadata import stable_hash
from app.services.requirement_candidate_contract import project_candidate_context, check_candidate_compliance
from app.services.requirement_policy_comparison import NORMATIVE_CATEGORIES


def build_requirement_envelope(project, row, item, *, max_input_bytes=64000):
    context = project_candidate_context(row.input_json, item.field_id, item.section)
    if (row.project_id != project.id or context.get("project_id") != project.id
            or item.input_id != row.id):
        raise ValueError("requirement input scope mismatch")
    scope = SkillScope(scope_type="task", institution_id=project.institution_id,
        project_id=project.id, invocation_key="requirement_fields")
    units = context.pop("evidence", [])
    facts = [SkillEvidence(id=f"requirement-input:{row.id}", kind="requirement_context", value=context,
        source=EvidenceSource(source_type="requirement_input", source_id=str(row.id),
            source_version=row.input_hash, locator=f"field:{item.field_id}:{item.section}", scope=scope),
        confidentiality=project.confidentiality_level or "internal")]
    policy = []
    gaps = []
    for unit in units:
        normative = unit.get("source_category") in NORMATIVE_CATEGORIES
        evidence = SkillEvidence(id=f"knowledge-unit:{unit['unit_id']}",
            kind="policy_clause" if normative else "knowledge_evidence", value=unit,
            source=EvidenceSource(source_type="knowledge_clause" if normative else "knowledge_unit",
                source_id=str(unit["unit_id"]), source_version=f"{unit['document_version_id']}:{unit['content_hash']}",
                locator=stable_hash(unit.get("locator") or {"unit_id": unit["unit_id"]}), scope=scope),
            confidentiality=unit["confidentiality_level"])
        (policy if normative else facts).append(evidence)
    if not policy:
        gaps.append(SkillGap(code="missing_basis", message="缺少固定的有效制度依据，技术材料不能替代制度条款"))
    return SkillInputEnvelope(skill_key="requirement_candidate_generation", task_key="requirement_candidate_generation",
        scope=scope, subject_ref=f"requirement-input:{row.id}:field:{item.field_id}:{item.section}",
        facts=facts, policy_evidence=policy, gaps=gaps, max_input_bytes=max_input_bytes)


def validate_requirement_output(candidate, envelope):
    snapshots = [fact for fact in envelope.facts if fact.kind == "requirement_context"]
    if len(snapshots) != 1 or not isinstance(snapshots[0].value, dict):
        raise ValueError("one fixed requirement context is required")
    context = deepcopy(snapshots[0].value)
    if context.get("project_id") != envelope.scope.project_id:
        raise ValueError("requirement context project mismatch")
    fields = context.get("fields", [])
    if len(fields) != 1:
        raise ValueError("one requirement target is required")
    project_candidate_context(context, fields[0]["target"]["id"], context.get("section"))
    # Rebuild only from their separate, typed evidence layers, never trust a
    # nested evidence list supplied inside the requirement snapshot.
    context["evidence"] = []
    for evidence in [*envelope.facts, *envelope.policy_evidence]:
        if evidence.kind not in {"knowledge_evidence", "policy_clause"}:
            continue
        unit = deepcopy(evidence.value)
        if not isinstance(unit, dict) or type(unit.get("unit_id")) is not int:
            raise ValueError("invalid requirement evidence identity")
        normative = unit.get("source_category") in NORMATIVE_CATEGORIES
        if normative != (evidence.kind == "policy_clause"):
            raise ValueError("requirement policy evidence classification mismatch")
        context["evidence"].append(unit)
    violations = check_candidate_compliance(context, candidate.model_dump())
    if violations:
        raise ValueError(violations[0])
