"""Add allow_anonymous column to namespace

Revision ID: 108519de76ac
Revises: 5188e62d0afb
Create Date: 2025-12-20 11:05:36.134829

"""

# revision identifiers, used by Alembic.
revision = '108519de76ac'
down_revision = '5188e62d0afb'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.add_column('rb_namespace', sa.Column('allow_anonymous', sa.Boolean(), nullable=True, server_default='0'))


def downgrade():
    op.drop_column('rb_namespace', 'allow_anonymous')
