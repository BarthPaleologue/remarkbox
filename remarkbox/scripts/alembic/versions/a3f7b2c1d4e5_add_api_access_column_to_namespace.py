"""Add api_access column to namespace

Revision ID: a3f7b2c1d4e5
Revises: d1213344ca99
Create Date: 2026-02-01 00:00:00.000000

"""

# revision identifiers, used by Alembic.
revision = 'a3f7b2c1d4e5'
down_revision = 'd1213344ca99'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.add_column('rb_namespace', sa.Column('api_access', sa.Boolean(), nullable=True, server_default='1'))


def downgrade():
    op.drop_column('rb_namespace', 'api_access')
