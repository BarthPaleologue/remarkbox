"""
Tests for T24: Discord connections for namespaces.

Covers:
  - Unit tests for remarkbox.lib.discord webhook helpers
  - Unit tests for our discord notify fan-out in remarkbox.lib.notify
  - Unit tests for our slack notify guard (a revoked token must not raise)
  - Unit tests for oauth_discord / oauth_discord_delete view logic
"""

import unittest

from unittest.mock import patch, MagicMock

import requests

from remarkbox.lib.discord import (
    exchange_oauth_code,
    post_webhook_message,
    delete_webhook,
    DISCORD_MESSAGE_LIMIT,
)

from remarkbox.lib.notify import (
    build_slack_deliveries,
    build_discord_deliveries,
    deliver_webhook_notifications,
    deliver_webhook_notifications_async,
)

from remarkbox.views.authenticated.oauth import oauth_discord, oauth_discord_delete


WEBHOOK_URI = "https://discord.com/api/webhooks/123/token-abc"


def make_request(params=None):
    """Build a MagicMock request good enough for our oauth views."""
    request = MagicMock()
    request.user.authenticated = True
    request.params = params or {}
    request.referer = "/back"
    request.app = {"discord.public": "cid", "discord.secret": "sec"}
    request.route_url.return_value = "https://my.remarkbox.com/somewhere"
    request.session.get_csrf_token.return_value = "nonce123"
    return request


# ---------------------------------------------------------------------------
# Unit tests for remarkbox.lib.discord helpers.
# ---------------------------------------------------------------------------


class TestPostWebhookMessage(unittest.TestCase):
    @patch("remarkbox.lib.discord.requests.post")
    def test_success(self, mock_post):
        self.assertTrue(post_webhook_message(WEBHOOK_URI, "hello"))
        args, kwargs = mock_post.call_args
        self.assertEqual(args[0], WEBHOOK_URI)
        self.assertEqual(kwargs["json"], {"content": "hello"})

    @patch("remarkbox.lib.discord.requests.post")
    def test_truncates_to_discord_limit(self, mock_post):
        post_webhook_message(WEBHOOK_URI, "x" * 3000)
        sent = mock_post.call_args.kwargs["json"]["content"]
        self.assertLessEqual(len(sent), DISCORD_MESSAGE_LIMIT)
        self.assertTrue(sent.endswith("…"))

    @patch("remarkbox.lib.discord.requests.post")
    def test_failure_returns_false_and_never_raises(self, mock_post):
        mock_post.side_effect = requests.RequestException("boom")
        self.assertFalse(post_webhook_message(WEBHOOK_URI, "hello"))


class TestDeleteWebhook(unittest.TestCase):
    @patch("remarkbox.lib.discord.requests.delete")
    def test_success(self, mock_delete):
        self.assertTrue(delete_webhook(WEBHOOK_URI))
        self.assertEqual(mock_delete.call_args.args[0], WEBHOOK_URI)

    @patch("remarkbox.lib.discord.requests.delete")
    def test_failure_returns_false_and_never_raises(self, mock_delete):
        mock_delete.side_effect = requests.RequestException("boom")
        self.assertFalse(delete_webhook(WEBHOOK_URI))


class TestExchangeOauthCode(unittest.TestCase):
    @patch("remarkbox.lib.discord.requests.post")
    def test_success_returns_body(self, mock_post):
        mock_post.return_value.json.return_value = {"webhook": {"url": WEBHOOK_URI}}
        request = make_request()
        body = exchange_oauth_code(request, "code123")
        self.assertEqual(body["webhook"]["url"], WEBHOOK_URI)
        data = mock_post.call_args.kwargs["data"]
        self.assertEqual(data["client_id"], "cid")
        self.assertEqual(data["client_secret"], "sec")
        self.assertEqual(data["code"], "code123")
        self.assertEqual(data["grant_type"], "authorization_code")

    @patch("remarkbox.lib.discord.requests.post")
    def test_http_failure_returns_none(self, mock_post):
        mock_post.side_effect = requests.RequestException("boom")
        self.assertIsNone(exchange_oauth_code(make_request(), "code123"))

    @patch("remarkbox.lib.discord.requests.post")
    def test_bad_json_returns_none(self, mock_post):
        mock_post.return_value.json.side_effect = ValueError("not json")
        self.assertIsNone(exchange_oauth_code(make_request(), "code123"))


# ---------------------------------------------------------------------------
# Unit tests for notify fan-out.
# ---------------------------------------------------------------------------


