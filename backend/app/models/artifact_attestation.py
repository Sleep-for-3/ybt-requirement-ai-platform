"""人工核对登记：自动验收跑不了的产物（内置版式 xlsx / 客户模板 Word），由人看完写一条依据。

为什么不复用检查记录表：检查记录是**机器按契约算出来的结论**（结构自检、模板列逐字比对……），
人工核对是**人的判断**。两者混在一张表里，"已检查 N 个"就再也说不清是机器查的还人工看的，
而评审现场恰恰要区分这两件事。所以单独一张追加表：不覆盖、不删、不改，只记"谁在什么时候、
基于什么依据、得出什么结论"。它不改变交付状态，也不关闭任何缺口。
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.entities import TimestampMixin


class RequirementArtifactAttestation(Base, TimestampMixin):
    __tablename__ = "requirement_artifact_attestations"
    __table_args__ = (
        Index("ix_artifact_attestation_scope", "project_id", "artifact_id", "created_at"),
        Index("ix_artifact_attestation_requirement", "requirement_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    requirement_id: Mapped[int] = mapped_column(ForeignKey("requirements.id"), index=True)
    artifact_id: Mapped[int] = mapped_column(ForeignKey("requirement_render_artifacts.id"))
    # 为什么这台机器不能自动验收（来自 acceptance_scope 的 code），事后可追。
    scope_code: Mapped[str] = mapped_column(String(64))
    conclusion: Mapped[str] = mapped_column(String(16))
    basis: Mapped[str] = mapped_column(Text)
    attested_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
