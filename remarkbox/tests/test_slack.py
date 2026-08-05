"""
Tests for T25: slack upgrade — OAuth v2 incoming webhooks, slacker removed.

Covers:
  - Unit tests for remarkbox.lib.slack helpers (exchange, webhook post,
    legacy chat.postMessage, revoke, target detection)
  - Dual-path delivery in remarkbox.lib.notify (v2 webhook rows and
    legacy token rows in one fan-out)
  - Unit tests for oauth_slack / oauth_slack_delete view logic
"""

import unittest

from unittest.mock import patch, MagicMock

import requests

from remarkbox.lib.slack import (
    exchange_oauth_code,
    post_webhook_message,
    post_chat_message,
    revoke_token,
    is_webhook_target,
    SLACK_MESSAGE_LIMIT,
)

from remarkbox.lib.notify import deliver_webhook_notifications

from remarkbox.views.authenticated.oauth import oauth_slack, oauth_slack_delete


WEBHOOK_URI = "https://hooks.slack.com/services/T111/B222/secret-abc"

LEGACY_TOKEN = "xoxp-legacy-token"


def make_request(params=None):
    """Build a MagicMock request good enough for our oauth views."""
    request = MagicMock()
    request.user.authenticated = True
    request.params = params or {}
    request.referer = "/back"
    request.app = {"slack.public": "cid", "slack.secret": "sec"}
    request.route_url.return_value = "https://my.remarkbox.com/oauth/slack"
    request.session.get_csrf_token.return_value = "nonce123"
    return request


V2_BODY = {
    "ok": True,
    "access_token": "xoxb-v2-token",
    "team": {"name": "gumyum", "id": "T111"},
    "incoming_webhook": {
        "url": WEBHOOK_URI,
        "channel": "#storefront",
        "channel_id": "C333",
        "configuration_url": "https://gumyum.slack.com/services/B222",
    },
}


# ---------------------------------------------------------------------------
# Unit tests for remarkbox.lib.slack helpers.
# ---------------------------------------------------------------------------


class TestIsWebhookTarget(unittest.TestCase):
    def test_v2_webhook_uri(self):
        self.assertTrue(is_webhook_target(WEBHOOK_URI))

    def test_legacy_token(self):
        self.assertFalse(is_webhook_target(LEGACY_TOKEN))

    def test_empty_and_none(self):
        self.assertFalse(is_webhook_target(""))
        self.assertFalse(is_webhook_target(None))


class TestExchangeOauthCode(unittest.TestCase):
    @patch("remarkbox.lib.slack.requests.post")
    def test_success_returns_body(self, mock_post):
        mock_post.return_value.json.return_value = V2_BODY
        body = exchange_oauth_code(make_request(), "code123")
        self.assertEqual(body["incoming_webhook"]["url"], WEBHOOK_URI)
        args, kwargs = mock_post.call_args
        self.assertEqual(args[0], "https://slack.com/api/oauth.v2.access")
        self.assertEqual(kwargs["data"]["code"], "code123")
        self.assertEqual(
            kwargs["data"]["redirect_uri"], "https://my.remarkbox.com/oauth/slack"
        )

    @patch("remarkbox.lib.slack.requests.post")
    def test_ok_false_is_failure(self, mock_post):
        # Slack signals errors in a 200 body with ok=false.
        mock_post.return_value.json.return_value = {
            "ok": False,
            "error": "invalid_code",
        }
        self.assertIsNone(exchange_oauth_code(make_request(), "bad"))

    @patch("remarkbox.lib.slack.requests.post")
    def test_network_error_returns_none(self, mock_post):
        mock_post.side_effect = requests.ConnectionError("down")
        self.assertIsNone(exchange_oauth_code(make_request(), "code123"))


class TestPostWebhookMessage(unittest.TestCase):
    @patch("remarkbox.lib.slack.requests.post")
    def test_success(self, mock_post):
        self.assertTrue(post_webhook_message(WEBHOOK_URI, "hello"))
        args, kwargs = mock_post.call_args
        self.assertEqual(args[0], WEBHOOK_URI)
        self.assertEqual(kwargs["json"], {"text": "hello"})

    @patch("remarkbox.lib.slack.requests.post")
    def test_failure_never_raises(self, mock_post):
        mock_post.side_effect = requests.ConnectionError("revoked")
        self.assertFalse(post_webhook_message(WEBHOOK_URI, "hello"))

    @patch("remarkbox.lib.slack.requests.post")
    def test_long_message_truncated(self, mock_post):
        post_webhook_message(WEBHOOK_URI, "x" * (SLACK_MESSAGE_LIMIT * 2))
        _, kwargs = mock_post.call_args
        sent = kwargs["json"]["text"]
        self.assertLessEqual(len(sent), SLACK_MESSAGE_LIMIT)
        self.assertTrue(sent.endswith("…"))


