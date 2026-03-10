"""add source_format to node

Revision ID: d47dc908d2ea
Revises: 7c624a8fae9e
Create Date: 2026-03-09 23:08:19.266162

"""

# revision identifiers, used by Alembic.
revision = 'd47dc908d2ea'
down_revision = '7c624a8fae9e'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.add_column(
        'rb_node',
        sa.Column('source_format', sa.Unicode(length=16), nullable=False, server_default='markdown'),
    )


def downgrade():
    op.drop_column('rb_node', 'source_format')
