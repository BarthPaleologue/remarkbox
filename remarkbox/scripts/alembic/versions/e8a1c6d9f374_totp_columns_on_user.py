"""authenticator app columns on user (time-based one-time password)

Revision ID: e8a1c6d9f374
Revises: c7e94b3a5f21
Create Date: 2026-07-29 02:15:00.000000

Optional login via time-based one-time password (TOTP, RFC 6238) codes
from any standard authenticator app, instead of emailed codes. Columns
store the time-based one-time password secret, its replay-protection
counter, hashed single-use paper backup codes & attempt throttling
state.
"""

# revision identifiers, used by Alembic.
revision = "e8a1c6d9f374"
down_revision = "c7e94b3a5f21"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


COLUMNS = [
    ("totp_secret", sa.Unicode(length=64), {"nullable": True}),
    ("totp_enabled", sa.Boolean(), {"nullable": False, "server_default": "0"}),
    ("totp_last_counter", sa.BigInteger(), {"nullable": True}),
    ("totp_backup_codes", sa.UnicodeText(), {"nullable": True}),
    ("totp_attempts", sa.Integer(), {"nullable": False, "server_default": "0"}),
    ("totp_attempts_timestamp", sa.BigInteger(), {"nullable": True}),
]


def upgrade():
    for name, column_type, kwargs in COLUMNS:
        op.add_column("rb_user", sa.Column(name, column_type, **kwargs))


def downgrade():
    for name, _column_type, _kwargs in reversed(COLUMNS):
        op.drop_column("rb_user", name)
