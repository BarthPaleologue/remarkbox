"""Cron entry point: take a verified, consistent backup of our SQLite database.

Usage:
    env/bin/remarkbox_backup_db -c production.ini

One invocation backs up ONE database — the one behind the ini's
sqlalchemy.url. Our production box runs three remarkbox databases
(my.remarkbox.com, westworld2.com, foxhop.net), so salt installs three
cron entries, one per ini. See foxhop-states/remarkbox/crontab.sls.

Why not `cp remarkbox.sqlite backup.sqlite`? Our databases run in WAL mode,
so committed transactions can live in the `-wal` sidecar file rather than
the main database. Copying the one file mid-write yields a backup that is
missing recent writes at best and torn at worst. SQLite's online backup API
takes a consistent snapshot of a live database without locking writers out,
which is what this script uses.

Every backup is verified with `PRAGMA integrity_check` before it is kept.
An unverified backup is a guess, and the day we need it is the worst
possible day to discover it was a bad one.

Remote upload is optional and only happens when `backup.bucket` is set in
the ini along with explicit `backup.access_key` / `backup.secret_key`.
Credentials come from the ini (rendered by salt) — never from the command
line, where `ps aux` would expose them to every user on the box.
"""

import gzip
import logging
import os
import re
import shutil
import sqlite3
import sys
import time
from datetime import datetime, timezone

from pyramid.paster import get_appsettings, setup_logging

from .. import expand_env_vars
from . import base_parser


log = logging.getLogger(__name__)

DEFAULT_RETENTION_DAYS = 30

# Retention only ever considers files this script itself wrote: the exact
# `<database>.backup-YYYYMMDD-HHMMSS` stamp, optionally gzipped. Matching on
# a bare prefix instead would sweep up hand-made backups, an operator's
# `.bak-before-the-scary-thing`, and SQLite's own -wal/-shm sidecars.
BACKUP_STAMP = re.compile(r"^\d{8}-\d{6}(\.gz)?$")


def parse_args(argv):
    parser = base_parser(
        "Take a verified, consistent backup of our SQLite database."
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help=(
            "Directory to write backups into. Defaults to the ini's "
            "backup.directory, then to a 'backups' directory beside the "
            "database."
        ),
    )
    parser.add_argument(
        "--retention-days",
        type=int,
        default=None,
        help=(
            f"Delete backups older than this many days, locally and "
            f"remotely. Defaults to the ini's backup.retention_days, then "
            f"to {DEFAULT_RETENTION_DAYS}."
        ),
    )
    parser.add_argument(
        "--no-upload",
        action="store_true",
        help="Skip the remote upload even when a backup bucket is configured.",
    )
    parser.add_argument(
        "--no-compress",
        action="store_true",
        help="Keep the raw .sqlite snapshot instead of gzipping it.",
    )
    return parser.parse_args(argv[1:])


def database_path_from_settings(settings):
    """Return the filesystem path behind our sqlalchemy.url, or None.

    Only SQLite URLs are supported — a backup of any other backend belongs
    to that backend's own tooling (pg_dump for our postgres deployments),
    not to this script.
    """
    url = expand_env_vars(settings.get("sqlalchemy.url", ""))
    if not url.startswith("sqlite:///"):
        return None
    return url[len("sqlite:///") :]


def snapshot(source_path, destination_path, progress=None):
    """Copy a live SQLite database to destination_path, consistently.

    Uses the online backup API, which cooperates with concurrent writers
    instead of blocking them: if a write lands mid-copy, SQLite restarts
    the affected pages rather than handing us a torn file.
    """
    source = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
    try:
        destination = sqlite3.connect(destination_path)
        try:
            source.backup(destination, pages=1000, progress=progress)
            # The snapshot inherits WAL mode from the source, which would
            # make our backup a three-file set (.sqlite, -wal, -shm) that
            # is easy to separate and hard to notice is incomplete. A
            # backup artifact should be exactly one file, so fold the WAL
            # in and switch the copy to rollback journalling.
            destination.execute("PRAGMA journal_mode = DELETE")
        finally:
            destination.close()
    finally:
        source.close()


