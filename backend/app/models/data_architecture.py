"""Architecture metadata attaches to the existing physical catalog identity."""
from sqlalchemy import CheckConstraint, ForeignKey, Integer, JSON, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.entities import TimestampMixin


class DataArchitecture(Base, TimestampMixin):
    __tablename__ = "data_architectures"
    __table_args__ = (
        CheckConstraint("(project_id IS NULL) <> (institution_id IS NULL)", name="ck_architecture_one_owner"),
        UniqueConstraint("project_id", name="uq_data_architecture_project"),
        UniqueConstraint("institution_id", name="uq_data_architecture_institution"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"))
    institution_id: Mapped[int | None] = mapped_column(ForeignKey("institutions.id"))
    version: Mapped[int] = mapped_column(Integer, default=1)
    definition_json: Mapped[dict] = mapped_column(JSON)


class DataArchitectureRevision(Base, TimestampMixin):
    __tablename__ = "data_architecture_revisions"
    __table_args__ = (UniqueConstraint("architecture_id", "version", name="uq_architecture_revision"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    architecture_id: Mapped[int] = mapped_column(ForeignKey("data_architectures.id"))
    version: Mapped[int] = mapped_column(Integer)
    definition_json: Mapped[dict] = mapped_column(JSON)


class CatalogClassification(Base, TimestampMixin):
    __tablename__ = "catalog_classifications"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    catalog_table_id: Mapped[int] = mapped_column(ForeignKey("catalog_tables.id"), unique=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    architecture_revision_id: Mapped[int | None] = mapped_column(ForeignKey("data_architecture_revisions.id"))
    assignment_json: Mapped[dict] = mapped_column(JSON, default=dict)
