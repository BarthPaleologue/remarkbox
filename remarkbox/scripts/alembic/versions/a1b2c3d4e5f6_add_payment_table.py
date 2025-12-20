"""Add payment table for Stripe Checkout

Revision ID: a1b2c3d4e5f6
Revises: fa8402aa1a00
Create Date: 2024-12-19

"""

# revision identifiers, used by Alembic.
revision = "a1b2c3d4e5f6"
down_revision = None
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa
from sqlalchemy_utils import UUIDType


def upgrade():
    op.create_table(
        "rb_payment",
        sa.Column("id", UUIDType(binary=False), primary_key=True, index=True),
        sa.Column("user_id", UUIDType(binary=False), sa.ForeignKey("rb_user.id"), index=True, nullable=False),
        sa.Column("stripe_session_id", sa.Unicode(128), unique=True, nullable=False, index=True),
        sa.Column(
            "payment_type",
            sa.Enum("pay_what_you_want", "annual", "top_up", name="payment_type_enum"),
            nullable=False,
        ),
        sa.Column("amount_cents", sa.BigInteger(), nullable=False),
        sa.Column("duration_months", sa.BigInteger(), default=0, nullable=False),
        sa.Column(
            "status",
            sa.Enum("pending", "completed", "failed", "refunded", name="payment_status_enum"),
            default="pending",
            nullable=False,
        ),
        sa.Column("created_timestamp", sa.BigInteger(), nullable=False),
        sa.Column("completed_timestamp", sa.BigInteger(), nullable=True),
    )


def downgrade():
    op.drop_table("rb_payment")
    op.execute("DROP TYPE IF EXISTS payment_type_enum")
    op.execute("DROP TYPE IF EXISTS payment_status_enum")
