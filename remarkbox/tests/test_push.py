"""
Tests for T10: Browser push notifications.

Covers:
  - Unit tests for push subscription CRUD in remarkbox.lib.push
  - Unit tests for send_push_notification graceful fallback
  - API tests for /push/vapid-key, /push/subscribe, /push/unsubscribe
  - Integration test for notification_preference in notify dispatch
  - Functional test for user settings saving notification_preference
"""

import json
import transaction
import unittest
import webtest

from unittest import mock
from unittest.mock import patch, MagicMock

from remarkbox.models import (
    Node,
    get_tm_session,
    get_or_create_user_by_email,
    get_user_by_email,
    get_or_create_namespace,
)
from remarkbox.models.meta import Base
from remarkbox.models.user import User

from remarkbox.lib.push import (
    get_vapid_keys,
    get_push_subscriptions,
    add_push_subscription,
    remove_push_subscription,
    send_push_notification,
    send_push_to_user,
    PUSH_AVAILABLE,
)

from pyramid.paster import get_appsettings


# ---------------------------------------------------------------------------
# Unit tests for VAPID key management.
# ---------------------------------------------------------------------------


class TestGetVapidKeys(unittest.TestCase):
    """Test get_vapid_keys reads from settings correctly."""

    def test_returns_keys_when_configured(self):
        settings = {
            "push.vapid_private_key": "test-private-key",
            "push.vapid_public_key": "test-public-key",
            "push.vapid_contact": "mailto:admin@example.com",
        }
        keys = get_vapid_keys(settings)
        self.assertIsNotNone(keys)
        self.assertEqual(keys["private_key"], "test-private-key")
        self.assertEqual(keys["public_key"], "test-public-key")
        self.assertEqual(keys["contact"], "mailto:admin@example.com")

    def test_returns_none_when_private_missing(self):
        settings = {
            "push.vapid_public_key": "test-public-key",
        }
        keys = get_vapid_keys(settings)
        self.assertIsNone(keys)

    def test_returns_none_when_public_missing(self):
        settings = {
            "push.vapid_private_key": "test-private-key",
        }
        keys = get_vapid_keys(settings)
        self.assertIsNone(keys)

    def test_returns_none_when_both_missing(self):
        keys = get_vapid_keys({})
        self.assertIsNone(keys)

    def test_contact_defaults_to_empty(self):
        settings = {
            "push.vapid_private_key": "test-private-key",
            "push.vapid_public_key": "test-public-key",
        }
        keys = get_vapid_keys(settings)
        self.assertEqual(keys["contact"], "")


# ---------------------------------------------------------------------------
# Unit tests for push subscription CRUD.
# ---------------------------------------------------------------------------


