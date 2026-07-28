"""Namespace list-privacy enforcement, behind a deploy switch.

`Namespace.public` was unenforced for years and defaulted to `False`, so every
row in a live database says `False` while behaving publicly. Migration
`554e2329ebf0` backfills those rows to `True`.

Namespaces are public by default — the column defaults to `True`, NULL reads
as public, and salt applies our backfill on every release (`alembic upgrade
head`, in `foxhop-states/uwsgi/sites.sls`). Privacy is something an owner
chooses, so enforcement is on by default and needs no configuration.

The setting remains only as a kill switch:

    namespace.enforce_private_lists = false

Set that if list privacy ever misbehaves, or on a database that predates our
backfill (a restored pre-backfill backup, a hand-rolled install that skipped
`make migrate`) where rows still read `False` and enforcing would hide every
index at once. Backing out costs a config reload rather than a code deploy.
"""


SETTING = "namespace.enforce_private_lists"


def enforcement_enabled(settings):
    """True when this deployment enforces `Namespace.public`. On by default."""
    if not settings:
        return True
    return settings.get(SETTING, "true").strip().lower() in ("true", "1", "yes")


def list_is_visible(request, namespace):
    """True when this caller may enumerate `namespace`'s threads."""
    if not enforcement_enabled(request.registry.settings):
        return True
    return namespace.can_list_roots(request.user)
