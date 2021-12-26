"""approve column

Revision ID: c97ddfcbc406
Revises: 2e00b92495e4
Create Date: 2017-08-13 18:49:09.057118

"""

# revision identifiers, used by Alembic.
revision = "c97ddfcbc406"
down_revision = "2e00b92495e4"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.add_column("Node", sa.Column("approved", sa.Boolean(), nullable=True))


def downgrade():
    op.drop_column("Node", "approved")
