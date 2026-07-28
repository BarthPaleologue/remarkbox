"""backfill namespace public to true and default new namespaces public

Revision ID: 554e2329ebf0
Revises: 8e3c406e4049
Create Date: 2026-07-27 19:55:59.192074

`Namespace.public` shipped years ago with `default=False` and was never read
by any code path, so every namespace on our platform carries `public = 0` (or
NULL, for rows predating the column) while listing its threads publicly.

Enforcing the flag without this backfill would turn every namespace private
the moment our deploy lands. So we flip our stored data to match our observed
behaviour first: every existing namespace becomes explicitly public, and
`False` becomes an opt-in an owner chooses in namespace settings.

Data-only. Our model default changes in Python (`models/namespace.py`); no
DDL runs here, which also keeps this safe on SQLite where ALTER COLUMN is not
supported natively.
"""

# revision identifiers, used by Alembic.
revision = '554e2329ebf0'
down_revision = '8e3c406e4049'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.execute(
        sa.text(
            "UPDATE rb_namespace SET public = 1 "
            "WHERE public IS NULL OR public = 0"
        )
    )


def downgrade():
    # Every row was 0 or NULL before this migration ran, so restoring that
    # state is exact rather than lossy.
    op.execute(sa.text("UPDATE rb_namespace SET public = 0"))
