from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ReportingCycle(Base):
    __tablename__ = "reporting_cycles"
    __table_args__ = (
        UniqueConstraint("project_id", "cycle_code", name="uq_reporting_cycles_project_code"),
        Index("ix_reporting_cycles_project_status", "project_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    institution_id: Mapped[int | None] = mapped_column(ForeignKey("institutions.id"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    cycle_code: Mapped[str] = mapped_column(String(100), nullable=False)
    cycle_name: Mapped[str] = mapped_column(String(255), nullable=False)
    reporting_type: Mapped[str] = mapped_column(String(50), default="regular", index=True)
    period_start: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    data_cutoff_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    submission_deadline: Mapped[object | None] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(30), default="draft", index=True)
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    owner_department: Mapped[str | None] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class MetricSnapshot(Base):
    __tablename__ = "metric_snapshots"
    __table_args__ = (
        UniqueConstraint("project_id", "reporting_cycle_id", "metric_code", name="uq_metric_snapshots_project_cycle_metric"),
        Index("ix_metric_snapshots_project_cycle", "project_id", "reporting_cycle_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    institution_id: Mapped[int | None] = mapped_column(ForeignKey("institutions.id"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    reporting_cycle_id: Mapped[int] = mapped_column(ForeignKey("reporting_cycles.id"), index=True)
    metric_code: Mapped[str] = mapped_column(String(120), index=True)
    numerator: Mapped[float] = mapped_column(Float, nullable=False)
    denominator: Mapped[float] = mapped_column(Float, nullable=False)
    value: Mapped[float | None] = mapped_column(Float)
    scope: Mapped[str] = mapped_column(String(500), nullable=False)
    as_of: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    calculated_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    definition_version: Mapped[str] = mapped_column(String(30), nullable=False, default="1.0")