class TestPostChatMessage(unittest.TestCase):
    @patch("remarkbox.lib.slack.requests.post")
    def test_success_uses_bearer_token_and_channel(self, mock_post):
        mock_post.return_value.json.return_value = {"ok": True}
        self.assertTrue(post_chat_message(LEGACY_TOKEN, "#remarks", "hello"))
        args, kwargs = mock_post.call_args
        self.assertEqual(args[0], "https://slack.com/api/chat.postMessage")
        self.assertEqual(
            kwargs["headers"]["Authorization"], "Bearer " + LEGACY_TOKEN
        )
        self.assertEqual(
            kwargs["json"], {"channel": "#remarks", "text": "hello"}
        )

    @patch("remarkbox.lib.slack.requests.post")
    def test_ok_false_is_failure(self, mock_post):
        mock_post.return_value.json.return_value = {
            "ok": False,
            "error": "channel_not_found",
        }
        self.assertFalse(post_chat_message(LEGACY_TOKEN, "#remarks", "hello"))

    @patch("remarkbox.lib.slack.requests.post")
    def test_network_error_never_raises(self, mock_post):
        mock_post.side_effect = requests.ConnectionError("down")
        self.assertFalse(post_chat_message(LEGACY_TOKEN, "#remarks", "hello"))


class TestRevokeToken(unittest.TestCase):
    @patch("remarkbox.lib.slack.requests.post")
    def test_success(self, mock_post):
        mock_post.return_value.json.return_value = {"ok": True, "revoked": True}
        self.assertTrue(revoke_token("xoxb-v2-token"))
        args, kwargs = mock_post.call_args
        self.assertEqual(args[0], "https://slack.com/api/auth.revoke")
        self.assertIn("Bearer xoxb-v2-token", kwargs["headers"]["Authorization"])

    @patch("remarkbox.lib.slack.requests.post")
    def test_failure_never_raises(self, mock_post):
        mock_post.side_effect = requests.ConnectionError("down")
        self.assertFalse(revoke_token("xoxb-v2-token"))

    def test_empty_token_is_false_without_network(self):
        self.assertFalse(revoke_token(None))
        self.assertFalse(revoke_token(""))


# ---------------------------------------------------------------------------
# Dual-path delivery — mixed legacy + v2 rows in one fan-out.
# ---------------------------------------------------------------------------


class TestDualPathDelivery(unittest.TestCase):
    @patch("remarkbox.lib.slack.post_chat_message")
    @patch("remarkbox.lib.slack.post_webhook_message")
    def test_mixed_rows_route_per_shape(self, mock_webhook, mock_chat):
        deliver_webhook_notifications(
            [
                ("slack", WEBHOOK_URI, "msg-1", None),
                ("slack", LEGACY_TOKEN, "msg-2", "#remarks"),
            ]
        )
        mock_webhook.assert_called_once_with(WEBHOOK_URI, "msg-1")
        mock_chat.assert_called_once_with(LEGACY_TOKEN, "#remarks", "msg-2")


# ---------------------------------------------------------------------------
# Unit tests for oauth_slack / oauth_slack_delete view logic.
# ---------------------------------------------------------------------------


