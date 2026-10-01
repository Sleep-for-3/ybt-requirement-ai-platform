"""Editable configuration is bounded data, never executable tools or policies."""
from typing import Annotated, Literal

from pydantic import Field, StringConstraints

from app.schemas.ai_skill import ContractModel, EvaluationMode, Key, PositiveId, SkillInputEnvelope, SkillKey, SkillScope

TaskKey = Literal[
    "requirement_document_assistance",
    "lineage_edge_explanation", "policy_comparison", "requirement_candidate_generation",
    "scenario_business_mapping", "scenario_technical_lineage", "source_to_mart_mapping",
    "mart_to_ybt_mapping", "regulatory_qa", "data_field_explanation", "field_semantic_matching",
    "change_impact_explanation", "quality_rule_suggestion", "uat_suggestion", "project_assistant",
]


class ContextPolicy(ContractModel):
    providers: list[Literal[
        "lineage_edge_facts", "bounded_lineage_paths", "asset_identity", "script_evidence",
        "regulatory_clauses", "field_constraints", "quality_profile", "prior_human_decisions", "script_diff",
    ]] = Field(default_factory=lambda: ["lineage_edge_facts", "script_evidence", "asset_identity", "regulatory_clauses", "bounded_lineage_paths"])
    max_input_bytes: Annotated[int, Field(strict=True, ge=256, le=256000)] = 64000
    max_depth: Annotated[int, Field(strict=True, ge=1, le=10)] = 4
    max_paths: Annotated[int, Field(strict=True, ge=1, le=100)] = 20
    max_policy_clauses: Annotated[int, Field(strict=True, ge=1, le=30)] = 12
    overflow_policy: Literal["fail_with_breakdown"] = "fail_with_breakdown"


class SkillContent(ContractModel):
    input_contract_version: Literal["1.0"] = "1.0"
    system_prompt: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=16000)]
    user_prompt_template: Annotated[str, StringConstraints(min_length=1, max_length=16000)] = "{subject}\n{facts}\n{policy_evidence}\n{gaps}"
    model_profile_id: PositiveId
    context_policy: ContextPolicy = Field(default_factory=ContextPolicy)
    output_schema_key: Literal["grounded_claims_v1", "requirement_candidate_v1", "mapping_candidate_v1", "document_assistance_v1", "field_ranking_v1"] = "grounded_claims_v1"
    require_fact_references: Literal[True] = True
    require_policy_references: Literal[True] = True
    allow_tools: Literal[False] = False
    fallback_mode: Literal["deterministic_only"] = "deterministic_only"


class SkillDefinitionCreate(ContractModel):
    skill_key: SkillKey
    task_key: TaskKey
    display_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
    description: Annotated[str, StringConstraints(max_length=4000)] = ""


class SkillVersionCreate(ContractModel):
    scope: SkillScope
    content: SkillContent


class SkillVersionEdit(ContractModel):
    expected_lock_version: PositiveId
    content: SkillContent


class SkillVersionAction(ContractModel):
    expected_lock_version: PositiveId


class SkillDiffRequest(ContractModel):
    other_version: PositiveId


class SkillAssertions(ContractModel):
    minimum_claims: Annotated[int, Field(strict=True, ge=0, le=100)] = 0
    required_gap_codes: list[Key] = Field(default_factory=list)


class SkillTestCaseCreate(ContractModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
    input: SkillInputEnvelope
    assertions: SkillAssertions = Field(default_factory=SkillAssertions)
    replay_output: dict | None = None


class SkillTestRunCreate(ContractModel):
    version: PositiveId
    project_id: PositiveId
    mode: EvaluationMode
    expected_lock_version: PositiveId


class SkillPublishRequest(SkillVersionAction):
    test_project_id: PositiveId
    expected_binding_lock: PositiveId | None = None


class SkillBindingRequest(ContractModel):
    version: PositiveId
    scope: SkillScope
    expected_binding_lock: PositiveId | None = None


class SkillHumanReview(ContractModel):
    passed: bool
    comment: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
