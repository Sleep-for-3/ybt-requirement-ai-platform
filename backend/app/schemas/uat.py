from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


SuiteType = Literal["end_to_end_delivery", "knowledge_and_citation", "catalog_and_source", "governance_workflow", "sql_lineage", "change_impact", "excel_fidelity", "permission_security", "performance", "deployment_readiness", "custom"]
ExecutionMode = Literal["automatic", "manual", "hybrid"]
Severity = Literal["critical", "high", "medium", "low"]


class UatCaseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_code: str = Field(min_length=1, max_length=100)
    case_name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    case_category: str = Field(min_length=1, max_length=50)
    precondition_json: dict = Field(default_factory=dict)
    input_requirement_json: dict = Field(default_factory=dict)
    expected_result_json: dict = Field(default_factory=dict)
    execution_mode: ExecutionMode
    severity: Severity
    enabled: bool = True
    display_order: int = Field(default=0, ge=0)


class UatSuiteCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    suite_name: str = Field(min_length=1, max_length=255)
    suite_type: SuiteType = "custom"
    description: str | None = None
    enabled: bool = True
    cases: list[UatCaseCreate] = Field(default_factory=list, max_length=500)


class UatRunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_name: str = Field(min_length=1, max_length=255)
    environment_name: str = Field(default="test", min_length=1, max_length=100)
    application_version: str | None = Field(default=None, max_length=100)
    git_commit_sha: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{7,64}$")


class EmptyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class UatFindingCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    uat_case_result_id: int | None = Field(default=None, gt=0)
    finding_type: Literal["functional", "data", "document", "workflow", "security", "performance", "usability", "deployment", "other"]
    severity: Severity
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1, max_length=10000)
    reproduction_steps: str | None = Field(default=None, max_length=10000)
    expected_behavior: str | None = Field(default=None, max_length=10000)
    actual_behavior: str | None = Field(default=None, max_length=10000)
    assigned_role: str | None = Field(default=None, max_length=50)
    assigned_user_id: int | None = Field(default=None, gt=0)


class UatFindingUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["open", "assigned", "fixing", "rejected", "closed"] | None = None
    assigned_role: str | None = Field(default=None, max_length=50)
    assigned_user_id: int | None = Field(default=None, gt=0)
    severity: Severity | None = None


class UatFindingResolve(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resolution_text: str = Field(min_length=1, max_length=10000)


class UatFindingVerify(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verification_comment: str = Field(min_length=1, max_length=5000)


class UatSignoffCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    signoff_role: Literal["business_owner", "technical_owner", "project_manager", "final_acceptance"]
    signoff_status: Literal["pending", "approved", "rejected"]
    comment: str | None = Field(default=None, max_length=5000)


class UatSuiteCloneRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    suite_name: str | None = Field(default=None, min_length=1, max_length=255)


class UatManualResultComplete(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["passed", "failed", "blocked", "skipped"]
    actual_result_json: dict = Field(default_factory=dict)
    evidence_json: dict = Field(default_factory=dict)
    error_message: str | None = Field(default=None, max_length=2000)


class UatEvidenceAttach(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence: dict
