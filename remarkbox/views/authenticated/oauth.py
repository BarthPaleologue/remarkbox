from pyramid.view import view_config

from pyramid.httpexceptions import HTTPFound

from remarkbox.views import (
    get_referer_or_home,
    get_join_or_log_in_route_uri,
    user_required,
)

from remarkbox.models import get_oauth_by_id


def get_namespace_settings_route(request, anchor=None):
    return request.route_url(
        "basic-namespace-settings", namespace=request.namespace.name, _anchor=anchor
    )


@view_config(route_name="oauth-slack-delete")
@user_required()
def oauth_slack_delete(request):
    oauth_id = request.params.get("oauth-id", "")
    oauth_record = get_oauth_by_id(request.dbsession, oauth_id)

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
