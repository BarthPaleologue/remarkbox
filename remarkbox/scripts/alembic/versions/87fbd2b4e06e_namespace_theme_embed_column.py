"""namespace theme embed column

Revision ID: 87fbd2b4e06e
Revises: 591800942adf
Create Date: 2017-09-27 10:20:27.168937

"""

# revision identifiers, used by Alembic.
revision = "87fbd2b4e06e"
down_revision = "591800942adf"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.add_column(
        "Namespace", sa.Column("theme_embed", sa.Unicode(length=256), nullable=True)
    )


def downgrade():
    op.drop_column("Namespace", "theme_embed")
