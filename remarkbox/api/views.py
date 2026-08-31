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
from remarkbox.models.namespace import (
    get_namespace_by_name,
    get_or_create_namespace,
    get_topsecret_namespaces,
)
from remarkbox.models.uri import get_or_create_uri
from remarkbox.models.node import Node, get_or_create_node_by_uri
from remarkbox.lib.mail import send_verification_digits_to_email, send_sudo_otp_email
from remarkbox.models.sudo_otp import create_sudo_otp, verify_sudo_otp
from remarkbox.lib.notify import schedule_notifications
from remarkbox.views import verify_pending_nodes_in_session

from remarkbox.models.meta import now_timestamp
from remarkbox.models.spam import score_content
from remarkbox.models.spam_llm import (
    check_thread_relevance,
    check_reply_relevance,
    current_model,
)
from remarkbox.models.spam_event import (
    SpamEvent,
    record_spam_event,
    spam_event_summary,
    ACTION_ALLOWED,
    SOURCE_API,
)

from .serializers import serialize_node, serialize_namespace_brief

MAX_CONTENT_LENGTH = 500000

_email_regex = re.compile(r"^[^@]+@[^@]+\.[^.@]+$")


def check_namespace_api_access(request, namespace):
    """Return an error dict if the namespace has API access disabled, else None."""
    if not namespace.api_access:
        request.response.status_code = 403
        return {"error": "API access is disabled for this namespace"}
    return None


def check_namespace_listable(request, namespace):
    """Return an error dict when this caller may not enumerate our threads.

    A namespace whose owner set `public = False` keeps its thread index
    private. Individual threads stay reachable by id so our embed product
    keeps working; see `Namespace.can_list_roots`.
    """
    if not namespace.can_list_roots(request.user):
        request.response.status_code = 403
        return {"error": "This namespace's thread list is private"}
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


def check_spam(request, data, user=None, namespace=None, title=None,
               parent_node=None):
    """Check content for spam. Always returns a result dict.

    Returns dict with keys:
        action: None (clean), "held", or "rejected"
        spam_score: float 0.0-1.0
        signals: list of signal strings
        spam_reason: human-readable LLM explanation or None
        error: present only when action == "rejected"

    - Hard threshold: action="rejected", sets 403 on response.
    - Soft threshold: action="held", caller should set approved=False.
    - An irrelevant LLM verdict holds the post on its own, whatever the
      score. It never rejects alone: an unaided model false positive should
      wait for a human, not silently 403 a real comment.
    - Below thresholds: action=None, spam data still returned for storage.
    - Superusers bypass all checks (returns score 0.0).
    """
    settings = request.registry.settings
    result = {"action": None, "spam_score": 0.0, "signals": [], "spam_reason": None}

    if settings.get("spam.enabled", "true").strip().lower() not in ("true", "1", "yes"):
        return result

    if user and getattr(user, "is_superuser", False):
        return result

    llm_ran = False
    llm_verdict = None

    hard_threshold = float(settings.get("spam.hard_threshold", 0.8))
    soft_threshold = float(settings.get("spam.soft_threshold", 0.5))
    # How much an irrelevant verdict contributes to our score. It no longer
    # has to clear soft_threshold by itself -- an irrelevant verdict holds the
    # post regardless -- but the weight still decides how close to rejection
    # the heuristics need to be before the two together reject.
    irrelevant_weight = float(settings.get("spam.llm.irrelevant_weight", 0.4))

    spam_score, signals = score_content(
        data,
        user=user,
        ip_address=str(request.client_addr),
        dbsession=request.dbsession,
        settings=settings,
    )

    spam_reason = None

    # LLM relevance check: runs when globally enabled AND namespace allows it
    llm_globally_enabled = settings.get(
        "spam.llm.enabled", "false"
    ).strip().lower() in ("true", "1", "yes")
    ns_filter_enabled = True
    if namespace and hasattr(namespace, "spam_filter_enabled"):
        ns_filter_enabled = namespace.spam_filter_enabled is not False

    if llm_globally_enabled and ns_filter_enabled:
        llm_ran = True
        relevant, explanation = _llm_relevance_check(
            settings, data, title=title, namespace=namespace,
            parent_node=parent_node,
        )
        llm_verdict = relevant
        if explanation:
            spam_reason = explanation
        if relevant is False:
            spam_score = min(spam_score + irrelevant_weight, 1.0)
            signals.append("llm_irrelevant")
            if explanation:
                signals.append("llm_reason:{}".format(explanation[:80]))

    result["spam_score"] = spam_score
    result["signals"] = signals
    result["spam_reason"] = spam_reason

    if spam_score >= hard_threshold:
        request.response.status_code = 403
        result["action"] = "rejected"
        result["error"] = "Content flagged as spam"
    elif spam_score >= soft_threshold or llm_verdict is False:
        # An irrelevant verdict holds the post on its own. Previously it only
        # nudged the score, and since the weight sits below the soft
        # threshold, a correct "this is off-topic" call could not hold
        # anything unless the heuristics already suspected the post. The
        # check was arithmetically incapable of acting alone.
        #
        # Holding is the ceiling for an unaided model verdict: a false
        # positive waits for a human instead of silently 403ing a real
        # comment. Rejection still requires the heuristics to agree.
        result["action"] = "held"

    # Record the decision. A rejected post is never written as a node, so
    # without this our blocked spam left no trace at all and the filter could
    # not be shown to be working.
    record_spam_event(
        request.dbsession,
        action=result["action"] or ACTION_ALLOWED,
        namespace=namespace,
        user=user,
        source=SOURCE_API,
        spam_score=spam_score,
        signals=signals,
        llm_ran=llm_ran,
        llm_verdict=llm_verdict,
        llm_model=current_model() if llm_ran else None,
    )

    return result


