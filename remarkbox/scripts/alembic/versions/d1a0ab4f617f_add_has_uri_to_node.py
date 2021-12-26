"""add has_uri to Node

Revision ID: d1a0ab4f617f
Revises: 6db39621f46c
Create Date: 2019-06-29 16:23:09.323221

"""

# revision identifiers, used by Alembic.
revision = 'd1a0ab4f617f'
down_revision = '6db39621f46c'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.add_column('rb_node', sa.Column('has_uri', sa.Boolean(), nullable=False, server_default="0"))


def downgrade():
    op.drop_column('rb_node', 'has_uri')
