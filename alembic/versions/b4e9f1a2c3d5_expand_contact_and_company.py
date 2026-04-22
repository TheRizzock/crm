"""expand contact and company fields

Revision ID: b4e9f1a2c3d5
Revises: 923963de68a2
Create Date: 2026-04-22 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b4e9f1a2c3d5'
down_revision: Union[str, Sequence[str], None] = '923963de68a2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # contact
    op.add_column('contact', sa.Column('email', sa.String(), nullable=True))
    op.add_column('contact', sa.Column('personal_email', sa.String(), nullable=True))
    op.add_column('contact', sa.Column('mobile_number', sa.String(), nullable=True))
    op.add_column('contact', sa.Column('job_title', sa.String(), nullable=True))
    op.add_column('contact', sa.Column('industry', sa.String(), nullable=True))
    op.add_column('contact', sa.Column('seniority_level', sa.String(), nullable=True))
    op.add_column('contact', sa.Column('functional_level', sa.String(), nullable=True))
    op.add_column('contact', sa.Column('city', sa.String(), nullable=True))
    op.add_column('contact', sa.Column('state', sa.String(), nullable=True))
    op.add_column('contact', sa.Column('country', sa.String(), nullable=True))
    op.add_column('contact', sa.Column('zb_status', sa.String(), nullable=True))
    op.add_column('contact', sa.Column('zb_sub_status', sa.String(), nullable=True))
    op.add_column('contact', sa.Column('zb_free_email', sa.String(), nullable=True))
    op.add_column('contact', sa.Column('zb_did_you_mean', sa.String(), nullable=True))
    op.add_column('contact', sa.Column('email_validated_at', sa.DateTime(), nullable=True))
    op.create_index(op.f('ix_contact_email'), 'contact', ['email'], unique=False)

    # activity
    op.add_column('activity', sa.Column('subject', sa.String(), nullable=True))
    op.add_column('activity', sa.Column('body', sa.Text(), nullable=True))
    op.add_column('activity', sa.Column('status', sa.String(), nullable=True))
    op.add_column('activity', sa.Column('resend_id', sa.String(), nullable=True))
    op.create_index(op.f('ix_activity_type'), 'activity', ['type'], unique=False)

    # company
    op.add_column('company', sa.Column('domain', sa.String(), nullable=True))
    op.add_column('company', sa.Column('phone', sa.String(), nullable=True))
    op.add_column('company', sa.Column('linkedin_uid', sa.String(), nullable=True))
    op.add_column('company', sa.Column('founded_year', sa.String(), nullable=True))
    op.add_column('company', sa.Column('annual_revenue', sa.String(), nullable=True))
    op.add_column('company', sa.Column('annual_revenue_clean', sa.String(), nullable=True))
    op.add_column('company', sa.Column('total_funding', sa.String(), nullable=True))
    op.add_column('company', sa.Column('total_funding_clean', sa.String(), nullable=True))
    op.add_column('company', sa.Column('description', sa.Text(), nullable=True))
    op.add_column('company', sa.Column('keywords', sa.Text(), nullable=True))
    op.add_column('company', sa.Column('technologies', sa.Text(), nullable=True))
    op.add_column('company', sa.Column('street_address', sa.String(), nullable=True))
    op.add_column('company', sa.Column('full_address', sa.String(), nullable=True))
    op.add_column('company', sa.Column('city', sa.String(), nullable=True))
    op.add_column('company', sa.Column('state', sa.String(), nullable=True))
    op.add_column('company', sa.Column('country', sa.String(), nullable=True))
    op.add_column('company', sa.Column('postal_code', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_index(op.f('ix_contact_email'), table_name='contact')
    for col in ['email_validated_at', 'zb_did_you_mean', 'zb_free_email',
                'zb_sub_status', 'zb_status', 'country', 'state', 'city', 'functional_level',
                'seniority_level', 'industry', 'job_title', 'mobile_number', 'personal_email', 'email']:
        op.drop_column('contact', col)

    op.drop_index(op.f('ix_activity_type'), table_name='activity')
    for col in ['resend_id', 'status', 'body', 'subject']:
        op.drop_column('activity', col)

    for col in ['postal_code', 'country', 'state', 'city', 'full_address', 'street_address',
                'technologies', 'keywords', 'description', 'total_funding_clean', 'total_funding',
                'annual_revenue_clean', 'annual_revenue', 'founded_year', 'linkedin_uid', 'phone', 'domain']:
        op.drop_column('company', col)
