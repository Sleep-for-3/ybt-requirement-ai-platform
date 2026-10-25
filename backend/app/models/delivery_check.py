"""交付前检查的留痕记录。

检查本身是只读的（算一遍给结论），但"谁在什么时候检查过、当时是否通过"是审计事实：
评审现场问"这份文件交出去之前查过吗"，光有实时计算的界面回答不了。
本表只存结论快照（verdict / 阻断项 / 逐项明细），不存文件内容——文件在产物表里。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, ForeignKey, Index, String, Text
from sqlalchemy.ext.mutable import MutableDict, MutableList
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.entities import TimestampMixin


class RequirementDeliveryCheck(Base, TimestampMixin):
    __tablename__ = "requirement_delivery_checks"
    __table_args__ = (
        Index("ix_delivery_check_scope", "project_id", "requirement_id", "created_at"),
        Index("ix_delivery_check_artifact", "artifact_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    requirement_id: Mapped[int] = mapped_column(ForeignKey("requirements.id"), index=True)
    artifact_id: Mapped[int] = mapped_column(ForeignKey("requirement_render_artifacts.id"))
    checklist_version: Mapped[str] = mapped_column(String(64))
    verdict: Mapped[str] = mapped_column(String(16))
    blocking_keys_json: Mapped[list] = mapped_column(MutableList.as_mutable(JSON), default=list)
    checks_json: Mapped[list] = mapped_column(MutableList.as_mutable(JSON), default=list)
    summary_json: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSON), default=dict)
    note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
