"""Persist independent domain-scoped advisory policy bindings.

Revision ID: 0015_active_policy_bindings
Revises: 0014_offline_policy_training_experiences
"""

import sqlalchemy as sa
from alembic import op

revision = "0015_active_policy_bindings"
down_revision = "0014_offline_policy_training_experiences"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("active_policy_bindings"):
        op.create_table(
            "active_policy_bindings",
            sa.Column("binding_id", sa.String(), primary_key=True),
            sa.Column("policy_domain", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("idempotency_key", sa.String(), nullable=True, unique=True),
            sa.Column("payload_json", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index(
            "ix_active_policy_bindings_policy_domain",
            "active_policy_bindings",
            ["policy_domain"],
        )
        op.create_index(
            "ix_active_policy_bindings_status", "active_policy_bindings", ["status"]
        )


def downgrade() -> None:
    op.drop_index("ix_active_policy_bindings_status", table_name="active_policy_bindings")
    op.drop_index("ix_active_policy_bindings_policy_domain", table_name="active_policy_bindings")
    op.drop_table("active_policy_bindings")