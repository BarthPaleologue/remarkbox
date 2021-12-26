"""Add link_protection column to Namespace

Revision ID: fa8402aa1a00
Revises: 0208c10ea67f
Create Date: 2018-04-05 15:08:49.493735

"""

# revision identifiers, used by Alembic.
revision = "fa8402aa1a00"
down_revision = "0208c10ea67f"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.add_column(
        "rb_namespace", sa.Column("link_protection", sa.Boolean(), nullable=True)
    )


def downgrade():
    op.drop_column("rb_namespace", "link_protection")
