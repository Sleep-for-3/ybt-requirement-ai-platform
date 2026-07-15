from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.ext.mutable import MutableDict, MutableList
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.entities import TimestampMixin


class Institution(Base, TimestampMixin):
    __tablename__ = "institutions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    institution_code: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    institution_name: Mapped[str] = mapped_column(String(255), nullable=False)
    institution_type: Mapped[str] = mapped_column(String(50), default="bank", index=True)
    status: Mapped[str] = mapped_column(String(50), default="active", index=True)
    data_classification_policy_json: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSON), default=dict)


class InstitutionMembership(Base):
    __tablename__ = "institution_memberships"
    __table_args__ = (UniqueConstraint("institution_id", "user_id", name="uq_institution_membership"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    institution_id: Mapped[int] = mapped_column(ForeignKey("institutions.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(50), default="member", index=True)
    status: Mapped[str] = mapped_column(String(50), default="active", index=True)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class ProjectMembership(Base):
    __tablename__ = "project_memberships"
    __table_args__ = (UniqueConstraint("project_id", "user_id", name="uq_project_membership"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    project_role: Mapped[str] = mapped_column(String(50), index=True)
    status: Mapped[str] = mapped_column(String(50), default="active", index=True)
    joined_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    token_jti: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), index=True)
    replaced_by_jti: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LoginAttempt(Base):
    __tablename__ = "login_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    identifier_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    last_attempt_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WorkflowDefinition(Base, TimestampMixin):
    __tablename__ = "workflow_definitions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    workflow_key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    workflow_name: Mapped[str] = mapped_column(String(255), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    steps_json: Mapped[list] = mapped_column(MutableList.as_mutable(JSON), default=list)


class WorkflowInstance(Base, TimestampMixin):
    __tablename__ = "workflow_instances"
    __table_args__ = (Index("ix_workflow_target", "project_id", "target_type", "target_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    workflow_key: Mapped[str] = mapped_column(String(100), index=True)
    target_type: Mapped[str] = mapped_column(String(100), index=True)
    target_id: Mapped[int] = mapped_column(Integer, index=True)
    status: Mapped[str] = mapped_column(String(50), default="draft", index=True)
    current_step: Mapped[str | None] = mapped_column(String(100), index=True)
    started_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)


class ReviewTask(Base, TimestampMixin):
    __tablename__ = "review_tasks"
    __table_args__ = (Index("ix_review_task_assignee_status", "assignee_user_id", "status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    workflow_instance_id: Mapped[int] = mapped_column(ForeignKey("workflow_instances.id"), index=True)
    step_key: Mapped[str] = mapped_column(String(100), index=True)
    task_type: Mapped[str] = mapped_column(String(100), index=True)
    target_type: Mapped[str] = mapped_column(String(100), index=True)
    target_id: Mapped[int] = mapped_column(Integer, index=True)
    assignee_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    assignee_role: Mapped[str | None] = mapped_column(String(50), index=True)
    status: Mapped[str] = mapped_column(String(50), default="pending", index=True)
    due_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), index=True)
    claimed_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ReviewDecision(Base):
    __tablename__ = "review_decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    review_task_id: Mapped[int] = mapped_column(ForeignKey("review_tasks.id"), index=True)
    decision: Mapped[str] = mapped_column(String(50), index=True)
    comment: Mapped[str | None] = mapped_column(Text)
    content_snapshot_json: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSON), default=dict)
    decided_by: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    decided_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ScenarioReviewPackage(Base, TimestampMixin):
    __tablename__ = "scenario_review_packages"
    __table_args__ = (
        UniqueConstraint("project_id", "target_field_id", "scenario_id", name="uq_scenario_review_package_scope"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    target_field_id: Mapped[int] = mapped_column(ForeignKey("target_fields.id"), index=True)
    scenario_id: Mapped[int] = mapped_column(ForeignKey("product_scenarios.id"), index=True)
    business_mapping_id: Mapped[int] = mapped_column(ForeignKey("scenario_business_mappings.id"), index=True)
    technical_lineage_id: Mapped[int] = mapped_column(ForeignKey("scenario_technical_lineages.id"), index=True)
    status: Mapped[str] = mapped_column(String(50), default="draft", index=True)
    current_version_no: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)


class BackgroundJob(Base, TimestampMixin):
    __tablename__ = "background_jobs"
    __table_args__ = (Index("ix_background_jobs_project_status", "project_id", "status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    institution_id: Mapped[int | None] = mapped_column(ForeignKey("institutions.id"), index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    job_type: Mapped[str] = mapped_column(String(100), index=True)
    celery_task_id: Mapped[str | None] = mapped_column(String(255), index=True)
    status: Mapped[str] = mapped_column(String(50), default="queued", index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    current_step: Mapped[str | None] = mapped_column(String(255))
    payload_summary_json: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSON), default=dict)
    result_summary_json: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSON), default=dict)
    error_message: Mapped[str | None] = mapped_column(Text)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, default=3)
    started_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)


class BackgroundJobItem(Base):
    __tablename__ = "background_job_items"
    __table_args__ = (UniqueConstraint("background_job_id", "item_key", name="uq_background_job_item"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    background_job_id: Mapped[int] = mapped_column(ForeignKey("background_jobs.id"), index=True)
    item_key: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(50), index=True)
    result_summary_json: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSON), default=dict)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_logs_lookup", "institution_id", "project_id", "action", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    institution_id: Mapped[int | None] = mapped_column(ForeignKey("institutions.id"), index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), index=True)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    action: Mapped[str] = mapped_column(String(100), index=True)
    resource_type: Mapped[str] = mapped_column(String(100), index=True)
    resource_id: Mapped[str | None] = mapped_column(String(100), index=True)
    request_id: Mapped[str | None] = mapped_column(String(64), index=True)
    before_summary_json: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSON), default=dict)
    after_summary_json: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSON), default=dict)
    result: Mapped[str] = mapped_column(String(50), default="success", index=True)
    ip_address_masked: Mapped[str | None] = mapped_column(String(100))
    user_agent_summary: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_user_read", "user_id", "read_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), index=True)
    notification_type: Mapped[str] = mapped_column(String(100), index=True)
    title: Mapped[str] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(Text)
    resource_type: Mapped[str | None] = mapped_column(String(100))
    resource_id: Mapped[str | None] = mapped_column(String(100))
    read_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class StoredFile(Base, TimestampMixin):
    __tablename__ = "stored_files"
    __table_args__ = (Index("ix_stored_files_scope", "institution_id", "project_id", "classification"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    institution_id: Mapped[int] = mapped_column(ForeignKey("institutions.id"), index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), index=True)
    storage_key: Mapped[str] = mapped_column(String(500), unique=True, nullable=False)
    original_file_name: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(255))
    byte_size: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    classification: Mapped[str] = mapped_column(String(50), default="internal", index=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
