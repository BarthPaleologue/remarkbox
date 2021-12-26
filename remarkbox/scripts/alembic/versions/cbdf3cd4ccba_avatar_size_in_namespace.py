"""avatar_size in namespace

Revision ID: cbdf3cd4ccba
Revises: 953d42406dbb
Create Date: 2017-07-15 12:45:52.158320

"""

# revision identifiers, used by Alembic.
revision = "cbdf3cd4ccba"
down_revision = "953d42406dbb"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.add_column("Namespace", sa.Column("avatar_size", sa.Integer(), nullable=True))


def downgrade():
    op.drop_column("Namespace", "avatar_size")
