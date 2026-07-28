"""Namespace list-privacy enforcement, behind a deploy switch.

`Namespace.public` was unenforced for years and defaulted to `False`, so every
row in a live database says `False` while behaving publicly. Migration
`554e2329ebf0` backfills those rows to `True`.

Salt does run `alembic upgrade head` on every release
(`foxhop-states/uwsgi/sites.sls`) — but do not conclude from that that any
given database is backfilled. On 2026-07-27 production still read
`public = False` everywhere despite that step, and enabling enforcement took
every thread index to 403 for eleven minutes. Salt also runs
`Base.metadata.create_all()` immediately beforehand, which builds missing
tables straight from our models and knows nothing about alembic, so a table
existing proves nothing about which migrations ran. T22 tracks the stalled
chain; `docs/postmortem-2026-07-27-thread-index-403.md` has the full account.

Enforcement is therefore opt-in per deployment:

    namespace.enforce_private_lists = true

Off means every list stays visible exactly as before, whatever the column
says. Turn it on only after **observing** that deployment's rows — read the
data, do not reason about the pipeline. It doubles as a kill switch: backing
out costs a config reload rather than a code deploy, which is the only reason
that outage lasted minutes instead of longer.
"""


SETTING = "namespace.enforce_private_lists"


def enforcement_enabled(settings):
    """True when this deployment enforces `Namespace.public`."""
    if not settings:
        return False
    return settings.get(SETTING, "false").strip().lower() in ("true", "1", "yes")


def list_is_visible(request, namespace):
    """True when this caller may enumerate `namespace`'s threads."""
    if not enforcement_enabled(request.registry.settings):
        return True
    return namespace.can_list_roots(request.user)
