"""Durable SQL change events: one row per semantic change, at most one agent task.

The event row is the idempotency anchor: (project, script, old version, new version,
semantic hash) is unique, so re-importing the same version tuple can never create a
second analysis task.
"""
from __future__ import annotations

from sqlalchemy import JSON, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.ext.mutable import MutableList
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.entities import TimestampMixin


class SqlChangeEvent(Base, TimestampMixin):
    __tablename__ = "sql_change_events"
    __table_args__ = (
        UniqueConstraint("project_id", "script_file_id", "old_version_id", "new_version_id", "semantic_hash",
                         name="uq_sql_change_event_identity"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    institution_id: Mapped[int] = mapped_column(ForeignKey("institutions.id"), nullable=False, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    script_file_id: Mapped[int] = mapped_column(ForeignKey("script_files.id"), nullable=False, index=True)
    old_version_id: Mapped[int | None] = mapped_column(ForeignKey("script_file_versions.id"))
    new_version_id: Mapped[int] = mapped_column(ForeignKey("script_file_versions.id"), nullable=False)
    semantic_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    old_semantic_hash: Mapped[str | None] = mapped_column(String(64))
    severity: Mapped[str] = mapped_column(String(20), default="low")
    categories_json: Mapped[list] = mapped_column(MutableList.as_mutable(JSON), default=list)
    diff_summary_json: Mapped[dict] = mapped_column(JSON, default=dict)
    change_note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="detected", index=True)
    agent_task_id: Mapped[int | None] = mapped_column(ForeignKey("agent_tasks.id"))
    detected_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    error_message: Mapped[str | None] = mapped_column(Text)
