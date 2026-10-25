"""embedding_records.vector_record_ids_json

长知识单元分片索引后，一条知识单元会对应多条向量记录（每个片段一条）。原来的
`vector_record_id` 只能存一个 id，无法审计"这条单元到底写了哪几条向量"。本迁移
新增 `vector_record_ids_json`（可空，默认空列表），并保留 `vector_record_id` 为
第一条记录的 id，保证旧读取路径不变。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "202611010005"
down_revision = "202611010004"
branch_labels = None
depends_on = None


def _column_exists(table: str, column: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return column in {item["name"] for item in inspector.get_columns(table)}


def upgrade() -> None:
    if not _column_exists("embedding_records", "vector_record_ids_json"):
        op.add_column(
            "embedding_records",
            sa.Column("vector_record_ids_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        )


def downgrade() -> None:
    if _column_exists("embedding_records", "vector_record_ids_json"):
        op.drop_column("embedding_records", "vector_record_ids_json")
