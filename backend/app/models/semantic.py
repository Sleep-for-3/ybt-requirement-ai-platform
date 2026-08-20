from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.ext.mutable import MutableList
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.entities import TimestampMixin


class SemanticConcept(Base, TimestampMixin):
    __tablename__ = "semantic_concepts"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "concept_type", "concept_code",
            name="uq_semantic_concept_project_type_code",
        ),
        Index("ix_semantic_concept_project_status", "project_id", "status"),
        Index("ix_semantic_concept_project_name", "project_id", "concept_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    institution_id: Mapped[int | None] = mapped_column(ForeignKey("institutions.id"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    concept_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    concept_code: Mapped[str] = mapped_column(String(150), nullable=False)
    concept_name: Mapped[str] = mapped_column(String(255), nullable=False)
    definition: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    aliases_json: Mapped[list] = mapped_column(MutableList.as_mutable(JSON), default=list)
    business_domain: Mapped[str | None] = mapped_column(String(200), index=True)
    owner_department: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(30), default="draft", nullable=False, index=True)
    confidence_level: Mapped[str] = mapped_column(String(30), default="medium", nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    source_type: Mapped[str] = mapped_column(String(50), default="manual", nullable=False)
    source_id: Mapped[int | None] = mapped_column(Integer)
    created_by: Mapped[str | None] = mapped_column(String(100))
    confirmed_by: Mapped[str | None] = mapped_column(String(100))
    confirmed_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))


class SemanticBinding(Base, TimestampMixin):
    __tablename__ = "semantic_bindings"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "semantic_concept_id", "entity_type", "entity_id", "binding_type",
            name="uq_semantic_binding_concept_entity_type",
        ),
        Index("ix_semantic_binding_entity", "project_id", "entity_type", "entity_id", "status"),
        Index("ix_semantic_binding_concept_status", "project_id", "semantic_concept_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    institution_id: Mapped[int | None] = mapped_column(ForeignKey("institutions.id"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    semantic_concept_id: Mapped[int] = mapped_column(ForeignKey("semantic_concepts.id"), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    binding_type: Mapped[str] = mapped_column(String(50), default="describes", nullable=False)
    confidence_level: Mapped[str] = mapped_column(String(30), default="medium", nullable=False)
    confidence_score: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(30), default="draft", nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(50), default="manual", nullable=False)
    source_id: Mapped[int | None] = mapped_column(Integer)
    created_by: Mapped[str | None] = mapped_column(String(100))
    confirmed_by: Mapped[str | None] = mapped_column(String(100))
    confirmed_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))


class SemanticRelation(Base, TimestampMixin):
    __tablename__ = "semantic_relations"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "source_concept_id", "relation_type", "target_concept_id",
            name="uq_semantic_relation_triple",
        ),
        Index("ix_semantic_relation_source", "project_id", "source_concept_id", "status"),
        Index("ix_semantic_relation_target", "project_id", "target_concept_id", "status"),
        CheckConstraint("source_concept_id <> target_concept_id", name="ck_semantic_relation_not_self"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    institution_id: Mapped[int | None] = mapped_column(ForeignKey("institutions.id"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    source_concept_id: Mapped[int] = mapped_column(ForeignKey("semantic_concepts.id"), nullable=False, index=True)
    relation_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    target_concept_id: Mapped[int] = mapped_column(ForeignKey("semantic_concepts.id"), nullable=False, index=True)
    confidence_level: Mapped[str] = mapped_column(String(30), default="medium", nullable=False)
    confidence_score: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(30), default="draft", nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(50), default="manual", nullable=False)
    source_id: Mapped[int | None] = mapped_column(Integer)
    created_by: Mapped[str | None] = mapped_column(String(100))
    confirmed_by: Mapped[str | None] = mapped_column(String(100))
    confirmed_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