class TestOauthSlackView(unittest.TestCase):
    def test_bad_state_nonce_rejected(self):
        request = make_request(params={"state": "example.com:wrong-nonce"})
        oauth_slack(request)
        flashed = request.session.flash.call_args.args[0]
        self.assertEqual(flashed, ("Invalid OAuth state.", "error"))

    def test_missing_state_rejected(self):
        request = make_request(params={})
        oauth_slack(request)
        flashed = request.session.flash.call_args.args[0]
        self.assertEqual(flashed, ("Invalid OAuth state.", "error"))

    @patch("remarkbox.views.authenticated.oauth.get_namespace_by_name")
    def test_non_owner_rejected(self, mock_get_ns):
        request = make_request(params={"state": "example.com:nonce123"})
        mock_get_ns.return_value.owners = []
        oauth_slack(request)
        flashed = request.session.flash.call_args.args[0]
        self.assertEqual(flashed, ("You do not own that Namespace.", "error"))

    @patch("remarkbox.views.authenticated.oauth.get_namespace_by_name")
    def test_access_denied_flashes_info(self, mock_get_ns):
        request = make_request(
            params={"state": "example.com:nonce123", "error": "access_denied"}
        )
        namespace = mock_get_ns.return_value
        namespace.owners = [request.user]
        oauth_slack(request)
        flashed = request.session.flash.call_args.args[0]
        self.assertEqual(flashed[1], "info")
        namespace.add_oauth_record.assert_not_called()

    @patch("remarkbox.lib.notify.deliver_webhook_notifications_async")
    @patch("remarkbox.lib.slack.exchange_oauth_code")
    @patch("remarkbox.views.authenticated.oauth.get_namespace_by_name")
    def test_success_stores_webhook_url_and_posts_test_message(
        self, mock_get_ns, mock_exchange, mock_deliver
    ):
        request = make_request(
            params={"state": "example.com:nonce123", "code": "code123"}
        )
        namespace = mock_get_ns.return_value
        namespace.owners = [request.user]
        namespace.name = "example.com"
        mock_exchange.return_value = V2_BODY
        oauth_slack(request)
        namespace.add_oauth_record.assert_called_once_with(
            user=request.user,
            service="slack",
            token=WEBHOOK_URI,
            data=V2_BODY,
        )
        deliveries = mock_deliver.call_args.args[0]
        self.assertEqual(len(deliveries), 1)
        kind, target, message, channel = deliveries[0]
        self.assertEqual((kind, target), ("slack", WEBHOOK_URI))
        self.assertIn("Success!", message)

    @patch("remarkbox.lib.slack.exchange_oauth_code")
    @patch("remarkbox.views.authenticated.oauth.get_namespace_by_name")
    def test_failed_exchange_flashes_error(self, mock_get_ns, mock_exchange):
        request = make_request(
            params={"state": "example.com:nonce123", "code": "bad"}
        )
        namespace = mock_get_ns.return_value
        namespace.owners = [request.user]
        mock_exchange.return_value = None
        oauth_slack(request)
        flashed = request.session.flash.call_args.args[0]
        self.assertEqual(flashed[1], "error")
        namespace.add_oauth_record.assert_not_called()


class TestOauthSlackDeleteView(unittest.TestCase):
    @patch("remarkbox.lib.slack.revoke_token")
    @patch("remarkbox.views.authenticated.oauth.get_oauth_by_id")
    def test_v2_row_revokes_stored_access_token(self, mock_get_oauth, mock_revoke):
        request = make_request(params={"oauth-id": "oid"})
        oauth_record = mock_get_oauth.return_value
        oauth_record.namespace.owners = [request.user]
        oauth_record.token = WEBHOOK_URI
        oauth_record.data = {"access_token": "xoxb-v2-token"}
        oauth_slack_delete(request)
        mock_revoke.assert_called_once_with("xoxb-v2-token")
        request.dbsession.delete.assert_called_once_with(oauth_record)

    @patch("remarkbox.lib.slack.revoke_token")
    @patch("remarkbox.views.authenticated.oauth.get_oauth_by_id")
    def test_legacy_row_revokes_its_own_token(self, mock_get_oauth, mock_revoke):
        request = make_request(params={"oauth-id": "oid"})
        oauth_record = mock_get_oauth.return_value
        oauth_record.namespace.owners = [request.user]
        oauth_record.token = LEGACY_TOKEN
        oauth_record.data = {"team_name": "old team"}
        oauth_slack_delete(request)
        mock_revoke.assert_called_once_with(LEGACY_TOKEN)
        request.dbsession.delete.assert_called_once_with(oauth_record)

    @patch("remarkbox.lib.slack.revoke_token")
    @patch("remarkbox.views.authenticated.oauth.get_oauth_by_id")
    def test_non_owner_rejected(self, mock_get_oauth, mock_revoke):
        request = make_request(params={"oauth-id": "oid"})
        mock_get_oauth.return_value.namespace.owners = []
        oauth_slack_delete(request)
        mock_revoke.assert_not_called()
        request.dbsession.delete.assert_not_called()

    @patch("remarkbox.lib.slack.revoke_token")
    @patch("remarkbox.views.authenticated.oauth.get_oauth_by_id")
    def test_invalid_id_flashes_error(self, mock_get_oauth, mock_revoke):
        request = make_request(params={"oauth-id": "nope"})
        mock_get_oauth.return_value = None
        oauth_slack_delete(request)
        mock_revoke.assert_not_called()
        flashed = request.session.flash.call_args.args[0]
        self.assertEqual(flashed, ("Invalid OAuth Id.", "error"))


if __name__ == "__main__":
    unittest.main()
