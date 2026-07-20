"""Create explicit workflow demonstration and draft candidate storage.

Revision ID: 0006_workflow_demonstration
Revises: 0005_interaction_capture
"""

import sqlalchemy as sa
from alembic import op

revision = "0006_workflow_demonstration"
down_revision = "0005_interaction_capture"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("demonstration_sessions"):
        op.create_table(
            "demonstration_sessions",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("label", sa.String(), nullable=False),
            sa.Column("state", sa.String(), nullable=False),
            sa.Column("timeout_seconds", sa.Integer(), nullable=False),
            sa.Column("emergency_stop_shortcut", sa.String(), nullable=False),
            sa.Column("started_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("step_count", sa.Integer(), nullable=False),
            sa.Column("candidate_id", sa.String(), nullable=True),
        )
    if not inspector.has_table("demonstration_steps"):
        op.create_table(
            "demonstration_steps",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("session_id", sa.String(), nullable=False),
            sa.Column("sequence", sa.Integer(), nullable=False),
            sa.Column("payload_json", sa.Text(), nullable=False),
        )
    if not inspector.has_table("demonstration_variables"):
        op.create_table(
            "demonstration_variables",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("session_id", sa.String(), nullable=False),
            sa.Column("event_id", sa.String(), nullable=False),
            sa.Column("label", sa.String(), nullable=False),
            sa.Column("field_name", sa.String(), nullable=True),
        )
    if not inspector.has_table("workflow_candidates"):
        op.create_table(
            "workflow_candidates",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("session_id", sa.String(), nullable=False),
            sa.Column("title", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("activated", sa.Boolean(), nullable=False),
            sa.Column("payload_json", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
    if not inspector.has_table("demonstration_idempotency"):
        op.create_table(
            "demonstration_idempotency",
            sa.Column("key", sa.String(), primary_key=True),
            sa.Column("operation", sa.String(), nullable=False),
            sa.Column("result_json", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )


def downgrade() -> None:
    op.drop_table("demonstration_idempotency")
    op.drop_table("workflow_candidates")
    op.drop_table("demonstration_variables")
    op.drop_table("demonstration_steps")
    op.drop_table("demonstration_sessions")
