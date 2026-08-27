from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.entities import TimestampMixin


class DataQualityExpectation(Base, TimestampMixin):
    """A governed rule definition; evaluation is intentionally out of scope here."""

    __tablename__ = "data_quality_expectations"
    __table_args__ = (
        UniqueConstraint("project_id", "rule_code", name="uq_quality_expectations_project_code"),
        Index("ix_quality_expectations_project_status", "project_id", "status"),
        Index("ix_quality_expectations_project_rule_type", "project_id", "rule_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    rule_code: Mapped[str] = mapped_column(String(120), nullable=False)
    rule_name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    rule_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    expression: Mapped[str | None] = mapped_column(Text)
    parameters_json: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSON), default=dict)
    severity: Mapped[str] = mapped_column(String(20), default="warning", index=True)
    status: Mapped[str] = mapped_column(String(30), default="draft", index=True)
    source_type: Mapped[str] = mapped_column(String(50), default="manual")
    source_id: Mapped[int | None] = mapped_column(Integer)
    confidence_level: Mapped[str] = mapped_column(String(20), default="medium")
    created_by: Mapped[str | None] = mapped_column(String(100))
    confirmed_by: Mapped[str | None] = mapped_column(String(100))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status_reason: Mapped[str | None] = mapped_column(Text)


class DataQualityExpectationBinding(Base, TimestampMixin):
    """Connect one quality expectation to requirement, mapping, UAT, or monitoring scopes."""

    __tablename__ = "data_quality_expectation_bindings"
    __table_args__ = (
        Index("ix_quality_expectation_bindings_project_scope", "project_id", "scope_type", "entity_type", "entity_id"),
        Index("ix_quality_expectation_bindings_expectation", "expectation_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    expectation_id: Mapped[int] = mapped_column(ForeignKey("data_quality_expectations.id"), index=True)
    scope_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    entity_id: Mapped[int | None] = mapped_column(Integer, index=True)
    entity_key: Mapped[str | None] = mapped_column(String(500), index=True)
    binding_status: Mapped[str] = mapped_column(String(30), default="active", index=True)
    configuration_json: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSON), default=dict)
