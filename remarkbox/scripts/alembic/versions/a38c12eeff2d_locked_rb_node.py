"""locked-rb-node

Revision ID: a38c12eeff2d
Revises: 76deff88cfd6
Create Date: 2020-04-20 10:22:43.611168

"""

# revision identifiers, used by Alembic.
revision = 'a38c12eeff2d'
down_revision = '76deff88cfd6'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.add_column('rb_node', sa.Column('locked', sa.Boolean(), nullable=True))


def downgrade():
    op.drop_column('rb_node', 'locked')
