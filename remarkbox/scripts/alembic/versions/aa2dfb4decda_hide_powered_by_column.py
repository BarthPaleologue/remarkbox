"""hide_powered_by column

Revision ID: aa2dfb4decda
Revises: 4aeda8e797ab
Create Date: 2018-03-15 15:44:31.591391

"""

# revision identifiers, used by Alembic.
revision = "aa2dfb4decda"
down_revision = "4aeda8e797ab"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.add_column(
        "rb_namespace", sa.Column("hide_powered_by", sa.Boolean(), nullable=True)
    )


def downgrade():
    op.drop_column("rb_namespace", "hide_powered_by")
