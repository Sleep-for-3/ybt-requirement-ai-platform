"""字段派工的状态变更事件（只追加，不覆盖）。

`requirement_field_dispatches` 只留最近一次处置；审计要问"这个字段谁在什么时候把状态改成什么"，
最近一次答不出来。事件表按追加写，用于还原处置轨迹；它仍然只记录处置事实，不关缺口、不改正文。
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.entities import TimestampMixin


class RequirementFieldDispatchEvent(Base, TimestampMixin):
    __tablename__ = "requirement_field_dispatch_events"
    __table_args__ = (
        Index("ix_dispatch_event_scope", "requirement_id", "field_id", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    requirement_id: Mapped[int] = mapped_column(ForeignKey("requirements.id"), index=True)
    field_id: Mapped[int] = mapped_column(ForeignKey("target_fields.id"), index=True)
    owner: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(32), default="in_progress")
    note: Mapped[str | None] = mapped_column(Text)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
