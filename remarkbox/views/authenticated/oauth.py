from pyramid.view import view_config

from pyramid.httpexceptions import HTTPFound

from remarkbox.views import (
    get_referer_or_home,
    get_join_or_log_in_route_uri,
    user_required,
)

from remarkbox.models import get_oauth_by_id, get_namespace_by_name


def get_namespace_settings_route(request, anchor=None, namespace_name=None):
    if namespace_name is None:
        namespace_name = request.namespace.name
    return request.route_url(
        "basic-namespace-settings", namespace=namespace_name, _anchor=anchor
    )


@view_config(route_name="oauth-slack-delete")
@user_required()
def oauth_slack_delete(request):
    from remarkbox.lib.slack import is_webhook_target, revoke_token

    oauth_id = request.params.get("oauth-id", "")
    oauth_record = get_oauth_by_id(request.dbsession, oauth_id)

    if oauth_record and request.user not in oauth_record.namespace.owners:
        request.session.flash(("You do not own that Namespace.", "error"))
        return HTTPFound(get_join_or_log_in_route_uri(request))

    if oauth_record:
        # best effort: revoke the Slack side too. v2 rows keep their
        # access token in json_data (revoking it kills the granted
        # incoming webhook); legacy rows ARE the access token.
        if is_webhook_target(oauth_record.token):
            access_token = (oauth_record.data or {}).get("access_token")
        else:
            access_token = oauth_record.token
        revoke_token(access_token)
        request.dbsession.delete(oauth_record)
        request.dbsession.flush()
        request.session.flash(
            ("You disconnected that Slack channel from this Namespace.", "success")
        )
    else:
        request.session.flash(("Invalid OAuth Id.", "error"))

    return HTTPFound(get_namespace_settings_route(request, "notifications"))


@view_config(route_name="oauth-slack")
@user_required()
def oauth_slack(request):
    """
    Slack OAuth v2 callback (incoming-webhook scope) — T25.

    Mirrors our discord flow: v2 requires exact-match redirect URIs, so
    our namespace rides in `state` (`namespace-name:nonce`) instead of
    a query string like our old v1 flow. Our nonce is our session csrf
    token, which stops a forged callback from attaching an attacker's
    webhook to a victim's namespace — protection the v1 flow never had.
    Slack's consent screen picks the channel, so the `#remarks`
    ceremony is gone for new connections.
    """
    from remarkbox.lib.slack import exchange_oauth_code
    from remarkbox.lib.notify import deliver_webhook_notifications_async

    state = request.params.get("state", "")
    namespace_name, _, nonce = state.rpartition(":")

    if not namespace_name or nonce != request.session.get_csrf_token():
        request.session.flash(("Invalid OAuth state.", "error"))
        return HTTPFound(get_referer_or_home(request))

    namespace = get_namespace_by_name(request.dbsession, namespace_name)

    if namespace is None or request.user not in namespace.owners:
        request.session.flash(("You do not own that Namespace.", "error"))
        return HTTPFound(get_join_or_log_in_route_uri(request))

    settings_route = get_namespace_settings_route(
        request, "notifications", namespace_name=namespace.name
    )

    oauth_error = request.params.get("error", "")
    if oauth_error:
        if oauth_error == "access_denied":
            request.session.flash(
                ("You declined to grant Remarkbox access to Slack", "info")
            )
        else:
            request.session.flash((oauth_error, "error"))
        return HTTPFound(settings_route)

    oauth_code = request.params.get("code", "")
    oauth_response = exchange_oauth_code(request, oauth_code)
    incoming_webhook = (oauth_response or {}).get("incoming_webhook", {})

    if incoming_webhook.get("url"):
        namespace.add_oauth_record(
            user=request.user,
            service="slack",
            token=incoming_webhook["url"],
            data=oauth_response,
        )
        request.dbsession.add(namespace)
        request.dbsession.flush()
        team_name = (oauth_response.get("team") or {}).get("name", "Slack")
        channel = incoming_webhook.get("channel", "a channel")
        request.session.flash(
            (
                "Success, you connected this Namespace to <b>{}</b> in "
                "<b>{}</b> (Slack).".format(channel, team_name),
                "success",
            )
        )
        # test message posts async so a slow Slack never blocks this
        # redirect back to namespace settings.
        deliver_webhook_notifications_async(
            [
                (
                    "slack",
                    incoming_webhook["url"],
                    "*Success!* {} connected this Slack channel to a "
                    "Remarkbox Namespace (`{}`). New threads and comments "
                    "will appear here.".format(
                        request.user.name, namespace.name
                    ),
                    None,
                )
            ]
        )
    else:
        request.session.flash(
            ("Slack did not grant a webhook, please try again.", "error")
        )

    return HTTPFound(settings_route)


