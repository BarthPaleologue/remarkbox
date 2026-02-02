"""Add spam_score spam_reason to Node and spam_filter_enabled to Namespace

Revision ID: e99b1524710c
Revises: 03061161fc3d
Create Date: 2026-02-02 13:04:45.514654

"""

# revision identifiers, used by Alembic.
revision = 'e99b1524710c'
down_revision = '03061161fc3d'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.add_column('rb_node', sa.Column('spam_score', sa.Float(), nullable=True))
    op.add_column('rb_node', sa.Column('spam_reason', sa.UnicodeText(), nullable=True))
    op.add_column('rb_namespace', sa.Column('spam_filter_enabled', sa.Boolean(), nullable=True))


def downgrade():
    op.drop_column('rb_namespace', 'spam_filter_enabled')
    op.drop_column('rb_node', 'spam_reason')
    op.drop_column('rb_node', 'spam_score')
