from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.entities import TimestampMixin


class RequirementScriptBatch(Base, TimestampMixin):
    __tablename__ = "requirement_script_batches"
    __table_args__ = (UniqueConstraint("project_id", "idempotency_key", name="uq_requirement_script_batch_request"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    import_batch_id: Mapped[int | None] = mapped_column(ForeignKey("resource_import_batches.id"))
    idempotency_key: Mapped[str] = mapped_column(String(100))
    request_hash: Mapped[str] = mapped_column(String(64))
    result_json: Mapped[dict] = mapped_column(JSON, default=dict)


class RequirementUatLink(Base, TimestampMixin):
    __tablename__ = "requirement_uat_links"
    __table_args__ = (UniqueConstraint("revision_id", name="uq_requirement_uat_revision"),
        UniqueConstraint("suite_id", name="uq_requirement_uat_suite"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    requirement_id: Mapped[int] = mapped_column(ForeignKey("requirements.id"), index=True)
    revision_id: Mapped[int] = mapped_column(ForeignKey("requirement_revisions.id"))
    suite_id: Mapped[int] = mapped_column(ForeignKey("uat_suites.id"))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    content_hash: Mapped[str] = mapped_column(String(64))
    cases_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(30), default="draft")


class RequirementRecheck(Base, TimestampMixin):
    __tablename__ = "requirement_rechecks"
    __table_args__ = (UniqueConstraint("revision_id", "change_hash", name="uq_requirement_recheck_change"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    requirement_id: Mapped[int] = mapped_column(ForeignKey("requirements.id"), index=True)
    revision_id: Mapped[int] = mapped_column(ForeignKey("requirement_revisions.id"))
    replacement_revision_id: Mapped[int | None] = mapped_column(ForeignKey("requirement_revisions.id"))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    change_hash: Mapped[str] = mapped_column(String(64))
    changes_json: Mapped[list] = mapped_column(JSON)
    resolution: Mapped[str | None] = mapped_column(String(10000))
    status: Mapped[str] = mapped_column(String(30), default="pending")


class Requirement(Base, TimestampMixin):
    __tablename__ = "requirements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    version: Mapped[int] = mapped_column(Integer, default=1)
    scope_json: Mapped[dict] = mapped_column(JSON, default=dict)
    content_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class RequirementRevision(Base, TimestampMixin):
    __tablename__ = "requirement_revisions"
    __table_args__ = (UniqueConstraint("requirement_id", "content_version", name="uq_requirement_content_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    requirement_id: Mapped[int] = mapped_column(ForeignKey("requirements.id"), index=True)
    content_version: Mapped[int] = mapped_column(Integer)
    scope_version: Mapped[int] = mapped_column(Integer)
    parent_version: Mapped[int | None] = mapped_column(Integer)
    content_json: Mapped[dict] = mapped_column(JSON)
    content_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(30), default="draft")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class RequirementGenerationInput(Base, TimestampMixin):
    __tablename__ = "requirement_generation_inputs"
    __table_args__ = (UniqueConstraint("requirement_id", "idempotency_key", name="uq_requirement_generation_input_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    requirement_id: Mapped[int] = mapped_column(ForeignKey("requirements.id"), index=True)
    revision_id: Mapped[int] = mapped_column(ForeignKey("requirement_revisions.id"))
    idempotency_key: Mapped[str] = mapped_column(String(100))
    request_hash: Mapped[str] = mapped_column(String(64))
    input_hash: Mapped[str] = mapped_column(String(64))
    input_json: Mapped[dict] = mapped_column(JSON)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    job_id: Mapped[int | None] = mapped_column(ForeignKey("background_jobs.id"))


class RequirementGenerationItem(Base, TimestampMixin):
    __tablename__ = "requirement_generation_items"
    __table_args__ = (UniqueConstraint("input_id", "field_id", "section", name="uq_requirement_generation_item"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    input_id: Mapped[int] = mapped_column(ForeignKey("requirement_generation_inputs.id"), index=True)
    field_id: Mapped[int] = mapped_column(Integer)
    section: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(30), default="pending")
    lease_key: Mapped[str | None] = mapped_column(String(64))
    lease_until: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    candidate_json: Mapped[dict | None] = mapped_column(JSON)
    candidate_hash: Mapped[str | None] = mapped_column(String(64))
    reason_code: Mapped[str | None] = mapped_column(String(80))
    decision: Mapped[str] = mapped_column(String(30), default="pending", server_default="pending")
    decision_reason: Mapped[str | None] = mapped_column(String(2000))
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    adopted_content_version: Mapped[int | None] = mapped_column(Integer)


class RequirementDelivery(Base, TimestampMixin):
    __tablename__ = "requirement_deliveries"
    __table_args__ = (
        UniqueConstraint(
            "requirement_id",
            "requirement_version",
            "content_hash",
            name="uq_requirement_draft_snapshot",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    requirement_id: Mapped[int] = mapped_column(ForeignKey("requirements.id"), index=True)
    requirement_version: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(64))
    content_json: Mapped[dict] = mapped_column(JSON)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class RequirementReviewSubmission(Base, TimestampMixin):
    __tablename__ = "requirement_review_submissions"
    __table_args__ = (
        UniqueConstraint("revision_id", name="uq_requirement_review_revision"),
        UniqueConstraint("submission_hash", name="uq_requirement_review_submission_hash"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    requirement_id: Mapped[int] = mapped_column(ForeignKey("requirements.id"), index=True)
    revision_id: Mapped[int] = mapped_column(ForeignKey("requirement_revisions.id"), index=True)
    content_version: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(64))
    submission_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(30), default="pending_review", index=True)
    submitted_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    submitted_at: Mapped[object] = mapped_column(DateTime(timezone=True))
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))


class RequirementFormalDelivery(Base):
    __tablename__ = "requirement_formal_deliveries"
    __table_args__ = (
        UniqueConstraint("requirement_id", "version_no", name="uq_requirement_formal_version"),
        UniqueConstraint("review_submission_id", name="uq_requirement_formal_review"),
        UniqueConstraint("workflow_instance_id", name="uq_requirement_formal_workflow"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    requirement_id: Mapped[int] = mapped_column(ForeignKey("requirements.id"), index=True)
    revision_id: Mapped[int] = mapped_column(ForeignKey("requirement_revisions.id"), index=True)
    review_submission_id: Mapped[int] = mapped_column(ForeignKey("requirement_review_submissions.id"))
    workflow_instance_id: Mapped[int] = mapped_column(ForeignKey("workflow_instances.id"))
    version_no: Mapped[int] = mapped_column(Integer)
    content_version: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(64))
    snapshot_hash: Mapped[str] = mapped_column(String(64))
    stored_file_id: Mapped[int] = mapped_column(ForeignKey("stored_files.id"))
    file_hash: Mapped[str] = mapped_column(String(64))
    content_json: Mapped[dict] = mapped_column(JSON)
    approved_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    approved_at: Mapped[object] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now())
