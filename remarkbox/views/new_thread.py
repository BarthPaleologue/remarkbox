from pyramid.view import view_config

from pyramid.csrf import check_csrf_token

from pyramid.httpexceptions import HTTPFound

from remarkbox.models import create_root_node, get_or_create_user_surrogate_by_name

from . import get_referer_or_home, get_node_route_uri, set_node_to_pending_in_session

from remarkbox.lib.notify import schedule_notifications

try:
    unicode("")
except:
    from six import u as unicode


@view_config(route_name="new", renderer="new.j2", require_csrf=False)
def new_thread(request):
    """Display new page and handle posting of form."""
    thread_title = request.params.get("thread_title", "")
    thread_data = request.params.get("thread_data", "")
    anonymous_name = request.params.get("anonymous_name", "").strip()

    if request.spam:
        return request.spam

    # check CSRF only if user is authenticated.
    if request.method == "POST" and request.csrf_token:
        check_csrf_token(request)

    if thread_title and thread_data:
        # handle the submitted form new/create form.

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

        # create a new root node.
        node = create_root_node()
        node.namespace = request.namespace
        node.ip_address = unicode(request.client_addr)
        node.title = thread_title
        node.set_data(thread_data)

        # Handle anonymous vs authenticated user
        if user_surrogate:
            # Anonymous mode: attach surrogate, mark as verified
            node.user_surrogate = user_surrogate
            node.verified = True
            node_event = None  # No notifications for anonymous posts
            request.dbsession.add(user_surrogate)
        else:
            # Normal mode: attach user
            node.user = request.user
            node.verified = request.user.authenticated
            node_event = node.new_event(request.user, "created")
            request.dbsession.add(request.user)

        request.dbsession.add(node)
        if node_event:
            request.dbsession.add(node_event)
        request.dbsession.add(node.namespace)
        request.dbsession.flush()

        if node_event:
            # TODO: schedule_notification expects the request to have a node.
            request.node = node
            schedule_notifications(request, node_event)

        msg = ("Your post was successful!", "success")
        request.session.flash(msg)

        # set return_to to the node's URI.
        return_to = get_node_route_uri(request, node)

        # Anonymous users are always verified, redirect immediately
        if user_surrogate or node.verified:
            return HTTPFound(return_to)

        set_node_to_pending_in_session(request, node)

        # Redirect to join-or-log-in, posting email and submit.
        uri = request.route_url(
            route_name="basic-join-or-log-in",
            _query={
                "email": request.user.email,
                "return-to": return_to,
                "submit": True,
            },
        )
        return HTTPFound(uri)

    return {
        "title": "Create a new thread",
        "thread_title": thread_title,
        "thread_data": thread_data,
    }
