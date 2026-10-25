"""requirement_runtime_fact_packs

P2-A：接收授权环境产出的脱敏运行事实包。事实包决定"这条结论是静态推断还是运行
验证过"，因此必须落库并冻结导入当时的校验结论（``validation_json`` /
``issues_json`` / ``level`` / ``status``）。

- 内容身份 ``pack_sha256`` 与 ``requirement_id`` 唯一：同一份事实只存一行。
- ``payload_json`` 保留原始事实包，便于复核"当时依据是什么"。
- 历史事实包不随代码升级重算，避免审核人当时看到的结论被悄悄改写。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "202611010006"
down_revision = "202611010005"
branch_labels = None
depends_on = None


def _table_exists(table: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return table in set(inspector.get_table_names())


def upgrade() -> None:
    if _table_exists("requirement_runtime_fact_packs"):
        return
    op.create_table(
        "requirement_runtime_fact_packs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("requirement_id", sa.Integer(), sa.ForeignKey("requirements.id"), nullable=False),
        sa.Column("pack_sha256", sa.String(length=64), nullable=False),
        sa.Column("pack_version", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("level", sa.String(length=32), nullable=False, server_default="static_inference"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="unverified"),
        sa.Column("execution_batch", sa.String(length=128), nullable=True),
        sa.Column("business_date", sa.String(length=10), nullable=True),
        sa.Column("payload_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("validation_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("issues_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("requirement_id", "pack_sha256", name="uq_requirement_runtime_fact_pack"),
    )
    op.create_index("ix_requirement_runtime_fact_packs_project_id", "requirement_runtime_fact_packs", ["project_id"])
    op.create_index("ix_requirement_runtime_fact_packs_requirement_id", "requirement_runtime_fact_packs", ["requirement_id"])
    op.create_index("ix_requirement_runtime_fact_packs_pack_sha256", "requirement_runtime_fact_packs", ["pack_sha256"])
    op.create_index("ix_requirement_runtime_fact_packs_level", "requirement_runtime_fact_packs", ["level"])
    op.create_index(
        "ix_requirement_runtime_fact_scope",
        "requirement_runtime_fact_packs",
        ["project_id", "requirement_id", "created_at"],
    )


def downgrade() -> None:
    if _table_exists("requirement_runtime_fact_packs"):
        op.drop_table("requirement_runtime_fact_packs")
