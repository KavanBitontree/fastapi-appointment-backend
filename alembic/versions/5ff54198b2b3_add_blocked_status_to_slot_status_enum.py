"""add BLOCKED status to slot_status enum

Revision ID: 5ff54198b2b3
Revises: afc2652e7bd9
Create Date: 2026-02-02 15:23:20.158072

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5ff54198b2b3'
down_revision: Union[str, Sequence[str], None] = 'afc2652e7bd9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add BLOCKED value to the slot_status enum
    # In PostgreSQL, we need to use raw SQL to ALTER TYPE and ADD VALUE
    op.execute("ALTER TYPE slot_status ADD VALUE IF NOT EXISTS 'BLOCKED'")


def downgrade() -> None:
    """Downgrade schema."""
    # Note: PostgreSQL doesn't allow removing enum values directly
    # This is a limitation, so we'll leave the downgrade empty
    # In practice, you wouldn't want to remove enum values anyway as it could cause data loss
    pass