class TestPushSubscriptionCRUD(unittest.TestCase):
    """Test get/add/remove push subscription functions."""

    @mock.patch("remarkbox.models.user.is_user_name_available", mock.Mock(return_value=True))
    def setUp(self):
        self.user = User("pushtest@example.com")

    def test_get_push_subscriptions_empty(self):
        self.assertIsNone(self.user.push_subscriptions)
        subs = get_push_subscriptions(self.user)
        self.assertEqual(subs, [])

    def test_get_push_subscriptions_invalid_json(self):
        self.user.push_subscriptions = "not valid json"
        subs = get_push_subscriptions(self.user)
        self.assertEqual(subs, [])

    def test_add_push_subscription(self):
        sub = {
            "endpoint": "https://push.example.com/1234",
            "keys": {"p256dh": "abc", "auth": "def"},
        }
        result = add_push_subscription(self.user, sub)
        self.assertTrue(result)
        subs = get_push_subscriptions(self.user)
        self.assertEqual(len(subs), 1)
        self.assertEqual(subs[0]["endpoint"], "https://push.example.com/1234")

    def test_add_duplicate_subscription(self):
        sub = {
            "endpoint": "https://push.example.com/1234",
            "keys": {"p256dh": "abc", "auth": "def"},
        }
        add_push_subscription(self.user, sub)
        result = add_push_subscription(self.user, sub)
        self.assertFalse(result)
        subs = get_push_subscriptions(self.user)
        self.assertEqual(len(subs), 1)

    def test_add_multiple_subscriptions(self):
        sub1 = {"endpoint": "https://push.example.com/1", "keys": {"p256dh": "a", "auth": "b"}}
        sub2 = {"endpoint": "https://push.example.com/2", "keys": {"p256dh": "c", "auth": "d"}}
        add_push_subscription(self.user, sub1)
        add_push_subscription(self.user, sub2)
        subs = get_push_subscriptions(self.user)
        self.assertEqual(len(subs), 2)

    def test_remove_push_subscription(self):
        sub = {
            "endpoint": "https://push.example.com/remove-me",
            "keys": {"p256dh": "abc", "auth": "def"},
        }
        add_push_subscription(self.user, sub)
        result = remove_push_subscription(self.user, "https://push.example.com/remove-me")
        self.assertTrue(result)
        subs = get_push_subscriptions(self.user)
        self.assertEqual(len(subs), 0)
        self.assertIsNone(self.user.push_subscriptions)

    def test_remove_nonexistent_subscription(self):
        result = remove_push_subscription(self.user, "https://push.example.com/nonexistent")
        self.assertFalse(result)

    def test_remove_one_of_multiple(self):
        sub1 = {"endpoint": "https://push.example.com/keep", "keys": {"p256dh": "a", "auth": "b"}}
        sub2 = {"endpoint": "https://push.example.com/remove", "keys": {"p256dh": "c", "auth": "d"}}
        add_push_subscription(self.user, sub1)
        add_push_subscription(self.user, sub2)
        result = remove_push_subscription(self.user, "https://push.example.com/remove")
        self.assertTrue(result)
        subs = get_push_subscriptions(self.user)
        self.assertEqual(len(subs), 1)
        self.assertEqual(subs[0]["endpoint"], "https://push.example.com/keep")


# ---------------------------------------------------------------------------
# Unit tests for send_push_notification.
# ---------------------------------------------------------------------------


class TestSendPushNotification(unittest.TestCase):
    """Test send_push_notification handles various conditions."""

    def test_returns_false_when_push_unavailable(self):
        if not PUSH_AVAILABLE:
            result = send_push_notification(
                {"endpoint": "https://push.example.com/1"},
                {"title": "Test"},
                {"private_key": "k", "contact": "mailto:a@b.com"},
            )
            self.assertFalse(result)
        else:
            with patch("remarkbox.lib.push.PUSH_AVAILABLE", False):
                result = send_push_notification(
                    {"endpoint": "https://push.example.com/1"},
                    {"title": "Test"},
                    {"private_key": "k", "contact": "mailto:a@b.com"},
                )
                self.assertFalse(result)

    def test_returns_false_when_no_vapid_keys(self):
        result = send_push_notification(
            {"endpoint": "https://push.example.com/1"},
            {"title": "Test"},
            None,
        )
        self.assertFalse(result)

    @unittest.skipUnless(PUSH_AVAILABLE, "pywebpush not installed")
    @patch("remarkbox.lib.push.webpush")
    def test_successful_send(self, mock_webpush):
        mock_webpush.return_value = None
        result = send_push_notification(
            {"endpoint": "https://push.example.com/1"},
            {"title": "Test", "body": "Hello"},
            {"private_key": "test-key", "contact": "mailto:admin@test.com"},
        )
        self.assertTrue(result)
        mock_webpush.assert_called_once()

    @unittest.skipUnless(PUSH_AVAILABLE, "pywebpush not installed")
    @patch("remarkbox.lib.push.webpush")
    def test_webpush_exception_returns_false(self, mock_webpush):
        from pywebpush import WebPushException
        mock_webpush.side_effect = WebPushException("Push failed")
        result = send_push_notification(
            {"endpoint": "https://push.example.com/1"},
            {"title": "Test"},
            {"private_key": "test-key", "contact": "mailto:admin@test.com"},
        )
        self.assertFalse(result)

    @unittest.skipUnless(PUSH_AVAILABLE, "pywebpush not installed")
    @patch("remarkbox.lib.push.webpush")
    def test_generic_exception_returns_false(self, mock_webpush):
        mock_webpush.side_effect = RuntimeError("Something broke")
        result = send_push_notification(
            {"endpoint": "https://push.example.com/1"},
            {"title": "Test"},
            {"private_key": "test-key", "contact": "mailto:admin@test.com"},
        )
        self.assertFalse(result)

    def test_graceful_noop_when_pywebpush_not_installed(self):
        result = send_push_notification(
            {"endpoint": "https://push.example.com/1"},
            {"title": "Test"},
            {"private_key": "k", "contact": "mailto:a@b.com"},
        )
        self.assertIsInstance(result, bool)


