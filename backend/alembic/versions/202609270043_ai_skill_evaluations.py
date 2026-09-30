"""Skill test snapshots and nullable links from legacy runtime records."""
from alembic import op
import sqlalchemy as sa

revision = "202609270043"
down_revision = "202609270042"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("ai_skill_test_cases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("definition_id", sa.Integer(), sa.ForeignKey("ai_skill_definitions.id"), nullable=False),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("source_feedback_id", sa.Integer(), sa.ForeignKey("ai_user_feedback.id"), unique=True),
        sa.Column("input_json", sa.JSON(), nullable=False),
        sa.Column("assertions_json", sa.JSON(), nullable=False),
        sa.Column("replay_output_json", sa.JSON()),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_table("ai_skill_test_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("version_id", sa.Integer(), sa.ForeignKey("ai_skill_versions.id"), nullable=False),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("mode", sa.String(30), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("dependency_hash", sa.String(64), nullable=False),
        sa.Column("case_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("metrics_json", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("mode IN ('deterministic','mock_model','real_model','replay','human_review')", name="ck_ai_skill_test_mode"),
        sa.CheckConstraint("status IN ('running','passed','failed','pending_review')", name="ck_ai_skill_test_status"))
    op.create_table("ai_skill_test_results",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("ai_skill_test_runs.id"), nullable=False),
        sa.Column("case_id", sa.Integer(), sa.ForeignKey("ai_skill_test_cases.id"), nullable=False),
        sa.Column("passed", sa.Boolean()),
        sa.Column("assertions_json", sa.JSON(), nullable=False),
        sa.Column("output_json", sa.JSON()),
        sa.Column("error_code", sa.String(100)),
        sa.UniqueConstraint("run_id", "case_id", name="uq_ai_skill_test_result"))
    for table, columns in (("ai_skill_test_cases", ["definition_id", "project_id"]),
                           ("ai_skill_test_runs", ["version_id", "project_id"]),
                           ("ai_skill_test_results", ["run_id"])):
        for column in columns:
            op.create_index(f"ix_{table}_{column}", table, [column])
    with op.batch_alter_table("prompt_template_versions") as batch:
        batch.add_column(sa.Column("skill_version_id", sa.Integer(), nullable=True))
        batch.create_foreign_key("fk_prompt_skill_version", "ai_skill_versions", ["skill_version_id"], ["id"])
        batch.create_unique_constraint("uq_prompt_skill_version", ["skill_version_id"])
    with op.batch_alter_table("model_call_logs") as batch:
        batch.add_column(sa.Column("skill_version_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("input_contract_version", sa.String(30), nullable=True))
        batch.create_foreign_key("fk_model_call_skill_version", "ai_skill_versions", ["skill_version_id"], ["id"])
        batch.create_index("ix_model_call_logs_skill_version_id", ["skill_version_id"])


def downgrade():
    with op.batch_alter_table("model_call_logs") as batch:
        batch.drop_index("ix_model_call_logs_skill_version_id")
        batch.drop_constraint("fk_model_call_skill_version", type_="foreignkey")
        batch.drop_column("input_contract_version")
        batch.drop_column("skill_version_id")
    with op.batch_alter_table("prompt_template_versions") as batch:
        batch.drop_constraint("uq_prompt_skill_version", type_="unique")
        batch.drop_constraint("fk_prompt_skill_version", type_="foreignkey")
        batch.drop_column("skill_version_id")
    for table in ("ai_skill_test_results", "ai_skill_test_runs", "ai_skill_test_cases"):
        op.drop_table(table)
