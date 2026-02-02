import os
import re
import subprocess
import sys

from pyramid.response import Response
from pyramid.view import view_config

from remarkbox.models import (
    create_root_node,
    get_node_by_id,
    get_or_create_user_surrogate_by_name,
    get_nodes_who_share_root,
)
from remarkbox.models.user import (
    get_or_create_user_by_email,
    is_user_name_valid,
    is_user_name_available,
)
from remarkbox.models.namespace import get_or_create_namespace
from remarkbox.lib.mail import send_verification_digits_to_email
from remarkbox.lib.notify import schedule_notifications
from remarkbox.views import verify_pending_nodes_in_session

from .serializers import serialize_node, serialize_namespace_brief

MAX_CONTENT_LENGTH = 500000

_email_regex = re.compile(r"^[^@]+@[^@]+\.[^.@]+$")


def check_namespace_api_access(request, namespace):
    """Return an error dict if the namespace has API access disabled, else None."""
    if not namespace.api_access:
        request.response.status_code = 403
        return {"error": "API access is disabled for this namespace"}
    return None


def get_json_body(request):
    """Get JSON body from request, or empty dict if not present."""
    try:
        return request.json_body
    except Exception:
        return {}


def get_param(request, key, default=None):
    """Get a parameter from JSON body, then fall back to query/form params."""
    body = get_json_body(request)
    if key in body:
        return body[key]
    return request.params.get(key, default)


def _get_git_commit():
    """Read the current git commit hash, once at import time.

    Checks commit-hash.txt (written by CI build) first,
    then falls back to git rev-parse for dev environments.
    """
    # CI build writes commit-hash.txt as a build artifact
    _this_dir = os.path.dirname(os.path.abspath(__file__))
    for candidate in [
        os.path.join(_this_dir, "..", "..", "commit-hash.txt"),  # repo root
        os.path.join(sys.prefix, "commit-hash.txt"),  # inside virtualenv
        "/opt/remarkbox/commit-hash.txt",
    ]:
        try:
            with open(candidate) as f:
                sha = f.read().strip()
                if sha:
                    return sha[:7]
        except OSError:
            pass

    # Dev environment: read from git
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=_this_dir,
            stderr=subprocess.DEVNULL,
        ).decode().strip()
    except Exception:
        return "unknown"


_GIT_COMMIT = _get_git_commit()


# ---------------------------------------------------------------------------
# Version
# ---------------------------------------------------------------------------


@view_config(
    route_name="api-version",
    request_method="GET",
    renderer="json",
    require_csrf=False,
)
def api_version(request):
    """Return the deployed version (git commit)."""
    return {"version": _GIT_COMMIT}


# ---------------------------------------------------------------------------
# Threads
# ---------------------------------------------------------------------------


@view_config(
    route_name="api-threads-list",
    request_method="GET",
    renderer="json",
    require_csrf=False,
)
def api_list_threads(request):
    """List threads (root nodes) in a namespace."""
    namespace_name = get_param(request, "namespace")
    if not namespace_name:
        request.response.status_code = 400
        return {"error": "namespace parameter is required"}

    namespace = get_or_create_namespace(request.dbsession, namespace_name)

    denied = check_namespace_api_access(request, namespace)
    if denied:
        return denied

    roots = (
        namespace.visible_roots
        .limit(request.page_size)
        .offset(request.page_offset)
        .all()
    )

    return {
        "namespace": serialize_namespace_brief(namespace),
        "threads": [serialize_node(root, include_children=True) for root in roots],
        "page": request.page_number,
        "page_size": request.page_size,
    }


@view_config(
    route_name="api-threads-search",
    request_method="GET",
    renderer="json",
    require_csrf=False,
)
def api_search_threads(request):
    """Search threads by title prefix within a namespace."""
    namespace_name = get_param(request, "namespace")
    q = get_param(request, "q", "").strip()

    if not namespace_name:
        request.response.status_code = 400
        return {"error": "namespace parameter is required"}

    if not q or len(q) < 2:
        return {"threads": []}

    namespace = get_or_create_namespace(request.dbsession, namespace_name)

    from remarkbox.models.node import Node

    roots = (
        namespace.visible_roots
        .filter(Node.title.ilike("{}%".format(q.replace("%", "\\%").replace("_", "\\_"))))
        .limit(10)
        .all()
    )

    return {
        "threads": [
            {
                "id": str(root.id),
                "title": root.title,
                "path": root.path,
                "created_ago": root.human_created_timestamp,
                "stats": root.stats if root.cache else None,
            }
            for root in roots
        ],
    }


