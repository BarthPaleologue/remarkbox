"""Idempotency helpers for alembic migrations.

Our deploy runs `Base.metadata.create_all()` immediately before
`alembic upgrade head` (`foxhop-states/uwsgi/sites.sls`). `create_all` builds
any table our models gained, knowing nothing about alembic, so a migration
that then runs `CREATE TABLE` hits a table that already exists, raises, and
aborts the whole upgrade — taking every later revision, including data
migrations, down with it. That is how production sat three revisions behind
while its schema looked correct; see T22 and our 2026-07-27 postmortem.

Creating schema through these helpers makes a migration safe to meet a table
that `create_all` got to first: it skips what already exists and carries on,
so the chain advances and data migrations actually run.

This does not check that an existing table *matches* what the migration would
have built. It cannot — `create_all` and our migration both derive from the
same models, so in our deploy they agree by construction. If you are hand-
repairing a database whose schema may have drifted, verify before trusting a
skip.
"""

import sqlalchemy as sa
from alembic import op


def _inspector():
    return sa.inspect(op.get_bind())


def table_exists(table_name):
    """True when `table_name` is already present."""
    return table_name in _inspector().get_table_names()


def index_exists(table_name, index_name):
    """True when `index_name` is already present on `table_name`."""
    if not table_exists(table_name):
        return False
    return index_name in {ix["name"] for ix in _inspector().get_indexes(table_name)}


def create_table_if_missing(table_name, *columns, **kwargs):
    """`op.create_table`, skipped when the table already exists."""
    if table_exists(table_name):
        return False
    op.create_table(table_name, *columns, **kwargs)
    return True


def create_index_if_missing(index_name, table_name, columns, **kwargs):
    """`op.create_index`, skipped when the index already exists."""
    if index_exists(table_name, index_name):
        return False
    op.create_index(index_name, table_name, columns, **kwargs)
    return True


def drop_table_if_present(table_name):
    """`op.drop_table`, skipped when the table is already gone."""
    if not table_exists(table_name):
        return False
    op.drop_table(table_name)
    return True


def drop_index_if_present(index_name, table_name):
    """`op.drop_index`, skipped when the index is already gone."""
    if not index_exists(table_name, index_name):
        return False
    op.drop_index(index_name, table_name=table_name)
    return True
