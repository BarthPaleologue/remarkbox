"""Namespace list-privacy enforcement, behind a deploy switch.

`Namespace.public` was unenforced for years and defaulted to `False`, so every
row in a live database says `False` while behaving publicly. Migration
`554e2329ebf0` backfills those rows to `True` — but nothing in our pipeline
runs migrations automatically, so code can reach production before its
migration does. Enforcing on un-backfilled data would take every namespace's
index private at once.

So enforcement is opt-in per deployment:

    namespace.enforce_private_lists = true

Off means every list stays visible exactly as before, whatever the column
says. Turn it on once `make migrate` has run against that deployment's
database. It doubles as a kill switch: if list privacy ever misbehaves,
flipping this back costs a config reload rather than a code deploy.
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
