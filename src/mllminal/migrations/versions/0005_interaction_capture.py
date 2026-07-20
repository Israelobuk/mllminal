"""Create semantic interaction capture and replay-permission storage.

Revision ID: 0005_interaction_capture
Revises: 0004_privacy_controls
"""

import sqlalchemy as sa
from alembic import op

revision = "0005_interaction_capture"
down_revision = "0004_privacy_controls"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("interaction_state"):
        op.create_table(
            "interaction_state",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("replay_authorized", sa.Boolean(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
    if not inspector.has_table("interaction_events"):
        op.create_table(
            "interaction_events",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("kind", sa.String(), nullable=False),
            sa.Column("payload_json", sa.Text(), nullable=False),
            sa.Column("replayable", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
    if not inspector.has_table("interaction_idempotency"):
        op.create_table(
            "interaction_idempotency",
            sa.Column("key", sa.String(), primary_key=True),
            sa.Column("operation", sa.String(), nullable=False),
            sa.Column("result_json", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )


def downgrade() -> None:
    op.drop_table("interaction_idempotency")
    op.drop_table("interaction_events")
    op.drop_table("interaction_state")
