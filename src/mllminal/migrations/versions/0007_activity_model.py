"""Create activity, application-session, and task-session projections.

Revision ID: 0007_activity_model
Revises: 0006_workflow_demonstration
"""

import sqlalchemy as sa
from alembic import op

revision = "0007_activity_model"
down_revision = "0006_workflow_demonstration"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    for name in (
        "activity_segments",
        "application_sessions",
        "task_sessions",
        "activity_context_switches",
        "task_boundaries",
        "activity_summaries",
    ):
        if not inspector.has_table(name):
            op.create_table(
                name,
                sa.Column("id", sa.String(), primary_key=True),
                sa.Column("payload_json", sa.Text(), nullable=False),
                sa.Column("created_at", sa.DateTime(), nullable=False),
            )
    if not inspector.has_table("activity_idempotency"):
        op.create_table(
            "activity_idempotency",
            sa.Column("key", sa.String(), primary_key=True),
            sa.Column("operation", sa.String(), nullable=False),
            sa.Column("result_json", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )


def downgrade() -> None:
    op.drop_table("activity_idempotency")
    op.drop_table("activity_summaries")
    op.drop_table("task_boundaries")
    op.drop_table("activity_context_switches")
    op.drop_table("task_sessions")
    op.drop_table("application_sessions")
    op.drop_table("activity_segments")
