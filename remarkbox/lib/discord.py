"""
Discord integration helpers.

Remarkbox connects a Namespace to a Discord channel via OAuth2 with our
webhook.incoming scope. Discord's consent screen has our user pick a
server and channel, and our token exchange returns an incoming webhook
URI. Delivering a notification is a plain HTTPS POST to that URI —
no gateway connection, no bot token, no discord library.
"""

from __future__ import unicode_literals

import requests

import logging

log = logging.getLogger(__name__)

DISCORD_API = "https://discord.com/api"

# Discord rejects message content over 2000 characters.
DISCORD_MESSAGE_LIMIT = 2000


def exchange_oauth_code(request, code):
    """
    Exchange an OAuth2 authorization code for a token response.

    Returns Discord's parsed response body (a dict containing a
    "webhook" object with our incoming webhook URI) or None on failure.
    """
    try:
        response = requests.post(
            DISCORD_API + "/oauth2/token",
            data={
                "client_id": request.app.get("discord.public"),
                "client_secret": request.app.get("discord.secret"),
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": request.route_url("oauth-discord"),
            },
            timeout=10,
        )
        response.raise_for_status()
        return response.json()
    except (requests.RequestException, ValueError) as e:
        log.warning("discord oauth code exchange failed: {}".format(e))
        return None


def post_webhook_message(webhook_uri, content):
    """
    POST a message to a Discord incoming webhook URI.

    Returns True on success, False on any failure. Never raises — a
    revoked webhook must not break the code path that triggered the
    notification (for example a comment submission).
    """
    if len(content) > DISCORD_MESSAGE_LIMIT:
        content = content[: DISCORD_MESSAGE_LIMIT - 1] + "…"
    try:
        response = requests.post(
            webhook_uri, json={"content": content}, timeout=10
        )
        response.raise_for_status()
        return True
    except requests.RequestException as e:
        log.warning("discord webhook post failed: {}".format(e))
        return False


def delete_webhook(webhook_uri):
    """
    Delete a Discord incoming webhook (best effort).

    A webhook URI embeds its own token, so no other auth is needed.
    Returns True on success, False on any failure.
    """
    try:
        response = requests.delete(webhook_uri, timeout=10)
        response.raise_for_status()
        return True
    except requests.RequestException as e:
        log.warning("discord webhook delete failed: {}".format(e))
        return False
