"""Persist advisory workflow suggestions and preference learning.

Revision ID: 0012_adaptive_suggestions_preferences
Revises: 0011_adaptive_execution_decisions
"""

import sqlalchemy as sa
from alembic import op

revision = "0012_adaptive_suggestions_preferences"
down_revision = "0011_adaptive_execution_decisions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("adaptive_workflow_suggestions"):
        op.create_table(
            "adaptive_workflow_suggestions",
            sa.Column("suggestion_id", sa.String(), primary_key=True),
            sa.Column("candidate_id", sa.String(), nullable=False),
            sa.Column("application", sa.String(), nullable=False),
            sa.Column("evidence_key", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("payload_json", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("candidate_id", "evidence_key"),
        )
        op.create_index(
            "ix_adaptive_workflow_suggestions_candidate_id",
            "adaptive_workflow_suggestions",
            ["candidate_id"],
        )
        op.create_index(
            "ix_adaptive_workflow_suggestions_application",
            "adaptive_workflow_suggestions",
            ["application"],
        )
    if not inspector.has_table("suggestion_feedback"):
        op.create_table(
            "suggestion_feedback",
            sa.Column("feedback_id", sa.String(), primary_key=True),
            sa.Column("suggestion_id", sa.String(), nullable=False),
            sa.Column("candidate_id", sa.String(), nullable=False),
            sa.Column("kind", sa.String(), nullable=False),
            sa.Column("idempotency_key", sa.String(), nullable=False, unique=True),
            sa.Column("payload_json", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index(
            "ix_suggestion_feedback_suggestion_id", "suggestion_feedback", ["suggestion_id"]
        )
        op.create_index(
            "ix_suggestion_feedback_candidate_id", "suggestion_feedback", ["candidate_id"]
        )
    if not inspector.has_table("user_workflow_preferences"):
        op.create_table(
            "user_workflow_preferences",
            sa.Column("preference_id", sa.String(), primary_key=True),
            sa.Column("scope", sa.String(), nullable=False),
            sa.Column("application", sa.String(), nullable=True),
            sa.Column("candidate_id", sa.String(), nullable=True),
            sa.Column("payload_json", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("scope", "application", "candidate_id"),
        )
    if not inspector.has_table("suggestion_ranking_decisions"):
        op.create_table(
            "suggestion_ranking_decisions",
            sa.Column("decision_id", sa.String(), primary_key=True),
            sa.Column("suggestion_id", sa.String(), nullable=False),
            sa.Column("candidate_id", sa.String(), nullable=False),
            sa.Column("payload_json", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
    if not inspector.has_table("workflow_adaptation_proposals"):
        op.create_table(
            "workflow_adaptation_proposals",
            sa.Column("proposal_id", sa.String(), primary_key=True),
            sa.Column("candidate_id", sa.String(), nullable=False),
            sa.Column("source_suggestion_id", sa.String(), nullable=False),
            sa.Column("payload_json", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )


def downgrade() -> None:
    op.drop_table("workflow_adaptation_proposals")
    op.drop_table("suggestion_ranking_decisions")
    op.drop_table("user_workflow_preferences")
    op.drop_index("ix_suggestion_feedback_candidate_id", table_name="suggestion_feedback")
    op.drop_index("ix_suggestion_feedback_suggestion_id", table_name="suggestion_feedback")
    op.drop_table("suggestion_feedback")
    op.drop_index(
        "ix_adaptive_workflow_suggestions_application", table_name="adaptive_workflow_suggestions"
    )
    op.drop_index(
        "ix_adaptive_workflow_suggestions_candidate_id", table_name="adaptive_workflow_suggestions"
    )
    op.drop_table("adaptive_workflow_suggestions")
