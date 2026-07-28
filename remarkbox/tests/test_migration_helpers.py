"""Tests for our alembic idempotency helpers.

These guard the failure that stranded production three revisions behind: our
deploy runs `create_all()` before `alembic upgrade head`, so a migration can
meet a table that already exists. Unguarded, that aborts the whole upgrade and
every later revision — including data migrations — never runs.
"""

import unittest

import sqlalchemy as sa

from alembic.migration import MigrationContext
from alembic.operations import Operations

from remarkbox.lib.migration_helpers import (
    create_index_if_missing,
    create_table_if_missing,
    drop_index_if_present,
    drop_table_if_present,
    index_exists,
    table_exists,
)


class MigrationHelperTests(unittest.TestCase):
    def setUp(self):
        self.engine = sa.create_engine("sqlite:///:memory:")
        self.connection = self.engine.connect()
        context = MigrationContext.configure(self.connection)
        # Helpers call op.get_bind(), which needs an active operations context.
        self._ctx = Operations.context(context)
        self._ctx.__enter__()

    def tearDown(self):
        self._ctx.__exit__(None, None, None)
        self.connection.close()
        self.engine.dispose()

    def _columns(self):
        return [
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("name", sa.Unicode(length=32), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        ]

    def test_creates_a_table_that_is_absent(self):
        self.assertFalse(table_exists("widget"))
        self.assertTrue(create_table_if_missing("widget", *self._columns()))
        self.assertTrue(table_exists("widget"))

    def test_skips_a_table_that_create_all_already_built(self):
        create_table_if_missing("widget", *self._columns())
        # Unguarded, this second call is what aborted our upgrade in production.
        self.assertFalse(create_table_if_missing("widget", *self._columns()))
        self.assertTrue(table_exists("widget"))

    def test_running_a_whole_migration_twice_is_safe(self):
        def migration():
            create_table_if_missing("widget", *self._columns())
            create_index_if_missing("ix_widget_name", "widget", ["name"])

        migration()
        migration()
        self.assertTrue(table_exists("widget"))
        self.assertTrue(index_exists("widget", "ix_widget_name"))

    def test_index_helpers_are_idempotent(self):
        create_table_if_missing("widget", *self._columns())
        self.assertTrue(create_index_if_missing("ix_widget_name", "widget", ["name"]))
        self.assertFalse(create_index_if_missing("ix_widget_name", "widget", ["name"]))

    def test_index_on_a_missing_table_reads_as_absent(self):
        """Must not raise: a guard is useless if checking it can throw."""
        self.assertFalse(index_exists("nonexistent", "ix_nope"))

    def test_drop_helpers_tolerate_what_is_already_gone(self):
        self.assertFalse(drop_table_if_present("widget"))
        create_table_if_missing("widget", *self._columns())
        create_index_if_missing("ix_widget_name", "widget", ["name"])
        self.assertTrue(drop_index_if_present("ix_widget_name", "widget"))
        self.assertFalse(drop_index_if_present("ix_widget_name", "widget"))
        self.assertTrue(drop_table_if_present("widget"))
        self.assertFalse(table_exists("widget"))


# Keep this module's tests together on one xdist worker. Test modules share a
# per-worker database; when --dist=loadgroup deals unmarked tests out
# individually, classes from different modules interleave on a worker and one
# class's tearDownClass drop_all yanks tables from another class mid-run.
import pytest as _pytest

pytestmark = _pytest.mark.xdist_group("test_migration_helpers")