def verify(path):
    """Return True when `path` is a readable, self-consistent database."""
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        log.exception("backup_db: could not open %s for verification", path)
        return False
    try:
        result = conn.execute("PRAGMA integrity_check").fetchone()
        return bool(result) and result[0] == "ok"
    except sqlite3.Error:
        log.exception("backup_db: integrity check failed on %s", path)
        return False
    finally:
        conn.close()


def compress(path):
    """Gzip `path` in place, returning the new path."""
    compressed_path = f"{path}.gz"
    with open(path, "rb") as raw, gzip.open(compressed_path, "wb") as gz:
        shutil.copyfileobj(raw, gz)
    os.remove(path)
    return compressed_path


def is_our_backup(name, prefix):
    """True only for a filename this script generated.

    `prefix` is `<database>.backup-`; what follows must be our exact
    timestamp stamp and nothing else. This is deliberately strict — it is
    the only thing standing between a retention policy and somebody's
    hand-made backup that happened to share a prefix.
    """
    if not name.startswith(prefix):
        return False
    return bool(BACKUP_STAMP.match(name[len(prefix) :]))


def prune_local(directory, prefix, retention_days):
    """Delete backups in `directory` older than `retention_days`.

    Only files this script generated are ever considered — see
    `is_our_backup`. Callers are additionally expected not to point
    retention at the directory holding the live database; `run` enforces
    that.
    """
    if retention_days <= 0:
        return []
    cutoff = time.time() - (retention_days * 86400)
    removed = []
    for name in sorted(os.listdir(directory)):
        if not is_our_backup(name, prefix):
            continue
        path = os.path.join(directory, name)
        if not os.path.isfile(path):
            continue
        if os.path.getmtime(path) < cutoff:
            os.remove(path)
            removed.append(name)
    return removed


def backup_bucket_settings(settings):
    """Return (bucket, prefix, client_kwargs) or None when unconfigured.

    Remote backup is opt-in: without `backup.bucket` we keep local copies
    only and say so. Unlike make_post_sell there is no media-bucket
    credential fallback here — remote backup requires explicit
    backup.access_key / backup.secret_key in the ini.
    """
    bucket = expand_env_vars(settings.get("backup.bucket", "")).strip()
    if not bucket:
        return None

    def setting(name):
        return expand_env_vars(settings.get(f"backup.{name}", "")).strip()

    client_kwargs = {
        "region_name": setting("region"),
        "endpoint_url": setting("endpoint"),
        "aws_access_key_id": setting("access_key"),
        "aws_secret_access_key": setting("secret_key"),
    }
    if not client_kwargs["aws_access_key_id"]:
        log.error(
            "backup_db: backup.bucket is set but backup.access_key is not; "
            "refusing to attempt an upload."
        )
        return None

    prefix = setting("prefix")
    return bucket, prefix or "remarkbox/", client_kwargs


def upload(path, bucket, prefix, client_kwargs):
    """Upload `path` under `prefix` in `bucket`. Returns the key, or None."""
    import boto3

    session = boto3.session.Session()
    client = session.client("s3", **client_kwargs)
    key = f"{prefix}{os.path.basename(path)}"
    # private: a database backup is the single most sensitive object we own.
    client.upload_file(path, bucket, key, ExtraArgs={"ACL": "private"})
    return key


def prune_remote(bucket, prefix, client_kwargs, retention_days):
    """Delete remote backups older than `retention_days`. Returns keys removed."""
    if retention_days <= 0:
        return []
    import boto3

    session = boto3.session.Session()
    client = session.client("s3", **client_kwargs)
    cutoff = time.time() - (retention_days * 86400)
    removed = []
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            if obj["LastModified"].timestamp() < cutoff:
                client.delete_object(Bucket=bucket, Key=obj["Key"])
                removed.append(obj["Key"])
    return removed


