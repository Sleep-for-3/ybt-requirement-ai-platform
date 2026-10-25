"""脚本依据滞后的复核决定（谁、什么时候、决定跟随还是暂不跟随）。

为什么需要落库：看板能标出"哪条需求的脚本依据落后了"，但"看了之后决定怎么办"只存在人脑里——
下一次打开看板还是一片橙色告警，既分不清"没人看过"和"看过后决定暂不跟随"，
也无法解释为什么这条需求一直停在旧脚本上。决定本身就是要审计的事实。
"""

from __future__ import annotations

from sqlalchemy import Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.entities import TimestampMixin


class RequirementScriptBasisDecision(Base, TimestampMixin):
    __tablename__ = "requirement_script_basis_decisions"
    __table_args__ = (
        UniqueConstraint(
            "requirement_id",
            "script_file_id",
            "latest_version_id",
            name="uq_script_basis_decision",
        ),
        Index("ix_script_basis_decision_scope", "project_id", "requirement_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(index=True)
    requirement_id: Mapped[int] = mapped_column(index=True)
    script_file_id: Mapped[int] = mapped_column(index=True)
    frozen_version_id: Mapped[int] = mapped_column()
    latest_version_id: Mapped[int] = mapped_column()
    decision: Mapped[str] = mapped_column(String(32))
    note: Mapped[str | None] = mapped_column(Text)
    decided_by: Mapped[int | None] = mapped_column()
