import re

from pyramid.view import view_config

from remarkbox.models import (
    create_root_node,
    get_node_by_id,
    get_or_create_user_surrogate_by_name,
    get_nodes_who_share_root,
)
from remarkbox.models.user import get_or_create_user_by_email
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
    route_name="api-thread-detail",
    request_method="GET",
    renderer="json",
    require_csrf=False,
)
def api_get_thread(request):
    """Get a thread with all its replies."""
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

    nodes = get_nodes_who_share_root(request.dbsession, root, namespace.node_order)

    return {
        "namespace": serialize_namespace_brief(namespace),
        "thread": serialize_node(root, include_children=True),
        "replies": [
            serialize_node(n)
            for n in nodes
            if n.id != root.id and namespace.can_see_node(n, request.user)
        ],
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
    node.set_data(data)

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
    child.set_data(data, namespace=namespace)

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
