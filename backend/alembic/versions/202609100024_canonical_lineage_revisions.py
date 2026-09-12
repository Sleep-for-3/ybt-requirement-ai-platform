"""Add immutable, project-level lineage revision snapshots.

Revision ID: 202609100024
Revises: 202609100023

The existing script/version and LineageNode/LineageEdge tables remain the
technical facts.  These tables only record the immutable membership and
serialized evidence used to reconstruct a project graph at a point in time.
"""

from alembic import op
import sqlalchemy as sa


revision = "202609100024"
down_revision = "202609100023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("lineage_revisions"):
        op.create_table(
            "lineage_revisions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("institution_id", sa.Integer(), sa.ForeignKey("institutions.id"), nullable=True),
            sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
            sa.Column("revision_no", sa.Integer(), nullable=False),
            sa.Column("parent_revision_id", sa.Integer(), sa.ForeignKey("lineage_revisions.id"), nullable=True),
            sa.Column("trigger_type", sa.String(length=50), nullable=False, server_default="manual"),
            sa.Column("source_commit_sha", sa.String(length=64), nullable=True),
            sa.Column("parser_version", sa.String(length=100), nullable=False, server_default="lineage-revision-v1"),
            sa.Column("graph_hash", sa.String(length=64), nullable=False),
            sa.Column("status", sa.String(length=50), nullable=False, server_default="draft"),
            sa.Column("warnings_json", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("source_manifest_json", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("node_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("edge_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("project_id", "revision_no", name="uq_lineage_revision_project_no"),
            sa.UniqueConstraint("project_id", "graph_hash", name="uq_lineage_revision_project_hash"),
        )
    if not inspector.has_table("lineage_revision_nodes"):
        op.create_table(
            "lineage_revision_nodes",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("revision_id", sa.Integer(), sa.ForeignKey("lineage_revisions.id", ondelete="CASCADE"), nullable=False),
            sa.Column("lineage_node_id", sa.Integer(), sa.ForeignKey("lineage_nodes.id"), nullable=False),
            sa.Column("node_key", sa.String(length=1500), nullable=False),
            sa.Column("snapshot_hash", sa.String(length=64), nullable=False),
            sa.Column("snapshot_json", sa.JSON(), nullable=False, server_default="{}"),
            sa.UniqueConstraint("revision_id", "lineage_node_id", name="uq_lineage_revision_node_member"),
            sa.UniqueConstraint("revision_id", "node_key", name="uq_lineage_revision_node_key"),
        )
    if not inspector.has_table("lineage_revision_edges"):
        op.create_table(
            "lineage_revision_edges",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("revision_id", sa.Integer(), sa.ForeignKey("lineage_revisions.id", ondelete="CASCADE"), nullable=False),
            sa.Column("lineage_edge_id", sa.Integer(), sa.ForeignKey("lineage_edges.id"), nullable=False),
            sa.Column("edge_key", sa.String(length=2000), nullable=False),
            sa.Column("snapshot_hash", sa.String(length=64), nullable=False),
            sa.Column("snapshot_json", sa.JSON(), nullable=False, server_default="{}"),
            sa.UniqueConstraint("revision_id", "lineage_edge_id", name="uq_lineage_revision_edge_member"),
            sa.UniqueConstraint("revision_id", "edge_key", name="uq_lineage_revision_edge_key"),
        )

    _create_index("ix_lineage_revisions_project_status", "lineage_revisions", ["project_id", "status", "revision_no"])
    _create_index("ix_lineage_revisions_project_id", "lineage_revisions", ["project_id"])
    _create_index("ix_lineage_revisions_parent_revision_id", "lineage_revisions", ["parent_revision_id"])
    _create_index("ix_lineage_revisions_source_commit_sha", "lineage_revisions", ["source_commit_sha"])
    _create_index("ix_lineage_revisions_graph_hash", "lineage_revisions", ["graph_hash"])
    _create_index("ix_lineage_revision_nodes_revision", "lineage_revision_nodes", ["revision_id", "id"])
    _create_index("ix_lineage_revision_nodes_lineage_node_id", "lineage_revision_nodes", ["lineage_node_id"])
    _create_index("ix_lineage_revision_nodes_snapshot_hash", "lineage_revision_nodes", ["snapshot_hash"])
    _create_index("ix_lineage_revision_edges_revision", "lineage_revision_edges", ["revision_id", "id"])
    _create_index("ix_lineage_revision_edges_lineage_edge_id", "lineage_revision_edges", ["lineage_edge_id"])
    _create_index("ix_lineage_revision_edges_snapshot_hash", "lineage_revision_edges", ["snapshot_hash"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("lineage_revision_edges"):
        op.drop_table("lineage_revision_edges")
    if inspector.has_table("lineage_revision_nodes"):
        op.drop_table("lineage_revision_nodes")
    if inspector.has_table("lineage_revisions"):
        op.drop_table("lineage_revisions")


def _create_index(name: str, table: str, columns: list[str]) -> None:
    inspector = sa.inspect(op.get_bind())
    existing = {item["name"] for item in inspector.get_indexes(table)}
    if name not in existing:
        op.create_index(name, table, columns)
