"""Persist explainable adaptive workflow execution decisions.

Revision ID: 0011_adaptive_execution_decisions
Revises: 0010_application_learning_profiles
"""

import sqlalchemy as sa
from alembic import op

revision = "0011_adaptive_execution_decisions"
down_revision = "0010_application_learning_profiles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("adaptive_execution_decisions"):
        op.create_table(
            "adaptive_execution_decisions",
            sa.Column("decision_id", sa.String(), primary_key=True),
            sa.Column("workflow_run_id", sa.String(), nullable=False),
            sa.Column("workflow_step_id", sa.String(), nullable=False),
            sa.Column("application_profile_id", sa.String(), nullable=False),
            sa.Column("payload_json", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index(
            "ix_adaptive_execution_decisions_workflow_run_id",
            "adaptive_execution_decisions",
            ["workflow_run_id"],
        )


def downgrade() -> None:
    op.drop_index(
        "ix_adaptive_execution_decisions_workflow_run_id",
        table_name="adaptive_execution_decisions",
    )
    op.drop_table("adaptive_execution_decisions")
