"""Backup + restore-drill + WAL engine tests.

Ported from make_post_sell's MPS-28 suite — same scripts, same
guarantees: our nightly backup produces a verified, self-contained,
consistent copy, never deletes anything it did not create, and the
drill proves the newest backup actually restores.
"""

import gzip
import os
import shutil
import sqlite3
import stat
import tempfile
import time
import unittest

import mock


REVISION = "abc123def456"


def _make_database(path, revision=REVISION):
    conn = sqlite3.connect(path)
    # WAL, exactly as our application runs it — the mode that makes a
    # plain file copy an unreliable backup.
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("CREATE TABLE rb_user (id TEXT PRIMARY KEY, name TEXT)")
    conn.execute("CREATE TABLE rb_namespace (id TEXT PRIMARY KEY)")
    conn.execute("CREATE TABLE rb_node (id TEXT PRIMARY KEY)")
    conn.execute("CREATE TABLE rb_uri (id TEXT PRIMARY KEY)")
    conn.execute("CREATE TABLE rb_watcher (id TEXT PRIMARY KEY)")
    conn.execute("CREATE TABLE alembic_version (version_num TEXT)")
    conn.execute(f"INSERT INTO alembic_version VALUES ('{revision}')")
    conn.execute("INSERT INTO rb_user VALUES ('user-1', 'Test User')")
    conn.execute("INSERT INTO rb_namespace VALUES ('ns-1')")
    conn.commit()
    conn.close()


class TestEngineWALPragmas(unittest.TestCase):
    """get_engine must put SQLite databases into WAL mode with NORMAL
    syncing, and must NOT flip on foreign-key enforcement (historical
    orphan rows would start rejecting deletes)."""

    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.path = os.path.join(self.directory, "engine-test.sqlite")

    def tearDown(self):
        shutil.rmtree(self.directory, ignore_errors=True)

    def test_sqlite_engine_runs_wal_normal_no_fk(self):
        from remarkbox.models import get_engine

        engine = get_engine({"sqlalchemy.url": f"sqlite:///{self.path}"})
        with engine.connect() as conn:
            raw = conn.connection
            self.assertEqual(
                raw.execute("PRAGMA journal_mode").fetchone()[0], "wal"
            )
            # synchronous: 1 == NORMAL
            self.assertEqual(raw.execute("PRAGMA synchronous").fetchone()[0], 1)
            self.assertEqual(raw.execute("PRAGMA foreign_keys").fetchone()[0], 0)
        engine.dispose()


