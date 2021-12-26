"""new namespace column for stylesheet uris

Revision ID: 4aeda8e797ab
Revises: 43c1e5a99d4e
Create Date: 2018-01-28 16:11:09.507278

"""

# revision identifiers, used by Alembic.
revision = "4aeda8e797ab"
down_revision = "43c1e5a99d4e"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.add_column(
        "rb_namespace",
        sa.Column("stylesheet_embed_uri", sa.Unicode(length=256), nullable=True),
    )
    op.add_column(
        "rb_namespace",
        sa.Column("stylesheet_uri", sa.Unicode(length=256), nullable=True),
    )


def downgrade():
    op.drop_column("rb_namespace", "stylesheet_uri")
    op.drop_column("rb_namespace", "stylesheet_embed_uri")