def run(settings, output_dir=None, retention_days=None, upload_enabled=True,
        compress_enabled=True):
    """Take one backup. Returns a result dict; raises only on unusable input."""
    database_path = database_path_from_settings(settings)
    if not database_path:
        raise SystemExit(
            "backup_db: sqlalchemy.url is not a sqlite:/// path — nothing to back up."
        )
    if not os.path.exists(database_path):
        raise SystemExit(f"backup_db: no database at {database_path}")

    if output_dir is None:
        output_dir = expand_env_vars(settings.get("backup.directory", "")).strip()
    if not output_dir:
        output_dir = os.path.join(os.path.dirname(database_path) or ".", "backups")

    if retention_days is None:
        configured = expand_env_vars(settings.get("backup.retention_days", "")).strip()
        retention_days = int(configured) if configured else DEFAULT_RETENTION_DAYS

    # umask 077 before creating the directory: a database backup must never
    # be world-readable, and our permacomputer nodes alert on files that are.
    previous_umask = os.umask(0o077)
    try:
        os.makedirs(output_dir, exist_ok=True)

        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        prefix = f"{os.path.basename(database_path)}.backup-"
        destination = os.path.join(output_dir, f"{prefix}{stamp}")

        started = time.time()
        snapshot(database_path, destination)

        if not verify(destination):
            os.remove(destination)
            raise SystemExit(
                "backup_db: integrity check FAILED — backup discarded. "
                "Investigate the source database before trusting any backup."
            )

        raw_bytes = os.path.getsize(destination)
        if compress_enabled:
            destination = compress(destination)
        os.chmod(destination, 0o600)
        stored_bytes = os.path.getsize(destination)
        elapsed = time.time() - started
    finally:
        os.umask(previous_umask)

    # Never run retention against the directory holding the live database.
    # That directory is shared with hand-made backups, operator scratch
    # copies, and — on our box — the OTHER two live remarkbox databases.
    # Retention belongs to a directory this script owns outright.
    live_directory = os.path.abspath(os.path.dirname(database_path) or ".")
    prunes_live_directory = os.path.abspath(output_dir) == live_directory
    if prunes_live_directory and retention_days > 0:
        log.info(
            "backup_db: skipping retention — %s holds the live database. "
            "Point --output-dir at a dedicated backup directory to enable it.",
            output_dir,
        )

    result = {
        "path": destination,
        "raw_bytes": raw_bytes,
        "stored_bytes": stored_bytes,
        "seconds": elapsed,
        "pruned_local": (
            []
            if prunes_live_directory
            else prune_local(output_dir, prefix, retention_days)
        ),
        "retention_skipped": prunes_live_directory,
        "uploaded_key": None,
        "pruned_remote": [],
        "retention_days": retention_days,
    }

    bucket_settings = backup_bucket_settings(settings) if upload_enabled else None
    if bucket_settings:
        bucket, remote_prefix, client_kwargs = bucket_settings
        try:
            result["uploaded_key"] = upload(
                destination, bucket, remote_prefix, client_kwargs
            )
            result["pruned_remote"] = prune_remote(
                bucket, remote_prefix, client_kwargs, retention_days
            )
        except Exception:
            # A failed upload must not discard a good local backup, and must
            # not exit non-zero in a way that hides that we still have one.
            log.exception("backup_db: remote upload failed; local backup kept")

    return result


def main(argv=sys.argv):
    args = parse_args(argv)
    setup_logging(args.config)
    settings = get_appsettings(args.config)

    result = run(
        settings,
        output_dir=args.output_dir,
        retention_days=args.retention_days,
        upload_enabled=not args.no_upload,
        compress_enabled=not args.no_compress,
    )

    megabytes = result["stored_bytes"] / (1024 * 1024)
    print(
        f"backup_db: wrote {result['path']} "
        f"({megabytes:.1f}MB, verified, {result['seconds']:.1f}s)"
    )
    if result["uploaded_key"]:
        print(f"backup_db: uploaded {result['uploaded_key']}")
    else:
        print("backup_db: no backup bucket configured — local copy only.")
    if result["retention_skipped"]:
        print(
            "backup_db: retention skipped — output directory holds the live "
            "database. Use a dedicated backup directory to enable it."
        )
    elif result["pruned_local"]:
        print(
            f"backup_db: pruned {len(result['pruned_local'])} local backup(s) "
            f"older than {result['retention_days']} days"
        )
    if result["pruned_remote"]:
        print(
            f"backup_db: pruned {len(result['pruned_remote'])} remote backup(s) "
            f"older than {result['retention_days']} days"
        )


if __name__ == "__main__":
    main()
