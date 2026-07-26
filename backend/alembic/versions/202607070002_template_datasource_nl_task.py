"""template datasource nl task

Revision ID: 202607070002
Revises: 202607070001
Create Date: 2026-07-07
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

from app.models import DataSource, NaturalLanguageTask, SqlExecutionLog, TemplateDocument, TemplateParseResult

revision = "202607070002"
down_revision = "202607070001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    for table in [
        TemplateDocument.__table__,
        TemplateParseResult.__table__,
        DataSource.__table__,
        SqlExecutionLog.__table__,
        NaturalLanguageTask.__table__,
    ]:
        table.create(bind=bind, checkfirst=True)

    inspector = inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("field_mapping_drafts")}
    if "template_reference_summary" not in columns:
        op.add_column("field_mapping_drafts", sa.Column("template_reference_summary", sa.Text(), nullable=True))
    if "db_query_summary" not in columns:
        op.add_column("field_mapping_drafts", sa.Column("db_query_summary", sa.Text(), nullable=True))
    if "data_quality_notes" not in columns:
        op.add_column("field_mapping_drafts", sa.Column("data_quality_notes", sa.Text(), nullable=True))
    if "evidence_completeness" not in columns:
        op.add_column("field_mapping_drafts", sa.Column("evidence_completeness", sa.String(length=50), nullable=True))


def downgrade() -> None:
    for column in ["evidence_completeness", "data_quality_notes", "db_query_summary", "template_reference_summary"]:
        try:
            op.drop_column("field_mapping_drafts", column)
        except Exception:
            pass
    for table_name in [
        "sql_execution_logs",
        "natural_language_tasks",
        "template_parse_results",
        "template_documents",
        "data_sources",
    ]:
        try:
            op.drop_table(table_name)
        except Exception:
            pass
