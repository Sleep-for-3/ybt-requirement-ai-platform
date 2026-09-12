from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class StructuredRequirementSnapshot(Base):
    """Immutable, replayable working snapshot for a regulatory requirement.

    ``DeliverablePackageVersion`` remains the source of truth for an approved
    rendered deliverable.  This table intentionally covers the earlier
    working stage where a team needs to freeze a structured requirement before
    a file has been rendered or submitted for approval.
    """

    __tablename__ = "structured_requirement_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "target_table_id",
            "scenario_id",
            "snapshot_no",
            name="uq_structured_requirement_snapshot_scope_version",
        ),
        UniqueConstraint(
            "project_id",
            "target_table_id",
            "scenario_id",
            "content_hash",
            name="uq_structured_requirement_snapshot_scope_hash",
        ),
        # ``scenario_id`` is nullable, and SQL NULL values are not equal for
        # a normal UNIQUE constraint.  Keep the legacy constraints for
        # backwards-compatible migrations, but enforce the actual logical
        # scope through the non-null ``scope_key`` constraints below.
        UniqueConstraint(
            "scope_key",
            "snapshot_no",
            name="uq_structured_requirement_snapshot_scope_key_version",
        ),
        UniqueConstraint(
            "scope_key",
            "content_hash",
            name="uq_structured_requirement_snapshot_scope_key_hash",
        ),
        Index(
            "ix_structured_requirement_snapshots_project_scope",
            "project_id",
            "target_table_id",
            "scenario_id",
            "snapshot_no",
        ),
        Index(
            "ix_structured_requirement_snapshots_project_status",
            "project_id",
            "status",
            "created_at",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    institution_id: Mapped[int | None] = mapped_column(ForeignKey("institutions.id"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    target_table_id: Mapped[int] = mapped_column(ForeignKey("target_tables.id"), nullable=False, index=True)
    scenario_id: Mapped[int | None] = mapped_column(ForeignKey("product_scenarios.id"), index=True)
    # Stable, non-null representation of the logical scope.  This prevents
    # duplicate versions when ``scenario_id`` is NULL on PostgreSQL/SQLite.
    scope_key: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    snapshot_no: Mapped[int] = mapped_column(Integer, nullable=False)
    requirement_version: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    schema_version: Mapped[str] = mapped_column(String(50), nullable=False, default="structured-requirement-v1")
    model_version: Mapped[str] = mapped_column(String(100), nullable=False, default="requirement-workspace-v2")
    catalog_revision: Mapped[str | None] = mapped_column(String(100), index=True)
    lineage_revision: Mapped[str | None] = mapped_column(String(100), index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft", index=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    content_snapshot_json: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSON), nullable=False, default=dict)
    change_note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
