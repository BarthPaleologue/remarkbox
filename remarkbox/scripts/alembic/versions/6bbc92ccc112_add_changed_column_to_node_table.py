"""add changed column to node table

Revision ID: 6bbc92ccc112
Revises: 
Create Date: 2016-09-04 11:41:20.795668

"""

# revision identifiers, used by Alembic.
revision = "6bbc92ccc112"
down_revision = None
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa

from time import time


def upgrade():
    now = int(time() * 1000)
    op.add_column(
        "Node",
        sa.Column("changed", sa.BigInteger, nullable=False, server_default=str(now)),
    )


def downgrade():
    # this will fail for sqlite3 databases...
    op.drop_column("Node", "changed")
