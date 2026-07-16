"""Persist provider response audit metadata.

Revision ID: 0002_provider_metadata
Revises: 0001_foundation
"""

from alembic import op

import mllminal.runtime_store  # noqa: F401
from mllminal.persistence import Base

revision = "0002_provider_metadata"
down_revision = "0001_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    op.drop_table("provider_responses")