class TestBackupDb(unittest.TestCase):
    """Our nightly backup produces a verified, self-contained, consistent
    copy — and never deletes anything it did not create. These drive the
    real script against a real SQLite file rather than mocking the
    interesting parts away."""

    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.database_path = os.path.join(self.directory, "remarkbox.sqlite")
        _make_database(self.database_path)
        self.settings = {"sqlalchemy.url": f"sqlite:///{self.database_path}"}

    def tearDown(self):
        shutil.rmtree(self.directory, ignore_errors=True)

    def _run(self, **kwargs):
        from remarkbox.scripts.backup_db import run

        kwargs.setdefault("upload_enabled", False)
        return run(self.settings, **kwargs)

    def test_backup_is_written_verified_and_self_contained(self):
        result = self._run(compress_enabled=False)

        self.assertTrue(os.path.exists(result["path"]))
        # One file, not three: no -wal/-shm sidecars beside the artifact,
        # which is what makes a backup safe to move or upload alone.
        for suffix in ("-wal", "-shm"):
            self.assertFalse(
                os.path.exists(result["path"] + suffix),
                f"backup left a {suffix} sidecar behind",
            )

    def test_backup_contains_our_rows(self):
        result = self._run(compress_enabled=False)
        conn = sqlite3.connect(result["path"])
        try:
            self.assertEqual(
                conn.execute("SELECT name FROM rb_user").fetchone()[0], "Test User"
            )
        finally:
            conn.close()

    def test_compressed_backup_restores(self):
        result = self._run(compress_enabled=True)
        self.assertTrue(result["path"].endswith(".gz"))

        restored = os.path.join(self.directory, "restored.sqlite")
        with gzip.open(result["path"], "rb") as gz, open(restored, "wb") as raw:
            raw.write(gz.read())
        conn = sqlite3.connect(restored)
        try:
            self.assertEqual(
                conn.execute("SELECT count(*) FROM rb_user").fetchone()[0], 1
            )
        finally:
            conn.close()

    def test_backup_is_not_world_readable(self):
        result = self._run(compress_enabled=False)
        mode = stat.S_IMODE(os.stat(result["path"]).st_mode)
        self.assertEqual(
            mode & 0o077, 0, "a database backup must not be group/world readable"
        )

    def test_retention_never_runs_in_the_live_database_directory(self):
        """The guard that matters most on our box: /opt/remarkbox holds
        THREE live databases plus hand-made backups. Pointed there,
        retention must refuse."""
        ours = os.path.join(self.directory, "remarkbox.sqlite.backup-20200101-000000")
        theirs = os.path.join(
            self.directory, "remarkbox.sqlite.backup-before-the-scary-thing"
        )
        for path in (ours, theirs):
            with open(path, "w") as f:
                f.write("x")
            ancient = time.time() - (400 * 86400)
            os.utime(path, (ancient, ancient))

        result = self._run(
            output_dir=self.directory, retention_days=30, compress_enabled=False
        )

        self.assertTrue(result["retention_skipped"])
        self.assertEqual(result["pruned_local"], [])
        self.assertTrue(os.path.exists(ours))
        self.assertTrue(os.path.exists(theirs))

    def test_retention_only_removes_files_we_generated(self):
        backup_dir = os.path.join(self.directory, "backups")
        os.makedirs(backup_dir)

        ours = os.path.join(backup_dir, "remarkbox.sqlite.backup-20200101-000000")
        ours_gz = os.path.join(
            backup_dir, "remarkbox.sqlite.backup-20200102-000000.gz"
        )
        theirs = os.path.join(
            backup_dir, "remarkbox.sqlite.backup-before-the-scary-thing"
        )
        unrelated = os.path.join(backup_dir, "notes.txt")
        for path in (ours, ours_gz, theirs, unrelated):
            with open(path, "w") as f:
                f.write("x")
            ancient = time.time() - (400 * 86400)
            os.utime(path, (ancient, ancient))

        result = self._run(
            output_dir=backup_dir, retention_days=30, compress_enabled=False
        )

        self.assertFalse(result["retention_skipped"])
        self.assertFalse(os.path.exists(ours))
        self.assertFalse(os.path.exists(ours_gz))
        # not ours, not deleted.
        self.assertTrue(os.path.exists(theirs))
        self.assertTrue(os.path.exists(unrelated))
        # and today's backup survives its own retention pass.
        self.assertTrue(os.path.exists(result["path"]))

    def test_retention_disabled_keeps_everything(self):
        backup_dir = os.path.join(self.directory, "backups")
        os.makedirs(backup_dir)
        old = os.path.join(backup_dir, "remarkbox.sqlite.backup-20200101-000000")
        with open(old, "w") as f:
            f.write("x")
        ancient = time.time() - (400 * 86400)
        os.utime(old, (ancient, ancient))

        self._run(output_dir=backup_dir, retention_days=0, compress_enabled=False)

        self.assertTrue(os.path.exists(old))

    def test_sibling_database_backups_are_never_touched(self):
        """Three databases share one backups/ directory on our box. A
        my.remarkbox.com run must never prune westworld2 or foxhop
        backups — the prefix embeds the database filename."""
        backup_dir = os.path.join(self.directory, "backups")
        os.makedirs(backup_dir)
        siblings = [
            os.path.join(backup_dir, "westworld2.com.sqlite.backup-20200101-000000"),
            os.path.join(backup_dir, "foxhop.net.sqlite.backup-20200101-000000.gz"),
        ]
        for path in siblings:
            with open(path, "w") as f:
                f.write("x")
            ancient = time.time() - (400 * 86400)
            os.utime(path, (ancient, ancient))

        self._run(output_dir=backup_dir, retention_days=30, compress_enabled=False)

        for path in siblings:
            self.assertTrue(
                os.path.exists(path), f"pruned a sibling database's backup: {path}"
            )

    def test_corrupt_source_is_not_kept_as_a_backup(self):
        """A backup that fails its integrity check is discarded loudly."""
        from remarkbox.scripts import backup_db

        with mock.patch.object(backup_db, "verify", return_value=False):
            with self.assertRaises(SystemExit):
                self._run(compress_enabled=False)

        leftovers = [
            name
            for name in os.listdir(self.directory)
            if name.startswith("remarkbox.sqlite.backup-")
        ]
        self.assertEqual(leftovers, [], "a failed backup was left on disk")

    def test_missing_database_is_reported(self):
        os.remove(self.database_path)
        with self.assertRaises(SystemExit):
            self._run()

    def test_non_sqlite_url_is_refused(self):
        """Our postgres deployments back up with pg_dump, not this."""
        from remarkbox.scripts.backup_db import run

        with self.assertRaises(SystemExit):
            run({"sqlalchemy.url": "postgres://localhost/remarkbox"})

    def test_upload_is_skipped_without_a_bucket(self):
        result = self._run(upload_enabled=True, compress_enabled=False)
        self.assertIsNone(result["uploaded_key"])

    def test_upload_refused_without_explicit_credentials(self):
        """No media-bucket credential fallback here — backup.bucket
        without backup.access_key must refuse, not guess."""
        from remarkbox.scripts.backup_db import backup_bucket_settings

        self.assertIsNone(
            backup_bucket_settings({"backup.bucket": "some-bucket"})
        )