@view_config(
    route_name="api-thread-detail",
    request_method="GET",
    renderer="json",
    require_csrf=False,
)
def api_get_thread(request):
    """Get a thread with its replies (paginated).

    Query parameters:
        limit:  Maximum replies to return (default 100, max 500).
        offset: Number of replies to skip (default 0).
    """
    node_id = request.matchdict["node_id"]
    node = get_node_by_id(request.dbsession, node_id)

    if node is None:
        request.response.status_code = 404
        return {"error": "Thread not found"}

    root = node if node.is_root else node.root
    namespace = root.namespace

    denied = check_namespace_api_access(request, namespace)
    if denied:
        return denied

    # Parse pagination params
    try:
        limit = int(get_param(request, "limit", 100))
    except (TypeError, ValueError):
        limit = 100
    limit = max(1, min(limit, 500))

    try:
        offset = int(get_param(request, "offset", 0))
    except (TypeError, ValueError):
        offset = 0
    offset = max(0, offset)

    # Build SQL-side visibility filters (mirrors namespace.can_see_node logic
    # for anonymous / non-moderator users; moderators and node owners would
    # see hidden nodes but that edge case is small and acceptable to omit
    # from the API for performance).
    visibility_filters = {"disabled": False}
    if namespace.hide_unless_approved:
        visibility_filters["approved"] = True
    if namespace.hide_unverified:
        visibility_filters["verified"] = True

    # Get total visible reply count (excluding root) for pagination metadata
    count_query = get_nodes_who_share_root(
        request.dbsession, root,
        exclude_root=True,
        visibility_filters=visibility_filters,
    )
    total_replies = count_query.count()

    # Fetch the paginated slice
    nodes = get_nodes_who_share_root(
        request.dbsession, root, namespace.node_order,
        limit=limit, offset=offset,
        exclude_root=True,
        visibility_filters=visibility_filters,
    )

    page = (offset // limit) + 1 if limit else 1

    return {
        "namespace": serialize_namespace_brief(namespace),
        "thread": serialize_node(root, include_children=True),
        "replies": [serialize_node(n) for n in nodes],
        "total_replies": total_replies,
        "page": page,
        "limit": limit,
        "offset": offset,
        "has_more": (offset + limit) < total_replies,
    }


@view_config(
    route_name="api-threads-list",
    request_method="POST",
    renderer="json",
    require_csrf=False,
)
def api_create_thread(request):
    """Create a new thread."""
    body = get_json_body(request)
    namespace_name = body.get("namespace") or request.params.get("namespace")
    title = body.get("title") or request.params.get("thread_title", "")
    data = body.get("data") or request.params.get("thread_data", "")
    anonymous_name = (
        body.get("anonymous_name") or request.params.get("anonymous_name", "")
    ).strip()
    email = body.get("email") or request.params.get("email", "")

    if not namespace_name:
        request.response.status_code = 400
        return {"error": "namespace is required"}

    if not title:
        request.response.status_code = 400
        return {"error": "title is required"}

    if not data:
        request.response.status_code = 400
        return {"error": "data is required"}

    if len(data) > MAX_CONTENT_LENGTH:
        request.response.status_code = 400
        return {
            "error": "data exceeds maximum length of {} characters".format(
                MAX_CONTENT_LENGTH
            )
        }

    namespace = get_or_create_namespace(request.dbsession, namespace_name)

    denied = check_namespace_api_access(request, namespace)
    if denied:
        return denied

    # Determine user or surrogate
    user_surrogate = None
    user = request.user

    if not user and email:
        user = get_or_create_user_by_email(request.dbsession, email)

    if namespace.allow_anonymous and not user:
        if not anonymous_name:
            anonymous_name = "Anonymous"
        user_surrogate = get_or_create_user_surrogate_by_name(
            request.dbsession, anonymous_name, namespace
        )
    elif user is None:
        request.response.status_code = 400
        return {"error": "email is required (or namespace must allow_anonymous)"}

    # Create root node
    node = create_root_node()
    node.namespace = namespace
    node.ip_address = str(request.client_addr)
    node.title = title
    node.set_data(data, dbsession=request.dbsession)

    if user_surrogate:
        node.user_surrogate = user_surrogate
        node.verified = True
        node_event = None
        request.dbsession.add(user_surrogate)
    else:
        node.user = user
        node.verified = user.authenticated
        node_event = node.new_event(user, "created")
        request.dbsession.add(user)

    request.dbsession.add(node)
    if node_event:
        request.dbsession.add(node_event)
    request.dbsession.add(namespace)
    request.dbsession.flush()

    if node_event:
        request.node = node
        schedule_notifications(request, node_event)

    request.response.status_code = 201
    return {
        "node": serialize_node(node),
        "verified": node.verified,
    }


# ---------------------------------------------------------------------------
# Replies
# ---------------------------------------------------------------------------


@view_config(
    route_name="api-thread-replies",
    request_method="POST",
    renderer="json",
    require_csrf=False,
)
def api_reply(request):
    """Reply to a thread (create a child node)."""
    node_id = request.matchdict["node_id"]
    parent = get_node_by_id(request.dbsession, node_id)

    if parent is None:
        request.response.status_code = 404
        return {"error": "Parent node not found"}

    if parent.disabled:
        request.response.status_code = 403
        return {"error": "Cannot reply to a disabled node"}

    if parent.root.locked:
        request.response.status_code = 403
        return {"error": "Thread is locked"}

    # Enforce max nesting depth (T8)
    namespace = parent.root.namespace
    if namespace.max_nesting_depth is not None:
        if parent.depth >= namespace.max_nesting_depth:
            request.response.status_code = 403
            return {"error": "Maximum nesting depth reached"}

    body = get_json_body(request)
    data = body.get("data") or request.params.get("thread_data", "")
    anonymous_name = (
        body.get("anonymous_name") or request.params.get("anonymous_name", "")
    ).strip()
    email = body.get("email") or request.params.get("email", "")

    if not data:
        request.response.status_code = 400
        return {"error": "data is required"}

    if len(data) > MAX_CONTENT_LENGTH:
        request.response.status_code = 400
        return {
            "error": "data exceeds maximum length of {} characters".format(
                MAX_CONTENT_LENGTH
            )
        }

    namespace = parent.root.namespace

    denied = check_namespace_api_access(request, namespace)
    if denied:
        return denied

    # Determine user or surrogate
    user_surrogate = None
    user = request.user

    if not user and email:
        user = get_or_create_user_by_email(request.dbsession, email)

    if namespace.allow_anonymous and not user:
        if not anonymous_name:
            anonymous_name = "Anonymous"
        user_surrogate = get_or_create_user_surrogate_by_name(
            request.dbsession, anonymous_name, namespace
        )
    elif user is None:
        request.response.status_code = 400
        return {"error": "email is required (or namespace must allow_anonymous)"}

    # Create child node
    child = parent.new_child()
    child.ip_address = str(request.client_addr)
    child.set_data(data, namespace=namespace, dbsession=request.dbsession)

    if user_surrogate:
        child.user_surrogate = user_surrogate
        child.verified = True
        child_event = None
        request.dbsession.add(user_surrogate)
    else:
        child.user = user
        child.verified = user.authenticated
        child_event = child.new_event(user, "commented")

    if namespace.hide_unless_approved:
        if user:
            child.approved = namespace.is_moderator(user)
        else:
            child.approved = False

    # Bump thread
    parent.root.changed = child.changed
    parent._invalidate_cache()

    if user:
        request.dbsession.add(user)
    request.dbsession.add(child)
    if child_event:
        request.dbsession.add(child_event)
    request.dbsession.add(parent)
    request.dbsession.add(parent.root)
    request.dbsession.flush()

    if child_event:
        schedule_notifications(request, child_event)

    request.response.status_code = 201
    return {
        "node": serialize_node(child),
        "verified": child.verified,
    }


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------


@view_config(
    route_name="api-node-detail",
    request_method="GET",
    renderer="json",
    require_csrf=False,
)
def api_get_node(request):
    """Get a single node by ID."""
    node_id = request.matchdict["node_id"]
    node = get_node_by_id(request.dbsession, node_id)

    if node is None:
        request.response.status_code = 404
        return {"error": "Node not found"}

    denied = check_namespace_api_access(request, node.root.namespace)
    if denied:
        return denied

    return {"node": serialize_node(node)}


@view_config(
    route_name="api-node-detail",
    request_method="PATCH",
    renderer="json",
    require_csrf=False,
)
def api_edit_node(request):
    """Edit an existing node (requires authentication)."""
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

    if not namespace.can_alter_node(node, request.user):
        request.response.status_code = 403
        return {"error": "You do not have permission to edit this node"}

    body = get_json_body(request)
    data = body.get("data") or request.params.get("thread_data", "")
    title = body.get("title") or request.params.get("thread_title", "")

    if not data and not title:
        request.response.status_code = 400
        return {"error": "data or title is required"}

    if data and len(data) > MAX_CONTENT_LENGTH:
        request.response.status_code = 400
        return {
            "error": "data exceeds maximum length of {} characters".format(
                MAX_CONTENT_LENGTH
            )
        }

    if title and node.is_root:
        node.title = title
    if data:
        node.edit(data)

    request.dbsession.add(node)
    request.dbsession.flush()

    return {"node": serialize_node(node)}


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------


@view_config(
    route_name="api-auth-login",
    request_method="POST",
    renderer="json",
    require_csrf=False,
)
def api_auth_login(request):
    """Submit email to receive OTP."""
    body = get_json_body(request)
    email = body.get("email") or request.params.get("email", "")

    if not email or _email_regex.match(email) is None:
        request.response.status_code = 400
        return {"error": "A valid email address is required"}

    user = get_or_create_user_by_email(request.dbsession, email)

    if user.throttle_password():
        return {
            "status": "throttled",
            "message": "Verification code already sent to {}. Check email to log in.".format(
                email
            ),
        }

    raw_otp = user.new_password()
    request.dbsession.add(user)
    request.dbsession.flush()

    send_verification_digits_to_email(request, user.email, raw_otp)

    return {
        "status": "sent",
        "message": "Verification code sent to {}.".format(email),
    }


@view_config(
    route_name="api-auth-verify",
    request_method="POST",
    renderer="json",
    require_csrf=False,
)
def api_auth_verify(request):
    """Submit OTP to verify and authenticate."""
    body = get_json_body(request)
    email = body.get("email") or request.params.get("email", "")
    raw_otp = body.get("otp") or request.params.get("raw-otp", "")

    if not email or not raw_otp:
        request.response.status_code = 400
        return {"error": "email and otp are required"}

    user = get_or_create_user_by_email(request.dbsession, email)

    if user.check_password(raw_otp):
        user.verified = True
        request.session["authenticated_user_id"] = str(user.id)

        verify_pending_nodes_in_session(request, user)
        user.create_default_reply_watcher()

        request.dbsession.add(user)
        request.dbsession.flush()

        return {
            "status": "authenticated",
            "user": {
                "id": str(user.id),
                "name": user.name,
                "email": user.email,
            },
        }

    request.response.status_code = 401
    return {"error": "Invalid verification code"}


# ---------------------------------------------------------------------------
# User Profile
# ---------------------------------------------------------------------------


@view_config(
    route_name="api-user-profile",
    request_method="GET",
    renderer="json",
    require_csrf=False,
)
def api_get_profile(request):
    """Get the current user's profile."""
    if not request.user or not request.user.authenticated:
        request.response.status_code = 401
        return {"error": "Authentication required"}

    return {
        "user": {
            "id": str(request.user.id),
            "name": request.user.name,
            "email": request.user.email,
        },
    }


@view_config(
    route_name="api-user-profile",
    request_method="PATCH",
    renderer="json",
    require_csrf=False,
)
def api_update_profile(request):
    """Update the current user's profile (display name)."""
    if not request.user or not request.user.authenticated:
        request.response.status_code = 401
        return {"error": "Authentication required"}

    body = get_json_body(request)
    name = body.get("name", "").strip()

    if not name:
        request.response.status_code = 400
        return {"error": "name is required"}

    if not is_user_name_valid(name):
        request.response.status_code = 400
        return {"error": "name must be alphanumeric (dashes allowed)"}

    # Allow setting to current name (idempotent)
    if name.lower() != request.user.name.lower():
        if not is_user_name_available(request.dbsession, name):
            request.response.status_code = 409
            return {"error": "name is already taken"}

    request.user.name = name
    request.dbsession.add(request.user)
    request.dbsession.flush()

    return {
        "user": {
            "id": str(request.user.id),
            "name": request.user.name,
            "email": request.user.email,
        },
    }


# ---------------------------------------------------------------------------
# Clients
# ---------------------------------------------------------------------------

_client_dir = os.path.dirname(os.path.abspath(__file__))


@view_config(
    route_name="api-client-python",
    request_method="GET",
    require_csrf=False,
)
def api_client_python(request):
    """Serve the Python client for agents to download."""
    path = os.path.join(_client_dir, "remarkbox_client.py")
    with open(path) as f:
        content = f.read()
    return Response(
        body=content,
        content_type="text/plain",
        charset="utf-8",
    )
