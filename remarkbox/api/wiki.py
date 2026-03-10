"""Wiki mode and revision history API endpoints."""

from pyramid.view import view_config

from remarkbox.models.node import get_node_by_id, Node
from remarkbox.models.revision import Revision

from .views import check_namespace_api_access, get_json_body, MAX_CONTENT_LENGTH
from .serializers import serialize_node

from remarkbox.models.meta import get_object_by_id


def serialize_revision(rev):
    """Serialize a Revision to a dict."""
    return {
        "id": str(rev.id),
        "node_id": str(rev.node_id),
        "user_id": str(rev.user_id) if rev.user_id else None,
        "author": rev.user.name if rev.user else None,
        "data": rev.data,
        "source_format": rev.source_format,
        "revision_number": rev.revision_number,
        "created": rev.created,
    }


@view_config(
    route_name="api-node-revisions",
    request_method="GET",
    renderer="json",
    require_csrf=False,
)
def api_node_revisions(request):
    """Get revision history for a node."""
    node_id = request.matchdict["node_id"]
    node = get_node_by_id(request.dbsession, node_id)

    if node is None:
        request.response.status_code = 404
        return {"error": "Node not found"}

    namespace = node.root.namespace
    denied = check_namespace_api_access(request, namespace)
    if denied:
        return denied

    revisions = (
        request.dbsession.query(Revision)
        .filter(Revision.node_id == node.id)
        .order_by(Revision.revision_number.desc())
        .all()
    )

    return {
        "node_id": str(node.id),
        "revisions": [serialize_revision(r) for r in revisions],
        "count": len(revisions),
    }


@view_config(
    route_name="api-node-wiki-edit",
    request_method="POST",
    renderer="json",
    require_csrf=False,
)
def api_wiki_edit(request):
    """Wiki-edit a node (creates a revision, any authenticated user if wiki mode)."""
    node_id = request.matchdict["node_id"]
    node = get_node_by_id(request.dbsession, node_id)

    if node is None:
        request.response.status_code = 404
        return {"error": "Node not found"}

    if not request.user or not request.user.authenticated:
        request.response.status_code = 401
        return {"error": "Authentication required"}

    namespace = node.root.namespace

    denied = check_namespace_api_access(request, namespace)
    if denied:
        return denied

    if not namespace.can_wiki_edit(node, request.user):
        request.response.status_code = 403
        return {"error": "Wiki editing not permitted for this node"}

    body = get_json_body(request)
    data = body.get("data", "")

    if not data:
        request.response.status_code = 400
        return {"error": "data is required"}

    if len(data) > MAX_CONTENT_LENGTH:
        request.response.status_code = 400
        return {"error": "data exceeds maximum length"}

    source_format = body.get("source_format")

    node.wiki_edit(data, user=request.user, source_format=source_format)
    request.dbsession.add(node)
    request.dbsession.flush()

    return {"node": serialize_node(node)}


@view_config(
    route_name="api-revision-detail",
    request_method="GET",
    renderer="json",
    require_csrf=False,
)
def api_get_revision(request):
    """Get a specific revision by ID."""
    revision_id = request.matchdict["revision_id"]

    revision = get_object_by_id(request.dbsession, revision_id, Revision)

    if revision is None:
        request.response.status_code = 404
        return {"error": "Revision not found"}

    node = get_node_by_id(request.dbsession, revision.node_id)
    if node:
        namespace = node.root.namespace
        denied = check_namespace_api_access(request, namespace)
        if denied:
            return denied

    return {"revision": serialize_revision(revision)}
