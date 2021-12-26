"""Namespace stylesheet_embed column

Revision ID: ba8e83a3b8fd
Revises: 87fbd2b4e06e
Create Date: 2017-10-01 11:00:26.447925

"""

# revision identifiers, used by Alembic.
revision = "ba8e83a3b8fd"
down_revision = "87fbd2b4e06e"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.add_column(
        "Namespace", sa.Column("stylesheet_embed", sa.UnicodeText(), nullable=True)
    )
    op.add_column(
        "Namespace",
        sa.Column("stylesheet_embed_timestamp", sa.BigInteger(), nullable=True),
    )


def downgrade():
    op.drop_column("Namespace", "stylesheet_embed_timestamp")
    op.drop_column("Namespace", "stylesheet_embed")
