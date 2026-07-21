"""Persist universal application interaction profiles and backend evidence.

Revision ID: 0010_application_learning_profiles
Revises: 0009_application_bridge
"""

import sqlalchemy as sa
from alembic import op

revision = "0010_application_learning_profiles"
down_revision = "0009_application_bridge"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("application_interaction_profiles"):
        op.create_table(
            "application_interaction_profiles",
            sa.Column("profile_id", sa.String(), primary_key=True),
            sa.Column("identity_key", sa.String(), nullable=False, unique=True),
            sa.Column("payload_json", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
    if not inspector.has_table("profile_observations"):
        op.create_table(
            "profile_observations",
            sa.Column("event_id", sa.String(), primary_key=True),
            sa.Column("profile_id", sa.String(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
    if not inspector.has_table("backend_reliability"):
        op.create_table(
            "backend_reliability",
            sa.Column("record_id", sa.String(), primary_key=True),
            sa.Column("profile_id", sa.String(), nullable=False),
            sa.Column("abstract_action", sa.String(), nullable=False),
            sa.Column("backend", sa.String(), nullable=False),
            sa.Column("target_type", sa.String(), nullable=False),
            sa.Column("payload_json", sa.Text(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint(
                "profile_id",
                "abstract_action",
                "backend",
                "target_type",
                name="uq_backend_reliability_identity",
            ),
        )
    if not inspector.has_table("profile_learning_experiences"):
        op.create_table(
            "profile_learning_experiences",
            sa.Column("experience_id", sa.String(), primary_key=True),
            sa.Column("profile_id", sa.String(), nullable=False),
            sa.Column("idempotency_key", sa.String(), nullable=False, unique=True),
            sa.Column("payload_json", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )


def downgrade() -> None:
    op.drop_table("profile_learning_experiences")
    op.drop_table("backend_reliability")
    op.drop_table("profile_observations")
    op.drop_table("application_interaction_profiles")
