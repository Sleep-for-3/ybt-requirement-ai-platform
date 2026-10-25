"""external_sync_cursors / external_sync_events

P2-B：外部系统（元数据平台 / 调度平台 / 脚本版本库）的增量事件只允许产生
"待复核"状态，不能直接改写需求或正式交付。本迁移建两张表：

- ``external_sync_cursors``：每项目每来源已处理到的游标，单调前进。
- ``external_sync_events``：待复核事件，``(project, source, object_kind,
  object_key, source_version)`` 唯一 → 重放不会新增行。

不修改任何既有表：同步是独立入口，旧需求与历史交付不受影响。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "202611010007"
down_revision = "202611010006"
branch_labels = None
depends_on = None


def _table_exists(table: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return table in set(inspector.get_table_names())


def upgrade() -> None:
    if not _table_exists("external_sync_cursors"):
        op.create_table(
            "external_sync_cursors",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
            sa.Column("source", sa.String(length=80), nullable=False),
            sa.Column("cursor", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_observed_at", sa.String(length=40), nullable=True),
            sa.Column("updated_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("project_id", "source", name="uq_external_sync_cursor"),
        )
        op.create_index("ix_external_sync_cursors_project_id", "external_sync_cursors", ["project_id"])

    if not _table_exists("external_sync_events"):
        op.create_table(
            "external_sync_events",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
            sa.Column("source", sa.String(length=80), nullable=False),
            sa.Column("object_kind", sa.String(length=80), nullable=False),
            sa.Column("object_key", sa.String(length=255), nullable=False),
            sa.Column("source_version", sa.Integer(), nullable=False),
            sa.Column("cursor", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("decision", sa.String(length=40), nullable=False),
            sa.Column("payload_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("payload_hash", sa.String(length=64), nullable=False, server_default=""),
            sa.Column("deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("permissions_changed", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("observed_at", sa.String(length=40), nullable=True),
            sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint(
                "project_id", "source", "object_kind", "object_key", "source_version",
                name="uq_external_sync_event",
            ),
        )
        op.create_index("ix_external_sync_events_project_id", "external_sync_events", ["project_id"])
        op.create_index("ix_external_sync_events_source", "external_sync_events", ["source"])
        op.create_index("ix_external_sync_events_decision", "external_sync_events", ["decision"])
        op.create_index(
            "ix_external_sync_event_pending", "external_sync_events", ["project_id", "decision"]
        )


def downgrade() -> None:
    if _table_exists("external_sync_events"):
        op.drop_table("external_sync_events")
    if _table_exists("external_sync_cursors"):
        op.drop_table("external_sync_cursors")
