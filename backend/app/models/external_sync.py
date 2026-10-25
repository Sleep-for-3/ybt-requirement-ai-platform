"""P2-B 外部增量同步落库：游标 + 待复核事件。

外部系统（元数据平台 / 调度平台 / 脚本版本库）的新版本**不能**直接改写需求或正式
交付。这张表只记录"看到了什么、裁决成什么"，所有可应用动作都以
``pending_review`` 结尾，由人复核后走既有需求修订流程。

与既有 ``MetadataSyncTask`` / ``MetadataDriftEvent`` 的区别：那两张表是**数据源
内省**（平台主动连库拉元数据、对比漂移）；这里的表是**外部事件订阅**（外部系统按
游标推送"某对象出了新版本/被删除/权限变了"），平台只做裁决与待复核，不主动抓取。

- ``external_sync_cursors``：每个项目每个来源已处理到的游标，单调不回退。
- ``external_sync_events``：按 ``(project, source, object_kind, object_key,
  source_version)`` 唯一，重放不产生第二行；重复/乱序/重放只出现在本次响应里，
  不落库，避免待复核列表被噪音淹没。
"""

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, JSON, String, UniqueConstraint, func
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.entities import TimestampMixin


class ExternalSyncCursor(Base, TimestampMixin):
    __tablename__ = "external_sync_cursors"
    __table_args__ = (UniqueConstraint("project_id", "source", name="uq_external_sync_cursor"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    source: Mapped[str] = mapped_column(String(80))
    #: 已处理到的位置；只允许前进。
    cursor: Mapped[int] = mapped_column(Integer, default=0)
    last_observed_at: Mapped[str | None] = mapped_column(String(40))
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class ExternalSyncEvent(Base, TimestampMixin):
    __tablename__ = "external_sync_events"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "source", "object_kind", "object_key", "source_version",
            name="uq_external_sync_event",
        ),
        Index("ix_external_sync_event_pending", "project_id", "decision"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    source: Mapped[str] = mapped_column(String(80), index=True)
    object_kind: Mapped[str] = mapped_column(String(80))
    object_key: Mapped[str] = mapped_column(String(255))
    source_version: Mapped[int] = mapped_column(Integer)
    cursor: Mapped[int] = mapped_column(Integer, default=0)

    #: pending_review / mark_deleted_pending_review / mark_permission_pending_review
    decision: Mapped[str] = mapped_column(String(40), index=True)
    payload_json: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSON), default=dict)
    payload_hash: Mapped[str] = mapped_column(String(64), default="")
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    permissions_changed: Mapped[bool] = mapped_column(Boolean, default=False)
    observed_at: Mapped[str | None] = mapped_column(String(40))

    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now())
