"""Add created_timestamp column to Oauth class, add email_notify enum to Namespace

Revision ID: a26302bcfa25
Revises: 00211ed642cc
Create Date: 2018-05-26 19:18:53.858014

"""

# revision identifiers, used by Alembic.
revision = "a26302bcfa25"
down_revision = "00211ed642cc"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.add_column(
        "rb_oauth",
        sa.Column(
            "created_timestamp",
            sa.BigInteger(),
            nullable=False,
            server_default="1527378962438",
        ),
    )
    op.add_column(
        "rb_namespace",
        sa.Column(
            "email_notify",
            sa.Enum("immediately", "daily", "weekly", name="email_notify"),
            nullable=True,
        ),
    )


def downgrade():
    op.drop_column("rb_oauth", "created_timestamp")
    op.drop_column("rb_namespace", "email_notify")
