"""Add structured AI feedback regression fields to evaluation cases."""

from alembic import op
import sqlalchemy as sa


revision = "202609200041"
down_revision = "202609200040"
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
        sa.Column("source_feedback_id", sa.Integer(), nullable=True),
    )
    _add_column(
        "rag_evaluation_cases",
        sa.Column("model_call_log_id", sa.Integer(), nullable=True),
    )
    _add_column(
        "rag_evaluation_cases",
        sa.Column("target_type", sa.String(length=50), nullable=True),
    )
    _add_column(
        "rag_evaluation_cases",
        sa.Column("target_id", sa.Integer(), nullable=True),
    )
    _add_column(
        "rag_evaluation_cases",
        sa.Column("execution_kind", sa.String(length=30), nullable=True),
    )
    _add_column(
        "rag_evaluation_cases",
        sa.Column("output_hash", sa.String(length=64), nullable=True),
    )
    _add_column(
        "rag_evaluation_cases",
        sa.Column("input_context_json", sa.JSON(), nullable=True),
    )
    _add_column(
        "rag_evaluation_cases",
        sa.Column("expected_output_json", sa.JSON(), nullable=True),
    )
    _add_column(
        "rag_evaluation_cases",
        sa.Column("assertions_json", sa.JSON(), nullable=True),
    )
    _create_foreign_key(
        "rag_evaluation_cases",
        "fk_rag_evaluation_cases_source_feedback_id",
        "ai_user_feedback",
        ["source_feedback_id"],
        ["id"],
    )
    _create_foreign_key(
        "rag_evaluation_cases",
        "fk_rag_evaluation_cases_model_call_log_id",
        "model_call_logs",
        ["model_call_log_id"],
        ["id"],
    )
    _create_index(
        "rag_evaluation_cases",
        "uq_rag_evaluation_cases_source_feedback_id",
        ["source_feedback_id"],
        unique=True,
    )
    _create_index(
        "rag_evaluation_cases",
        "ix_rag_evaluation_cases_model_call_log_id",
        ["model_call_log_id"],
    )
    _create_index(
        "rag_evaluation_cases",
        "ix_rag_evaluation_cases_output_hash",
        ["output_hash"],
    )


def downgrade():
    _drop_index("rag_evaluation_cases", "ix_rag_evaluation_cases_output_hash")
    _drop_index("rag_evaluation_cases", "ix_rag_evaluation_cases_model_call_log_id")
    _drop_index("rag_evaluation_cases", "uq_rag_evaluation_cases_source_feedback_id")
    _drop_foreign_key("rag_evaluation_cases", "fk_rag_evaluation_cases_model_call_log_id")
    _drop_foreign_key("rag_evaluation_cases", "fk_rag_evaluation_cases_source_feedback_id")
    for column in (
        "assertions_json",
        "expected_output_json",
        "input_context_json",
        "output_hash",
        "execution_kind",
        "target_id",
        "target_type",
        "model_call_log_id",
        "source_feedback_id",
    ):
        _drop_column("rag_evaluation_cases", column)