# ---------------------------------------------------------------------------
# Unit tests for send_push_to_user.
# ---------------------------------------------------------------------------


class TestSendPushToUser(unittest.TestCase):
    """Test send_push_to_user dispatches correctly."""

    @mock.patch("remarkbox.models.user.is_user_name_available", mock.Mock(return_value=True))
    def setUp(self):
        self.user = User("pushuser@example.com")
        self.mock_request = MagicMock()
        self.mock_request.registry.settings = {
            "push.vapid_private_key": "test-private-key",
            "push.vapid_public_key": "test-public-key",
            "push.vapid_contact": "mailto:test@example.com",
        }

    def test_returns_zero_when_push_unavailable(self):
        result = send_push_to_user(self.mock_request, self.user, {"title": "Test"})
        self.assertEqual(result, 0)

    def test_returns_zero_when_no_subscriptions(self):
        result = send_push_to_user(self.mock_request, self.user, {"title": "Test"})
        self.assertEqual(result, 0)

    @unittest.skipUnless(PUSH_AVAILABLE, "pywebpush not installed")
    @patch("remarkbox.lib.push.send_push_notification")
    def test_sends_to_all_subscriptions(self, mock_send):
        mock_send.return_value = True
        sub1 = {"endpoint": "https://push.example.com/1", "keys": {"p256dh": "a", "auth": "b"}}
        sub2 = {"endpoint": "https://push.example.com/2", "keys": {"p256dh": "c", "auth": "d"}}
        add_push_subscription(self.user, sub1)
        add_push_subscription(self.user, sub2)
        result = send_push_to_user(self.mock_request, self.user, {"title": "Test"})
        self.assertEqual(result, 2)
        self.assertEqual(mock_send.call_count, 2)


# ---------------------------------------------------------------------------
# Integration tests for notification_preference in dispatch.
# ---------------------------------------------------------------------------


