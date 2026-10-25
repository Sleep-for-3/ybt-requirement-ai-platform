"""target table meta (表级口径) and template version table meta

Revision ID: 202611010009
Revises: 202611010008
Create Date: 2026-10-25

一表通调研表的 `表级口径` sheet 里本来就有“主题 / 填报说明 / 报送数据域”，
导出文档的“数据主题名称 / 采集范围 / 一表通报送范围确认”三行此前只能写
“待业务补充”。这一版把表级信息落库，导出时直接引用，不再让模板里已有的
事实丢失在解析环节。
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "202611010009"
down_revision = "202611010008"
branch_labels = None
depends_on = None


def _column_exists(table: str, column: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(item["name"] == column for item in inspector.get_columns(table))


def _table_exists(table: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return table in inspector.get_table_names()


def upgrade() -> None:
    if _table_exists("target_tables"):
        for column, kind in (
            ("theme", sa.String(200)),
            ("filing_note", sa.Text()),
            ("reporting_domain_code", sa.String(64)),
            ("reporting_domain_name", sa.String(200)),
        ):
            if not _column_exists("target_tables", column):
                op.add_column("target_tables", sa.Column(column, kind, nullable=True))
    if _table_exists("template_versions") and not _column_exists(
        "template_versions", "table_meta_json"
    ):
        # JSON 列非空 + 默认值：ORM 侧是 Mapped[dict] default=dict，
        # SQLite 的 ADD COLUMN NOT NULL 需要非空默认值。
        op.add_column(
            "template_versions",
            sa.Column("table_meta_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        )


def downgrade() -> None:
    if _table_exists("template_versions") and _column_exists("template_versions", "table_meta_json"):
        op.drop_column("template_versions", "table_meta_json")
    if _table_exists("target_tables"):
        for column in ("reporting_domain_name", "reporting_domain_code", "filing_note", "theme"):
            if _column_exists("target_tables", column):
                op.drop_column("target_tables", column)
