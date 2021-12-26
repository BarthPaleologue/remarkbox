"""notification columns to rb_user table

Revision ID: 6fc1d0cf350c
Revises: a26302bcfa25
Create Date: 2018-05-27 21:04:17.704776

"""

# revision identifiers, used by Alembic.
revision = "6fc1d0cf350c"
down_revision = "a26302bcfa25"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.add_column(
        "rb_user",
        sa.Column(
            "auto_watch_threads_i_create",
            sa.Boolean(),
            nullable=False,
            server_default="1",
        ),
    )
    op.add_column(
        "rb_user",
        sa.Column(
            "auto_watch_threads_i_participate",
            sa.Boolean(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "rb_user",
        sa.Column(
            "default_node_watcher_frequency",
            sa.Enum("immediately", "daily", "weekly", name="frequency"),
            nullable=False,
            server_default="daily",
        ),
    )


def downgrade():
    op.drop_column("rb_user", "default_node_watcher_frequency")
    op.drop_column("rb_user", "auto_watch_threads_i_participate")
    op.drop_column("rb_user", "auto_watch_threads_i_create")
