"""add mathjax column to rb_namespace

Revision ID: f5f88293428a
Revises: ba8e83a3b8fd
Create Date: 2017-10-14 23:13:46.584415

"""

# revision identifiers, used by Alembic.
revision = "f5f88293428a"
down_revision = "ba8e83a3b8fd"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.add_column(
        "rb_namespace", sa.Column("mathjax", sa.Boolean(), server_default=sa.false())
    )


def downgrade():
    op.drop_column("rb_namespace", "mathjax")
