"""add google_site_verification column to namespace

Revision ID: d1213344ca99
Revises: 108519de76ac
Create Date: 2026-01-11 09:06:53.272415

"""

# revision identifiers, used by Alembic.
revision = 'd1213344ca99'
down_revision = '108519de76ac'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.add_column('rb_namespace', sa.Column('google_site_verification', sa.Unicode(length=128), nullable=True))


def downgrade():
    op.drop_column('rb_namespace', 'google_site_verification')
