from sqlalchemy import ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.entities import TimestampMixin


class ResourceImportBatch(Base, TimestampMixin):
    __tablename__ = "resource_import_batches"
    __table_args__ = (UniqueConstraint("project_id", "idempotency_key", name="uq_resource_import_request"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    idempotency_key: Mapped[str] = mapped_column(String(100))
    request_hash: Mapped[str] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(30), default="preview")
    options_json: Mapped[dict] = mapped_column(JSON, default=dict)
    preview_json: Mapped[dict] = mapped_column(JSON, default=dict)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("background_jobs.id"))


class ResourceImportItem(Base, TimestampMixin):
    __tablename__ = "resource_import_items"
    __table_args__ = (UniqueConstraint("batch_id", "relative_path", name="uq_resource_import_path"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("resource_import_batches.id"), index=True)
    relative_path: Mapped[str] = mapped_column(String(1000))
    file_kind: Mapped[str] = mapped_column(String(30))
    stored_file_id: Mapped[int] = mapped_column(ForeignKey("stored_files.id"))
    status: Mapped[str] = mapped_column(String(30), default="preview")
    parsed_json: Mapped[dict] = mapped_column(JSON, default=dict)
    result_json: Mapped[dict] = mapped_column(JSON, default=dict)
