"""字段级派工与处置登记。

派工单只回答"这个字段还缺什么"，但不回答"谁在跟、跟到哪一步"。项目负责人把清单发出去之后，
处置进展只能靠线下问；审计问"这个字段的缺口谁处理过、什么时候"，平台也答不出来。

这张表只登记**处置事实**：责任人（可以是平台外部的人名）、处置状态、说明。它不改需求内容、
不关缺口、不冻结——把"谁在处理"和"处理成什么样"分开记录，避免登记状态被当成验收。
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.entities import TimestampMixin


class RequirementFieldDispatch(Base, TimestampMixin):
    __tablename__ = "requirement_field_dispatches"
    __table_args__ = (
        UniqueConstraint("requirement_id", "field_id", name="uq_field_dispatch_scope"),
        Index("ix_field_dispatch_project", "project_id", "requirement_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    requirement_id: Mapped[int] = mapped_column(ForeignKey("requirements.id"), index=True)
    field_id: Mapped[int] = mapped_column(ForeignKey("target_fields.id"), index=True)
    # 责任人用自由文本：经办人往往不是平台用户，强制关联用户表会让这条登记无法落地。
    owner: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(32), default="in_progress")
    note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
