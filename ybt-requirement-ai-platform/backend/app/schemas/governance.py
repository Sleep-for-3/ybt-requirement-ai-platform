from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class OrmModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class BootstrapRequest(BaseModel):
    institution_code: str = Field(min_length=2, max_length=100)
    institution_name: str = Field(min_length=2, max_length=255)
    institution_type: str = "platform_operator"
    username: str = Field(min_length=3, max_length=100)
    display_name: str = Field(min_length=1, max_length=100)
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=12, max_length=256)


class LoginRequest(BaseModel):
    username: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class UserRead(OrmModel):
    id: int
    username: str
    display_name: str | None
    email: str | None
    status: str
    last_login_at: datetime | None


class AuthMe(UserRead):
    institution_memberships: list[dict[str, Any]] = Field(default_factory=list)
    project_memberships: list[dict[str, Any]] = Field(default_factory=list)


class BootstrapResponse(BaseModel):
    institution_id: int
    user: UserRead


class InstitutionCreate(BaseModel):
    institution_code: str = Field(min_length=2, max_length=100)
    institution_name: str = Field(min_length=2, max_length=255)
    institution_type: str = "bank"
    data_classification_policy_json: dict[str, Any] = Field(default_factory=dict)


class InstitutionRead(OrmModel):
    id: int
    institution_code: str
    institution_name: str
    institution_type: str
    status: str
    data_classification_policy_json: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class AdminUserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=100)
    display_name: str = Field(min_length=1, max_length=100)
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=12, max_length=256)
    institution_id: int
    institution_role: str = "member"


class ProjectMembershipCreate(BaseModel):
    user_id: int
    project_role: str


class ProjectMembershipRead(OrmModel):
    id: int
    project_id: int
    user_id: int
    project_role: str
    status: str
    joined_at: datetime


class WorkflowTarget(BaseModel):
    target_type: str
    target_id: int


class BatchReviewTaskCreate(BaseModel):
    workflow_key: str
    targets: list[WorkflowTarget] = Field(min_length=1, max_length=500)
    assignments: dict[str, int] = Field(default_factory=dict)
    due_at: datetime | None = None


class TaskDecisionRequest(BaseModel):
    comment: str | None = None
    return_to_step: str | None = None


class TaskAssignRequest(BaseModel):
    assignee_user_id: int


class BatchOperationRequest(BaseModel):
    field_ids: list[int] = Field(default_factory=list, max_length=10000)
    target_table_id: int | None = None
    scenario_id: int | None = None
    assignee_user_id: int | None = None
    due_at: datetime | None = None


class BatchReviewJobRequest(BatchReviewTaskCreate):
    pass
