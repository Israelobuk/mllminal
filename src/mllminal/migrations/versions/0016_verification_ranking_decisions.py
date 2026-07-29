"""Persist verification ranking score provenance."""

import sqlalchemy as sa
from alembic import op

revision = "0016_verification_ranking_decisions"
down_revision = "0015_active_policy_bindings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("verification_ranking_decisions"):
        op.create_table(
            "verification_ranking_decisions",
            sa.Column("decision_id", sa.String(), primary_key=True),
            sa.Column("profile_id", sa.String(), nullable=True),
            sa.Column("payload_json", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index(
            "ix_verification_ranking_decisions_profile_id",
            "verification_ranking_decisions",
            ["profile_id"],
        )


def downgrade() -> None:
    op.drop_index(
        "ix_verification_ranking_decisions_profile_id",
        table_name="verification_ranking_decisions",
    )
    op.drop_table("verification_ranking_decisions")
