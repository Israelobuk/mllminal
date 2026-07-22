"""Persist immutable offline policy replay snapshot metadata.

Revision ID: 0013_offline_policy_replay_snapshots
Revises: 0012_adaptive_suggestions_preferences
"""

import sqlalchemy as sa
from alembic import op

revision = "0013_offline_policy_replay_snapshots"
down_revision = "0012_adaptive_suggestions_preferences"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("replay_snapshots"):
        op.create_table(
            "replay_snapshots",
            sa.Column("snapshot_id", sa.String(), primary_key=True),
            sa.Column("policy_domain", sa.String(), nullable=False),
            sa.Column("dataset_digest", sa.String(), nullable=False, unique=True),
            sa.Column("payload_json", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_replay_snapshots_policy_domain", "replay_snapshots", ["policy_domain"])


def downgrade() -> None:
    op.drop_index("ix_replay_snapshots_policy_domain", table_name="replay_snapshots")
    op.drop_table("replay_snapshots")
