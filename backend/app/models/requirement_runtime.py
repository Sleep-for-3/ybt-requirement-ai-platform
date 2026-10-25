"""P2-A 运行事实包入库（requirement runtime fact packs）。

平台不执行客户跑批，只接收授权环境产出的脱敏事实包。事实包一旦被引用进需求，
就决定了"这条结论是静态推断还是运行验证过"——所以它必须落库、可追溯、可重复校验：

- ``pack_sha256`` 是内容身份：同一个事实包重复导入不会生成第二行。
- ``validation_json`` 保存导入时的校验结果（强度、问题、缺失项），**不随后续代码
  升级重算**：审核人当时看到的结论不能被悄悄改写。
- 事实包只按项目隔离；未验证的结论通过 ``fact_pack_gaps`` 进入需求缺口，不会因为
  导入成功就被当成"已验证"。
"""

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String, UniqueConstraint, func
from sqlalchemy.ext.mutable import MutableDict, MutableList
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.entities import TimestampMixin


class RequirementRuntimeFactPack(Base, TimestampMixin):
    __tablename__ = "requirement_runtime_fact_packs"
    __table_args__ = (
        UniqueConstraint("requirement_id", "pack_sha256", name="uq_requirement_runtime_fact_pack"),
        Index("ix_requirement_runtime_fact_scope", "project_id", "requirement_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    requirement_id: Mapped[int] = mapped_column(ForeignKey("requirements.id"), index=True)

    #: sha256 of the canonical JSON payload — content identity, not a file hash.
    pack_sha256: Mapped[str] = mapped_column(String(64), index=True)
    pack_version: Mapped[str] = mapped_column(String(64), default="")
    #: strongest level the evidence supports (never raised by callers).
    level: Mapped[str] = mapped_column(String(32), default="static_inference", index=True)
    status: Mapped[str] = mapped_column(String(32), default="unverified")
    execution_batch: Mapped[str | None] = mapped_column(String(128))
    business_date: Mapped[str | None] = mapped_column(String(10))

    payload_json: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSON), default=dict)
    validation_json: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSON), default=dict)
    issues_json: Mapped[list] = mapped_column(MutableList.as_mutable(JSON), default=list)

    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now())