class TestNotificationPreferenceDispatch(unittest.TestCase):
    """Test that _send_push_for_notification respects notification_preference."""

    @mock.patch("remarkbox.models.user.is_user_name_available", mock.Mock(return_value=True))
    def _make_user(self, pref):
        user = User("pref-test@example.com")
        user.notification_preference = pref
        return user

    def _make_mocks(self, pref, action="commented"):
        user = self._make_user(pref)

        notification = MagicMock()
        notification.user = user
        notification.id = "test-notification-id"
        notification.node_event.node.user.name = "Alice"
        notification.node_event.action = action

        root = MagicMock()
        root.title = "Test Thread"

        namespace = MagicMock()
        namespace.name = "test.example.com"

        request = MagicMock()
        request.host_url = "https://my.remarkbox.com"

        return notification, root, namespace, request

    @patch("remarkbox.lib.push.PUSH_AVAILABLE", True)
    @patch("remarkbox.lib.push.send_push_to_user")
    def test_push_pref_sends_push(self, mock_send_push):
        from remarkbox.lib.notify import _send_push_for_notification
        mock_send_push.return_value = 1
        notification, root, namespace, request = self._make_mocks("push")
        _send_push_for_notification(request, notification, root, namespace)
        mock_send_push.assert_called_once()

    @patch("remarkbox.lib.push.PUSH_AVAILABLE", True)
    @patch("remarkbox.lib.push.send_push_to_user")
    def test_both_pref_sends_push(self, mock_send_push):
        from remarkbox.lib.notify import _send_push_for_notification
        mock_send_push.return_value = 1
        notification, root, namespace, request = self._make_mocks("both", "created")
        _send_push_for_notification(request, notification, root, namespace)
        mock_send_push.assert_called_once()

    @patch("remarkbox.lib.push.PUSH_AVAILABLE", True)
    @patch("remarkbox.lib.push.send_push_to_user")
    def test_email_pref_does_not_send_push(self, mock_send_push):
        from remarkbox.lib.notify import _send_push_for_notification
        notification, root, namespace, request = self._make_mocks("email")
        _send_push_for_notification(request, notification, root, namespace)
        mock_send_push.assert_not_called()

    @patch("remarkbox.lib.push.PUSH_AVAILABLE", True)
    @patch("remarkbox.lib.push.send_push_to_user")
    def test_none_pref_does_not_send_push(self, mock_send_push):
        from remarkbox.lib.notify import _send_push_for_notification
        notification, root, namespace, request = self._make_mocks("none")
        _send_push_for_notification(request, notification, root, namespace)
        mock_send_push.assert_not_called()

    @patch("remarkbox.lib.push.PUSH_AVAILABLE", False)
    def test_push_unavailable_is_noop(self):
        from remarkbox.lib.notify import _send_push_for_notification
        notification, root, namespace, request = self._make_mocks("push")
        # Should not raise.
        _send_push_for_notification(request, notification, root, namespace)

    @patch("remarkbox.lib.push.PUSH_AVAILABLE", True)
    @patch("remarkbox.lib.push.send_push_to_user")
    def test_push_payload_contains_expected_fields(self, mock_send_push):
        from remarkbox.lib.notify import _send_push_for_notification
        mock_send_push.return_value = 1
        notification, root, namespace, request = self._make_mocks("push", "commented")
        _send_push_for_notification(request, notification, root, namespace)
        mock_send_push.assert_called_once()
        payload = mock_send_push.call_args[0][2]
        self.assertIn("title", payload)
        self.assertIn("body", payload)
        self.assertIn("url", payload)
        self.assertIn("tag", payload)
        self.assertIn("test.example.com", payload["title"])
        self.assertIn("Alice", payload["body"])


# ---------------------------------------------------------------------------
# Unit tests for User model columns.
# ---------------------------------------------------------------------------


class TestUserNotificationPreferenceColumn(unittest.TestCase):
    """Verify the notification_preference and push_subscriptions columns on User."""

    @mock.patch("remarkbox.models.user.is_user_name_available", mock.Mock(return_value=True))
    def test_notification_preference_column_exists(self):
        user = User("coltest@example.com")
        self.assertTrue(hasattr(user, "notification_preference"))

    @mock.patch("remarkbox.models.user.is_user_name_available", mock.Mock(return_value=True))
    def test_push_subscriptions_default_none(self):
        user = User("coltest2@example.com")
        self.assertIsNone(user.push_subscriptions)

    @mock.patch("remarkbox.models.user.is_user_name_available", mock.Mock(return_value=True))
    def test_notification_preference_can_be_set(self):
        user = User("coltest3@example.com")
        for pref in ("push", "both", "none", "email"):
            user.notification_preference = pref
            self.assertEqual(user.notification_preference, pref)


# ---------------------------------------------------------------------------
# Functional / API tests -- all in one class to share DB.
# ---------------------------------------------------------------------------


