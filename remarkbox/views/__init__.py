import functools

from remarkbox.models import get_node_by_id

from pyramid.httpexceptions import HTTPFound

try:
    unicode("")
except:
    from six import u as unicode

# CWE-407: cap user-submitted content before it reaches the bleach sanitization
# pipeline (clean_raw_html / set_data). bleach's LinkifyFilter uses a URL regex
# that exhibits O(2^N) catastrophic backtracking on adversarial input in Python
# < 3.11. Python 3.12 mitigates this at the runtime level (O(N)), but a content
# cap here ensures the code-level defence holds regardless of runtime version.
# The API path enforces the same limit via api/views.py:MAX_CONTENT_LENGTH.
MAX_CONTENT_LENGTH = 500_000


# view decorator.
def user_required(
    flash_msg="You must log in to access that area.",
    flash_level="error",
    return_to_route_name="",
):
    """This view requires that the request has a user."""

    def wrapped(fn):

        @functools.wraps(fn)
        def inner(request):
            if request.user and request.user.authenticated:
                return fn(request)
            request.session.flash((flash_msg, flash_level))
            return_to = ""
            if return_to_route_name:
                return_to = request.route_url(return_to_route_name)
            return HTTPFound(get_join_or_log_in_route_uri(request, return_to))

        return inner

    return wrapped


# view decorator.
def super_fly_required(fn):
    """This view requires that the request has a super fly admin."""
    @functools.wraps(fn)
    def wrapped(request):
        if (
            request.user
            and request.user.authenticated
            and getattr(request.user, "is_superuser", False)
        ):
            return fn(request)
        request.session.flash(
            ("You must be a super fly admin to access that.", "error")
        )
        return HTTPFound(get_referer_or_home(request))

    return wrapped


# view decorator.
def reject_stand_alone(fn):
    """Reject access to view if app is running in stand_alone_mode."""

    @functools.wraps(fn)
    def wrapped(request):
        if request.stand_alone_mode:
            request.session.flash(
                (
                    b"You may not access this page if stand-alone mode is enabled.",
                    b"error",
                )
            )
            return HTTPFound(get_referer_or_home(request))
        return fn(request)

    return wrapped


def get_referer_or_home(request):
    """return referer or safe_redirect or '/'"""
    return (
        request.referer
        if request.referer is not None
        else request.app.get("safe_redirect", "/")
    )


def get_node_route_uri(request, node, anchor=""):
    """return full URI for given node."""
    kwargs = {"node_id": node.id, "_anchor": anchor}
    route_name = "basic-show-node"
    if node.slug:
        route_name = "basic-show-node2"
        kwargs["slug"] = node.slug
    return request.route_url(route_name, **kwargs)


def get_embed_route_uri(request, external_uri, anchor=""):
    return request.route_url(
        "embed-show-node", _query={"thread_uri": external_uri}, _anchor=anchor
    )


def get_join_or_log_in_route_uri(request, return_to=""):
    query = None
    if return_to:
        query = {"return-to":return_to}
    return request.route_url(
        "{}-join-or-log-in".format(request.mode),
        _query=query,
        namespace=request.namespace,
    )


def nodes_pending_verify(request):
    if "nodes_pending_verify" not in request.session:
        request.session["nodes_pending_verify"] = []
    return request.session["nodes_pending_verify"]


def set_node_to_pending_in_session(request, node):
    """Update session to make node go into pending_verify state."""
    pending = nodes_pending_verify(request)
    node_id = str(node.id_without_dashes)
    # Only add if not already present and list isn't too large
    if node_id not in pending and len(pending) < 50:
        pending.append(node_id)


def verify_pending_nodes_in_session(request, user):
    """Attempt to verify all nodes pending verification in session."""
    still_pending_verify = list(nodes_pending_verify(request))
    for node_id in nodes_pending_verify(request):
        node = get_node_by_id(request.dbsession, node_id)
        if node is not None:
            # make sure these values match to prevent spoofing.
            if user == node.user:
                node.verified = True
                request.dbsession.add(node)
                still_pending_verify.remove(str(node.id_without_dashes))
    request.session["nodes_pending_verify"] = still_pending_verify
    request.dbsession.flush()