class TestRestoreDrill(unittest.TestCase):
    """The drill proves our newest backup actually restores. A backup
    nobody has restored is a rumour."""

    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.database_path = os.path.join(self.directory, "remarkbox.sqlite")
        self.backup_dir = os.path.join(self.directory, "backups")
        os.makedirs(self.backup_dir)
        self.settings = {"sqlalchemy.url": f"sqlite:///{self.database_path}"}
        _make_database(self.database_path)

    def tearDown(self):
        shutil.rmtree(self.directory, ignore_errors=True)

    def _backup(self, **kwargs):
        from remarkbox.scripts.backup_db import run

        kwargs.setdefault("upload_enabled", False)
        kwargs.setdefault("compress_enabled", False)
        return run(self.settings, output_dir=self.backup_dir, **kwargs)

    def test_drill_passes_on_a_real_backup(self):
        from remarkbox.scripts.restore_drill import inspect, newest_backup, restore

        self._backup()
        path = newest_backup(self.backup_dir, "remarkbox.sqlite.backup-")
        self.assertIsNotNone(path)

        handle, scratch = tempfile.mkstemp(suffix=".sqlite")
        os.close(handle)
        try:
            restore(path, scratch)
            ok, findings = inspect(scratch)
            self.assertTrue(ok, findings)
            self.assertTrue(any(REVISION in f for f in findings))
        finally:
            os.remove(scratch)

    def test_drill_reads_a_compressed_backup(self):
        from remarkbox.scripts.restore_drill import inspect, newest_backup, restore

        self._backup(compress_enabled=True)
        path = newest_backup(self.backup_dir, "remarkbox.sqlite.backup-")
        self.assertTrue(path.endswith(".gz"))

        handle, scratch = tempfile.mkstemp(suffix=".sqlite")
        os.close(handle)
        try:
            restore(path, scratch)
            ok, findings = inspect(scratch)
            self.assertTrue(ok, findings)
        finally:
            os.remove(scratch)

    def test_sidecars_are_never_mistaken_for_a_backup(self):
        from remarkbox.scripts.restore_drill import newest_backup

        result = self._backup()
        sidecar = result["path"] + "-shm"
        with open(sidecar, "w") as f:
            f.write("not a database")

        found = newest_backup(self.backup_dir, "remarkbox.sqlite.backup-")
        self.assertEqual(found, result["path"])

    def test_drill_only_sees_its_own_database_backups(self):
        """Per-ini isolation: the my.remarkbox.com drill must find
        my.remarkbox.com backups, never a fresher sibling's."""
        from remarkbox.scripts.restore_drill import newest_backup

        result = self._backup()
        # a fresher backup of a DIFFERENT database in the same directory.
        sibling = os.path.join(
            self.backup_dir, "westworld2.com.sqlite.backup-20990101-000000"
        )
        with open(sibling, "w") as f:
            f.write("x")

        found = newest_backup(self.backup_dir, "remarkbox.sqlite.backup-")
        self.assertEqual(found, result["path"])

    def test_drill_fails_on_a_truncated_backup(self):
        from remarkbox.scripts.restore_drill import inspect

        handle, scratch = tempfile.mkstemp(suffix=".sqlite")
        os.close(handle)
        try:
            with open(scratch, "wb") as f:
                f.write(b"this is not a database")
            ok, findings = inspect(scratch)
            self.assertFalse(ok)
            self.assertTrue(findings)
        finally:
            os.remove(scratch)

    def test_drill_fails_when_core_tables_are_empty(self):
        from remarkbox.scripts.restore_drill import inspect

        handle, scratch = tempfile.mkstemp(suffix=".sqlite")
        os.close(handle)
        try:
            conn = sqlite3.connect(scratch)
            for table in ("rb_user", "rb_namespace", "rb_node", "rb_uri", "rb_watcher"):
                conn.execute(f"CREATE TABLE {table} (id TEXT PRIMARY KEY)")
            conn.execute("CREATE TABLE alembic_version (version_num TEXT)")
            conn.execute(f"INSERT INTO alembic_version VALUES ('{REVISION}')")
            conn.commit()
            conn.close()

            ok, findings = inspect(scratch)
            self.assertFalse(ok)
            self.assertTrue(any("empty" in f for f in findings))
        finally:
            os.remove(scratch)

    def test_drill_fails_when_a_table_is_missing(self):
        from remarkbox.scripts.restore_drill import inspect

        handle, scratch = tempfile.mkstemp(suffix=".sqlite")
        os.close(handle)
        try:
            conn = sqlite3.connect(scratch)
            conn.execute("CREATE TABLE rb_user (id TEXT PRIMARY KEY)")
            conn.execute("INSERT INTO rb_user VALUES ('user-1')")
            conn.commit()
            conn.close()

            ok, findings = inspect(scratch)
            self.assertFalse(ok)
            self.assertTrue(any("missing tables" in f for f in findings))
        finally:
            os.remove(scratch)