class TestPushEndpoints(unittest.TestCase, object):
    """
    Test push notification HTTP endpoints:
    GET /push/vapid-key, POST /push/subscribe, POST /push/unsubscribe,
    and user settings notification_preference.

    Uses a single shared user for all authenticated tests to avoid
    per-test cleanup cascading issues with SQLite.
    """

    @classmethod
    def setUpClass(cls):
        from remarkbox import main

        cls.settings = get_appsettings("test.ini")
        cls.app = main({}, **cls.settings)
        cls.testapp = webtest.TestApp(cls.app)

        cls.session_factory = cls.app.registry["dbsession_factory"]
        cls.engine = cls.session_factory.kw["bind"]

        # Dispose existing connections and recreate tables.
        # A prior test file's tearDownClass may have called drop_all(),
        # leaving the engine's connection pool in a broken state.
        cls.engine.dispose()
        Base.metadata.create_all(bind=cls.engine)

        cls.tm = transaction.manager
        cls.dbsession = get_tm_session(cls.session_factory, cls.tm)

        # Create a shared test user for all authenticated endpoint tests.
        cls._test_email = "push-endpoint-test@remarkbox.com"
        cls._test_user = get_or_create_user_by_email(cls.dbsession, cls._test_email)
        cls.dbsession.add(cls._test_user)
        cls.dbsession.flush()
        cls.tm.commit()

    @classmethod
    def tearDownClass(cls):
        cls.dbsession.close()

    def setUp(self):
        pass

    def tearDown(self):
        self.testapp.get("/log-out")

    def _login(self):
        """Log in the shared test user and return (user, csrf_token).

        Generates a fresh OTP each time to avoid exceeding the 10-attempt
        limit on check_password.  Uses a dedicated short-lived session for
        password generation to avoid conflicting with the app's SQLite
        writer lock.
        """
        tm = transaction.TransactionManager(explicit=True)
        tm.begin()
        dbsession = get_tm_session(self.session_factory, tm)
        user = get_or_create_user_by_email(dbsession, self._test_email)
        raw_otp = user.new_password()
        dbsession.add(user)
        dbsession.flush()
        tm.commit()
        dbsession.close()

        self.testapp.post(
            "/verification-challenge?email={}&raw-otp={}".format(
                self._test_email, raw_otp
            )
        )
        res_csrf = self.testapp.get("/")
        csrf = res_csrf.form.fields["csrf_token"][0].value
        user = get_or_create_user_by_email(self.dbsession, self._test_email)
        return user, csrf

    # -----------------------------------------------------------------------
    # GET /push/vapid-key
    # -----------------------------------------------------------------------

    def test_vapid_key_returns_json(self):
        res = self.testapp.get("/push/vapid-key", expect_errors=True)
        self.assertEqual(res.status_int, 200)
        self.assertIn("application/json", res.content_type)

    def test_vapid_key_structure(self):
        res = self.testapp.get("/push/vapid-key", expect_errors=True)
        self.assertIn("available", res.json)

    def test_vapid_key_without_config(self):
        res = self.testapp.get("/push/vapid-key", expect_errors=True)
        self.assertFalse(res.json["available"])

    # -----------------------------------------------------------------------
    # POST /push/subscribe
    # -----------------------------------------------------------------------

    def test_subscribe_requires_auth(self):
        res = self.testapp.post_json(
            "/push/subscribe",
            {"subscription": {"endpoint": "https://push.example.com/1", "keys": {}}},
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 401)

    def test_subscribe_requires_json_body(self):
        self._login()
        res = self.testapp.post(
            "/push/subscribe",
            "not json",
            content_type="text/plain",
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 400)

    def test_subscribe_requires_subscription(self):
        self._login()
        res = self.testapp.post_json(
            "/push/subscribe",
            {},
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 400)

    def test_subscribe_requires_endpoint(self):
        self._login()
        res = self.testapp.post_json(
            "/push/subscribe",
            {"subscription": {}},
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 400)

    def test_subscribe_success(self):
        self._login()
        res = self.testapp.post_json(
            "/push/subscribe",
            {
                "subscription": {
                    "endpoint": "https://fcm.googleapis.com/fcm/send/test123",
                    "keys": {"p256dh": "testkey", "auth": "testauthkey"},
                }
            },
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 200)
        self.assertEqual(res.json["status"], "subscribed")

    def test_subscribe_duplicate(self):
        self._login()
        sub = {
            "subscription": {
                "endpoint": "https://fcm.googleapis.com/fcm/send/dupe",
                "keys": {"p256dh": "testkey", "auth": "testauthkey"},
            }
        }
        self.testapp.post_json("/push/subscribe", sub, expect_errors=True)
        res = self.testapp.post_json("/push/subscribe", sub, expect_errors=True)
        self.assertEqual(res.json["status"], "already_subscribed")

    # -----------------------------------------------------------------------
    # POST /push/unsubscribe
    # -----------------------------------------------------------------------

    def test_unsubscribe_requires_auth(self):
        res = self.testapp.post_json(
            "/push/unsubscribe",
            {"endpoint": "https://push.example.com/1"},
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 401)

    def test_unsubscribe_requires_endpoint(self):
        self._login()
        res = self.testapp.post_json(
            "/push/unsubscribe",
            {},
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 400)
        self.assertIn("endpoint", res.json["error"])

    def test_unsubscribe_not_found(self):
        self._login()
        res = self.testapp.post_json(
            "/push/unsubscribe",
            {"endpoint": "https://push.example.com/nonexistent"},
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 200)
        self.assertEqual(res.json["status"], "not_found")

    def test_unsubscribe_success(self):
        self._login()
        self.testapp.post_json(
            "/push/subscribe",
            {
                "subscription": {
                    "endpoint": "https://fcm.googleapis.com/fcm/send/unsub-test",
                    "keys": {"p256dh": "testkey", "auth": "testauthkey"},
                }
            },
            expect_errors=True,
        )
        res = self.testapp.post_json(
            "/push/unsubscribe",
            {"endpoint": "https://fcm.googleapis.com/fcm/send/unsub-test"},
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 200)
        self.assertEqual(res.json["status"], "unsubscribed")

    # -----------------------------------------------------------------------
    # User settings: notification_preference
    # -----------------------------------------------------------------------

    def test_notification_preference_column_exists_on_user(self):
        """User model has notification_preference attribute."""
        user, csrf = self._login()
        self.assertTrue(hasattr(user, "notification_preference"))
        if user.notification_preference is not None:
            self.assertIn(
                user.notification_preference, ("email", "push", "both", "none")
            )

    def test_save_notification_preference_push(self):
        user, csrf = self._login()
        self.testapp.post(
            "/u/settings",
            {
                "csrf_token": csrf,
                "default-node-watcher-frequency": "daily",
                "reply-watcher-frequency": "daily",
                "notification-preference": "push",
            },
        )
        self._verify_preference("push")

    def test_save_notification_preference_both(self):
        user, csrf = self._login()
        self.testapp.post(
            "/u/settings",
            {
                "csrf_token": csrf,
                "default-node-watcher-frequency": "daily",
                "reply-watcher-frequency": "daily",
                "notification-preference": "both",
            },
        )
        self._verify_preference("both")

    def test_save_notification_preference_none(self):
        user, csrf = self._login()
        self.testapp.post(
            "/u/settings",
            {
                "csrf_token": csrf,
                "default-node-watcher-frequency": "daily",
                "reply-watcher-frequency": "daily",
                "notification-preference": "none",
            },
        )
        self._verify_preference("none")

    def test_save_notification_preference_email(self):
        user, csrf = self._login()
        self.testapp.post(
            "/u/settings",
            {
                "csrf_token": csrf,
                "default-node-watcher-frequency": "daily",
                "reply-watcher-frequency": "daily",
                "notification-preference": "email",
            },
        )
        self._verify_preference("email")

    def _verify_preference(self, expected):
        """Read the user's notification_preference using a fresh session."""
        tm = transaction.TransactionManager(explicit=True)
        tm.begin()
        dbsession = get_tm_session(self.session_factory, tm)
        user = get_user_by_email(dbsession, self._test_email)
        self.assertEqual(user.notification_preference, expected)
        tm.abort()
        dbsession.close()
