"""namespace description

Revision ID: 1040ee4836af
Revises: cbdf3cd4ccba
Create Date: 2017-07-15 23:25:12.010472

"""

# revision identifiers, used by Alembic.
revision = "1040ee4836af"
down_revision = "cbdf3cd4ccba"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.add_column(
        "Namespace", sa.Column("description", sa.Unicode(length=256), nullable=True)
    )


def downgrade():
    op.drop_column("Namespace", "description")
