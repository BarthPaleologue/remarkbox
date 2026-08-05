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
    oauth_id = request.params.get("oauth-id", "")
    oauth_record = get_oauth_by_id(request.dbsession, oauth_id)

    if oauth_record and request.user not in oauth_record.namespace.owners:
        request.session.flash(("You do not own that Namespace.", "error"))
        return HTTPFound(get_join_or_log_in_route_uri(request))

    if oauth_record:
        request.dbsession.delete(oauth_record)
        request.session.flash(
            ("You deleted that Remarkbox side of that Slack integration.", "success")
        )
        request.session.flash(
            (
                "Please remember to delete the Slack Team side of the integration.",
                "info",
            )
        )
        request.dbsession.flush()
    else:
        request.session.flash(("Invalid OAuth Id.", "error"))

    return HTTPFound(get_namespace_settings_route(request, "notifications"))


@view_config(route_name="oauth-slack")
@user_required()
def oauth_slack(request):

    if not request.user in request.namespace.owners:
        request.session.flash(("You do not own that Namespace.", "error"))
        return HTTPFound(get_join_or_log_in_route_uri(request))

    oauth_error = request.params.get("error", "")
    oauth_code = request.params.get("code", "")

    if oauth_error:
        if oauth_error == "access_denied":
            request.session.flash(
                ("You declined to grant Remarkbox access to Slack", "info")
            )
        else:
            request.session.flash((oauth_error, "error"))
        return HTTPFound(get_namespace_settings_route(request, "notifications"))

    from slacker import Slacker

    # when doing the oauth dance, the first time
    # we connect we don't need a token.
    slack = Slacker("")

    # Request the auth tokens from Slack
    oauth_response = slack.oauth.access(
        client_id=request.app.get("slack.public"),
        client_secret=request.app.get("slack.secret"),
        code=oauth_code,
        redirect_uri=request.route_url(
            "oauth-slack", _query={"namespace": request.namespace.name}
        ),
    )

    if oauth_response.successful:

        #access_token = oauth_response.body["bot"]["bot_access_token"]
        access_token = oauth_response.body["access_token"]
        request.namespace.add_oauth_record(
            user=request.user,
            service="slack",
            token=access_token,
            data=oauth_response.body
        )
        request.dbsession.add(request.namespace)
        request.dbsession.flush()
        request.session.flash(
            (
                "Success, you integrated Remarkbox with <b>{}</b> (Slack Team)".format(
                    oauth_response.body["team_name"]
                ),
                "success",
            )
        )
        request.session.flash(
            (
                "Please create a channel in <b>{}</b> called <b>#remarks</b>".format(
                    oauth_response.body["team_name"]
                ),
                "info",
            )
        )

        # send a test message to #remark channel!
        msg1 = "*Success!* {} integrated this Slack Team with a Remarkbox Namespace (`{}`)".format(
            request.user.name,
            request.namespace.name,
        )
        msg2 = "Please create the `#remarks` channel."
        slack = Slacker(access_token)
        slack.chat.post_message(
            "#general",
            msg1,
        )
        slack.chat.post_message(
            "#general",
            msg2,
        )

    return HTTPFound(get_namespace_settings_route(request, "notifications"))


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
