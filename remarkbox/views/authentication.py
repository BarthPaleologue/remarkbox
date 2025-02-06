import re

from pyramid.view import view_config

from pyramid.httpexceptions import HTTPFound

from remarkbox.models import get_node_by_uri, get_node_by_id

from remarkbox.models.user import get_or_create_user_by_email

from remarkbox.lib.mail import send_verification_digits_to_email

from . import get_referer_or_home, get_embed_route_uri, verify_pending_nodes_in_session

from urllib.parse import urlencode


@view_config(route_name="log-out")
@view_config(route_name="embed-log-out")
def log_out(request):
    """log out the user, redirect to back to referer."""
    uri = get_referer_or_home(request)
    request.session["authenticated_user_id"] = None
    return HTTPFound(uri)


#@view_config(route_name="join-or-log-in", renderer="join-or-log-in.j2")
@view_config(route_name="basic-join-or-log-in", renderer="join-or-log-in.j2", require_csrf=False)
@view_config(route_name="embed-join-or-log-in", renderer="join-or-log-in.j2", require_csrf=False)
def join_or_log_in(request):
    """
    This view handles user registration, verification, and log in.
    It uses "password-less" authentication by sending 6 digit
    OTP (one-time-password) tokens to email addresses to verify both the email
    address & to authenticate the device displaying the challenge input field.
    """
    _email_regex = re.compile("^[^@]+@[^@]+\.[^.@]+$")

    # get the raw OTP (one-time-password) from posted parameters.
    raw_otp = request.params.get("raw-otp", "")

    # get the email from posted parameters.
    email = request.params.get("email", "")

    if email and _email_regex.match(email) is None:
        # posted email does not pass regex, set it to None.
        email = ""
        request.session.flash(("That email address is invalid.", "error"))

    if request.spam:
        return request.spam

    if request.user and request.user.authenticated:
        #return HTTPFound(get_referer_or_home(request))
        return HTTPFound("/")

    elif email:
        # get or create a User object from the posted email.
        user = get_or_create_user_by_email(request.dbsession, email)

        if user.throttle_password():
            msg = (
                "We already sent a link to {}. Check email to log in.".format(user.email),
                "info",
            )

        else:
            # generate a new one-time-password and save to database
            raw_otp = user.new_password()
            request.dbsession.add(user)
            request.dbsession.flush()

            # email user the one-time-password and flash message.
            send_verification_digits_to_email(request, user.email, raw_otp)

            msg = (
                "We just sent a link to {}. Check email to log in.".format(user.email),
                "info",
            )

        request.session.flash(msg)

        email_encoded = urlencode({"email": email})

        return HTTPFound("{}/verification-challenge?{}".format(request.link_prefix, email_encoded))

    return {
        "title": "join or log in",
    }


@view_config(route_name="basic-verification-challenge", renderer="verification-challenge.j2", require_csrf=False)
@view_config(route_name="embed-verification-challenge", renderer="verification-challenge.j2", require_csrf=False)
def verification_challenge(request):

    # get the raw OTP (one-time-password) from posted parameters.
    raw_otp = request.params.get("raw-otp", "")

    # get the email from posted parameters.
    email = request.params.get("email", "")

    user = None
    if email:
        # get or create a User object from the posted email.
        user = get_or_create_user_by_email(request.dbsession, email)

    if raw_otp:
        if user.check_password(raw_otp):
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

            return HTTPFound("{}/u/settings".format(request.link_prefix))

        else:
            msg = ("Invalid Verification Code", "error")
            request.session.flash(msg)

    return {
        "title": "Please Enter Verification Code",
        "email": email,
        "raw_otp": raw_otp,
    }

