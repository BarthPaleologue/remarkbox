"""namespace group conversations

Revision ID: 6db39621f46c
Revises: f7b42b2024fb
Create Date: 2019-03-22 09:40:30.185446

"""

# revision identifiers, used by Alembic.
revision = '6db39621f46c'
down_revision = 'f7b42b2024fb'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.add_column('rb_namespace', sa.Column('group_conversations', sa.Boolean(), nullable=True))


def downgrade():
    pass
