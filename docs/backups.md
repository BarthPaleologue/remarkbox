# Database Backups

Remarkbox runs on SQLite in WAL mode (`journal_mode=WAL`). WAL means
committed transactions can live in the `-wal` sidecar next to the main
file, so a bare `cp` of a live database can silently miss recent writes.
Never copy a live database. Every path below uses SQLite's online backup
API through `remarkbox_backup_db`, which snapshots a consistent image
while writers stay live, then integrity-checks the result before keeping
it.

## Local (development)

```bash
make backup-db        # verified snapshot of data/remarkbox.sqlite -> data/
make restore-drill    # prove the newest backup restores & carries real data
make migrate          # applies alembic migrations; depends on backup-db
```

## Your server

The remote targets are host-agnostic: point them at whatever server
runs your remarkbox install. One site dir may host several remarkbox
sites, each with its own ini + sqlite beside it; the backup loops every
ini it finds. Defaults assume a standard layout (site dir
`/opt/remarkbox`, service user `uwsgi`) & every one of them overrides
inline:

```bash
make backup-prod PROD_HOST=you@your.server
make backup-fetch PROD_HOST=you@your.server
# non-default layout:
make backup-prod PROD_HOST=you@your.server PROD_SITE_DIR=/srv/remarkbox PROD_USER=www-data
```

`backup-prod` loops over `<site dir>/*.ini` & runs the deployed
`remarkbox_backup_db` as the service user for each, so ownership stays
correct. Timestamped, gzipped, integrity-checked backups land in
`<site dir>/backups/` & old ones prune per the retention setting. A
site that fails to back up gets reported & the loop continues; the make
target exits nonzero. `backup-fetch` runs backup-prod, then copies the
newest backups into `./backups/` locally.

Both targets stay interactive: sudo on the server prompts for a
password. `backup-fetch` stages the uwsgi-owned files world-readable in
a private `/tmp` directory on the server, copies them down, then removes
the staging directory.

## Configuration (ini keys)

`remarkbox_backup_db` honors these keys in the ini it reads:

| key | meaning | default |
|-----|---------|---------|
| `backup.directory` | where backups land | `backups/` beside the database |
| `backup.retention_days` | prune backups older than this, locally & remotely | script default |
| `backup.bucket` | optional S3-compatible bucket for offsite upload | unset = no upload |
| `backup.access_key` / `backup.secret_key` | bucket credentials | unset |

Flags: `--no-upload` skips the bucket even when configured,
`--no-compress` keeps a raw `.sqlite` instead of gzip. Run
`remarkbox_backup_db --help` for the full list.

## Restore

1. Stop the affected site's uwsgi service.
2. Pick that site's backup & gunzip it: `gunzip -k <backup>.sqlite.gz`.
3. Check it: `sqlite3 <backup>.sqlite "PRAGMA integrity_check;"`.
4. Move the broken database aside (never delete it), put the backup at
   the path named by the site ini's `sqlalchemy.url`, then
   `chown uwsgi:uwsgi` & `chmod 600` it.
5. Start the service & verify a real page load.

Run `make restore-drill` monthly; a backup nobody has restored is a
hope, not a backup.

## Cadence

Deploys do not back up automatically; alembic runs on every deploy, so
run `make backup-prod` before pushing schema-changing work. For a
scheduled net, add a daily cron on your server (as your service user)
looping the same command `backup-prod` uses. Offsite copies: configure
`backup.bucket` per ini, or run `make backup-fetch` from any
workstation & let that machine's own backup regime carry the files.
