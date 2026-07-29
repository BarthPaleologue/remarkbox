"""multi-factor methods table replaces single totp secret

Revision ID: 8aa65ccc4241
Revises: e8a1c6d9f374
Create Date: 2026-07-29 17:31:06.730499

One authenticator secret per user only ever let somebody carry one
device: losing that phone dropped the account back to emailed codes, and
swapping phones meant a window with no second factor at all. Each
enrolled factor now lives as its own `rb_mfa_method` row, labelled and
revocable on its own, so removing one device leaves every other one
signing in.

Only account-level state stays on `rb_user`: hashed single-use paper
backup codes, plus the attempt throttle shared across every factor.

This revision backfills before it drops. We expect zero enrolled users
(`totp_enabled` shipped days ago and nobody turned it on), but an
enrollment must never vanish on a schema change, so any user carrying one
gets a `rb_mfa_method` row built from their existing columns first.

The backfilled secret is copied VERBATIM, which means it lands in the new
column as plaintext rather than in the wrapped `v1:` form that
`encrypt_secret` writes. That is deliberate and safe: `decrypt_secret`
returns an unprefixed value unchanged precisely so an enrollment written
before encryption existed keeps verifying instead of locking its owner
out. Re-enrolling the device, or any future rewrite, replaces it with a
wrapped secret.
"""

# revision identifiers, used by Alembic.
revision = '8aa65ccc4241'
down_revision = 'e8a1c6d9f374'
branch_labels = None
depends_on = None

import time
import uuid

from alembic import op
import sqlalchemy as sa
import sqlalchemy_utils

from remarkbox.lib.migration_helpers import (
    create_index_if_missing,
    create_table_if_missing,
    drop_index_if_present,
    drop_table_if_present,
)


def now_timestamp():
    """Epoch milliseconds. Inlined so this revision stays self-contained."""
    return int(time.time() * 1000)


TOTP_COLUMNS = [
    ("totp_secret", sa.Unicode(length=64), {"nullable": True}),
    ("totp_enabled", sa.Boolean(), {"nullable": False, "server_default": "0"}),
    ("totp_last_counter", sa.BigInteger(), {"nullable": True}),
    ("totp_backup_codes", sa.UnicodeText(), {"nullable": True}),
    ("totp_attempts", sa.Integer(), {"nullable": False, "server_default": "0"}),
    ("totp_attempts_timestamp", sa.BigInteger(), {"nullable": True}),
]

MFA_COLUMNS = [
    ("mfa_backup_codes", sa.UnicodeText(), {"nullable": True}),
    ("mfa_attempts", sa.Integer(), {"nullable": False, "server_default": "0"}),
    ("mfa_attempts_timestamp", sa.BigInteger(), {"nullable": True}),
]


def _user_columns():
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns("rb_user")}


def _add_missing(columns):
    """Add each column absent from `rb_user`.

    Guarded because our deploy runs create_all() before alembic: on a
    database it built from current models the column is already there.
    See T22.
    """
    present = _user_columns()
    for name, column_type, kwargs in columns:
        if name not in present:
            op.add_column("rb_user", sa.Column(name, column_type, **kwargs))


def _drop_present(names):
    """Drop each named column that `rb_user` still carries.

    SQLite gained native DROP COLUMN late and cannot drop a column
    referenced by an index, so batch mode rebuilds the table instead.
    """
    present = _user_columns()
    doomed = [name for name in names if name in present]
    if not doomed:
        return
    with op.batch_alter_table("rb_user") as batch:
        for name in doomed:
            batch.drop_column(name)


