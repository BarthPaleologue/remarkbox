"""Add ip_address column to rb_node

Revision ID: 00211ed642cc
Revises: fa8402aa1a00
Create Date: 2018-05-02 02:33:50.107923

"""

# revision identifiers, used by Alembic.
revision = "00211ed642cc"
down_revision = "fa8402aa1a00"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.add_column("rb_node", sa.Column("ip_address", sa.String(45)))


def downgrade():
    op.drop_column("rb_node", "ip_address")
