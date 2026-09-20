"""Add backward-compatible AI execution, evidence, and feedback lineage fields."""

from alembic import op
import sqlalchemy as sa


revision = "202609200040"
down_revision = "202609180039"
branch_labels = None
depends_on = None


def _column_names(table: str) -> set[str]:
    return {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}


def _index_names(table: str) -> set[str]:
    return {item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table)}


def _foreign_key_names(table: str) -> set[str]:
    return {
        item.get("name")
        for item in sa.inspect(op.get_bind()).get_foreign_keys(table)
        if item.get("name")
    }


def _add_column(table: str, column: sa.Column) -> None:
    if column.name not in _column_names(table):
        op.add_column(table, column)


def _create_index(table: str, name: str, columns: list[str], *, unique: bool = False) -> None:
    if name not in _index_names(table):
        op.create_index(name, table, columns, unique=unique)


def _create_foreign_key(
    table: str,
    name: str,
    referent_table: str,
    local_cols: list[str],
    remote_cols: list[str],
) -> None:
    if name in _foreign_key_names(table):
        return
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table(table) as batch:
            batch.create_foreign_key(name, referent_table, local_cols, remote_cols)
        return
    op.create_foreign_key(name, table, referent_table, local_cols, remote_cols)


def _drop_index(table: str, name: str) -> None:
    if name in _index_names(table):
        op.drop_index(name, table_name=table)


def _drop_foreign_key(table: str, name: str) -> None:
    if name not in _foreign_key_names(table):
        return
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table(table) as batch:
            batch.drop_constraint(name, type_="foreignkey")
        return
    op.drop_constraint(name, table, type_="foreignkey")


def _drop_column(table: str, name: str) -> None:
    if name not in _column_names(table):
        return
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table(table) as batch:
            batch.drop_column(name)
        return
    op.drop_column(table, name)


def upgrade():
    _add_column(
        "rag_evaluation_cases",
        sa.Column("institution_id", sa.Integer(), nullable=True),
    )
    _add_column(
        "rag_evaluation_cases",
        sa.Column("created_by", sa.String(length=100), nullable=True),
    )
    _create_foreign_key(
        "rag_evaluation_cases",
        "fk_rag_evaluation_cases_institution_id",
        "institutions",
        ["institution_id"],
        ["id"],
    )
    _create_index(
        "rag_evaluation_cases",
        "ix_rag_evaluation_cases_institution_id",
        ["institution_id"],
    )

    _add_column(
        "rag_evaluation_runs",
        sa.Column("institution_id", sa.Integer(), nullable=True),
    )
    _create_foreign_key(
        "rag_evaluation_runs",
        "fk_rag_evaluation_runs_institution_id",
        "institutions",
        ["institution_id"],
        ["id"],
    )
    _create_index(
        "rag_evaluation_runs",
        "ix_rag_evaluation_runs_institution_id",
        ["institution_id"],
    )

    _add_column(
        "rag_evaluation_results",
        sa.Column("execution_metadata_json", sa.JSON(), nullable=True),
    )

    _add_column(
        "ai_user_feedback",
        sa.Column("institution_id", sa.Integer(), nullable=True),
    )
    _add_column(
        "ai_user_feedback",
        sa.Column("model_call_log_id", sa.Integer(), nullable=True),
    )
    _add_column(
        "ai_user_feedback",
        sa.Column("output_hash", sa.String(length=64), nullable=True),
    )
    _add_column(
        "ai_user_feedback",
        sa.Column("execution_kind", sa.String(length=30), nullable=True),
    )
    _add_column(
        "ai_user_feedback",
        sa.Column("execution_metadata_json", sa.JSON(), nullable=True),
    )
    _create_foreign_key(
        "ai_user_feedback",
        "fk_ai_user_feedback_institution_id",
        "institutions",
        ["institution_id"],
        ["id"],
    )
    _create_foreign_key(
        "ai_user_feedback",
        "fk_ai_user_feedback_model_call_log_id",
        "model_call_logs",
        ["model_call_log_id"],
        ["id"],
    )
    _create_index(
        "ai_user_feedback",
        "ix_ai_user_feedback_institution_id",
        ["institution_id"],
    )
    _create_index(
        "ai_user_feedback",
        "ix_ai_user_feedback_model_call_log_id",
        ["model_call_log_id"],
    )
    _create_index(
        "ai_user_feedback",
        "ix_ai_user_feedback_output_hash",
        ["output_hash"],
    )
    _create_index(
        "ai_user_feedback",
        "ix_ai_user_feedback_execution_kind",
        ["execution_kind"],
    )

    model_call_columns = (
        sa.Column("skill_key", sa.String(length=100), nullable=True),
        sa.Column("skill_version", sa.String(length=50), nullable=True),
        sa.Column("execution_kind", sa.String(length=30), nullable=True),
        sa.Column("context_hash", sa.String(length=64), nullable=True),
        sa.Column("context_complete", sa.Boolean(), nullable=True),
        sa.Column("context_budget_json", sa.JSON(), nullable=True),
        sa.Column("output_hash", sa.String(length=64), nullable=True),
        sa.Column("citations_json", sa.JSON(), nullable=True),
        sa.Column("rejected_claims_json", sa.JSON(), nullable=True),
        sa.Column("execution_metadata_json", sa.JSON(), nullable=True),
    )
    for column in model_call_columns:
        _add_column("model_call_logs", column)
    for name, columns in (
        ("ix_model_call_logs_skill_key", ["skill_key"]),
        ("ix_model_call_logs_skill_version", ["skill_version"]),
        ("ix_model_call_logs_execution_kind", ["execution_kind"]),
        ("ix_model_call_logs_context_hash", ["context_hash"]),
        ("ix_model_call_logs_output_hash", ["output_hash"]),
    ):
        _create_index("model_call_logs", name, columns)


