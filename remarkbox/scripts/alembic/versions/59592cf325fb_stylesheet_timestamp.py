"""stylesheet_timestamp

Revision ID: 59592cf325fb
Revises: 256468780798
Create Date: 2017-07-06 00:30:42.512137

"""

# revision identifiers, used by Alembic.
revision = "59592cf325fb"
down_revision = "256468780798"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.add_column(
        "Namespace", sa.Column("stylesheet_timestamp", sa.BigInteger(), nullable=True)
    )


def downgrade():
    op.drop_column("Namespace", "stylesheet_timestamp")
