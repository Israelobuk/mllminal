"""Create durable privacy policy, history, and replay storage.

Revision ID: 0004_privacy_controls
Revises: 0003_learning_foundation
"""

import sqlalchemy as sa
from alembic import op

revision = "0004_privacy_controls"
down_revision = "0003_learning_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("privacy_state"):
        op.create_table(
            "privacy_state",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("policy_json", sa.Text(), nullable=False),
            sa.Column("consent_json", sa.Text(), nullable=True),
            sa.Column("incognito_json", sa.Text(), nullable=True),
            sa.Column("emergency_json", sa.Text(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
    if not inspector.has_table("privacy_rules"):
        op.create_table(
            "privacy_rules",
            sa.Column("rule_id", sa.String(), primary_key=True),
            sa.Column("rule_type", sa.String(), nullable=False),
            sa.Column("pattern", sa.Text(), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
    if not inspector.has_table("privacy_history"):
        op.create_table(
            "privacy_history",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("event_category", sa.String(), nullable=False),
            sa.Column("payload_json", sa.Text(), nullable=True),
            sa.Column("decision", sa.String(), nullable=False),
            sa.Column("rule_id", sa.String(), nullable=True),
            sa.Column("reason", sa.String(), nullable=False),
            sa.Column("timestamp", sa.DateTime(), nullable=False),
            sa.Column("adapter", sa.String(), nullable=False),
        )
    if not inspector.has_table("privacy_events"):
        op.create_table(
            "privacy_events",
            sa.Column("sequence", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("event_type", sa.String(), nullable=False),
            sa.Column("payload_json", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
    if not inspector.has_table("privacy_idempotency"):
        op.create_table(
            "privacy_idempotency",
            sa.Column("key", sa.String(), primary_key=True),
            sa.Column("operation", sa.String(), nullable=False),
            sa.Column("result_json", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )


def downgrade() -> None:
    op.drop_table("privacy_idempotency")
    op.drop_table("privacy_events")
    op.drop_table("privacy_history")
    op.drop_table("privacy_rules")
    op.drop_table("privacy_state")
