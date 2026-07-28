"""Cron entry point: prove our newest backup actually restores.

Usage:
    env/bin/remarkbox_restore_drill -c production.ini

Cron suggestion: monthly, shortly after that night's backup, one entry
per ini (we run three remarkbox databases on our production box).

A backup nobody has restored is a rumour. This drill takes the newest
backup we hold for this ini's database, restores it into a scratch copy,
and asks it the questions we would ask on the worst day: does it open,
does it pass an integrity check, does it carry the schema at the revision
our code expects, and does it still contain users, namespaces, and nodes.

It never touches the live database — the restore target is a temporary file
that is deleted on the way out — so it is safe to run on the production box.
"""

import gzip
import logging
import os
import shutil
import sqlite3
import sys
import tempfile

from pyramid.paster import get_appsettings, setup_logging

from .. import expand_env_vars
from . import base_parser
from .backup_db import database_path_from_settings, is_our_backup, verify


log = logging.getLogger(__name__)

# Tables whose emptiness would mean we restored something useless.
EXPECTED_POPULATED_TABLES = ("rb_user", "rb_namespace")

# Tables we expect to exist even when empty.
EXPECTED_TABLES = (
    "rb_user",
    "rb_namespace",
    "rb_node",
    "rb_uri",
    "rb_watcher",
    "alembic_version",
)


def parse_args(argv):
    parser = base_parser(
        "Restore our newest backup into a scratch file and check it."
    )
    parser.add_argument(
        "--backup-dir",
        default=None,
        help=(
            "Directory holding backups. Defaults to the ini's "
            "backup.directory, then to a 'backups' directory beside the "
            "database."
        ),
    )
    parser.add_argument(
        "--keep",
        action="store_true",
        help="Keep the restored scratch database instead of deleting it.",
    )
    return parser.parse_args(argv[1:])


def newest_backup(directory, prefix):
    """Return the path of the most recent backup we hold, or None.

    Matches only files backup_db generated, so SQLite's -wal/-shm sidecars
    (and the other two live databases sharing /opt/remarkbox) can never be
    mistaken for a backup.
    """
    if not os.path.isdir(directory):
        return None
    candidates = [
        os.path.join(directory, name)
        for name in os.listdir(directory)
        if is_our_backup(name, prefix)
        and os.path.isfile(os.path.join(directory, name))
    ]
    if not candidates:
        return None
    return max(candidates, key=os.path.getmtime)


def restore(backup_path, destination_path):
    """Materialize `backup_path` (gzipped or not) at `destination_path`."""
    if backup_path.endswith(".gz"):
        with gzip.open(backup_path, "rb") as gz, open(destination_path, "wb") as raw:
            shutil.copyfileobj(gz, raw)
    else:
        shutil.copyfile(backup_path, destination_path)
    return destination_path


def inspect(path):
    """Run our restore assertions. Returns (ok, list_of_findings)."""
    findings = []
    ok = True

    if not verify(path):
        return False, ["integrity_check did not return ok"]
    findings.append("integrity_check ok")

    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        present = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        missing = [table for table in EXPECTED_TABLES if table not in present]
        if missing:
            ok = False
            findings.append(f"missing tables: {', '.join(missing)}")
        else:
            findings.append(f"all {len(EXPECTED_TABLES)} expected tables present")

        if "alembic_version" in present:
            revision = conn.execute(
                "SELECT version_num FROM alembic_version"
            ).fetchone()
            if revision:
                findings.append(f"schema at alembic revision {revision[0]}")
            else:
                ok = False
                findings.append("alembic_version table is empty")

        for table in EXPECTED_POPULATED_TABLES:
            if table not in present:
                continue
            count = conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            if count == 0:
                ok = False
                findings.append(f"{table} is empty")
            else:
                findings.append(f"{table}: {count} rows")
    finally:
        conn.close()

    return ok, findings


def main(argv=sys.argv):
    args = parse_args(argv)
    setup_logging(args.config)
    settings = get_appsettings(args.config)

    database_path = database_path_from_settings(settings)
    if not database_path:
        raise SystemExit(
            "restore_drill: sqlalchemy.url is not a sqlite:/// path — nothing to drill."
        )

    backup_dir = args.backup_dir
    if backup_dir is None:
        backup_dir = expand_env_vars(settings.get("backup.directory", "")).strip()
    if not backup_dir:
        backup_dir = os.path.join(os.path.dirname(database_path) or ".", "backups")

    prefix = f"{os.path.basename(database_path)}.backup-"
    backup_path = newest_backup(backup_dir, prefix)
    if not backup_path:
        raise SystemExit(
            f"restore_drill: FAILED — no backups found in {backup_dir}. "
            "We are running without a tested recovery path."
        )

    handle, scratch_path = tempfile.mkstemp(prefix="restore-drill-", suffix=".sqlite")
    os.close(handle)
    try:
        restore(backup_path, scratch_path)
        ok, findings = inspect(scratch_path)

        print(f"restore_drill: restored {backup_path}")
        for finding in findings:
            print(f"restore_drill:   {finding}")

        if not ok:
            raise SystemExit("restore_drill: FAILED — see findings above.")
        print("restore_drill: PASSED — our newest backup restores cleanly.")
        if args.keep:
            print(f"restore_drill: scratch database kept at {scratch_path}")
    finally:
        if not args.keep and os.path.exists(scratch_path):
            os.remove(scratch_path)


if __name__ == "__main__":
    main()
