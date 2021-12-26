"""stripe_id for User

Revision ID: 98ced5f6ff36
Revises: f5f88293428a
Create Date: 2017-10-19 10:23:30.236902

"""

# revision identifiers, used by Alembic.
revision = "98ced5f6ff36"
down_revision = "f5f88293428a"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.add_column(
        "rb_user", sa.Column("stripe_id", sa.Unicode(length=18), nullable=True)
    )


def downgrade():
    op.drop_column("rb_user", "stripe_id")