def downgrade():
    for name in (
        "ix_model_call_logs_output_hash",
        "ix_model_call_logs_context_hash",
        "ix_model_call_logs_execution_kind",
        "ix_model_call_logs_skill_version",
        "ix_model_call_logs_skill_key",
    ):
        _drop_index("model_call_logs", name)
    for column in (
        "execution_metadata_json",
        "rejected_claims_json",
        "citations_json",
        "output_hash",
        "context_budget_json",
        "context_complete",
        "context_hash",
        "execution_kind",
        "skill_version",
        "skill_key",
    ):
        _drop_column("model_call_logs", column)

    for name in (
        "ix_ai_user_feedback_execution_kind",
        "ix_ai_user_feedback_output_hash",
        "ix_ai_user_feedback_model_call_log_id",
        "ix_ai_user_feedback_institution_id",
    ):
        _drop_index("ai_user_feedback", name)
    _drop_foreign_key("ai_user_feedback", "fk_ai_user_feedback_model_call_log_id")
    _drop_foreign_key("ai_user_feedback", "fk_ai_user_feedback_institution_id")
    for column in (
        "execution_metadata_json",
        "execution_kind",
        "output_hash",
        "model_call_log_id",
        "institution_id",
    ):
        _drop_column("ai_user_feedback", column)

    _drop_column("rag_evaluation_results", "execution_metadata_json")

    _drop_index("rag_evaluation_runs", "ix_rag_evaluation_runs_institution_id")
    _drop_foreign_key("rag_evaluation_runs", "fk_rag_evaluation_runs_institution_id")
    _drop_column("rag_evaluation_runs", "institution_id")

    _drop_index("rag_evaluation_cases", "ix_rag_evaluation_cases_institution_id")
    _drop_foreign_key("rag_evaluation_cases", "fk_rag_evaluation_cases_institution_id")
    _drop_column("rag_evaluation_cases", "created_by")
    _drop_column("rag_evaluation_cases", "institution_id")
