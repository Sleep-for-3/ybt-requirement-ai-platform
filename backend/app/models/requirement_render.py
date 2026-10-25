"""Frozen render artifacts for requirement documents (P1-A).

A formal delivery must be downloadable years later, byte-for-byte identical to
what was approved.  Rendering is not reproducible in general (library versions,
zip timestamps, template edits), so the bytes themselves become the record.

Identity is split the way the audit needs it:

- ``content_hash``    – what the requirement content said
- ``template_sha256`` – which customer template produced the layout ("" = built-in)
- ``renderer_version``/``config_version`` – which code and mapping config rendered it
- ``render_identity`` – the three above + format + frozen source, hashed together
- ``file_sha256``     – the bytes that are actually stored

``render_identity`` is unique per project: asking twice for the same identity
returns the stored artifact instead of rendering again.  A template change
produces a *new* artifact and never overwrites the old row or file.
"""

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String, UniqueConstraint, func
from sqlalchemy.ext.mutable import MutableDict, MutableList
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.entities import TimestampMixin


class RequirementRenderArtifact(Base, TimestampMixin):
    __tablename__ = "requirement_render_artifacts"
    __table_args__ = (
        UniqueConstraint("project_id", "render_identity", name="uq_requirement_render_identity"),
        Index("ix_requirement_render_scope", "project_id", "requirement_id", "source_kind", "source_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    requirement_id: Mapped[int] = mapped_column(ForeignKey("requirements.id"), index=True)
    #: ``formal_delivery`` (RequirementFormalDelivery.id) or ``draft_snapshot`` (StructuredRequirementSnapshot.id)
    source_kind: Mapped[str] = mapped_column(String(40), index=True)
    source_id: Mapped[int] = mapped_column(Integer, index=True)

    format: Mapped[str] = mapped_column(String(10))
    file_name: Mapped[str] = mapped_column(String(255))
    media_type: Mapped[str] = mapped_column(String(255))

    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    snapshot_hash: Mapped[str | None] = mapped_column(String(64))
    template_sha256: Mapped[str] = mapped_column(String(64), default="")
    renderer_version: Mapped[str] = mapped_column(String(80))
    config_version: Mapped[str] = mapped_column(String(80), default="")
    render_identity: Mapped[str] = mapped_column(String(64), index=True)

    file_sha256: Mapped[str] = mapped_column(String(64), index=True)
    file_size: Mapped[int] = mapped_column(Integer, default=0)
    storage_key: Mapped[str] = mapped_column(String(500), default="")
    storage_backend: Mapped[str] = mapped_column(String(40), default="local")

    status: Mapped[str] = mapped_column(String(20), default="ready", index=True)
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(String(500))
    diagnostics_json: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSON), default=dict)
    warnings_json: Mapped[list] = mapped_column(MutableList.as_mutable(JSON), default=list)

    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now())
