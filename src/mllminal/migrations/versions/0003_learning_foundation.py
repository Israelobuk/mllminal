"""Create durable learning foundation storage.

Revision ID: 0003_learning_foundation
Revises: 0002_provider_metadata
"""

import sqlalchemy as sa
from alembic import op

from mllminal.learning.contracts import PolicyLifecycle, PolicyVersion, utc_now

revision = "0003_learning_foundation"
down_revision = "0002_provider_metadata"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create only learning-owned tables and indexes, then seed defaults."""

    if not sa.inspect(op.get_bind()).has_table("learning_settings"):
        op.create_table(
            "learning_settings",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("enabled", sa.Boolean(), nullable=False),
            sa.Column("automatic_promotion_enabled", sa.Boolean(), nullable=False),
            sa.Column("minimum_experience_count", sa.Integer(), nullable=False),
            sa.Column("replay_capacity", sa.Integer(), nullable=False),
            sa.Column("seed", sa.Integer(), nullable=False),
            sa.Column("confidence_threshold", sa.Float(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
        op.create_table(
            "policy_decisions",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("task_id", sa.String(), nullable=False),
            sa.Column("decision_sequence", sa.Integer(), nullable=False),
            sa.Column("payload_json", sa.Text(), nullable=False),
            sa.Column("finalization_key", sa.String(), nullable=True),
            sa.Column("finalized_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("task_id", "decision_sequence"),
            sa.UniqueConstraint("finalization_key"),
        )
        op.create_index("ix_policy_decisions_task_id", "policy_decisions", ["task_id"])
        op.create_table(
            "experiences",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("task_id", sa.String(), nullable=False),
            sa.Column("decision_id", sa.String(), nullable=False),
            sa.Column("decision_sequence", sa.Integer(), nullable=False),
            sa.Column("idempotency_key", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("reward", sa.Float(), nullable=True),
            sa.Column("payload_json", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["decision_id"], ["policy_decisions.id"]),
            sa.UniqueConstraint("task_id", "decision_sequence"),
            sa.UniqueConstraint("idempotency_key"),
        )
        op.create_index("ix_experiences_task_id", "experiences", ["task_id"])
        op.create_index("ix_experiences_decision_id", "experiences", ["decision_id"])
        op.create_table(
            "replay_entries",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("experience_id", sa.String(), nullable=False, unique=True),
            sa.Column("features_json", sa.Text(), nullable=False),
            sa.Column("action", sa.String(), nullable=False),
            sa.Column("reward", sa.Float(), nullable=False),
            sa.Column("sampling_weight", sa.Float(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("consumed_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["experience_id"], ["experiences.id"]),
        )
        op.create_table(
            "learning_events",
            sa.Column("sequence", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("event_type", sa.String(), nullable=False),
            sa.Column("payload_json", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_table(
            "training_runs",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("payload_json", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_table(
            "evaluation_reports",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("training_run_id", sa.String(), nullable=False),
            sa.Column("payload_json", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["training_run_id"], ["training_runs.id"]),
        )
        op.create_index(
            "ix_evaluation_reports_training_run_id",
            "evaluation_reports",
            ["training_run_id"],
        )
        op.create_table(
            "policy_versions",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("version", sa.Integer(), nullable=False, unique=True),
            sa.Column("lifecycle", sa.String(), nullable=False),
            sa.Column("promoted", sa.Boolean(), nullable=False),
            sa.Column("checkpoint_sha256", sa.String(), nullable=True),
            sa.Column("payload_json", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index(
            "uq_policy_versions_one_promoted",
            "policy_versions",
            ["promoted"],
            unique=True,
            sqlite_where=sa.text("promoted = 1"),
        )
        op.create_table(
            "promotion_records",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("policy_version_id", sa.String(), nullable=False),
            sa.Column("idempotency_key", sa.String(), nullable=True, unique=True),
            sa.Column("payload_json", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["policy_version_id"], ["policy_versions.id"]),
        )
        op.create_index(
            "ix_promotion_records_policy_version_id",
            "promotion_records",
            ["policy_version_id"],
        )
        op.create_table(
            "rollback_records",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("from_policy_version_id", sa.String(), nullable=False),
            sa.Column("to_policy_version_id", sa.String(), nullable=False),
            sa.Column("idempotency_key", sa.String(), nullable=True, unique=True),
            sa.Column("payload_json", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["from_policy_version_id"], ["policy_versions.id"]),
            sa.ForeignKeyConstraint(["to_policy_version_id"], ["policy_versions.id"]),
        )

    now = utc_now()
    fallback = PolicyVersion(
        version=0,
        name="policy_v0",
        lifecycle=PolicyLifecycle.ACTIVE,
        checkpoint_sha256=None,
        training_run_id=None,
        created_at=now,
    )
    settings_table = sa.table(
        "learning_settings",
        sa.column("id", sa.Integer()),
        sa.column("enabled", sa.Boolean()),
        sa.column("automatic_promotion_enabled", sa.Boolean()),
        sa.column("minimum_experience_count", sa.Integer()),
        sa.column("replay_capacity", sa.Integer()),
        sa.column("seed", sa.Integer()),
        sa.column("confidence_threshold", sa.Float()),
        sa.column("updated_at", sa.DateTime()),
    )
    policies_table = sa.table(
        "policy_versions",
        sa.column("id", sa.String()),
        sa.column("version", sa.Integer()),
        sa.column("lifecycle", sa.String()),
        sa.column("promoted", sa.Boolean()),
        sa.column("checkpoint_sha256", sa.String()),
        sa.column("payload_json", sa.Text()),
        sa.column("created_at", sa.DateTime()),
    )
    op.bulk_insert(
        settings_table,
        [
            {
                "id": 1,
                "enabled": True,
                "automatic_promotion_enabled": False,
                "minimum_experience_count": 100,
                "replay_capacity": 10_000,
                "seed": 42,
                "confidence_threshold": 0.65,
                "updated_at": now,
            }
        ],
    )
    op.bulk_insert(
        policies_table,
        [
            {
                "id": fallback.id,
                "version": 0,
                "lifecycle": fallback.lifecycle.value,
                "promoted": True,
                "checkpoint_sha256": None,
                "payload_json": fallback.model_dump_json(),
                "created_at": now,
            }
        ],
    )


def downgrade() -> None:
    """Drop learning-owned indexes/tables only, in reverse dependency order."""

    op.drop_table("rollback_records")
    op.drop_index("ix_promotion_records_policy_version_id", table_name="promotion_records")
    op.drop_table("promotion_records")
    op.drop_index("uq_policy_versions_one_promoted", table_name="policy_versions")
    op.drop_table("policy_versions")
    op.drop_index("ix_evaluation_reports_training_run_id", table_name="evaluation_reports")
    op.drop_table("evaluation_reports")
    op.drop_table("training_runs")
    op.drop_table("learning_events")
    op.drop_table("replay_entries")
    op.drop_index("ix_experiences_decision_id", table_name="experiences")
    op.drop_index("ix_experiences_task_id", table_name="experiences")
    op.drop_table("experiences")
    op.drop_index("ix_policy_decisions_task_id", table_name="policy_decisions")
    op.drop_table("policy_decisions")
    op.drop_table("learning_settings")
