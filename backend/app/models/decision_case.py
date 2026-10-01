"""Retrieval-based decision / case memory.

A ``decision_cases`` row is *enterprise business experience*: what a human
approved (or what a formal review concluded) for one decision subject in one
project.  It is deliberately **not** model training material and needs no
embedding service — cases are retrieved with deterministic keyword/field
matching and may only assist ranking, recommendation and rationale.

A historical case is supporting context, never a regulatory basis: only
``regulatory_knowledge_items`` / ``requirements`` may be cited as policy.  See
``app.services.agent.case_memory.case_is_regulatory_basis``, which is the guard
callers must use before quoting a case.

The table is append-oriented.  ``effective_from`` / ``effective_to`` describe
when the experience applied, and a correction is a new case with a new window
instead of an edit of history (``status`` retires a case without deleting it).

``related_mapping_id`` is a *soft* reference on purpose: mapping rows in this
codebase are polymorphic (``mapping_versions`` keys them by
``mapping_type`` + ``mapping_id``), so there is no single table a foreign key
could point at.
"""
from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.ext.mutable import MutableList
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.entities import TimestampMixin


class DecisionCase(Base, TimestampMixin):
    """One human-confirmed decision or formal review outcome, kept as experience."""

    __tablename__ = "decision_cases"
    __table_args__ = (
        Index("ix_decision_cases_project_type", "project_id", "decision_type"),
        Index("ix_decision_cases_project_status", "project_id", "status"),
        Index("ix_decision_cases_project_subject", "project_id", "subject_type", "subject_id"),
        Index("ix_decision_cases_project_scenario", "project_id", "scenario_key"),
        Index("ix_decision_cases_project_effective", "project_id", "effective_from"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    institution_id: Mapped[int | None] = mapped_column(ForeignKey("institutions.id"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    scenario_key: Mapped[str | None] = mapped_column(String(100), index=True)
    subject_type: Mapped[str | None] = mapped_column(String(100), index=True)
    subject_id: Mapped[str | None] = mapped_column(String(200), index=True)
    decision_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    decision: Mapped[str] = mapped_column(Text, nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text)
    evidence_refs_json: Mapped[list] = mapped_column(MutableList.as_mutable(JSON), default=list)
    regulatory_refs_json: Mapped[list] = mapped_column(MutableList.as_mutable(JSON), default=list)
    # Soft reference: mapping rows are polymorphic (mapping_type + mapping_id).
    related_mapping_id: Mapped[int | None] = mapped_column(Integer, index=True)
    related_requirement_id: Mapped[int | None] = mapped_column(ForeignKey("requirements.id"), index=True)
    related_script_id: Mapped[int | None] = mapped_column(ForeignKey("script_files.id"), index=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    confidence_source: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    effective_from: Mapped[object | None] = mapped_column(DateTime(timezone=True), index=True)
    effective_to: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(50), default="active", index=True)
    embedding_version: Mapped[str | None] = mapped_column(String(100))