def make_node_event(action="commented", data="hello\nworld", discord_records=None):
    node_event = MagicMock()
    node_event.action = action
    node_event.node.data = data
    node_event.node.user.name = "alice"
    namespace = node_event.node.root.namespace
    namespace.name = "example.com"
    namespace.discord_oauth_records = discord_records or []
    return node_event


class TestBuildDiscordDeliveries(unittest.TestCase):
    def test_builds_one_delivery_per_record(self):
        records = [MagicMock(token="uri-1"), MagicMock(token="uri-2")]
        node_event = make_node_event(discord_records=records)
        request = make_request()
        request.host_url = "https://my.remarkbox.com"
        deliveries = build_discord_deliveries(request, node_event)
        self.assertEqual(len(deliveries), 2)
        kind, target, message, channel = deliveries[0]
        self.assertEqual(kind, "discord")
        self.assertEqual(target, "uri-1")
        self.assertIsNone(channel)
        self.assertIn("**alice**", message)
        self.assertIn("new comment", message)
        self.assertIn("> hello\n> world", message)
        self.assertIn("https://my.remarkbox.com/r/", message)

    def test_no_records_no_deliveries(self):
        node_event = make_node_event(discord_records=[])
        self.assertEqual(build_discord_deliveries(make_request(), node_event), [])

    def test_long_excerpt_truncated(self):
        node_event = make_node_event(
            data="x" * 5000, discord_records=[MagicMock(token="uri-1")]
        )
        _, _, message, _ = build_discord_deliveries(make_request(), node_event)[0]
        self.assertIn("…", message)
        self.assertLess(len(message), 1200)


class TestBuildSlackDeliveries(unittest.TestCase):
    def test_builds_one_delivery_per_record(self):
        node_event = make_node_event()
        node_event.node.root.namespace.slack_oauth_records = [MagicMock(token="t1")]
        request = make_request()
        request.host_url = "https://my.remarkbox.com"
        deliveries = build_slack_deliveries(request, node_event)
        self.assertEqual(len(deliveries), 1)
        kind, target, message, channel = deliveries[0]
        self.assertEqual((kind, target, channel), ("slack", "t1", "#remarks"))
        self.assertIn("*alice*", message)

    def test_no_records_no_deliveries(self):
        node_event = make_node_event()
        node_event.node.root.namespace.slack_oauth_records = []
        self.assertEqual(build_slack_deliveries(make_request(), node_event), [])


class TestDeliverWebhookNotifications(unittest.TestCase):
    @patch("remarkbox.lib.discord.post_webhook_message")
    def test_delivers_discord_tuples(self, mock_post):
        deliver_webhook_notifications(
            [("discord", "uri-1", "msg-1", None), ("discord", "uri-2", "msg-2", None)]
        )
        self.assertEqual(mock_post.call_count, 2)
        self.assertEqual(mock_post.call_args_list[0].args, ("uri-1", "msg-1"))

    @patch("remarkbox.lib.notify.Slacker")
    def test_delivers_slack_to_given_channel(self, mock_slacker):
        deliver_webhook_notifications([("slack", "token", "msg", "#general")])
        mock_slacker.return_value.chat.post_message.assert_called_once_with(
            "#general", "msg"
        )

    @patch("remarkbox.lib.notify.Slacker")
    def test_revoked_slack_token_never_raises(self, mock_slacker):
        mock_slacker.return_value.chat.post_message.side_effect = Exception("revoked")
        # must not raise: our delivery thread has nobody to catch for it.
        deliver_webhook_notifications([("slack", "token", "msg", "#remarks")])

    @patch("remarkbox.lib.discord.post_webhook_message")
    def test_async_runs_outside_caller(self, mock_post):
        thread = deliver_webhook_notifications_async(
            [("discord", "uri-1", "msg", None)]
        )
        thread.join(timeout=5)
        self.assertFalse(thread.is_alive())
        mock_post.assert_called_once_with("uri-1", "msg")

    def test_async_empty_deliveries_spawns_nothing(self):
        self.assertIsNone(deliver_webhook_notifications_async([]))


# ---------------------------------------------------------------------------
# Unit tests for oauth_discord / oauth_discord_delete view logic.
# ---------------------------------------------------------------------------


