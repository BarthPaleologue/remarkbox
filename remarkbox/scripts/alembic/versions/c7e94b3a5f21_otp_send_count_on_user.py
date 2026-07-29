"""otp_send_count on user for unverified login backoff

Revision ID: c7e94b3a5f21
Revises: df0217588814
Create Date: 2026-07-28 21:45:00.000000

Anti login-bombing: bots hammer OTP login forms with victims' addresses
& a flat 90s throttle still allows ~960 emails/day to a stranger.
`otp_send_count` drives an escalating backoff ladder for accounts that
never completed a verification (90s, 10m, 1h, 6h, 24h, then 48h
forever). One successful code entry resets the ladder. Existing rows
backfill at 0: a fresh ladder for every address.
"""

# revision identifiers, used by Alembic.
revision = "c7e94b3a5f21"
down_revision = "df0217588814"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.add_column(
        "rb_user",
        sa.Column("otp_send_count", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade():
    op.drop_column("rb_user", "otp_send_count")
