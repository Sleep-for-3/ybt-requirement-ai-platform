"""Version 1 Skill boundary contracts; these schemas do not authorize resources.

Adapters must obtain scope and evidence from authorized, versioned sources.
No legacy caller is switched to this contract until the Skill runtime is ready.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StringConstraints, model_validator

from app.services.llm.execution_metadata import ExecutionKind, stable_hash


Key = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,99}$")]
# Leave nine characters for the legacy snapshot prefix "ai_skill:".
SkillKey = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,90}$")]
Reference = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
PositiveId = Annotated[int, Field(strict=True, gt=0)]
Confidentiality = Literal["public", "internal", "confidential", "restricted"]
SkillVersionStatus = Literal["draft", "testing", "pending_approval", "published", "deprecated", "archived"]
EvaluationMode = Literal["deterministic", "mock_model", "real_model", "replay", "human_review"]


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SkillScope(ContractModel):
    scope_type: Literal["platform", "institution", "project", "task"]
    institution_id: PositiveId | None = None
    project_id: PositiveId | None = None
    invocation_key: Key | None = None

    @model_validator(mode="after")
    def require_exact_scope(self) -> SkillScope:
        actual = (self.institution_id is not None, self.project_id is not None, self.invocation_key is not None)
        expected = {
            "platform": (False, False, False),
            "institution": (True, False, False),
            "project": (True, True, False),
            "task": (True, True, True),
        }
        if actual != expected[self.scope_type]:
            raise ValueError("scope coordinates do not match scope_type")
        return self


class EvidenceSource(ContractModel):
    source_type: Key
    source_id: Reference
    source_version: Reference
    locator: Reference
    scope: SkillScope


class SkillEvidence(ContractModel):
    id: Reference
    kind: Key
    value: JsonValue
    source: EvidenceSource
    confidentiality: Confidentiality


class SkillGap(ContractModel):
    code: Key
    message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    source_ref: Reference | None = None


class SkillInputEnvelope(ContractModel):
    input_contract_version: Literal["1.0"] = "1.0"
    skill_key: SkillKey
    task_key: Key
    scope: SkillScope
    subject_ref: Reference
    facts: list[SkillEvidence] = Field(default_factory=list)
    policy_evidence: list[SkillEvidence] = Field(default_factory=list)
    gaps: list[SkillGap] = Field(default_factory=list)
    max_input_bytes: Annotated[int, Field(strict=True, gt=0)] = 64000

    @model_validator(mode="after")
    def validate_evidence_scope_and_identity(self) -> SkillInputEnvelope:
        if self.scope.scope_type not in {"project", "task"}:
            raise ValueError("business input requires a project scope")
        seen: set[str] = set()
        for evidence in [*self.facts, *self.policy_evidence]:
            if evidence.id in seen:
                raise ValueError("duplicate evidence id")
            seen.add(evidence.id)
            origin = evidence.source.scope
            if origin.institution_id is not None and origin.institution_id != self.scope.institution_id:
                raise ValueError("cross-institution evidence")
            if origin.project_id is not None and origin.project_id != self.scope.project_id:
                raise ValueError("cross-project evidence")
            if origin.invocation_key is not None and origin.invocation_key != self.scope.invocation_key:
                raise ValueError("cross-task evidence")
        for evidence in self.policy_evidence:
            if evidence.kind != "policy_clause" or evidence.source.source_type != "knowledge_clause":
                raise ValueError("policy evidence requires a governed knowledge clause")
        return self

    def context_hash(self) -> str:
        """Hash the versioned projection, including scope, order and budget.

        Trace/request IDs and credentials are deliberately not part of the input.
        This is not a hash of the eventual rendered/redacted model request.
        """
        return stable_hash(self.model_dump(mode="json"))


class SkillClaim(ContractModel):
    claim_type: Literal["observed_fact", "policy_requirement", "interpretation", "inference"]
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    fact_ids: list[Reference] = Field(default_factory=list)
    policy_clause_ids: list[Reference] = Field(default_factory=list)
    requires_human_confirmation: bool = True

    @model_validator(mode="after")
    def require_support(self) -> SkillClaim:
        if not self.fact_ids and not self.policy_clause_ids:
            raise ValueError("claims require evidence; missing basis belongs in gaps")
        if self.claim_type == "observed_fact" and not self.fact_ids:
            raise ValueError("observed facts require fact references")
        if self.claim_type == "policy_requirement":
            if not self.policy_clause_ids or not self.requires_human_confirmation:
                raise ValueError("policy requirements need clauses and human confirmation")
        return self


def validate_claim_references(claim: SkillClaim, envelope: SkillInputEnvelope) -> None:
    """Validate categories separately so script facts cannot become policy basis."""
    if not set(claim.fact_ids).issubset({item.id for item in envelope.facts}):
        raise ValueError("unknown fact reference")
    if not set(claim.policy_clause_ids).issubset({item.id for item in envelope.policy_evidence}):
        raise ValueError("unknown policy reference")


class SkillPolicyComparison(ContractModel):
    """An evidence-linked suggestion, never an adopted human decision."""
    status: Literal["matched", "conflict", "missing_implementation", "pending"]
    fact_ids: list[Reference] = Field(min_length=1, max_length=100)
    policy_clause_ids: list[Reference] = Field(min_length=1, max_length=100)
    rationale: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=10000)]
    difference: Annotated[str, StringConstraints(strip_whitespace=True, max_length=10000)] = ""
    requires_human_confirmation: Literal[True] = True

    @model_validator(mode="after")
    def require_difference(self):
        if self.status in {"conflict", "missing_implementation"} and not self.difference:
            raise ValueError("policy differences require an explicit explanation")
        return self


def validate_policy_comparison(comparison: SkillPolicyComparison, envelope: SkillInputEnvelope) -> None:
    if not set(comparison.fact_ids).issubset({item.id for item in envelope.facts}):
        raise ValueError("unknown fact reference")
    if not set(comparison.policy_clause_ids).issubset({item.id for item in envelope.policy_evidence}):
        raise ValueError("unknown policy reference")


class SkillRunIdentity(ContractModel):
    runtime_mode: Literal["legacy", "skill"]
    execution_kind: ExecutionKind
    skill_key: SkillKey | None = None
    skill_version_id: PositiveId | None = None
    skill_version_no: PositiveId | None = None
    input_contract_version: Literal["1.0"] | None = None
    context_hash: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]

    @model_validator(mode="after")
    def distinguish_published_skill_from_legacy_prompt(self) -> SkillRunIdentity:
        coordinates = (self.skill_key, self.skill_version_id, self.skill_version_no, self.input_contract_version)
        if self.runtime_mode == "skill" and any(item is None for item in coordinates):
            raise ValueError("Skill runtime requires an explicit version identity")
        if self.runtime_mode == "legacy" and any(item is not None for item in coordinates):
            raise ValueError("legacy Prompt identity is not a published Skill identity")
        return self
