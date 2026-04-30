"""add do_not_email to contact

Revision ID: d1e2f3a4b5c6
Revises: b4e9f1a2c3d5
Create Date: 2026-04-30 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd1e2f3a4b5c6'
down_revision: Union[str, Sequence[str], None] = 'b4e9f1a2c3d5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('contact', sa.Column('do_not_email', sa.Boolean(), nullable=True, server_default='false'))

    # Backfill: flag any contact that already has a bounced email activity
    op.execute("""
        UPDATE contact
        SET do_not_email = true
        WHERE id IN (
            SELECT DISTINCT contact_id
            FROM activity
            WHERE type = 'email' AND status = 'bounced'
        )
    """)


def downgrade() -> None:
    op.drop_column('contact', 'do_not_email')
