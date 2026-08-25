"""Persist bounded context-free Mil responses."""

import sqlalchemy as sa
from alembic import op

revision = "0017_mil_response_cache"
down_revision = "0016_verification_ranking_decisions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("mil_response_cache"):
        op.create_table(
            "mil_response_cache",
            sa.Column("key", sa.String(length=64), primary_key=True),
            sa.Column("response", sa.Text(), nullable=False),
            sa.Column("created_at", sa.Float(), nullable=False),
            sa.Column("expires_at", sa.Float(), nullable=False),
            sa.Column("last_accessed_at", sa.Float(), nullable=False),
            sa.Column("hit_count", sa.Integer(), nullable=False, server_default="0"),
        )
        op.create_index("ix_mil_response_cache_expires_at", "mil_response_cache", ["expires_at"])
        op.create_index(
            "ix_mil_response_cache_last_accessed_at",
            "mil_response_cache",
            ["last_accessed_at"],
        )


def downgrade() -> None:
    op.drop_index("ix_mil_response_cache_last_accessed_at", table_name="mil_response_cache")
    op.drop_index("ix_mil_response_cache_expires_at", table_name="mil_response_cache")
    op.drop_table("mil_response_cache")
