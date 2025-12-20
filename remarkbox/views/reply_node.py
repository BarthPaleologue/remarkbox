from pyramid.view import view_config

from pyramid.csrf import check_csrf_token

from pyramid.httpexceptions import HTTPFound

from . import (
    get_referer_or_home,
    get_embed_route_uri,
    get_node_route_uri,
    set_node_to_pending_in_session,
)

from remarkbox.lib.notify import schedule_notifications
from remarkbox.models import get_or_create_user_surrogate_by_name

try:
    unicode("")
except:
    from six import u as unicode


# check CSRF only if user is authenticated.
@view_config(route_name="embed-reply", require_csrf=False)
@view_config(route_name="embed-reply2", require_csrf=False)
@view_config(route_name="basic-reply", require_csrf=False)
@view_config(route_name="basic-reply2", require_csrf=False)
def reply_node(request):
    """handle posting of reply form from show-node pages."""
    thread_data = request.params.get("thread_data", "")
    anonymous_name = request.params.get("anonymous_name", "").strip()

    # return early if spam attribute is truthy.
    if request.spam:
        return request.spam

    # return early if node (parent) not not exist.
    if request.node is None:
        # redirect to the referer or home. No node found in database.
        return HTTPFound(get_referer_or_home(request))

    # return early if node (parent) is disabled.
    if request.node.disabled is True:
        # redirect to the referer or home.
        request.session.flash(("No remarks for the disabled.", "error"))
        return HTTPFound(get_referer_or_home(request))

    # Handle anonymous mode vs regular mode
    user_surrogate = None
    if request.namespace.allow_anonymous and not request.user:
        # Anonymous mode: create or get a surrogate
        if not anonymous_name:
            anonymous_name = "Anonymous"
        user_surrogate = get_or_create_user_surrogate_by_name(
            request.dbsession, anonymous_name, request.namespace
        )
    elif request.user is None:
        # Regular mode: require email/user
        request.session.flash(
            ("Press the back button to fix your email address", "error")
        )
        return HTTPFound(get_referer_or_home(request))

    # return early if thread (root node) is locked.
    if request.node.root.locked:
        request.session.flash(
            ("You may not comment, this thread is locked.", "error")
        )
        return HTTPFound(get_referer_or_home(request))


    # check CSRF only if user is authenticated.
    if request.method == "POST" and request.csrf_token:
        check_csrf_token(request)

    # flash error and return early if data is empty.
    if thread_data == "":
        request.session.flash(("Your message was empty", "error"))
        return HTTPFound(get_referer_or_home(request))

    # STEP 1: get a parent node.
    parent = request.node

    # STEP 2: attach a brand new child node to parent node.
    child = parent.new_child()
    child.ip_address = unicode(request.client_addr)
    child.set_data(thread_data, namespace=request.namespace)

    # Handle anonymous vs authenticated user
    if user_surrogate:
        # Anonymous mode: attach surrogate, mark as verified (no email to verify)
        child.user_surrogate = user_surrogate
        child.verified = True
        child_event = None  # No notifications for anonymous comments
        request.dbsession.add(user_surrogate)
    else:
        # Normal mode: attach user
        child.user = request.user
        child.verified = request.user.authenticated
        child_event = child.new_event(request.user, "commented")

    if request.namespace.hide_unless_approved:
        # by default comments are approved, unless Namespace hide_unless_approved
        # is enabled, moderators nodes are always auto approved.
        if request.user:
            child.approved = request.namespace.is_moderator(request.user)
        else:
            # Anonymous users are never auto-approved when moderation is on
            child.approved = False

    # STEP 3: update root's changed timestamp.
    # TODO: maybe we should find a better way to "bump" a thread.
    parent.root.changed = child.changed
    # invalidate root cache to force recomputation.
    parent._invalidate_cache()

    # STEP 4: commit to database.
    if request.user:
        request.dbsession.add(request.user)
    request.dbsession.add(child)
    if child_event:
        request.dbsession.add(child_event)
    request.dbsession.add(parent)
    request.dbsession.add(parent.root)
    request.dbsession.flush()

    if child_event:
        schedule_notifications(request, child_event)

    msg = ("Your post was successful!", "success")
    request.session.flash(msg)

    # set return_to URI.
    if request.mode == "embed":
        return_to = get_embed_route_uri(request, child.root.uri.data, child.id)
    else:
        return_to = get_node_route_uri(request, child.root, child.id)

    # Anonymous users are always verified, redirect immediately
    if user_surrogate or child.verified:
        return HTTPFound(return_to)

    set_node_to_pending_in_session(request, child)

    if request.mode == "embed":
        # set return_to to the parent iframe URI.
        return_to = "{}#{}".format(child.root.uri.data, child.id)

    # Redirect to join-or-log-in, posting email and submit.
    # Per the docs: " Extra replacement names are ignored."
    # In this case "namespace" is extra when mode is basic.
    # https://docs.pylonsproject.org/projects/pyramid/en/latest/api/request.html#pyramid.request.Request.route_url
    uri = request.route_url(
        route_name=request.mode + "-join-or-log-in",
        namespace=request.namespace.name,
        _query={"email": request.user.email, "return-to": return_to, "submit": True},
    )
    return HTTPFound(uri)
