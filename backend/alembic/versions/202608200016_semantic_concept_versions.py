"""Add canonical temporal semantic concept versions.

Revision ID: 202608200016
Revises: 202608200015
"""

from __future__ import annotations

from datetime import date, datetime

import sqlalchemy as sa
from alembic import op


revision = "202608200016"
down_revision = "202608200015"
branch_labels = None
depends_on = None

BOOTSTRAP_FALLBACK_DATE = date(2026, 8, 20)
SINGLE_COLUMN_INDEXES = (
    ("ix_semantic_concept_versions_semantic_concept_id", ["semantic_concept_id"]),
    ("ix_semantic_concept_versions_institution_id", ["institution_id"]),
    ("ix_semantic_concept_versions_project_id", ["project_id"]),
    ("ix_semantic_concept_versions_business_domain", ["business_domain"]),
    ("ix_semantic_concept_versions_status", ["status"]),
)


def _version_table() -> sa.Table:
    return sa.table(
        "semantic_concept_versions",
        sa.column("id", sa.Integer()),
        sa.column("semantic_concept_id", sa.Integer()),
        sa.column("institution_id", sa.Integer()),
        sa.column("project_id", sa.Integer()),
        sa.column("version_no", sa.Integer()),
        sa.column("concept_name", sa.String(length=255)),
        sa.column("definition", sa.Text()),
        sa.column("description", sa.Text()),
        sa.column("aliases_json", sa.JSON()),
        sa.column("business_domain", sa.String(length=200)),
        sa.column("owner_department", sa.String(length=200)),
        sa.column("provenance_json", sa.JSON()),
        sa.column("status", sa.String(length=30)),
        sa.column("confidence_level", sa.String(length=30)),
        sa.column("source_type", sa.String(length=50)),
        sa.column("source_id", sa.Integer()),
        sa.column("created_by", sa.String(length=100)),
        sa.column("confirmed_by", sa.String(length=100)),
        sa.column("confirmed_at", sa.DateTime(timezone=True)),
        sa.column("effective_from", sa.Date()),
        sa.column("effective_to", sa.Date()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )


def upgrade() -> None:
    if op.get_context().as_sql:
        _create_version_table()
        return

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("semantic_concept_versions"):
        _create_version_table()
    _bootstrap_legacy_concepts(bind)


def _create_version_table() -> None:
    op.create_table(
        "semantic_concept_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("semantic_concept_id", sa.Integer(), sa.ForeignKey("semantic_concepts.id"), nullable=False),
        sa.Column("institution_id", sa.Integer(), sa.ForeignKey("institutions.id"), nullable=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("concept_name", sa.String(length=255), nullable=False),
        sa.Column("definition", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("aliases_json", sa.JSON(), nullable=False),
        sa.Column("business_domain", sa.String(length=200), nullable=True),
        sa.Column("owner_department", sa.String(length=200), nullable=True),
        sa.Column("provenance_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="draft"),
        sa.Column("confidence_level", sa.String(length=30), nullable=False, server_default="medium"),
        sa.Column("source_type", sa.String(length=50), nullable=False, server_default="manual"),
        sa.Column("source_id", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.String(length=100), nullable=True),
        sa.Column("confirmed_by", sa.String(length=100), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("semantic_concept_id", "version_no", name="uq_semantic_concept_version"),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name="ck_semantic_concept_version_dates",
        ),
    )
    op.create_index(
        "ix_semantic_concept_version_project_status",
        "semantic_concept_versions",
        ["project_id", "status"],
    )
    op.create_index(
        "ix_semantic_concept_version_concept_status",
        "semantic_concept_versions",
        ["semantic_concept_id", "status"],
    )
    op.create_index(
        "ix_semantic_concept_version_project_effective",
        "semantic_concept_versions",
        ["project_id", "effective_from", "effective_to"],
    )
    for index_name, columns in SINGLE_COLUMN_INDEXES:
        op.create_index(index_name, "semantic_concept_versions", columns)


def _bootstrap_legacy_concepts(bind) -> None:
    legacy = sa.table(
        "semantic_concepts",
        sa.column("id", sa.Integer()),
        sa.column("institution_id", sa.Integer()),
        sa.column("project_id", sa.Integer()),
        sa.column("concept_name", sa.String(length=255)),
        sa.column("definition", sa.Text()),
        sa.column("description", sa.Text()),
        sa.column("aliases_json", sa.JSON()),
        sa.column("business_domain", sa.String(length=200)),
        sa.column("owner_department", sa.String(length=200)),
        sa.column("status", sa.String(length=30)),
        sa.column("confidence_level", sa.String(length=30)),
        sa.column("source_id", sa.Integer()),
        sa.column("created_by", sa.String(length=100)),
        sa.column("confirmed_by", sa.String(length=100)),
        sa.column("confirmed_at", sa.DateTime(timezone=True)),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    versions = _version_table()
    existing_ids = set(bind.execute(
        sa.select(versions.c.semantic_concept_id).where(versions.c.version_no == 1)
    ).scalars())
    rows = bind.execute(sa.select(legacy).order_by(legacy.c.id)).mappings().all()
    for row in rows:
        concept_id = row["id"]
        if concept_id in existing_ids:
            continue
        effective_from, used_fallback = _bootstrap_date(row.get("created_at"))
        created_at = row.get("created_at") or datetime.combine(effective_from, datetime.min.time())
        updated_at = row.get("updated_at") or created_at
        bind.execute(sa.insert(versions).values(
            semantic_concept_id=concept_id,
            institution_id=row.get("institution_id"),
            project_id=row["project_id"],
            version_no=1,
            concept_name=row["concept_name"],
            definition=row.get("definition"),
            description=row.get("description"),
            aliases_json=list(row.get("aliases_json") or []),
            business_domain=row.get("business_domain"),
            owner_department=row.get("owner_department"),
            provenance_json={
                "source": "legacy_concept_bootstrap",
                "legacy_concept_id": concept_id,
                "effective_date_fallback": used_fallback,
            },
            status=row.get("status") or "draft",
            confidence_level=row.get("confidence_level") or "medium",
            source_type="bootstrap",
            source_id=row.get("source_id"),
            created_by=row.get("created_by"),
            confirmed_by=row.get("confirmed_by"),
            confirmed_at=row.get("confirmed_at"),
            effective_from=effective_from,
            effective_to=None,
            created_at=created_at,
            updated_at=updated_at,
        ))
        existing_ids.add(concept_id)


def _bootstrap_date(value) -> tuple[date, bool]:
    if value is None:
        return BOOTSTRAP_FALLBACK_DATE, True
    if isinstance(value, datetime):
        return value.date(), False
    if isinstance(value, date):
        return value, False
    try:
        return date.fromisoformat(str(value)[:10]), False
    except ValueError:
        return BOOTSTRAP_FALLBACK_DATE, True


def downgrade() -> None:
    if op.get_context().as_sql:
        for index_name, _ in reversed(SINGLE_COLUMN_INDEXES):
            op.drop_index(index_name, table_name="semantic_concept_versions")
        op.drop_table("semantic_concept_versions")
        return
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("semantic_concept_versions"):
        existing_indexes = {item["name"] for item in inspector.get_indexes("semantic_concept_versions")}
        for index_name, _ in reversed(SINGLE_COLUMN_INDEXES):
            if index_name in existing_indexes:
                op.drop_index(index_name, table_name="semantic_concept_versions")
        op.drop_table("semantic_concept_versions")
