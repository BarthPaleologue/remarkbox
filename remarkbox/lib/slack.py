"""
Slack integration helpers (T25).

Remarkbox connects a Namespace to a Slack channel via OAuth v2 with our
incoming-webhook scope. Slack's consent screen has our user pick a
channel, and our token exchange returns an incoming webhook URI.
Delivering a notification is a plain HTTPS POST to that URI — no
persistent process, no slack library.

Legacy rows (connected before T25) store a v1 access token instead of a
webhook URI. Those tokens still authorize chat.postMessage, so delivery
stays dual-path: `is_webhook_target` picks per row, and nothing
connected before this upgrade silently stops notifying.
"""

from __future__ import unicode_literals

import requests

import logging

log = logging.getLogger(__name__)

SLACK_API = "https://slack.com/api"

WEBHOOK_PREFIX = "https://hooks.slack.com/"

# Slack truncates messages around 40k characters; we cap well below
# that for parity with our discord excerpt policy.
SLACK_MESSAGE_LIMIT = 3000


def is_webhook_target(target):
    """True when a stored slack Oauth token is a v2 incoming webhook
    URI, False when it is a legacy v1 access token."""
    return (target or "").startswith(WEBHOOK_PREFIX)


def exchange_oauth_code(request, code):
    """
    Exchange an OAuth v2 authorization code for a token response.

    Returns Slack's parsed response body (a dict containing an
    "incoming_webhook" object with our webhook URI) or None on failure.
    Slack signals errors in a 200 body with ok=false — that is a
    failure too.
    """
    try:
        response = requests.post(
            SLACK_API + "/oauth.v2.access",
            data={
                "client_id": request.app.get("slack.public"),
                "client_secret": request.app.get("slack.secret"),
                "code": code,
                "redirect_uri": request.route_url("oauth-slack"),
            },
            timeout=10,
        )
        response.raise_for_status()
        body = response.json()
        if not body.get("ok"):
            log.warning("slack oauth exchange not ok: {}".format(body.get("error")))
            return None
        return body
    except (requests.RequestException, ValueError) as e:
        log.warning("slack oauth code exchange failed: {}".format(e))
        return None


def post_webhook_message(webhook_uri, text):
    """
    POST a message to a Slack incoming webhook URI (v2 rows).

    Returns True on success, False on any failure. Never raises — a
    revoked webhook must not break the code path that triggered the
    notification (for example a comment submission).
    """
    if len(text) > SLACK_MESSAGE_LIMIT:
        text = text[: SLACK_MESSAGE_LIMIT - 1] + "…"
    try:
        response = requests.post(webhook_uri, json={"text": text}, timeout=10)
        response.raise_for_status()
        return True
    except requests.RequestException as e:
        log.warning("slack webhook post failed: {}".format(e))
        return False


def post_chat_message(token, channel, text):
    """
    POST a message via chat.postMessage with a legacy access token.

    Keeps namespaces connected before T25 notifying without slacker.
    Returns True on success, False on any failure. Never raises.
    """
    if len(text) > SLACK_MESSAGE_LIMIT:
        text = text[: SLACK_MESSAGE_LIMIT - 1] + "…"
    try:
        response = requests.post(
            SLACK_API + "/chat.postMessage",
            headers={"Authorization": "Bearer {}".format(token)},
            json={"channel": channel, "text": text},
            timeout=10,
        )
        response.raise_for_status()
        body = response.json()
        if not body.get("ok"):
            log.warning("slack chat.postMessage not ok: {}".format(body.get("error")))
            return False
        return True
    except (requests.RequestException, ValueError) as e:
        log.warning("slack chat.postMessage failed: {}".format(e))
        return False


def revoke_token(token):
    """
    Revoke a slack grant via auth.revoke (best effort, on disconnect).

    Works for both row shapes: legacy rows pass their access token
    directly; v2 rows pass the access_token stored in json_data —
    revoking it kills the granted incoming webhook too.
    Returns True when Slack confirmed, False otherwise. Never raises.
    """
    if not token:
        return False
    try:
        response = requests.post(
            SLACK_API + "/auth.revoke",
            headers={"Authorization": "Bearer {}".format(token)},
            timeout=10,
        )
        response.raise_for_status()
        return bool(response.json().get("ok"))
    except (requests.RequestException, ValueError) as e:
        log.warning("slack auth.revoke failed: {}".format(e))
        return False