def _llm_relevance_check(settings, data, title=None, namespace=None,
                         parent_node=None):
    """Run LLM relevance check if enabled. Returns (relevant, explanation).

    For replies, includes the parent page URL (embed mode) so the LLM knows
    what the parent site is about.
    """
    if parent_node is not None:
        # Reply: check relevance to thread
        root = parent_node.root if parent_node else None
        # In embed mode, root.uri.data has the parent page URL
        page_url = None
        if root and getattr(root, "has_uri", False) and root.uri:
            page_url = root.uri.data
        ns_name = namespace.name if namespace else None
        return check_reply_relevance(
            thread_title=root.title if root else None,
            thread_content=root.data if root else None,
            parent_content=parent_node.data if parent_node else None,
            reply_content=data,
            page_url=page_url,
            namespace_name=ns_name,
            settings=settings,
        )
    elif namespace is not None:
        # New thread: check relevance to namespace
        ns_desc = None
        if hasattr(namespace, "description"):
            ns_desc = namespace.description
        return check_thread_relevance(
            namespace_name=namespace.name,
            namespace_description=ns_desc,
            title=title,
            content=data,
            settings=settings,
        )
    return None, None


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

    denied = check_namespace_listable(request, namespace)
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
    """Search threads by keywords in title and content within a namespace."""
    namespace_name = get_param(request, "namespace")
    q = get_param(request, "q", "").strip()

    if not namespace_name:
        request.response.status_code = 400
        return {"error": "namespace parameter is required"}

    if not q or len(q) < 2:
        return {"threads": []}

    namespace = get_or_create_namespace(request.dbsession, namespace_name)

    # Search enumerates roots just as our list endpoint does, so it needs our
    # same two gates. It was missing the api_access one entirely.
    denied = check_namespace_api_access(request, namespace)
    if denied:
        return denied

    denied = check_namespace_listable(request, namespace)
    if denied:
        return denied

    from remarkbox.models.node import Node
    from sqlalchemy import or_, and_

    _STOP_WORDS = {
        "a", "an", "the", "is", "it", "in", "on", "of", "to", "do", "i",
        "we", "my", "me", "or", "if", "at", "by", "so", "no", "up", "am",
        "be", "he", "us", "you", "can", "did", "has", "had", "was", "are",
        "for", "not", "but", "how", "our", "its", "his", "her", "who",
        "all", "any", "got", "get", "this", "that", "with", "from",
        "your", "have", "will", "what", "when", "does", "there", "would",
        "should", "could",
    }

    def _escape(s):
        return s.replace("%", "\\%").replace("_", "\\_")

    def _clean_keyword(word):
        """Strip punctuation and return lowercase, or None if stop word."""
        cleaned = re.sub(r'[^\w-]', '', word).strip('-')
        if not cleaned or len(cleaned) < 2 or cleaned.lower() in _STOP_WORDS:
            return None
        return cleaned

    # Extract meaningful keywords from query.
    keywords = [_clean_keyword(w) for w in q.split()]
    keywords = [kw for kw in keywords if kw]

    # Fall back to whole query if all words were stop words.
    if not keywords:
        keywords = [q]

    # Build OR conditions: any keyword matching title or data.
    keyword_conditions = []
    for kw in keywords:
        pattern = "%{}%".format(_escape(kw))
        keyword_conditions.append(Node.title.ilike(pattern))
        keyword_conditions.append(Node.data.ilike(pattern))

    # Search root nodes.
    title_matches = (
        namespace.visible_roots
        .filter(or_(*keyword_conditions))
        .limit(10)
        .all()
    )
    seen_ids = {r.id for r in title_matches}

    # Also search child nodes and return their root threads.
    remaining = 10 - len(title_matches)
    child_roots = []
    if remaining > 0:
        child_conditions = []
        for kw in keywords:
            pattern = "%{}%".format(_escape(kw))
            child_conditions.append(Node.data.ilike(pattern))

        child_query = (
            request.dbsession.query(Node)
            .filter(
                Node.namespace_id == None,  # child nodes
                Node.disabled == False,
                or_(*child_conditions),
            )
        )

        # Get distinct root_ids from matching children, scoped to namespace.
        children = child_query.limit(50).all()
        for child in children:
            root = child.root
            if root.id not in seen_ids and root.namespace == namespace:
                seen_ids.add(root.id)
                child_roots.append(root)
                if len(child_roots) >= remaining:
                    break

    all_roots = title_matches + child_roots

    return {
        "threads": [
            {
                "id": str(root.id),
                "title": root.title,
                "path": root.path,
                "created_ago": root.human_created_timestamp,
                "stats": root.stats if root.cache else None,
            }
            for root in all_roots
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
    thread_uri = body.get("thread_uri") or request.params.get("thread_uri", "")
    anonymous_name = (
        body.get("anonymous_name") or request.params.get("anonymous_name", "")
    ).strip()
    email = body.get("email") or request.params.get("email", "")
    source_format = body.get("source_format") or request.params.get("source_format", "")
    source_format = source_format.strip() if source_format else None

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

    namespace = get_namespace_by_name(request.dbsession, namespace_name)
    if namespace is None:
        request.response.status_code = 404
        return {"error": "namespace '{}' does not exist".format(namespace_name)}

    denied = check_namespace_api_access(request, namespace)
    if denied:
        return denied

    # Determine user or surrogate
    user_surrogate = None
    user = request.user

    if not user and email:
        user = get_or_create_user_by_email(request.dbsession, email)

    # Spam check (before creating anything)
    spam_result = check_spam(request, data, user=user, namespace=namespace,
                             title=title)
    if spam_result.get("action") == "rejected":
        return {"error": spam_result["error"], "spam_score": spam_result["spam_score"]}

    if namespace.allow_anonymous and not user:
        if not anonymous_name:
            anonymous_name = "Anonymous"
        user_surrogate = get_or_create_user_surrogate_by_name(
            request.dbsession, anonymous_name, namespace
        )
    elif user is None:
        request.response.status_code = 400
        return {"error": "email is required (or namespace must allow_anonymous)"}

    if thread_uri:
        # Simulate what the embed iframe does: get or create the root node
        # via URI, then post the comment as a reply under it.
        root = get_or_create_node_by_uri(
            request.dbsession, thread_uri, node_title=title
        )
        request.dbsession.add(root)
        request.dbsession.flush()

        # Create the comment as a child of the root (same as api_reply)
        node = root.new_child()
        node.ip_address = str(request.client_addr)
        node.set_data(data, namespace=namespace, dbsession=request.dbsession,
                      source_format=source_format)

        if user_surrogate:
            node.user_surrogate = user_surrogate
            node.verified = True
            node_event = None
            request.dbsession.add(user_surrogate)
        else:
            node.user = user
            node.verified = user.authenticated
            node_event = node.new_event(user, "commented")
            request.dbsession.add(user)

        if spam_result.get("action") == "held":
            node.approved = False

        # Store spam data on node for moderation UI
        node.spam_score = spam_result.get("spam_score")
        node.spam_reason = spam_result.get("spam_reason")

        # Bump thread
        root.changed = node.changed
        root._invalidate_cache()

        request.dbsession.add(node)
        if node_event:
            request.dbsession.add(node_event)
        request.dbsession.add(root)
        request.dbsession.flush()

        if node_event:
            schedule_notifications(request, node_event)

        request.response.status_code = 201
        return {
            "node": serialize_node(node),
            "root_node_id": str(root.id),
            "verified": node.verified,
        }

    # No thread_uri — create a standalone thread (root node holds the content)
    node = create_root_node()
    node.namespace = namespace
    node.ip_address = str(request.client_addr)
    node.title = title
    node.set_data(data, dbsession=request.dbsession, source_format=source_format)

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

    if spam_result.get("action") == "held":
        node.approved = False

    # Store spam data on node for moderation UI
    node.spam_score = spam_result.get("spam_score")
    node.spam_reason = spam_result.get("spam_reason")

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
    source_format = body.get("source_format") or request.params.get("source_format", "")
    source_format = source_format.strip() if source_format else None

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

    # Spam check (before creating anything)
    spam_result = check_spam(request, data, user=user, namespace=namespace,
                             parent_node=parent)
    if spam_result.get("action") == "rejected":
        return {"error": spam_result["error"], "spam_score": spam_result["spam_score"]}

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
    child.set_data(data, namespace=namespace, dbsession=request.dbsession,
                   source_format=source_format)

    if user_surrogate:
        child.user_surrogate = user_surrogate
        child.verified = True
        child_event = None
        request.dbsession.add(user_surrogate)
    else:
        child.user = user
        child.verified = user.authenticated
        child_event = child.new_event(user, "commented")

    if spam_result.get("action") == "held":
        child.approved = False
    elif namespace.hide_unless_approved:
        if user:
            child.approved = namespace.is_moderator(user)
        else:
            child.approved = False

    # Store spam data on node for moderation UI
    child.spam_score = spam_result.get("spam_score")
    child.spam_reason = spam_result.get("spam_reason")

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
    source_format = body.get("source_format") or request.params.get("source_format", "")
    source_format = source_format.strip() if source_format else None

    # Moderation flags (require can_alter_node, already checked above)
    disabled = body.get("disabled")
    approved = body.get("approved")
    locked = body.get("locked")

    has_content_change = bool(data or title)
    has_moderation_change = (disabled is not None or approved is not None
                            or locked is not None)

    if not has_content_change and not has_moderation_change:
        request.response.status_code = 400
        return {"error": "data, title, disabled, approved, or locked is required"}

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
        node.set_data(data, source_format=source_format)
        node.changed = now_timestamp()
        node._invalidate_cache()

    if disabled is True:
        node.disable()
    elif disabled is False:
        node.enable()

    if approved is True:
        node.approved = True
    elif approved is False:
        node.approved = False

    if locked is not None and node.is_root:
        node.locked = bool(locked)

    request.dbsession.add(node)
    request.dbsession.flush()

    return {"node": serialize_node(node)}


@view_config(
    route_name="api-node-detail",
    request_method="DELETE",
    renderer="json",
    require_csrf=False,
)
def api_delete_node(request):
    """Delete a node permanently (requires moderator + sudo OTP)."""
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

    if not namespace.is_moderator(request.user):
        request.response.status_code = 403
        return {"error": "Only moderators can delete nodes"}

    # Sudo OTP gate.
    sudo_otp = request.headers.get("X-Sudo-OTP", "").strip()
    action_key = "delete_node:{}".format(node_id)

    if not sudo_otp:
        action_description = "Delete node {}".format(node_id)
        code = create_sudo_otp(
            request.dbsession,
            action_key,
            action_description,
            client_ip=str(request.client_addr),
        )
        send_sudo_otp_email(request, request.user.email, action_description, code)
        request.response.status_code = 202
        return {
            "status": "otp_required",
            "message": "A confirmation code has been sent to your email. "
                       "Repeat this request with the X-Sudo-OTP header.",
        }

    ok, err = verify_sudo_otp(request.dbsession, action_key, sudo_otp)
    if not ok:
        request.response.status_code = 403
        return {"error": err}

    node_id_str = str(node.id)
    request.dbsession.delete(node)
    request.dbsession.flush()

    return {"deleted": node_id_str}


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


@view_config(
    route_name="api-client-c",
    request_method="GET",
    require_csrf=False,
)
def api_client_c(request):
    """Serve the C client for download.

    ?file=rb.h returns the header library instead of the CLI.
    """
    filename = request.params.get("file", "rb.c")
    if filename not in ("rb.c", "rb.h"):
        filename = "rb.c"
    path = os.path.join(_client_dir, filename)
    with open(path) as f:
        content = f.read()
    return Response(
        body=content,
        content_type="text/plain",
        charset="utf-8",
    )


# ---------------------------------------------------------------------------
# Admin (superuser only)
# ---------------------------------------------------------------------------


def _require_superuser(request):
    """Return error dict if user is not a superuser, else None."""
    if not request.user or not request.user.authenticated:
        request.response.status_code = 401
        return {"error": "Authentication required"}
    if not getattr(request.user, "is_superuser", False):
        request.response.status_code = 403
        return {"error": "Superuser access required"}
    return None


@view_config(
    route_name="api-namespace-spam-events",
    request_method="GET",
    renderer="json",
    require_csrf=False,
)
def api_namespace_spam_events(request):
    """Spam decisions for one namespace (moderators and owners).

    Scoped to a namespace on purpose. Whether our filter is working is a
    question the people running a site should be able to answer themselves,
    without holding network-wide superuser.

    Query parameters:
        days: window to summarise (default 7, max 90).
        limit: how many recent events to return (default 50, max 200).
    """
    if not request.user or not request.user.authenticated:
        request.response.status_code = 401
        return {"error": "Authentication required"}

    namespace_name = request.matchdict.get("namespace_name")
    namespace = get_namespace_by_name(request.dbsession, namespace_name)
    if namespace is None:
        request.response.status_code = 404
        return {"error": "Namespace not found"}

    if not namespace.is_moderator(request.user):
        request.response.status_code = 403
        return {"error": "Moderator access required"}

    try:
        days = max(1, min(int(get_param(request, "days", 7)), 90))
    except (TypeError, ValueError):
        days = 7
    try:
        limit = max(1, min(int(get_param(request, "limit", 50)), 200))
    except (TypeError, ValueError):
        limit = 50

    summary = spam_event_summary(request.dbsession, namespace=namespace, days=days)

    since = now_timestamp() - (days * 86400)
    events = (
        request.dbsession.query(SpamEvent)
        .filter(
            SpamEvent.namespace_id == namespace.id,
            SpamEvent.created_timestamp >= since,
        )
        .order_by(SpamEvent.created_timestamp.desc())
        .limit(limit)
    )

    return {
        "namespace": namespace.name,
        "summary": summary,
        "events": [
            {
                "id": str(e.id),
                "created": e.created_timestamp,
                "action": e.action,
                "source": e.source,
                "spam_score": e.spam_score,
                "signals": e.signals.split(",") if e.signals else [],
                "llm_ran": e.llm_ran,
                "llm_verdict": e.llm_verdict,
                "llm_model": e.llm_model,
            }
            for e in events
        ],
    }


@view_config(
    route_name="api-admin-namespaces",
    request_method="GET",
    renderer="json",
    require_csrf=False,
)
def api_admin_namespaces(request):
    """List all namespaces (superuser only)."""
    denied = _require_superuser(request)
    if denied:
        return denied

    namespaces = get_topsecret_namespaces(request.dbsession)
    return {
        "namespaces": [
            {
                "id": str(ns.id),
                "name": ns.name,
                "subscription_type": ns.subscription_type,
                "owner_count": len(ns.owners),
                "root_count": ns.roots.count(),
            }
            for ns in namespaces
        ],
    }


@view_config(
    route_name="api-admin-recent-nodes",
    request_method="GET",
    renderer="json",
    require_csrf=False,
)
def api_admin_recent_nodes(request):
    """List recent nodes across all namespaces (superuser only).

    Query parameters:
        days: Number of days to look back (default 7, max 90).
        limit: Max results (default 100, max 500).
    """
    denied = _require_superuser(request)
    if denied:
        return denied

    import time
    try:
        days = int(get_param(request, "days", 7))
    except (TypeError, ValueError):
        days = 7
    days = max(1, min(days, 90))

    try:
        limit = int(get_param(request, "limit", 100))
    except (TypeError, ValueError):
        limit = 100
    limit = max(1, min(limit, 500))

    cutoff_ms = int((time.time() - days * 86400) * 1000)

    nodes = (
        request.dbsession.query(Node)
        .filter(Node.created > cutoff_ms)
        .order_by(Node.created.desc())
        .limit(limit)
        .all()
    )

    return {
        "days": days,
        "count": len(nodes),
        "nodes": [
            {
                "id": str(n.id),
                "root_id": str(n.root_id) if n.root_id else None,
                "namespace": n.root.namespace.name if n.root and n.root.namespace else None,
                "title": n.title,
                "data": n.data[:200] if n.data else None,
                "ip_address": n.ip_address,
                "created_ago": n.human_created_timestamp,
                "disabled": n.disabled,
                "verified": n.verified,
                "approved": n.approved,
                "author": n.user.name if n.user else (
                    n.user_surrogate.name if n.user_surrogate else None
                ),
            }
            for n in nodes
        ],
    }


# ---------------------------------------------------------------------------
# API tokens
# ---------------------------------------------------------------------------


def _serialize_token(token):
    """Token metadata only. The raw value exists once, at creation."""
    return {
        "id": str(token.id),
        "name": token.name,
        "created": token.created_timestamp,
        "last_used": token.last_used_timestamp,
    }


def _require_session_user(request):
    """Return an error dict unless our caller authenticated with our cookie.

    Token management deliberately refuses bearer authentication: a stolen
    token must not be able to mint more tokens, or revoke the ones its owner
    would use to lock it out.
    """
    from remarkbox.api.auth import is_bearer_authenticated

    if is_bearer_authenticated(request):
        request.response.status_code = 403
        return {
            "error": "Token management requires session authentication, "
                     "not a bearer token."
        }
    if not request.user or not request.user.authenticated:
        request.response.status_code = 401
        return {"error": "Authentication required"}
    return None


@view_config(
    route_name="api-user-tokens",
    request_method="GET",
    renderer="json",
    require_csrf=False,
)
def api_list_tokens(request):
    """List our caller's live API tokens, without their secret values."""
    denied = _require_session_user(request)
    if denied:
        return denied

    from remarkbox.models.api_token import get_api_tokens_by_user

    tokens = get_api_tokens_by_user(request.dbsession, request.user)
    return {"tokens": [_serialize_token(t) for t in tokens]}


@view_config(
    route_name="api-user-tokens",
    request_method="POST",
    renderer="json",
    require_csrf=False,
)
def api_create_token(request):
    """Mint a bearer token. Its raw value is returned here and never again."""
    denied = _require_session_user(request)
    if denied:
        return denied

    from remarkbox.models.api_token import create_api_token

    name = (get_param(request, "name", "") or "").strip()[:64] or None
    token, raw_token = create_api_token(request.dbsession, request.user, name=name)

    request.response.status_code = 201
    payload = _serialize_token(token)
    payload["token"] = raw_token
    payload["warning"] = (
        "Store this token now. We keep only its hash, so it cannot be shown again."
    )
    return payload


@view_config(
    route_name="api-user-token",
    request_method="DELETE",
    renderer="json",
    require_csrf=False,
)
def api_revoke_token(request):
    """Revoke one of our caller's tokens."""
    denied = _require_session_user(request)
    if denied:
        return denied

    from remarkbox.models.api_token import get_api_token_by_id

    token = get_api_token_by_id(request.dbsession, request.matchdict["token_id"])
    if token is None or token.user_id != request.user.id:
        # Same answer either way, so this cannot enumerate other users' tokens.
        request.response.status_code = 404
        return {"error": "Token not found"}

    token.revoked = True
    return {"revoked": True, "id": str(token.id)}
