"""Persist durable offline policy training experiences.

Revision ID: 0014_offline_policy_training_experiences
Revises: 0013_offline_policy_replay_snapshots
"""

import sqlalchemy as sa
from alembic import op

revision = "0014_offline_policy_training_experiences"
down_revision = "0013_offline_policy_replay_snapshots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("training_experiences"):
        op.create_table(
            "training_experiences",
            sa.Column("experience_id", sa.String(), primary_key=True),
            sa.Column("policy_domain", sa.String(), nullable=False),
            sa.Column("source_record_type", sa.String(), nullable=False),
            sa.Column("source_record_id", sa.String(), nullable=False),
            sa.Column("eligible_for_training", sa.Boolean(), nullable=False),
            sa.Column("payload_json", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("policy_domain", "source_record_type", "source_record_id"),
        )
        op.create_index(
            "ix_training_experiences_policy_domain", "training_experiences", ["policy_domain"]
        )


def downgrade() -> None:
    op.drop_index("ix_training_experiences_policy_domain", table_name="training_experiences")
    op.drop_table("training_experiences")