@view_config(route_name="oauth-discord-delete")
@user_required()
def oauth_discord_delete(request):
    from remarkbox.lib.discord import delete_webhook

    oauth_id = request.params.get("oauth-id", "")
    oauth_record = get_oauth_by_id(request.dbsession, oauth_id)

    if oauth_record and request.user not in oauth_record.namespace.owners:
        request.session.flash(("You do not own that Namespace.", "error"))
        return HTTPFound(get_join_or_log_in_route_uri(request))

    if oauth_record:
        # best effort: remove the Discord side too, a webhook URI
        # embeds its own token so no other auth is needed.
        delete_webhook(oauth_record.token)
        request.dbsession.delete(oauth_record)
        request.dbsession.flush()
        request.session.flash(
            ("You disconnected that Discord channel from this Namespace.", "success")
        )
    else:
        request.session.flash(("Invalid OAuth Id.", "error"))

    return HTTPFound(get_namespace_settings_route(request, "notifications"))


@view_config(route_name="oauth-discord")
@user_required()
def oauth_discord(request):
    """
    Discord OAuth2 callback (webhook.incoming scope).

    Discord requires exact-match redirect URIs, so our namespace rides
    in our `state` parameter (`namespace-name:nonce`) instead of a
    query string like our slack flow. Our nonce is our session csrf
    token, which stops a forged callback from attaching an attacker's
    webhook to a victim's namespace.
    """
    from remarkbox.lib.discord import exchange_oauth_code, post_webhook_message_async

    state = request.params.get("state", "")
    namespace_name, _, nonce = state.rpartition(":")

    if not namespace_name or nonce != request.session.get_csrf_token():
        request.session.flash(("Invalid OAuth state.", "error"))
        return HTTPFound(get_referer_or_home(request))

    namespace = get_namespace_by_name(request.dbsession, namespace_name)

    if namespace is None or request.user not in namespace.owners:
        request.session.flash(("You do not own that Namespace.", "error"))
        return HTTPFound(get_join_or_log_in_route_uri(request))

    settings_route = get_namespace_settings_route(
        request, "notifications", namespace_name=namespace.name
    )

    oauth_error = request.params.get("error", "")
    if oauth_error:
        if oauth_error == "access_denied":
            request.session.flash(
                ("You declined to grant Remarkbox access to Discord", "info")
            )
        else:
            request.session.flash((oauth_error, "error"))
        return HTTPFound(settings_route)

    oauth_code = request.params.get("code", "")
    oauth_response = exchange_oauth_code(request, oauth_code)
    webhook = (oauth_response or {}).get("webhook", {})

    if webhook.get("url"):
        namespace.add_oauth_record(
            user=request.user,
            service="discord",
            token=webhook["url"],
            data=oauth_response,
        )
        request.dbsession.add(namespace)
        request.dbsession.flush()
        request.session.flash(
            (
                "Success, you connected this Namespace to a Discord channel.",
                "success",
            )
        )
        post_webhook_message_async(
            webhook["url"],
            "**Success!** {} connected this Discord channel to a Remarkbox "
            "Namespace (`{}`). New threads and comments will appear here.".format(
                request.user.name, namespace.name
            ),
        )
    else:
        request.session.flash(
            ("Discord did not grant a webhook, please try again.", "error")
        )

    return HTTPFound(settings_route)
