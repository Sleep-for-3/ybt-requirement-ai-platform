"""N04/N05: freeze UAT run inputs and bind signoffs to their evidence.

``uat_runs.manifest_json`` captures the run/input identity (release identity, requirement version and
hash, model profiles) once at creation, so the evidence package of a closed run no longer changes
when the environment does.  ``uat_signoffs.evidence_hash`` binds each signature to the frozen
manifest plus the results it approved, and ``revoked_at``/``revoked_by`` make an explicit revocation
auditable instead of silently keeping a stale approval.
"""
import sqlalchemy as sa
from alembic import op

revision = "202610050002"
down_revision = "202610050001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The ORM declares these as NOT NULL with a Python-side default, so the migrated schema must
    # match (the schema-freeze contract test compares nullability against the model).
    op.add_column("uat_runs", sa.Column("manifest_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")))
    op.add_column("uat_signoffs", sa.Column("evidence_hash", sa.String(length=64), nullable=True))
    op.add_column("uat_signoffs", sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("uat_signoffs", sa.Column("revoked_by", sa.Integer(), nullable=True))
    # SQLite cannot ALTER a table to add a constraint; the repository uses batch mode there
    # (same pattern as 202609200040/202609200041).
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("uat_signoffs") as batch:
            batch.create_foreign_key(
                "fk_uat_signoffs_revoked_by_users", "users", ["revoked_by"], ["id"]
            )
    else:
        op.create_foreign_key(
            "fk_uat_signoffs_revoked_by_users", "uat_signoffs", "users", ["revoked_by"], ["id"]
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("uat_signoffs") as batch:
            batch.drop_constraint("fk_uat_signoffs_revoked_by_users", type_="foreignkey")
    else:
        op.drop_constraint("fk_uat_signoffs_revoked_by_users", "uat_signoffs", type_="foreignkey")
    op.drop_column("uat_signoffs", "revoked_by")
    op.drop_column("uat_signoffs", "revoked_at")
    op.drop_column("uat_signoffs", "evidence_hash")
    op.drop_column("uat_runs", "manifest_json")
