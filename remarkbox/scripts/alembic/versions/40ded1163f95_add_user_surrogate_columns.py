"""add user surrogate columns

Revision ID: 40ded1163f95
Revises: c9793937e756
Create Date: 2019-03-07 08:35:54.261514

"""

# revision identifiers, used by Alembic.
revision = '40ded1163f95'
down_revision = 'c9793937e756'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa

from remarkbox.models import UUIDType

def upgrade():
    op.add_column('rb_node', sa.Column('user_surrogate_id', UUIDType, nullable=True))


def downgrade():
    pass