def _backfill_enrollments():
    """Carry any live authenticator enrollment into `rb_mfa_method`.

    Reads only rows holding a secret, so an account that never enrolled
    costs nothing. A truthiness check on `totp_enabled` happens in Python
    rather than SQL: SQLite stores it 0/1 while PostgreSQL stores a real
    boolean, and we support both.

    Skipped when the old columns are absent: on a database create_all
    built from current models there was never anything to carry, and
    selecting a column that does not exist would abort the chain.
    """
    present = _user_columns()
    if not {"totp_enabled", "totp_secret"} <= present:
        return

    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT id, totp_enabled, totp_secret, totp_last_counter,"
            " totp_backup_codes FROM rb_user"
            " WHERE totp_secret IS NOT NULL AND totp_secret <> ''"
        )
    ).fetchall()

    for row in rows:
        if not row.totp_enabled:
            continue
        bind.execute(
            sa.text(
                "INSERT INTO rb_mfa_method (id, user_id, method_type, label,"
                " secret, last_counter, created_timestamp,"
                " last_used_timestamp, disabled)"
                " VALUES (:id, :user_id, 'totp', 'authenticator app',"
                " :secret, :last_counter, :created_timestamp, NULL, :disabled)"
            ),
            {
                "id": uuid.uuid1().hex,
                "user_id": row.id,
                # Verbatim, so plaintext: decrypt_secret tolerates an
                # unprefixed value & keeps this device verifying.
                "secret": row.totp_secret,
                "last_counter": row.totp_last_counter,
                "created_timestamp": now_timestamp(),
                "disabled": False,
            },
        )
        bind.execute(
            sa.text(
                "UPDATE rb_user SET mfa_backup_codes = :codes WHERE id = :id"
            ),
            {"codes": row.totp_backup_codes, "id": row.id},
        )


def upgrade():
    create_table_if_missing(
        "rb_mfa_method",
        sa.Column("id", sqlalchemy_utils.types.uuid.UUIDType(binary=False), nullable=False),
        sa.Column("user_id", sqlalchemy_utils.types.uuid.UUIDType(binary=False), nullable=False),
        sa.Column("method_type", sa.Unicode(length=16), nullable=False),
        sa.Column("label", sa.Unicode(length=64), nullable=False),
        # Wide enough for the wrapped form: nonce + ciphertext + tag,
        # base64 behind a "v1:" prefix, runs 83 characters.
        sa.Column("secret", sa.Unicode(length=128), nullable=True),
        sa.Column("last_counter", sa.BigInteger(), nullable=True),
        sa.Column("created_timestamp", sa.BigInteger(), nullable=False),
        sa.Column("last_used_timestamp", sa.BigInteger(), nullable=True),
        sa.Column("disabled", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["rb_user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    create_index_if_missing(op.f("ix_rb_mfa_method_id"), "rb_mfa_method", ["id"], unique=False)
    create_index_if_missing(
        op.f("ix_rb_mfa_method_user_id"), "rb_mfa_method", ["user_id"], unique=False
    )

    _add_missing(MFA_COLUMNS)

    # Never lose an enrollment: move it before the old columns go.
    _backfill_enrollments()

    _drop_present([name for name, _type, _kwargs in TOTP_COLUMNS])


def downgrade():
    """Restore the single-secret columns from the oldest active factor.

    A secret this revision backfilled went in verbatim, so it round-trips
    exactly. A secret enrolled after the upgrade is wrapped, and the old
    single-secret code cannot unwrap it: restoring that would leave an
    account holding a secret nothing can verify. We leave those accounts
    with the authenticator turned off instead, so they fall back to
    emailed codes and can enroll again, rather than locking them out.
    """
    _add_missing(TOTP_COLUMNS)

    bind = op.get_bind()
    have_table = "rb_mfa_method" in sa.inspect(bind).get_table_names()
    if have_table and "mfa_backup_codes" in _user_columns():
        rows = bind.execute(
            sa.text(
                "SELECT user_id, secret, last_counter, disabled, method_type"
                " FROM rb_mfa_method ORDER BY created_timestamp"
            )
        ).fetchall()
        seen = set()
        for row in rows:
            # Boolean truthiness in Python, not SQL: SQLite stores 0/1
            # while PostgreSQL stores a real boolean.
            if row.disabled or row.method_type != "totp":
                continue
            if row.user_id in seen or not row.secret:
                continue
            seen.add(row.user_id)
            if row.secret.startswith("v1:"):
                continue
            bind.execute(
                sa.text(
                    "UPDATE rb_user SET totp_secret = :secret,"
                    " totp_enabled = :enabled,"
                    " totp_last_counter = :last_counter,"
                    " totp_backup_codes = mfa_backup_codes WHERE id = :id"
                ),
                {
                    "secret": row.secret,
                    "enabled": True,
                    "last_counter": row.last_counter,
                    "id": row.user_id,
                },
            )

    _drop_present([name for name, _type, _kwargs in MFA_COLUMNS])

    drop_index_if_present(op.f("ix_rb_mfa_method_user_id"), "rb_mfa_method")
    drop_index_if_present(op.f("ix_rb_mfa_method_id"), "rb_mfa_method")
    drop_table_if_present("rb_mfa_method")
