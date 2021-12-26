"""new namespace column 3

Revision ID: 43c1e5a99d4e
Revises: a738d6859f18
Create Date: 2017-11-11 10:35:40.930389

"""

# revision identifiers, used by Alembic.
revision = "43c1e5a99d4e"
down_revision = "a738d6859f18"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.add_column(
        "rb_namespace",
        sa.Column("placeholder_text", sa.Unicode(length=256), nullable=True),
    )


def downgrade():
    op.drop_column("rb_namespace", "placeholder_text")
