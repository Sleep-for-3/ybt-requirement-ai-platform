"""Governed Mapping projection and native output checks shared with evaluation."""
from pydantic import ConfigDict

from app.schemas.ai_skill import EvidenceSource, SkillEvidence, SkillGap, SkillInputEnvelope, SkillScope
from app.services.llm.execution_metadata import stable_hash
from app.services.llm.prompt_runtime import partition_allowlisted_citations
from app.services.llm.structured_outputs import (
    SourceToMartOutput, MartToYbtOutput, ScenarioBusinessOutput, ScenarioTechnicalOutput,
)


class SourceToMartCandidate(SourceToMartOutput):
    model_config = ConfigDict(extra="forbid")


class MartToYbtCandidate(MartToYbtOutput):
    model_config = ConfigDict(extra="forbid")


class ScenarioBusinessCandidate(ScenarioBusinessOutput):
    model_config = ConfigDict(extra="forbid")


class ScenarioTechnicalCandidate(ScenarioTechnicalOutput):
    model_config = ConfigDict(extra="forbid")


MAPPING_TASKS = {
    "source_to_mart_mapping": ("source_to_mart", SourceToMartCandidate),
    "mart_to_ybt_mapping": ("mart_to_ybt", MartToYbtCandidate),
    "scenario_business_mapping": ("scenario_business", ScenarioBusinessCandidate),
    "scenario_technical_lineage": ("scenario_technical", ScenarioTechnicalCandidate),
}
PHYSICAL_FIELDS = ("source_database_name", "source_schema_name", "source_table_english_name", "source_field_english_name")


def normalized_source(values):
    return tuple(" ".join(str(value or "").split()).casefold() for value in values)


def mapping_constraint(envelope):
    records = [item for item in envelope.facts if item.kind == "mapping_context"]
    if len(records) != 1 or not isinstance(records[0].value, dict):
        raise ValueError("one governed Mapping context is required")
    value = records[0].value
    snapshot, projection = value["snapshot"], value["projection"]
    expected = MAPPING_TASKS[envelope.task_key][0]
    if (snapshot["task_type"] != expected or projection["task_type"] != expected
            or snapshot["project"]["id"] != envelope.scope.project_id
            or snapshot["project"]["institution_id"] != envelope.scope.institution_id
            or snapshot["task"]["project_id"] != envelope.scope.project_id):
        raise ValueError("Mapping context scope or task mismatch")
    if not projection["readiness"]["can_generate"] or projection["truncated"] or not projection["context_budget"]["complete"]:
        raise ValueError("Mapping projection is incomplete or blocked")
    actual_refs = {item.id for item in envelope.facts if item.kind != "mapping_context"}
    if set(projection["selected_fact_refs"]) != actual_refs:
        raise ValueError("Mapping selected references do not match actual evidence")
    return value


def validate_mapping_output(candidate, envelope):
    value = mapping_constraint(envelope)
    allowed = {item.id for item in envelope.facts if item.kind != "mapping_context"}
    _, rejected = partition_allowlisted_citations(candidate.citations, allowed)
    if rejected:
        raise ValueError("Mapping output cites evidence outside the governed projection")
    if envelope.task_key == "scenario_technical_lineage":
        data = candidate.model_dump(exclude_none=True)
        if any(key in data for key in PHYSICAL_FIELDS):
            proposed = normalized_source(data.get(key) for key in PHYSICAL_FIELDS)
            whitelist = {normalized_source(item) for item in value["projection"]["physical_whitelist"]}
            current = normalized_source(value["snapshot"]["task"].get(key) for key in PHYSICAL_FIELDS)
            if not all(proposed) or (proposed not in whitelist and proposed != current):
                raise ValueError("Mapping output introduces an unproved physical source")


def build_mapping_envelope(envelope, task_key, *, max_input_bytes=64000):
    snapshot, projection, context = envelope.snapshot, envelope.projection, envelope.context
    scope = SkillScope(scope_type="task", institution_id=snapshot.project.institution_id,
        project_id=snapshot.project.id, invocation_key=MAPPING_TASKS[task_key][0])
    if context.scope.project_id != scope.project_id or context.scope.institution_id != scope.institution_id:
        raise ValueError("Mapping Context belongs to a different scope")
    rank = {"public": 0, "internal": 1, "confidential": 2, "restricted": 3}
    levels = [snapshot.project.confidentiality_level, *projection.confidentiality_levels]
    if any(level not in rank for level in levels):
        raise ValueError("unknown Mapping confidentiality")
    highest = max(levels, key=rank.__getitem__)
    selected = set(projection.selected_fact_refs)
    facts = []
    grouped = {}
    for section in ("metadata", "candidates", "mappings", "semantic", "regulatory", "knowledge_evidence", "historical", "lineage", "quality"):
        for fact in getattr(context, section):
            ref = f"{fact.source_type}:{fact.source_id if fact.source_id is not None else '-'}:{fact.fact_type}"
            if ref not in selected:
                continue
            material = fact.model_dump(mode="json")
            if fact.provenance.project_id != scope.project_id or fact.provenance.institution_id not in {None, scope.institution_id}:
                raise ValueError("Mapping fact belongs to a different scope")
            level = fact.provenance.confidentiality_level or highest
            if level not in rank:
                raise ValueError("unknown Mapping fact confidentiality")
            grouped.setdefault(ref, []).append((material, level))
    ambiguous = []
    for ref, members in grouped.items():
        # Legacy Context references can collide across source models. Preserve
        # every member/provenance in an explicit bundle rather than dropping one
        # or pretending that the alias resolves to a single authoritative fact.
        unique = {stable_hash(material): material for material, _ in members}
        material = next(iter(unique.values())) if len(unique) == 1 else {"ambiguous_reference": ref, "members": list(unique.values())}
        if len(unique) > 1:
            ambiguous.append(ref)
        level = max((level for _, level in members), key=rank.__getitem__)
        facts.append(SkillEvidence(id=ref, kind="context_reference", value=material,
                source=EvidenceSource(source_type="regulatory_context", source_id=ref,
                    source_version=stable_hash(material), locator=ref, scope=scope), confidentiality=level))
    # Preserve the authorized projection, including its manual snapshot, gaps,
    # physical allowlist and full prompt text. Never rebuild or truncate it here.
    value = {"snapshot": snapshot.model_dump(mode="json"), "projection": projection.model_dump(mode="json")}
    facts.append(SkillEvidence(id=f"mapping-context:{snapshot.task.id}", kind="mapping_context", value=value,
        source=EvidenceSource(source_type="mapping_snapshot", source_id=str(snapshot.task.id),
            source_version=stable_hash(value), locator=task_key, scope=scope), confidentiality=highest))
    gaps = [SkillGap(code="mapping_context_gap", message=str(gap)) for gap in projection.context_gaps]
    gaps.extend(SkillGap(code="ambiguous_context_reference", message="上下文引用对应多个来源，已完整保留，需人工区分", source_ref=ref) for ref in ambiguous)
    gaps.append(SkillGap(code="missing_basis", message="Context 中的监管定义和检索摘要仅为参考，尚未提供经版本与效力校验的制度条款"))
    result = SkillInputEnvelope(skill_key=task_key, task_key=task_key, scope=scope,
        subject_ref=f"{task_key}:{snapshot.task.id}", facts=facts, gaps=gaps, max_input_bytes=max_input_bytes)
    mapping_constraint(result)
    return result
