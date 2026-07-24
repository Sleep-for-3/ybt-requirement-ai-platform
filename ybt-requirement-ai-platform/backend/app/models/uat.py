from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.entities import TimestampMixin


class UatSuite(Base, TimestampMixin):
    __tablename__ = "uat_suites"
    __table_args__ = (
        UniqueConstraint("project_id", "suite_name", name="uq_uat_suite_project_name"),
        Index("ix_uat_suites_project_type", "project_id", "suite_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    institution_id: Mapped[int | None] = mapped_column(ForeignKey("institutions.id"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    suite_name: Mapped[str] = mapped_column(String(255))
    suite_type: Mapped[str] = mapped_column(String(50), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class UatCase(Base, TimestampMixin):
    __tablename__ = "uat_cases"
    __table_args__ = (
        UniqueConstraint("uat_suite_id", "case_code", name="uq_uat_case_suite_code"),
        Index("ix_uat_cases_suite_order", "uat_suite_id", "display_order"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    uat_suite_id: Mapped[int] = mapped_column(ForeignKey("uat_suites.id"), index=True)
    case_code: Mapped[str] = mapped_column(String(100), index=True)
    case_name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    case_category: Mapped[str] = mapped_column(String(50), index=True)
    precondition_json: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSON), default=dict)
    input_requirement_json: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSON), default=dict)
    expected_result_json: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSON), default=dict)
    execution_mode: Mapped[str] = mapped_column(String(20), index=True)
    severity: Mapped[str] = mapped_column(String(20), index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    display_order: Mapped[int] = mapped_column(Integer, default=0)


class UatRun(Base, TimestampMixin):
    __tablename__ = "uat_runs"
    __table_args__ = (
        UniqueConstraint("project_id", "uat_suite_id", "run_no", name="uq_uat_run_suite_no"),
        Index("ix_uat_runs_project_status", "project_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    institution_id: Mapped[int | None] = mapped_column(ForeignKey("institutions.id"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    uat_suite_id: Mapped[int] = mapped_column(ForeignKey("uat_suites.id"), index=True)
    run_name: Mapped[str] = mapped_column(String(255))
    run_no: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    environment_name: Mapped[str] = mapped_column(String(100), default="test")
    application_version: Mapped[str | None] = mapped_column(String(100))
    git_commit_sha: Mapped[str | None] = mapped_column(String(64), index=True)
    started_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    started_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    summary_json: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSON), default=dict)
    background_job_id: Mapped[int | None] = mapped_column(ForeignKey("background_jobs.id"), index=True)


class UatCaseResult(Base, TimestampMixin):
    __tablename__ = "uat_case_results"
    __table_args__ = (
        UniqueConstraint("uat_run_id", "uat_case_id", name="uq_uat_result_run_case"),
        Index("ix_uat_case_results_run_status", "uat_run_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    uat_run_id: Mapped[int] = mapped_column(ForeignKey("uat_runs.id"), index=True)
    uat_case_id: Mapped[int] = mapped_column(ForeignKey("uat_cases.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    actual_result_json: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSON), default=dict)
    expected_result_json: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSON), default=dict)
    evidence_json: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSON), default=dict)
    error_message: Mapped[str | None] = mapped_column(Text)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    executed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    executed_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))


class UatFinding(Base, TimestampMixin):
    __tablename__ = "uat_findings"
    __table_args__ = (
        UniqueConstraint("uat_run_id", "finding_no", name="uq_uat_finding_run_no"),
        Index("ix_uat_findings_run_status", "uat_run_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    institution_id: Mapped[int | None] = mapped_column(ForeignKey("institutions.id"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    uat_run_id: Mapped[int] = mapped_column(ForeignKey("uat_runs.id"), index=True)
    uat_case_result_id: Mapped[int | None] = mapped_column(ForeignKey("uat_case_results.id"), index=True)
    finding_no: Mapped[int] = mapped_column(Integer)
    finding_type: Mapped[str] = mapped_column(String(30), index=True)
    severity: Mapped[str] = mapped_column(String(20), index=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text)
    reproduction_steps: Mapped[str | None] = mapped_column(Text)
    expected_behavior: Mapped[str | None] = mapped_column(Text)
    actual_behavior: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)
    assigned_role: Mapped[str | None] = mapped_column(String(50))
    assigned_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    resolution_text: Mapped[str | None] = mapped_column(Text)
    resolved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    resolved_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    verified_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    verified_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class UatSignoff(Base, TimestampMixin):
    __tablename__ = "uat_signoffs"
    __table_args__ = (Index("ix_uat_signoffs_run_role", "uat_run_id", "signoff_role"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    uat_run_id: Mapped[int] = mapped_column(ForeignKey("uat_runs.id"), index=True)
    signoff_role: Mapped[str] = mapped_column(String(30), index=True)
    signoff_status: Mapped[str] = mapped_column(String(20), index=True)
    comment: Mapped[str | None] = mapped_column(Text)
    signed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    signed_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UatPack(Base, TimestampMixin):
    __tablename__ = "uat_packs"
    __table_args__ = (Index("ix_uat_packs_project_status", "project_id", "status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    institution_id: Mapped[int | None] = mapped_column(ForeignKey("institutions.id"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    pack_name: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), default="uploaded", index=True)
    manifest_json: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSON), default=dict)
    validation_json: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSON), default=dict)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class UatPackItem(Base, TimestampMixin):
    __tablename__ = "uat_pack_items"
    __table_args__ = (
        UniqueConstraint("uat_pack_id", "relative_path", name="uq_uat_pack_item_path"),
        Index("ix_uat_pack_items_pack_type", "uat_pack_id", "material_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    uat_pack_id: Mapped[int] = mapped_column(ForeignKey("uat_packs.id"), index=True)
    stored_file_id: Mapped[int] = mapped_column(ForeignKey("stored_files.id"), index=True)
    relative_path: Mapped[str] = mapped_column(String(500))
    original_file_name: Mapped[str] = mapped_column(String(255))
    material_type: Mapped[str] = mapped_column(String(50), index=True)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    byte_size: Mapped[int] = mapped_column(Integer)
