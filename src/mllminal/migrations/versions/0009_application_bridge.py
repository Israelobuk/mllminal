"""Create application capability grant and bridge idempotency storage.

Revision ID: 0009_application_bridge
Revises: 0008_workflow_runtime
"""

import sqlalchemy as sa
from alembic import op

revision = "0009_application_bridge"
down_revision = "0008_workflow_runtime"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("application_grants"):
        op.create_table(
            "application_grants",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("application", sa.String(), nullable=False),
            sa.Column("scope", sa.String(), nullable=False),
            sa.Column("granted", sa.Boolean(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
    if not inspector.has_table("application_bridge_idempotency"):
        op.create_table(
            "application_bridge_idempotency",
            sa.Column("key", sa.String(), primary_key=True),
            sa.Column("operation", sa.String(), nullable=False),
            sa.Column("result_json", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )


def downgrade() -> None:
    op.drop_table("application_bridge_idempotency")
    op.drop_table("application_grants")
