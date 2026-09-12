"""Align migrated columns with the ORM nullability contract.

Revision ID: 202609120026
Revises: 202609100025

Historical revisions could add their columns as *nullable* because the schema
they ran against had already been created by the removed
``Base.metadata.create_all()`` call in revision 202607070001: the migration body
never actually shaped the table.  Now that the chain builds a real historical
schema, those columns end up nullable on a fresh database while the ORM - and
every existing installation - declares them ``NOT NULL``.

This revision closes that gap.  A column is only narrowed when it currently
holds no ``NULL`` value, so the migration can never fail on a database that
already contains data.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "202609120026"
down_revision = "202609100025"
branch_labels = None
depends_on = None

NOT_NULL_COLUMNS: dict[str, tuple[str, ...]] = {
    "audit_logs": ("created_at",),
    "background_job_items": ("created_at",),
    "background_jobs": ("created_at", "updated_at"),
    "candidate_source_recommendations": ("knowledge_unit_ids_json", "citation_summary_json"),
    "field_mapping_drafts": ("evidence_completeness",),
    "institution_memberships": ("created_at",),
    "institutions": ("created_at", "updated_at"),
    "knowledge_documents": (
        "knowledge_type",
        "knowledge_scope",
        "document_status",
        "confidentiality_level",
        "current_version_no",
        "parse_status",
        "parse_summary_json",
        "warnings_json",
        "updated_at",
    ),
    "login_attempts": ("last_attempt_at",),
    "notifications": ("created_at",),
    "project_memberships": ("joined_at",),
    "refresh_tokens": ("created_at",),
    "review_decisions": ("decided_at",),
    "review_tasks": ("created_at", "updated_at"),
    "scenario_review_packages": ("created_at", "updated_at"),
    "stored_files": ("created_at", "updated_at"),
    "workflow_definitions": ("created_at", "updated_at"),
    "workflow_instances": ("created_at", "updated_at"),
}


def _reconcile(desired_nullable: bool) -> list[str]:
    """Set the listed columns to ``desired_nullable`` where it is currently different."""

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    changed: list[str] = []
    for table, columns in NOT_NULL_COLUMNS.items():
        if not inspector.has_table(table):
            continue
        existing = {column["name"]: column for column in inspector.get_columns(table)}
        pending = [
            name
            for name in columns
            if name in existing and bool(existing[name]["nullable"]) is not desired_nullable
        ]
        if not pending:
            continue
        safe: list[str] = []
        for name in pending:
            if not desired_nullable:
                nulls = bind.execute(
                    sa.text(f'SELECT COUNT(*) FROM "{table}" WHERE "{name}" IS NULL')
                ).scalar()
                if nulls:
                    # Existing data wins: never force a constraint that the rows
                    # cannot satisfy.
                    continue
            safe.append(name)
        if not safe:
            continue
        with op.batch_alter_table(table) as batch:
            for name in safe:
                batch.alter_column(
                    name,
                    existing_type=existing[name]["type"],
                    nullable=desired_nullable,
                )
        changed.extend(f"{table}.{name}" for name in safe)
    return changed


def upgrade() -> None:
    _reconcile(False)


def downgrade() -> None:
    _reconcile(True)
