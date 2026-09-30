"""Add scoped Skill definitions, immutable-version identities and event history.

Self-contained historical DDL: never import the evolving ORM here.
"""
from alembic import op
import sqlalchemy as sa

revision = "202609270042"
down_revision = "202609200041"
branch_labels = None
depends_on = None

SCOPE_CHECK = """(scope_type = 'platform' AND institution_id IS NULL AND project_id IS NULL AND invocation_key IS NULL)
OR (scope_type = 'institution' AND institution_id IS NOT NULL AND project_id IS NULL AND invocation_key IS NULL)
OR (scope_type = 'project' AND institution_id IS NOT NULL AND project_id IS NOT NULL AND invocation_key IS NULL)
OR (scope_type = 'task' AND institution_id IS NOT NULL AND project_id IS NOT NULL AND invocation_key IS NOT NULL)"""


def _scope_columns():
    return [
        sa.Column("scope_type", sa.String(20), nullable=False),
        sa.Column("scope_key", sa.String(180), nullable=False),
        sa.Column("institution_id", sa.Integer(), sa.ForeignKey("institutions.id")),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id")),
        sa.Column("invocation_key", sa.String(100)),
    ]


def upgrade():
    op.create_table("ai_skill_definitions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("skill_key", sa.String(91), nullable=False, unique=True),
        sa.Column("task_key", sa.String(100), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("next_version_no", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("next_version_no > 0", name="ck_ai_skill_next_version"))
    op.create_table("ai_skill_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("definition_id", sa.Integer(), sa.ForeignKey("ai_skill_definitions.id"), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("lock_version", sa.Integer(), nullable=False),
        sa.Column("test_epoch", sa.Integer(), nullable=False),
        sa.Column("content_json", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("release_dependency_hash", sa.String(64)),
        sa.Column("restored_from_version_id", sa.Integer(), sa.ForeignKey("ai_skill_versions.id")),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("edited_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("approved_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        *_scope_columns(),
        sa.UniqueConstraint("definition_id", "version_no", name="uq_ai_skill_version_no"),
        sa.UniqueConstraint("id", "definition_id", name="uq_ai_skill_version_definition"),
        sa.CheckConstraint(SCOPE_CHECK, name="ck_ai_skill_version_scope"),
        sa.CheckConstraint("version_no > 0 AND lock_version > 0", name="ck_ai_skill_version_positive"),
        sa.CheckConstraint("status IN ('draft','testing','pending_approval','published','deprecated','archived')", name="ck_ai_skill_version_status"))
    op.create_table("ai_skill_scope_bindings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("definition_id", sa.Integer(), sa.ForeignKey("ai_skill_definitions.id"), nullable=False),
        sa.Column("version_id", sa.Integer(), nullable=False),
        sa.Column("inherited_from_scope", sa.String(180)),
        sa.Column("lock_version", sa.Integer(), nullable=False),
        sa.Column("updated_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        *_scope_columns(),
        sa.UniqueConstraint("definition_id", "scope_key", name="uq_ai_skill_binding_scope"),
        sa.ForeignKeyConstraint(["version_id", "definition_id"], ["ai_skill_versions.id", "ai_skill_versions.definition_id"], name="fk_ai_skill_binding_version"),
        sa.CheckConstraint(SCOPE_CHECK, name="ck_ai_skill_binding_scope"),
        sa.CheckConstraint("lock_version > 0", name="ck_ai_skill_binding_positive"))
    op.create_table("ai_skill_release_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("definition_id", sa.Integer(), sa.ForeignKey("ai_skill_definitions.id"), nullable=False),
        sa.Column("version_id", sa.Integer()),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("scope_key", sa.String(180), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("detail_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["version_id", "definition_id"], ["ai_skill_versions.id", "ai_skill_versions.definition_id"], name="fk_ai_skill_event_version"))
    for table in ("ai_skill_versions", "ai_skill_scope_bindings", "ai_skill_release_events"):
        op.create_index(f"ix_{table}_definition_id", table, ["definition_id"])
    for table in ("ai_skill_versions", "ai_skill_scope_bindings"):
        for column in ("institution_id", "project_id"):
            op.create_index(f"ix_{table}_{column}", table, [column])


def downgrade():
    for table in ("ai_skill_release_events", "ai_skill_scope_bindings", "ai_skill_versions", "ai_skill_definitions"):
        op.drop_table(table)
