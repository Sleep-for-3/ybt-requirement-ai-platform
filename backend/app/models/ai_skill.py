"""Skill control plane. Runtime and legacy model configuration remain separate."""
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Integer, JSON, String, Text, UniqueConstraint, event, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


@event.listens_for(Base.metadata, "after_create")
def _install_history_guards(metadata, connection, **kw):
    # Keep ORM-created isolated test databases consistent with migrated ones.
    from app.schema_freeze.ai_skill_guards_20260927 import install
    install(connection)


class SkillScopeColumns:
    scope_type: Mapped[str] = mapped_column(String(20))
    scope_key: Mapped[str] = mapped_column(String(180))
    institution_id: Mapped[int | None] = mapped_column(ForeignKey("institutions.id"), index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), index=True)
    invocation_key: Mapped[str | None] = mapped_column(String(100))


SCOPE_CHECK = """(scope_type = 'platform' AND institution_id IS NULL AND project_id IS NULL AND invocation_key IS NULL)
OR (scope_type = 'institution' AND institution_id IS NOT NULL AND project_id IS NULL AND invocation_key IS NULL)
OR (scope_type = 'project' AND institution_id IS NOT NULL AND project_id IS NOT NULL AND invocation_key IS NULL)
OR (scope_type = 'task' AND institution_id IS NOT NULL AND project_id IS NOT NULL AND invocation_key IS NOT NULL)"""


class AISkillDefinition(Base):
    __tablename__ = "ai_skill_definitions"
    __table_args__ = (CheckConstraint("next_version_no > 0", name="ck_ai_skill_next_version"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    skill_key: Mapped[str] = mapped_column(String(91), unique=True)
    task_key: Mapped[str] = mapped_column(String(100))
    display_name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    next_version_no: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AISkillVersion(Base, SkillScopeColumns):
    __tablename__ = "ai_skill_versions"
    __table_args__ = (
        UniqueConstraint("definition_id", "version_no", name="uq_ai_skill_version_no"),
        UniqueConstraint("id", "definition_id", name="uq_ai_skill_version_definition"),
        CheckConstraint(SCOPE_CHECK, name="ck_ai_skill_version_scope"),
        CheckConstraint("version_no > 0 AND lock_version > 0", name="ck_ai_skill_version_positive"),
        CheckConstraint("status IN ('draft','testing','pending_approval','published','deprecated','archived')", name="ck_ai_skill_version_status"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    definition_id: Mapped[int] = mapped_column(ForeignKey("ai_skill_definitions.id"), index=True)
    version_no: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30), default="draft")
    lock_version: Mapped[int] = mapped_column(Integer, default=1)
    test_epoch: Mapped[int] = mapped_column(Integer, default=1)
    content_json: Mapped[dict] = mapped_column(JSON)
    content_hash: Mapped[str] = mapped_column(String(64))
    release_dependency_hash: Mapped[str | None] = mapped_column(String(64))
    restored_from_version_id: Mapped[int | None] = mapped_column(ForeignKey("ai_skill_versions.id"))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    edited_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AISkillScopeBinding(Base, SkillScopeColumns):
    """One explicit, pinned binding per scope; history lives in release events."""
    __tablename__ = "ai_skill_scope_bindings"
    __table_args__ = (
        UniqueConstraint("definition_id", "scope_key", name="uq_ai_skill_binding_scope"),
        ForeignKeyConstraint(["version_id", "definition_id"], ["ai_skill_versions.id", "ai_skill_versions.definition_id"], name="fk_ai_skill_binding_version"),
        CheckConstraint(SCOPE_CHECK, name="ck_ai_skill_binding_scope"),
        CheckConstraint("lock_version > 0", name="ck_ai_skill_binding_positive"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    definition_id: Mapped[int] = mapped_column(ForeignKey("ai_skill_definitions.id"), index=True)
    version_id: Mapped[int] = mapped_column(Integer)
    inherited_from_scope: Mapped[str | None] = mapped_column(String(180))
    lock_version: Mapped[int] = mapped_column(Integer, default=1)
    updated_by: Mapped[int] = mapped_column(ForeignKey("users.id"))


class AISkillReleaseEvent(Base):
    __tablename__ = "ai_skill_release_events"
    __table_args__ = (
        ForeignKeyConstraint(["version_id", "definition_id"], ["ai_skill_versions.id", "ai_skill_versions.definition_id"], name="fk_ai_skill_event_version"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    definition_id: Mapped[int] = mapped_column(ForeignKey("ai_skill_definitions.id"), index=True)
    version_id: Mapped[int | None] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(40))
    scope_key: Mapped[str] = mapped_column(String(180))
    actor_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    detail_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AISkillTestCase(Base):
    __tablename__ = "ai_skill_test_cases"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    definition_id: Mapped[int] = mapped_column(ForeignKey("ai_skill_definitions.id"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    source_feedback_id: Mapped[int | None] = mapped_column(ForeignKey("ai_user_feedback.id"), unique=True)
    input_json: Mapped[dict] = mapped_column(JSON)
    assertions_json: Mapped[dict] = mapped_column(JSON)
    replay_output_json: Mapped[dict | None] = mapped_column(JSON)
    content_hash: Mapped[str] = mapped_column(String(64))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AISkillTestRun(Base):
    __tablename__ = "ai_skill_test_runs"
    __table_args__ = (
        CheckConstraint("mode IN ('deterministic','mock_model','real_model','replay','human_review')", name="ck_ai_skill_test_mode"),
        CheckConstraint("status IN ('running','passed','failed','pending_review')", name="ck_ai_skill_test_status"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("ai_skill_versions.id"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    mode: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(30))
    content_hash: Mapped[str] = mapped_column(String(64))
    dependency_hash: Mapped[str] = mapped_column(String(64))
    case_snapshot_json: Mapped[list] = mapped_column(JSON)
    metrics_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AISkillTestResult(Base):
    __tablename__ = "ai_skill_test_results"
    __table_args__ = (UniqueConstraint("run_id", "case_id", name="uq_ai_skill_test_result"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("ai_skill_test_runs.id"), index=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("ai_skill_test_cases.id"))
    passed: Mapped[bool | None] = mapped_column(Boolean)
    assertions_json: Mapped[dict] = mapped_column(JSON)
    output_json: Mapped[dict | None] = mapped_column(JSON)
    error_code: Mapped[str | None] = mapped_column(String(100))
