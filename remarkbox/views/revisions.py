"""HTML revision history view with side-by-side diffs."""

import difflib

from pyramid.view import view_config
from pyramid.httpexceptions import HTTPNotFound

from remarkbox.models.node import get_node_by_id
from remarkbox.models.revision import Revision


@view_config(route_name="node-revisions-html", renderer="revision-history.j2")
def node_revisions_html(request):
    node_id = request.matchdict["node_id"]
    node = get_node_by_id(request.dbsession, node_id)

    if node is None:
        raise HTTPNotFound()

    revisions = (
        request.dbsession.query(Revision)
        .filter(Revision.node_id == node.id)
        .order_by(Revision.revision_number.asc())
        .all()
    )

    d = difflib.HtmlDiff(wrapcolumn=80)
    entries = []
    for i, rev in enumerate(revisions):
        prev = revisions[i - 1] if i > 0 else None
        from_lines = prev.data.splitlines() if prev else []
        to_lines = rev.data.splitlines()
        from_desc = "rev {}".format(prev.revision_number) if prev else "empty"
        to_desc = "rev {}".format(rev.revision_number)
        diff_html = d.make_table(
            from_lines, to_lines,
            fromdesc=from_desc, todesc=to_desc,
            context=True, numlines=2,
        )
        entries.append({
            "revision": rev,
            "diff_html": diff_html,
        })

    # Most recent first
    entries.reverse()

    return {
        "node": node,
        "entries": entries,
        "title": "{} — revision history".format(node.title or node_id),
    }
