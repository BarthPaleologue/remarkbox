"""Export API — render threads and namespaces via pandoc.

URI scheme:
    GET /api/v1/export/namespace/{name}.{format}   — full book
    GET /api/v1/export/threads/{node_id}.{format}   — single chapter
    GET /api/v1/export/nodes/{node_id}.{format}     — on-demand subthread
    GET /api/v1/export/formats                      — list available formats
"""

import logging
import subprocess

from pyramid.response import Response
from pyramid.view import view_config

from remarkbox.models.namespace import get_namespace_by_name
from remarkbox.models.node import (
    get_node_by_id,
    get_nodes_who_share_root,
)

from remarkbox.lib.pandoc import (
    convert,
    node_tree_to_markdown,
    namespace_to_markdown,
    get_available_output_formats,
    resolve_format,
    CONTENT_TYPES,
    FILE_EXTENSIONS,
    BINARY_FORMATS,
)
from remarkbox.lib import provenance as prov

from .views import check_namespace_api_access

log = logging.getLogger(__name__)


def _public_host(request):
    """Return the host the user is browsing from.

    The edge proxy rewrites the Host header (e.g. www.foxhop.net → foxhop.net)
    before reaching origin. Caddy preserves the original in X-Forwarded-Host,
    so prefer that when present — otherwise fall back to request.host.
    Handles a comma-separated chain by taking the first entry.
    """
    forwarded = request.headers.get("X-Forwarded-Host", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.host


def _visibility_filters(namespace):
    """Return the SQL visibility filters an anonymous reader is entitled to.

    Mirrors `api_get_thread` (api/views.py) and `namespace.can_see_node`. Export
    previously filtered only `disabled`, so a namespace running pre-moderation
    served its moderation queue — including posts our spam pipeline soft-flagged
    and held at `spam.soft_threshold` — to anyone who asked for markdown.

    Like the JSON thread endpoint, this does not widen for moderators or node
    owners; they see held content in our web UI, not in exports.
    """
    filters = {"disabled": False}
    if namespace.hide_unless_approved:
        filters["approved"] = True
    if namespace.hide_unverified:
        filters["verified"] = True
    return filters


def _json_error(request, status, message):
    """Build a JSON error response on `request.response`."""
    request.response.status_code = status
    request.response.content_type = "application/json"
    request.response.json_body = {"error": message}
    return request.response


def _parse_format_from_subpath(subpath):
    """Extract format from the subpath (e.g. 'abc-123.md' -> ('abc-123', 'markdown')).

    Extensions are resolved through EXTENSION_ALIASES so users can hit common
    file extensions (.md, .html, .tex) instead of pandoc's internal names.
    """
    if "." in subpath:
        stem, ext = subpath.rsplit(".", 1)
        return stem, resolve_format(ext)
    return subpath, "markdown"


def _export_response(content, to_format, filename_stem):
    """Build a Response for exported content."""
    content_type = CONTENT_TYPES.get(to_format, "application/octet-stream")
    ext = FILE_EXTENSIONS.get(to_format, "")
    filename = "{}{}".format(filename_stem, ext)

    is_binary = isinstance(content, bytes)

    response = Response(
        body=content if is_binary else content.encode("utf-8"),
        content_type=content_type,
    )
    response.content_disposition = 'attachment; filename="{}"'.format(filename)
    return response


# ---------------------------------------------------------------------------
# List formats
# ---------------------------------------------------------------------------


@view_config(
    route_name="api-export-formats",
    request_method="GET",
    renderer="json",
    require_csrf=False,
)
def api_export_formats(request):
    """List all available export formats."""
    available = sorted(get_available_output_formats())
    return {
        "formats": available,
        "count": len(available),
    }


# ---------------------------------------------------------------------------
# Export thread (single root node = chapter)
# ---------------------------------------------------------------------------


@view_config(
    route_name="api-export-thread",
    request_method="GET",
    require_csrf=False,
)
def api_export_thread(request):
    """Export a single thread (root node + all replies) in any pandoc format."""
    subpath = request.matchdict["subpath"]
    node_id, to_format = _parse_format_from_subpath(subpath)

    available = get_available_output_formats()
    if to_format not in available:
        request.response.status_code = 400
        request.response.content_type = "application/json"
        request.response.json_body = {
            "error": "Unsupported format: {}".format(to_format),
            "available": sorted(available),
        }
        return request.response

    node = get_node_by_id(request.dbsession, node_id)
    if node is None:
        request.response.status_code = 404
        request.response.content_type = "application/json"
        request.response.json_body = {"error": "Thread not found"}
        return request.response

    root = node if node.is_root else node.root
    namespace = root.namespace

    denied = check_namespace_api_access(request, namespace)
    if denied:
        request.response.content_type = "application/json"
        request.response.json_body = denied
        return request.response

    # A disabled root is a thread a moderator removed. Node ids are not secret
    # — they appear in RSS, sitemaps, permalinks, and prior exports — so
    # without this check a takedown could be undone by anyone holding the id.
    if root.disabled:
        return _json_error(request, 404, "Thread not found")

    if not namespace.can_see_node(root, request.user):
        return _json_error(request, 404, "Thread not found")

    # Fetch all visible nodes in the thread
    nodes = get_nodes_who_share_root(
        request.dbsession, root,
        exclude_root=True,
        visibility_filters=_visibility_filters(namespace),
    ).all()

    # Build provenance bundle so the exported document points back to its
    # living source on Remarkbox (canonical URI + QR + per-reply permalinks).
    # Use request.host (the host the export was actually fetched from) so
    # canonical URIs preserve user-facing prefixes like `www.` that the
    # namespace's stored name may omit.
    provenance = prov.build(
        canonical_uri=prov.canonical_uri_for_node(root, host=_public_host(request)),
        version=request.static_version,
        kind="thread",
        host=_public_host(request),
    )

    # Render tree to markdown
    md = node_tree_to_markdown(root, nodes, provenance=provenance)
    title = root.title or str(root.id)

    if to_format in ("markdown", "gfm", "commonmark"):
        # Short-circuit: already markdown, no pandoc needed
        return _export_response(md, to_format, root.slug or str(root.id))

    try:
        output = convert(md, from_format="markdown", to_format=to_format, title=title)
    except subprocess.CalledProcessError as e:
        log.error("Pandoc conversion failed: %s", e.stderr)
        request.response.status_code = 500
        request.response.content_type = "application/json"
        request.response.json_body = {
            "error": "Conversion failed",
            "detail": e.stderr[:500] if e.stderr else "unknown error",
        }
        return request.response

    return _export_response(output, to_format, root.slug or str(root.id))


# ---------------------------------------------------------------------------
# Export namespace (full book)
# ---------------------------------------------------------------------------


@view_config(
    route_name="api-export-namespace",
    request_method="GET",
    require_csrf=False,
)
def api_export_namespace(request):
    """Export an entire namespace as a book in any pandoc format."""
    subpath = request.matchdict["subpath"]
    name, to_format = _parse_format_from_subpath(subpath)

    available = get_available_output_formats()
    if to_format not in available:
        request.response.status_code = 400
        request.response.content_type = "application/json"
        request.response.json_body = {
            "error": "Unsupported format: {}".format(to_format),
            "available": sorted(available),
        }
        return request.response

    namespace = get_namespace_by_name(request.dbsession, name)
    if namespace is None:
        request.response.status_code = 404
        request.response.content_type = "application/json"
        request.response.json_body = {"error": "Namespace not found"}
        return request.response

    denied = check_namespace_api_access(request, namespace)
    if denied:
        request.response.content_type = "application/json"
        request.response.json_body = denied
        return request.response

    # A whole-namespace export is our thread index in book form, so it answers
    # to the same privacy flag as our list endpoints.
    from remarkbox.lib.privacy import list_is_visible

    if not list_is_visible(request, namespace):
        return _json_error(
            request, 403, "This namespace's thread list is private"
        )

    # visible_roots already filters verified + not-disabled at the root level;
    # replies need the same moderation filters applied per thread.
    roots = namespace.visible_roots.all()
    reply_filters = _visibility_filters(namespace)

    def node_fetcher(root):
        return get_nodes_who_share_root(
            request.dbsession, root,
            exclude_root=True,
            visibility_filters=reply_filters,
        ).all()

    provenance = prov.build(
        canonical_uri=prov.canonical_uri_for_namespace(namespace, host=_public_host(request)),
        version=request.static_version,
        kind="namespace",
        host=_public_host(request),
    )

    md = namespace_to_markdown(namespace, roots, node_fetcher, provenance=provenance)
    title = namespace.description or namespace.name

    if to_format in ("markdown", "gfm", "commonmark"):
        return _export_response(md, to_format, name)

    try:
        output = convert(md, from_format="markdown", to_format=to_format, title=title)
    except subprocess.CalledProcessError as e:
        log.error("Pandoc conversion failed: %s", e.stderr)
        request.response.status_code = 500
        request.response.content_type = "application/json"
        request.response.json_body = {
            "error": "Conversion failed",
            "detail": e.stderr[:500] if e.stderr else "unknown error",
        }
        return request.response

    return _export_response(output, to_format, name)


# ---------------------------------------------------------------------------
# Export node (on-demand subthread at any depth)
# ---------------------------------------------------------------------------


@view_config(
    route_name="api-export-node",
    request_method="GET",
    require_csrf=False,
)
def api_export_node(request):
    """Export a node and its subtree in any pandoc format (on-demand)."""
    subpath = request.matchdict["subpath"]
    node_id, to_format = _parse_format_from_subpath(subpath)

    available = get_available_output_formats()
    if to_format not in available:
        request.response.status_code = 400
        request.response.content_type = "application/json"
        request.response.json_body = {
            "error": "Unsupported format: {}".format(to_format),
            "available": sorted(available),
        }
        return request.response

    node = get_node_by_id(request.dbsession, node_id)
    if node is None:
        request.response.status_code = 404
        request.response.content_type = "application/json"
        request.response.json_body = {"error": "Node not found"}
        return request.response

    namespace = node.root.namespace

    denied = check_namespace_api_access(request, namespace)
    if denied:
        request.response.content_type = "application/json"
        request.response.json_body = denied
        return request.response

    if node.disabled or not namespace.can_see_node(node, request.user):
        return _json_error(request, 404, "Node not found")

    # For a non-root node, we need to get its subtree.
    # Fetch all nodes in the root's tree, then filter to descendants.
    from remarkbox.models.node import get_graph_from_nodes, flatten_graph
    all_nodes = get_nodes_who_share_root(
        request.dbsession, node.root,
        visibility_filters=_visibility_filters(namespace),
    ).all()

    # Include root so the graph is complete
    all_with_root = [node.root] + list(all_nodes) if not node.is_root else list(all_nodes)

    graph = get_graph_from_nodes(all_with_root)

    # Get descendant IDs of the target node
    if node.id in graph:
        descendant_ids = set(flatten_graph(node.id, graph, include_given_node_id=False))
    else:
        descendant_ids = set()

    # Filter to just the subtree
    subtree_nodes = [n for n in all_nodes if n.id in descendant_ids]

    provenance = prov.build(
        canonical_uri=prov.canonical_uri_for_node(node, host=_public_host(request)),
        version=request.static_version,
        kind="subthread",
        host=_public_host(request),
    )

    md = node_tree_to_markdown(
        node, subtree_nodes, include_root=True, provenance=provenance,
    )
    title = node.title or "Thread {}".format(str(node.id)[:8])

    if to_format in ("markdown", "gfm", "commonmark"):
        slug = node.slug or str(node.id)
        return _export_response(md, to_format, slug)

    try:
        output = convert(md, from_format="markdown", to_format=to_format, title=title)
    except subprocess.CalledProcessError as e:
        log.error("Pandoc conversion failed: %s", e.stderr)
        request.response.status_code = 500
        request.response.content_type = "application/json"
        request.response.json_body = {
            "error": "Conversion failed",
            "detail": e.stderr[:500] if e.stderr else "unknown error",
        }
        return request.response

    slug = node.slug or str(node.id)
    return _export_response(output, to_format, slug)
