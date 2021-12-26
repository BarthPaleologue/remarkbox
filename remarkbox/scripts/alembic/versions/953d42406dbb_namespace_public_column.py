"""namespace public column

Revision ID: 953d42406dbb
Revises: 59592cf325fb
Create Date: 2017-07-08 15:48:41.261312

"""

# revision identifiers, used by Alembic.
revision = "953d42406dbb"
down_revision = "59592cf325fb"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.add_column("Namespace", sa.Column("public", sa.Boolean(), nullable=True))


def downgrade():
    op.drop_column("Namespace", "public")
