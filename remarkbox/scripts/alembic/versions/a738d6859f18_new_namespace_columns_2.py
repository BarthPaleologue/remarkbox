"""new namespace columns 2

Revision ID: a738d6859f18
Revises: 98ced5f6ff36
Create Date: 2017-11-06 00:05:09.284352

"""

# revision identifiers, used by Alembic.
revision = "a738d6859f18"
down_revision = "98ced5f6ff36"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.add_column(
        "rb_namespace",
        sa.Column("google_analytics_id", sa.Unicode(length=18), nullable=True),
    )
    op.add_column(
        "rb_namespace",
        sa.Column("no_nodes_text", sa.Unicode(length=256), nullable=True),
    )
    op.add_column(
        "rb_namespace",
        sa.Column("owner_request_timestamp", sa.BigInteger(), nullable=True),
    )


def downgrade():
    op.drop_column("rb_namespace", "owner_request_timestamp")
    op.drop_column("rb_namespace", "no_nodes_text")
    op.drop_column("rb_namespace", "google_analytics_id")
