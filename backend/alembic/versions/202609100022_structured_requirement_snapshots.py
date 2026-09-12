"""Add immutable structured requirement working snapshots.

Revision ID: 202609100022
Revises: 202608290021
"""

from alembic import op
import sqlalchemy as sa


revision = "202609100022"
down_revision = "202608290021"
branch_labels = None
depends_on = None

TABLE_NAME = "structured_requirement_snapshots"
STATE_TABLE = "structured_requirement_snapshot_migration_state"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_preexisted = inspector.has_table(TABLE_NAME)

    # Installations that were created before revision 202607070001 was frozen
    # got this table from the old ``Base.metadata.create_all`` root, so the table
    # can already exist when this revision runs.  Persist a tiny ownership
    # marker so downgrade never drops a table that this revision did not create.
    if not inspector.has_table(STATE_TABLE):
        op.create_table(
            STATE_TABLE,
            sa.Column("revision", sa.String(length=50), primary_key=True),
            sa.Column("table_created_by_revision", sa.Boolean(), nullable=False),
        )
    state = sa.table(
        STATE_TABLE,
        sa.column("revision", sa.String(length=50)),
        sa.column("table_created_by_revision", sa.Boolean()),
    )
    marker = bind.execute(sa.select(state.c.table_created_by_revision).where(state.c.revision == revision)).scalar()
    if marker is None:
        bind.execute(state.insert().values(
            revision=revision,
            table_created_by_revision=not table_preexisted,
        ))
    if table_preexisted:
        return

    op.create_table(
        TABLE_NAME,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("institution_id", sa.Integer(), sa.ForeignKey("institutions.id")),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("target_table_id", sa.Integer(), sa.ForeignKey("target_tables.id"), nullable=False),
        sa.Column("scenario_id", sa.Integer(), sa.ForeignKey("product_scenarios.id")),
        sa.Column("snapshot_no", sa.Integer(), nullable=False),
        sa.Column("requirement_version", sa.String(length=100), nullable=False),
        sa.Column("schema_version", sa.String(length=50), nullable=False, server_default="structured-requirement-v1"),
        sa.Column("model_version", sa.String(length=100), nullable=False, server_default="requirement-workspace-v2"),
        sa.Column("catalog_revision", sa.String(length=100)),
        sa.Column("lineage_revision", sa.String(length=100)),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="draft"),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("content_snapshot_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("change_note", sa.Text()),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "project_id",
            "target_table_id",
            "scenario_id",
            "snapshot_no",
            name="uq_structured_requirement_snapshot_scope_version",
        ),
        sa.UniqueConstraint(
            "project_id",
            "target_table_id",
            "scenario_id",
            "content_hash",
            name="uq_structured_requirement_snapshot_scope_hash",
        ),
    )
    op.create_index(
        "ix_structured_requirement_snapshots_project_scope",
        TABLE_NAME,
        ["project_id", "target_table_id", "scenario_id", "snapshot_no"],
    )
    op.create_index(
        "ix_structured_requirement_snapshots_project_status",
        TABLE_NAME,
        ["project_id", "status", "created_at"],
    )
    for name, column in (
        ("ix_structured_requirement_snapshots_institution_id", "institution_id"),
        ("ix_structured_requirement_snapshots_project_id", "project_id"),
        ("ix_structured_requirement_snapshots_target_table_id", "target_table_id"),
        ("ix_structured_requirement_snapshots_scenario_id", "scenario_id"),
        ("ix_structured_requirement_snapshots_requirement_version", "requirement_version"),
        ("ix_structured_requirement_snapshots_catalog_revision", "catalog_revision"),
        ("ix_structured_requirement_snapshots_lineage_revision", "lineage_revision"),
        ("ix_structured_requirement_snapshots_status", "status"),
        ("ix_structured_requirement_snapshots_content_hash", "content_hash"),
        ("ix_structured_requirement_snapshots_created_by", "created_by"),
    ):
        op.create_index(name, "structured_requirement_snapshots", [column])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    created_by_revision = False
    if inspector.has_table(STATE_TABLE):
        state = sa.table(
            STATE_TABLE,
            sa.column("revision", sa.String(length=50)),
            sa.column("table_created_by_revision", sa.Boolean()),
        )
        created_by_revision = bool(bind.execute(
            sa.select(state.c.table_created_by_revision).where(state.c.revision == revision)
        ).scalar())
    if not inspector.has_table(TABLE_NAME):
        if inspector.has_table(STATE_TABLE):
            op.drop_table(STATE_TABLE)
        return
    if not created_by_revision:
        # This revision observed a pre-existing table (most commonly created
        # by the legacy initial schema migration).  Preserve it on downgrade.
        if inspector.has_table(STATE_TABLE):
            op.drop_table(STATE_TABLE)
        return
    for name in (
        "ix_structured_requirement_snapshots_created_by",
        "ix_structured_requirement_snapshots_content_hash",
        "ix_structured_requirement_snapshots_status",
        "ix_structured_requirement_snapshots_lineage_revision",
        "ix_structured_requirement_snapshots_catalog_revision",
        "ix_structured_requirement_snapshots_requirement_version",
        "ix_structured_requirement_snapshots_scenario_id",
        "ix_structured_requirement_snapshots_target_table_id",
        "ix_structured_requirement_snapshots_project_id",
        "ix_structured_requirement_snapshots_institution_id",
        "ix_structured_requirement_snapshots_project_status",
        "ix_structured_requirement_snapshots_project_scope",
    ):
        op.drop_index(name, table_name=TABLE_NAME, if_exists=True)
    op.drop_table(TABLE_NAME)
    if inspector.has_table(STATE_TABLE):
        op.drop_table(STATE_TABLE)
