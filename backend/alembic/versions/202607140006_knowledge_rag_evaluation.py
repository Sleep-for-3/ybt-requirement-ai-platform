"""knowledge rag evaluation

Revision ID: 202607140006
Revises: 202607140005

Table definitions are frozen from git history instead of being imported from the
current ORM (see ``app/schema_freeze``).
"""

import sqlalchemy as sa
from alembic import op

from app.schema_freeze import create_frozen_tables, drop_frozen_tables


revision = "202607140006"
down_revision = "202607140005"
branch_labels = None
depends_on = None

FROZEN_REVISION = revision

KNOWLEDGE_DOCUMENT_COLUMN_NAMES = (
    "knowledge_type",
    "knowledge_scope",
    "institution_name",
    "document_status",
    "confidentiality_level",
    "file_hash",
    "current_version_no",
    "parse_status",
    "parse_summary_json",
    "warnings_json",
    "error_message",
    "created_by",
    "updated_at",
)

DATABASE_NAME_TABLES = ("catalog_tables", "catalog_columns", "source_tables", "mart_tables")

CANDIDATE_COLUMN_NAMES = (
    "retrieval_log_id",
    "knowledge_unit_ids_json",
    "citation_summary_json",
    "recommendation_basis",
)

PROMPT_LABELS = {
    "scenario_business_mapping": "场景业务口径",
    "scenario_technical_lineage": "场景技术溯源",
    "source_to_mart_mapping": "业务系统到监管集市",
    "mart_to_ybt_mapping": "监管集市到一表通",
    "source_recommendation_explanation": "来源字段推荐解释",
    "regulatory_field_explanation": "监管字段解释",
}


def _columns(table: str) -> set[str]:
    return {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}


def _add(table: str, column: sa.Column) -> None:
    if column.name not in _columns(table):
        op.add_column(table, column)


def _add_with_batch(table: str, column: sa.Column) -> None:
    if column.name not in _columns(table):
        with op.batch_alter_table(table) as batch:
            batch.add_column(column)


def _drop_indexes_for_columns(table: str, columns) -> None:
    target = set(columns)
    for index in sa.inspect(op.get_bind()).get_indexes(table):
        if target.intersection(index.get("column_names") or []):
            op.drop_index(index["name"], table_name=table)


def _knowledge_document_columns() -> dict[str, sa.Column]:
    return {
        "knowledge_type": sa.Column("knowledge_type", sa.String(50), server_default="manual_note"),
        "knowledge_scope": sa.Column("knowledge_scope", sa.String(50), server_default="project"),
        "institution_name": sa.Column("institution_name", sa.String(255)),
        "document_status": sa.Column("document_status", sa.String(50), server_default="pending"),
        "confidentiality_level": sa.Column("confidentiality_level", sa.String(50), server_default="internal"),
        "file_hash": sa.Column("file_hash", sa.String(64)),
        "current_version_no": sa.Column("current_version_no", sa.Integer, server_default="1"),
        "parse_status": sa.Column("parse_status", sa.String(50), server_default="pending"),
        "parse_summary_json": sa.Column("parse_summary_json", sa.JSON, server_default="{}"),
        "warnings_json": sa.Column("warnings_json", sa.JSON, server_default="[]"),
        "error_message": sa.Column("error_message", sa.Text),
        "created_by": sa.Column("created_by", sa.String(100)),
        "updated_at": sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    }


def upgrade() -> None:
    bind = op.get_bind()
    create_frozen_tables(FROZEN_REVISION, bind=bind)

    for column in _knowledge_document_columns().values():
        _add("knowledge_documents", column)

    for table in DATABASE_NAME_TABLES:
        _add(table, sa.Column("database_name", sa.String(255)))

    _add_with_batch(
        "candidate_source_recommendations",
        sa.Column(
            "retrieval_log_id",
            sa.Integer,
            sa.ForeignKey("retrieval_logs.id", name="fk_candidate_recommendation_retrieval_log"),
        ),
    )
    _add(
        "candidate_source_recommendations",
        sa.Column("knowledge_unit_ids_json", sa.JSON, server_default="[]"),
    )
    _add(
        "candidate_source_recommendations",
        sa.Column("citation_summary_json", sa.JSON, server_default="[]"),
    )
    _add(
        "candidate_source_recommendations",
        sa.Column("recommendation_basis", sa.String(100)),
    )

    prompt_table = sa.table(
        "prompt_template_versions",
        sa.column("prompt_key", sa.String),
        sa.column("version_no", sa.Integer),
        sa.column("system_prompt", sa.Text),
        sa.column("user_prompt_template", sa.Text),
        sa.column("output_schema_json", sa.JSON),
        sa.column("enabled", sa.Boolean),
    )
    op.bulk_insert(
        prompt_table,
        [
            {
                "prompt_key": key,
                "version_no": 1,
                "system_prompt": f"你正在生成{label}。仅依据所给证据生成可验证草稿，不得虚构来源；证据不足必须标记待确认。",
                "user_prompt_template": "目标：{target}\n证据：{evidence}",
                "output_schema_json": {},
                "enabled": True,
            }
            for key, label in PROMPT_LABELS.items()
        ],
    )


def downgrade() -> None:
    bind = op.get_bind()

    _drop_indexes_for_columns("candidate_source_recommendations", CANDIDATE_COLUMN_NAMES)
    existing = _columns("candidate_source_recommendations")
    with op.batch_alter_table("candidate_source_recommendations") as batch:
        for column in reversed(CANDIDATE_COLUMN_NAMES):
            if column in existing:
                batch.drop_column(column)

    for table in DATABASE_NAME_TABLES:
        _drop_indexes_for_columns(table, ["database_name"])
        if "database_name" in _columns(table):
            with op.batch_alter_table(table) as batch:
                batch.drop_column("database_name")

    _drop_indexes_for_columns("knowledge_documents", KNOWLEDGE_DOCUMENT_COLUMN_NAMES)
    existing_documents = _columns("knowledge_documents")
    with op.batch_alter_table("knowledge_documents") as batch:
        for column in reversed(KNOWLEDGE_DOCUMENT_COLUMN_NAMES):
            if column in existing_documents:
                batch.drop_column(column)

    drop_frozen_tables(FROZEN_REVISION, bind=bind)