class TestOauthDiscordView(unittest.TestCase):
    def test_bad_state_nonce_rejected(self):
        request = make_request(params={"state": "example.com:wrong-nonce"})
        oauth_discord(request)
        flashed = request.session.flash.call_args.args[0]
        self.assertEqual(flashed, ("Invalid OAuth state.", "error"))

    def test_missing_state_rejected(self):
        request = make_request(params={})
        oauth_discord(request)
        flashed = request.session.flash.call_args.args[0]
        self.assertEqual(flashed, ("Invalid OAuth state.", "error"))

    @patch("remarkbox.views.authenticated.oauth.get_namespace_by_name")
    def test_non_owner_rejected(self, mock_get_ns):
        request = make_request(params={"state": "example.com:nonce123"})
        mock_get_ns.return_value.owners = []
        oauth_discord(request)
        flashed = request.session.flash.call_args.args[0]
        self.assertEqual(flashed, ("You do not own that Namespace.", "error"))

    @patch("remarkbox.views.authenticated.oauth.get_namespace_by_name")
    def test_access_denied_flashes_info(self, mock_get_ns):
        request = make_request(
            params={"state": "example.com:nonce123", "error": "access_denied"}
        )
        namespace = mock_get_ns.return_value
        namespace.owners = [request.user]
        oauth_discord(request)
        flashed = request.session.flash.call_args.args[0]
        self.assertEqual(flashed[1], "info")
        namespace.add_oauth_record.assert_not_called()

    @patch("remarkbox.lib.discord.post_webhook_message_async")
    @patch("remarkbox.lib.discord.exchange_oauth_code")
    @patch("remarkbox.views.authenticated.oauth.get_namespace_by_name")
    def test_success_stores_record_and_posts_test_message(
        self, mock_get_ns, mock_exchange, mock_post
    ):
        request = make_request(
            params={"state": "example.com:nonce123", "code": "code123"}
        )
        namespace = mock_get_ns.return_value
        namespace.owners = [request.user]
        namespace.name = "example.com"
        mock_exchange.return_value = {"webhook": {"url": WEBHOOK_URI}}
        oauth_discord(request)
        namespace.add_oauth_record.assert_called_once_with(
            user=request.user,
            service="discord",
            token=WEBHOOK_URI,
            data={"webhook": {"url": WEBHOOK_URI}},
        )
        self.assertEqual(mock_post.call_args.args[0], WEBHOOK_URI)

    @patch("remarkbox.lib.discord.exchange_oauth_code")
    @patch("remarkbox.views.authenticated.oauth.get_namespace_by_name")
    def test_failed_exchange_flashes_error(self, mock_get_ns, mock_exchange):
        request = make_request(
            params={"state": "example.com:nonce123", "code": "bad"}
        )
        namespace = mock_get_ns.return_value
        namespace.owners = [request.user]
        mock_exchange.return_value = None
        oauth_discord(request)
        flashed = request.session.flash.call_args.args[0]
        self.assertEqual(flashed[1], "error")
        namespace.add_oauth_record.assert_not_called()


class TestOauthDiscordDeleteView(unittest.TestCase):
    @patch("remarkbox.lib.discord.delete_webhook")
    @patch("remarkbox.views.authenticated.oauth.get_oauth_by_id")
    def test_owner_deletes_record_and_discord_webhook(
        self, mock_get_oauth, mock_delete
    ):
        request = make_request(params={"oauth-id": "some-id"})
        record = mock_get_oauth.return_value
        record.token = WEBHOOK_URI
        record.namespace.owners = [request.user]
        oauth_discord_delete(request)
        mock_delete.assert_called_once_with(WEBHOOK_URI)
        request.dbsession.delete.assert_called_once_with(record)

    @patch("remarkbox.lib.discord.delete_webhook")
    @patch("remarkbox.views.authenticated.oauth.get_oauth_by_id")
    def test_non_owner_rejected(self, mock_get_oauth, mock_delete):
        request = make_request(params={"oauth-id": "some-id"})
        record = mock_get_oauth.return_value
        record.namespace.owners = []
        oauth_discord_delete(request)
        mock_delete.assert_not_called()
        request.dbsession.delete.assert_not_called()

    @patch("remarkbox.lib.discord.delete_webhook")
    @patch("remarkbox.views.authenticated.oauth.get_oauth_by_id")
    def test_unknown_id_flashes_error(self, mock_get_oauth, mock_delete):
        request = make_request(params={"oauth-id": "nope"})
        mock_get_oauth.return_value = None
        oauth_discord_delete(request)
        mock_delete.assert_not_called()
        flashed = request.session.flash.call_args.args[0]
        self.assertEqual(flashed, ("Invalid OAuth Id.", "error"))


if __name__ == "__main__":
    unittest.main()
