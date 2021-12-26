from pyramid.view import view_config

from pyramid.httpexceptions import HTTPFound

from remarkbox.models import get_node_by_uri, get_node_by_id

from remarkbox.lib.mail import send_otp_email

from . import get_referer_or_home, get_embed_route_uri, verify_pending_nodes_in_session


@view_config(route_name="log-out")
@view_config(route_name="embed-log-out")
def log_out(request):
    """log out the user, redirect to back to referer."""
    uri = get_referer_or_home(request)
    request.session["authenticated_user_id"] = None
    return HTTPFound(uri)


# disable CSRF checking for iframe embedded version of this view.
# If a client has 3rd party cookies disabled this security feature causes
# more trouble then it helps, essentially blocking unauthenticated users.
# disable CSRF checking for basic mode since we only set the
# CSRF token for logged in users.
@view_config(route_name="basic-join-or-log-in", renderer="join-or-log-in.j2", require_csrf=False)
@view_config(route_name="embed-join-or-log-in", renderer="join-or-log-in.j2", require_csrf=False)
def join_or_log_in(request):
    """
    This view handles user registration, verification, and log in.
    It uses "password-less" authentication by sending OTP (one-time-password)
    links to the user's email address.
    """
    # get the return_to uri from posted parameters.
    return_to = request.params.get("return-to", "")

    # get the return_to uri from posted parameters.
    thread_uri = request.params.get("thread_uri", "")

    # get the raw OTP (one-time-password) from posted parameters.
    raw_otp = request.params.get("raw-otp", "")

    # get the email_id from posted parameters.
    email_id = request.params.get("email-id", "")

    if request.spam:
        return request.spam

    if request.user is not None:

        if request.user.authenticated:
            # user already authenticated, return early.
            if return_to:
                return HTTPFound(return_to)
            return HTTPFound(get_referer_or_home(request))

        user = request.user

        if raw_otp and user.check_password(raw_otp):
            # success: the user was verified.
            user.verified = True
            msg = ("Welcome {}".format(user.name), "success")
            request.session["authenticated_user_id"] = str(user.id)
            request.session.flash(msg)

            # attempt to verify all nodes_pending_verify in user's session.
            verify_pending_nodes_in_session(request, user)

            # Idempotent operation. Make certain a user has at least one reply_watcher.
            user.create_default_reply_watcher()

            request.dbsession.add(user)
            request.dbsession.flush()

            return HTTPFound(return_to)

        if user.throttle_password():
            msg = (
                "We already sent a link to {}. Click it to log in.".format(user.email),
                "info",
            )

        else:
            # generate a new one-time-password and save to database
            raw_otp = user.new_password()
            request.dbsession.add(user)
            request.dbsession.flush()

            email_return_to = return_to

            if thread_uri:
                if "#" not in thread_uri:
                    thread_uri = thread_uri + "#remarkbox-div"
                email_return_to = thread_uri

            # email user the one-time-password and flash message.
            send_otp_email(request, user.email, raw_otp, email_return_to)

            msg = (
                "We just sent a link to {}. Click it to log in.".format(user.email),
                "info",
            )

        request.session.flash(msg)

        if request.mode == "basic":
            return HTTPFound(return_to)

        if request.mode == "embed":
            # determine if fragment is a valid node.id.
            if "#" in return_to:
                node = get_node_by_id(request.dbsession, return_to.split("#")[-1])
                if node is not None:
                    if node.root.uri:
                        return HTTPFound(
                            get_embed_route_uri(request, node.root.uri.data, node.id)
                        )

            # determine if return_to is a valid uri in database.
            root = get_node_by_uri(request.dbsession, return_to.split("#")[0])
            if root is not None:
                # embeded external site, uses embed routes.
                return HTTPFound(get_embed_route_uri(request, root.uri.data))

    return {
        # 'the_title' : 'join or log in',
        "title": "join or log in",
        "return_to": return_to,
        "thread_uri": thread_uri,
    }
