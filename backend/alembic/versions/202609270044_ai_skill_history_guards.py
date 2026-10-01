"""Enforce published Skill content and compatibility snapshot immutability."""
from alembic import op
from app.schema_freeze.ai_skill_guards_20260927 import install, uninstall

revision = "202609270044"
down_revision = "202609270043"
branch_labels = None
depends_on = None


def upgrade():
    install(op.get_bind())


def downgrade():
    uninstall(op.get_bind())
