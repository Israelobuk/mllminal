"""Create the MLLminal foundation schema.

Revision ID: 0001_foundation
Revises:
Create Date: 2026-07-16
"""

from alembic import op

import mllminal.runtime_store  # noqa: F401
from mllminal.persistence import Base

revision = "0001_foundation"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
