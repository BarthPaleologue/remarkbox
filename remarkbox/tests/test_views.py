import transaction
import unittest
import webtest

from remarkbox.models import (
    Node,
    get_tm_session,
    get_or_create_user_by_email,
    get_user_by_email,
    get_or_create_namespace,
    NodeEventNotification,
    UserSurrogate,
)

from remarkbox.models.meta import Base

from remarkbox.lib.notify import deliver_scheduled_notifications

from pyramid.paster import get_appsettings

from unittest import mock
from unittest.mock import patch, call
import re

try:
    unicode("")
except:
    from six import u as unicode


# todo we should pick a new file to put test helpers.
mock_always_true = mock.Mock(return_value=True)


# todo we should pick a new file to put test helpers.
class FunctionalTests(unittest.TestCase, object):

    @classmethod
    def setUpClass(cls):
        from remarkbox import main

        cls.settings = get_appsettings("test.ini")

        cls.app = main({}, **cls.settings)
        cls.testapp = webtest.TestApp(cls.app)

        cls.session_factory = cls.app.registry["dbsession_factory"]
        cls.engine = cls.session_factory.kw["bind"]
        Base.metadata.create_all(bind=cls.engine)

        cls.tm = transaction.manager
        cls.dbsession = get_tm_session(cls.session_factory, cls.tm)

    @classmethod
    def tearDownClass(cls):
        # drop all tables in database.
        cls.dbsession.close()
        Base.metadata.drop_all(bind=cls.engine)

    def tearDown(self):
        # log out test_user.
        self.testapp.get("/log-out")


class UnauthenticatedFunctionalTests(FunctionalTests):

    def test_root_home_page(self):
        res = self.testapp.get("/", status=200)
        self.assertTrue(b"FAQ" in res.body)
        self.assertTrue(b"Meta" in res.body)
        self.assertTrue(b"About" in res.body)
        self.assertTrue(b"Demo" in res.body)
        self.assertTrue(b"Plans" in res.body)
        self.assertTrue(b"join-or-log-in" in res.body)

    def test_top_secret_redirects(self):
        redirect_res = self.testapp.get("/topsecret", status=302)
        res = redirect_res.follow()
        self.assertTrue(b"You must be a super fly admin to access that." in res.body)

    def test_billing_redirects(self):
        redirect_res = self.testapp.get("/billing", status=302)
        res = redirect_res.follow()
        self.assertTrue(b"Please verify your email to access billing." in res.body)

    def test_user_settings_redirects(self):
        redirect_res = self.testapp.get("/u/settings", status=302)
        res = redirect_res.follow()
        self.assertTrue(b"You must log in to access that area." in res.body)

    @patch("smtplib.SMTP")
    def test_new_thread(self, mock_smtp):
        redirect_res1 = self.testapp.post(
            "/new",
            {
                "thread_title": "test title",
                "thread_data": "test data",
                "email": "test@example.com",
            },
            status=302,
        )
        redirect_res2 = redirect_res1.follow()
        self.assertIn(b"The resource was found at", redirect_res2.body)

        res = redirect_res2.follow()
        self.assertIn(b"Your post was successful!", res.body)
        self.assertIn(b"We just sent a link to test@example.com. Check email to log in.", res.body)

    def test_new_thread_without_email(self):
        redirect_res = self.testapp.post(
            "/new",
            {
                "thread_title": "test title",
                "thread_data": "test data",
            },
            status=302,
        )
        res = redirect_res.follow()
        self.assertTrue(b"Press the back button to fix your email address" in res.body)

    def _get_nodes_by_ip(self, ip):
        from sqlalchemy.orm.exc import NoResultFound

        try:
            return (
                self.dbsession.query(Node).filter(Node.ip_address == unicode(ip)).all()
            )

        except NoResultFound:
            return None

    def test_ip_addr(self):
        # this mocks the inbound request ip address.
        test_addr = "127.0.0.2"
        self.testapp.extra_environ.update({"REMOTE_ADDR": test_addr})

        response = self.testapp.post(
            "/new",
            {
                "thread_title": "test title",
                "thread_data": "test data",
                "email": "test@remarkbox.com",
            },
        )
        self.assertTrue(bool(response))

        nodes = self._get_nodes_by_ip(test_addr)
        self.assertTrue(bool(nodes))


class AuthenticatedFunctionalTests(FunctionalTests):

    @classmethod
    def setUpClass(cls):
        try:
            # Python 2.
            FunctionalTests.setUpClass.im_func(cls)
        except AttributeError:
            # Python 3.
            FunctionalTests.setUpClass.__func__(cls)

    def setUp(self):
        # create test_user1
        self.test_user1 = get_or_create_user_by_email(
            self.dbsession, "test1@remarkbox.com"
        )
        self.raw_otp1 = self.test_user1.new_password()

        # create test_user2
        self.test_user2 = get_or_create_user_by_email(
            self.dbsession, "test2@remarkbox.com"
        )
        self.raw_otp2 = self.test_user2.new_password()

        # add to transaction
        self.dbsession.add(self.test_user1)
        self.dbsession.add(self.test_user2)

        # flush to database.
        self.dbsession.flush()

        # commit the transaction.
        self.tm.commit()

        # requery to avoid detached instance error.
        self.test_user1 = get_or_create_user_by_email(
            self.dbsession, "test1@remarkbox.com"
        )
        self.test_user2 = get_or_create_user_by_email(
            self.dbsession, "test2@remarkbox.com"
        )

        self.test_creds1 = ("test1@remarkbox.com", self.raw_otp1)
        self.test_creds2 = ("test2@remarkbox.com", self.raw_otp2)

    def _clean_up_test_user(self, user):
        self.dbsession.delete(user)

    def tearDown(self):
        # log out and delete the test_users in between tests.
        super(AuthenticatedFunctionalTests, self).tearDown()
        self._clean_up_test_user(self.test_user1)
        self._clean_up_test_user(self.test_user2)
        self.dbsession.flush()
        self.tm.commit()

    def _log_in_test_user(self, test_creds):
        # log in user.
        res_login = self.testapp.post(
            "/verification-challenge?email={}&raw-otp={}&submit".format(*test_creds)
        )
        # attach csrf to class.
        res_csrf = self.testapp.get("/")
        self.csrf = res_csrf.form.fields["csrf_token"][0].value
        return res_login

    def test_log_in(self):
        redirect_res = self._log_in_test_user(self.test_creds1)
        res = redirect_res.follow()
        self.assertIn(self.test_user1.name.encode("utf-8"), res.body)

    def test_log_in_or_join_creates_default_watcher(self):
        """This tests makes sure a default watcher is created for new users."""

        # a brand new user has no reply_watchers.
        self.assertEqual(self.test_user1.reply_watchers.count(), 0)

        # after successful authentication, the user will get a default reply_watcher.
        self._log_in_test_user(self.test_creds1)

        # expire self.test_user1 so next time it is accessed it is reloaded.
        self.dbsession.expire(self.test_user1)

        self.assertEqual(self.test_user1.reply_watchers.count(), 1)

        # log the user out and then log back in again.
        self.testapp.get("/log-out")
        self._log_in_test_user(self.test_creds1)

        # expire self.test_user1 so next time it is accessed it is reloaded.
        self.dbsession.expire(self.test_user1)

        # after a subsequent re-authentication, the user will still have a
        # default reply_watcher. reply_watcher count does not increase.
        self.assertEqual(self.test_user1.reply_watchers.count(), 1)

    @patch("smtplib.SMTP")
    @patch("remarkbox.models.NamespaceRequest.scrape_target", mock_always_true)
    def test_namespace_request_and_verification(self, mock_smtp):
        """This tests steps through the process of setting up a new Namespace."""

        target_namespace_domain = "www.example.com"

        self._log_in_test_user(self.test_creds1)

        self.assertEqual(self.test_user1.namespace_owner_requests.count(), 0)

        setup_step_1_response = self.testapp.post(
            "/setup",
            {
                "namespace-domain": target_namespace_domain,
                "csrf_token": self.csrf,
            },
        )

        self.assertTrue(b"Great work, on to Step 2!" in setup_step_1_response.body)

        self.dbsession.refresh(self.test_user1)

        self.assertEqual(self.test_user1.namespace_owner_requests.count(), 1)

        namespace_request = self.test_user1.namespace_owner_requests[0]

        self.assertFalse(namespace_request.verified)
        self.assertEqual(namespace_request.namespace.name, target_namespace_domain)

        embed_thread_uri = "/embed?rb_owner_key={}&thread_uri={}/test.html"
        verify_response = self.testapp.get(
            embed_thread_uri.format(namespace_request.id, target_namespace_domain)
        )

        self.assertTrue(b"Namespace owner was verified!" in verify_response.body)

        self.dbsession.refresh(namespace_request)
        self.assertTrue(namespace_request.verified)

    @patch("smtplib.SMTP")
    def test_notifications(self, mock_smtp):
        """
        In this test we create 2 test users.
        
        The first test user logs in, configures notification settings, and creates a new thread. This test user logs out.
        
        The next test user logs in, configures notification settings, and replies to the original thread.
        
        We test that only 1 notification is created for the first user. 

        
        """

        self._log_in_test_user(self.test_creds1)

        # test for immediate notifications

        self.testapp.post(
            "/u/settings",
            {
                "csrf_token": self.csrf,
                "default-node-watcher-frequency": "immediately",
                "reply-watcher-frequency": "immediately",
            },
        )

        new_resp = self.testapp.post(
            "/new",
            {
                "thread_title": "test title",
                "thread_data": "test data",
                "csrf_token": self.csrf,
            },
        )

        thread_url = new_resp.headers["location"]
        root_id = re.search("\/([^/]*)\/[^/]*$", thread_url).group(1)

        self.testapp.post("/watch", {"csrf_token": self.csrf, "root-id": root_id})

        self.testapp.get("/log-out")
        self._log_in_test_user(self.test_creds2)

        self.testapp.post(
            "/u/settings",
            {
                "csrf_token": self.csrf,
                "default-node-watcher-frequency": "immediately",
                "reply-watcher-frequency": "immediately",
            },
        )

        self.testapp.post(
            "/{}/reply".format(root_id),
            {"csrf_token": self.csrf, "thread_data": "test reply data"},
        )

        notifications = list(self.dbsession.query(NodeEventNotification).all())
        self.assertEqual(len(notifications), 1)

        self.assertEqual(self.test_user1.id, notifications[0].user_id)

        instance = mock_smtp.return_value
        self.assertTrue(instance.sendmail.called)

        # log back in as the thread creator and rewatch thread as daily.
        self.testapp.get("/log-out")
        self._log_in_test_user(self.test_creds1)

        self.testapp.post("/unwatch", {"csrf_token": self.csrf, "root-id": root_id})

        self.testapp.post(
            "/u/settings",
            {
                "csrf_token": self.csrf,
                "default-node-watcher-frequency": "daily",
                "reply-watcher-frequency": "daily",
            },
        )

        self.testapp.post("/watch", {"csrf_token": self.csrf, "root-id": root_id})

        # log back in as 2nd test user and post another reply.
        self.testapp.get("/log-out")
        self._log_in_test_user(self.test_creds2)

        self.testapp.post(
            "/{}/reply".format(root_id),
            {"csrf_token": self.csrf, "thread_data": "test reply data"},
        )

        # prove that there is 1 notification waiting to go out.
        notifications = list(
            self.dbsession.query(NodeEventNotification).filter(
                NodeEventNotification.sent == False
            )
        )
        self.assertEqual(len(notifications), 1)

        from time import sleep

        # simulating waiting a "day" of time.
        # deliver_scheduled_notifications invokes as console script via cron.
        sleep(1)
        deliver_scheduled_notifications()
        self.assertTrue(instance.sendmail.called)

        # prove that the notification was sent.
        notifications = list(
            self.dbsession.query(NodeEventNotification).filter(
                NodeEventNotification.sent == False
            )
        )
        self.assertEqual(len(notifications), 0)

        notifications = list(self.dbsession.query(NodeEventNotification).all())
        self.assertEqual(len(notifications), 1)

        # make sure our daily notification was sent.
        self.assertEqual(notifications[0].frequency, "daily")
        self.assertTrue(notifications[0].sent)

    def test_billing_page_loads(self):
        """Test that the billing page loads for authenticated users."""
        self._log_in_test_user(self.test_creds1)
        res = self.testapp.get("/billing", status=200)
        self.assertIn(b"Support Remarkbox", res.body)
        self.assertIn(b"Pay with Stripe", res.body)

    @patch("remarkbox.stripe.checkout.stripe.checkout.Session.create")
    def test_create_checkout_redirects_to_stripe(self, mock_create):
        """Test that create-checkout redirects to Stripe."""
        mock_session = mock.MagicMock()
        mock_session.id = "cs_test_123"
        mock_session.url = "https://checkout.stripe.com/pay/cs_test_123"
        mock_create.return_value = mock_session

        self._log_in_test_user(self.test_creds1)

        redirect_res = self.testapp.post(
            "/billing/checkout",
            {
                "payment_type": "pay_what_you_want",
                "amount": "25",
                "duration_months": "0",
                "csrf_token": self.csrf,
            },
            status=302,
        )

        # Should redirect to Stripe Checkout
        self.assertIn("checkout.stripe.com", redirect_res.location)

    def test_create_checkout_minimum_amount(self):
        """Test that checkout enforces minimum amount."""
        self._log_in_test_user(self.test_creds1)

        redirect_res = self.testapp.post(
            "/billing/checkout",
            {
                "payment_type": "pay_what_you_want",
                "amount": "0.50",
                "duration_months": "0",
                "csrf_token": self.csrf,
            },
            status=302,
        )
        res = redirect_res.follow()
        self.assertIn(b"Minimum payment is $1.00", res.body)

    def test_create_checkout_invalid_amount(self):
        """Test checkout with invalid amount."""
        self._log_in_test_user(self.test_creds1)

        redirect_res = self.testapp.post(
            "/billing/checkout",
            {
                "payment_type": "pay_what_you_want",
                "amount": "not-a-number",
                "duration_months": "0",
                "csrf_token": self.csrf,
            },
            status=302,
        )
        res = redirect_res.follow()
        self.assertIn(b"Invalid amount specified", res.body)

    def test_billing_success_missing_session(self):
        """Test billing success without session_id."""
        self._log_in_test_user(self.test_creds1)

        redirect_res = self.testapp.get("/billing/success", status=302)
        res = redirect_res.follow()
        self.assertIn(b"Missing session information", res.body)


class AnonymousCommentingFunctionalTests(FunctionalTests):
    """Tests for anonymous commenting feature."""

    @classmethod
    def setUpClass(cls):
        try:
            FunctionalTests.setUpClass.im_func(cls)
        except AttributeError:
            FunctionalTests.setUpClass.__func__(cls)

    def setUp(self):
        # Create a namespace with allow_anonymous enabled
        anon_ns = get_or_create_namespace(
            self.dbsession, "anon-test.example.com"
        )
        anon_ns.allow_anonymous = True
        self.dbsession.add(anon_ns)

        # Create a namespace with allow_anonymous disabled (default)
        regular_ns = get_or_create_namespace(
            self.dbsession, "regular-test.example.com"
        )
        regular_ns.allow_anonymous = False
        self.dbsession.add(regular_ns)

        # Create a test user for namespace ownership
        test_user = get_or_create_user_by_email(
            self.dbsession, "anon-test@remarkbox.com"
        )
        self.raw_otp = test_user.new_password()
        self.dbsession.add(test_user)

        self.dbsession.flush()

        # Store IDs and names before commit
        self.anon_namespace_id = anon_ns.id
        self.anon_namespace_name = str(anon_ns.name)
        self.regular_namespace_id = regular_ns.id
        self.regular_namespace_name = str(regular_ns.name)

        self.tm.commit()

        self.test_creds = ("anon-test@remarkbox.com", self.raw_otp)

    def tearDown(self):
        super(AnonymousCommentingFunctionalTests, self).tearDown()
        # Clean up surrogates created during tests
        self.dbsession.query(UserSurrogate).filter(
            UserSurrogate.namespace_id.in_([
                self.anon_namespace_id,
                self.regular_namespace_id
            ])
        ).delete(synchronize_session=False)
        # Requery user before delete
        user = get_user_by_email(self.dbsession, "anon-test@remarkbox.com")
        if user:
            self.dbsession.delete(user)
        self.dbsession.flush()
        self.tm.commit()

    def _log_in_test_user(self):
        res_login = self.testapp.post(
            "/verification-challenge?email={}&raw-otp={}&submit".format(*self.test_creds)
        )
        res_csrf = self.testapp.get("/")
        self.csrf = res_csrf.form.fields["csrf_token"][0].value
        return res_login

    def test_anonymous_reply_creates_surrogate(self):
        """Test that anonymous reply creates a UserSurrogate."""
        # First create a thread with an authenticated user
        self._log_in_test_user()

        # Create a root node in the anonymous namespace
        from remarkbox.models import create_root_node
        anon_ns = get_or_create_namespace(self.dbsession, self.anon_namespace_name)
        user = get_or_create_user_by_email(self.dbsession, "anon-test@remarkbox.com")

        root = create_root_node()
        root.namespace = anon_ns
        root.user = user
        root.verified = True
        root.title = "Test Thread"
        root.set_data("Test content")
        self.dbsession.add(root)
        self.dbsession.flush()
        root_id = str(root.id)
        self.tm.commit()

        # Log out
        self.testapp.get("/log-out")

        # Post anonymous reply (no email, just name)
        redirect_res = self.testapp.post(
            "/{}/reply".format(root_id),
            {
                "thread_data": "Anonymous comment here",
                "anonymous_name": "TestAnon",
            },
            status=302,
        )

        # Should redirect to the thread (not to login)
        res = redirect_res.follow()
        self.assertIn(b"Your post was successful!", res.body)

        # Verify a surrogate was created
        surrogate = self.dbsession.query(UserSurrogate).filter(
            UserSurrogate.name == "TestAnon",
            UserSurrogate.namespace_id == self.anon_namespace_id
        ).first()
        self.assertIsNotNone(surrogate)

    def test_anonymous_reply_default_name(self):
        """Test that anonymous reply without name uses 'Anonymous'."""
        self._log_in_test_user()

        from remarkbox.models import create_root_node
        anon_ns = get_or_create_namespace(self.dbsession, self.anon_namespace_name)
        user = get_or_create_user_by_email(self.dbsession, "anon-test@remarkbox.com")

        root = create_root_node()
        root.namespace = anon_ns
        root.user = user
        root.verified = True
        root.title = "Test Thread 2"
        root.set_data("Test content 2")
        self.dbsession.add(root)
        self.dbsession.flush()
        root_id = str(root.id)
        self.tm.commit()

        self.testapp.get("/log-out")

        # Post without anonymous_name
        redirect_res = self.testapp.post(
            "/{}/reply".format(root_id),
            {
                "thread_data": "Anonymous comment without name",
            },
            status=302,
        )

        res = redirect_res.follow()
        self.assertIn(b"Your post was successful!", res.body)

        # Verify surrogate with default name
        surrogate = self.dbsession.query(UserSurrogate).filter(
            UserSurrogate.name == "Anonymous",
            UserSurrogate.namespace_id == self.anon_namespace_id
        ).first()
        self.assertIsNotNone(surrogate)

    def test_regular_namespace_requires_email(self):
        """Test that non-anonymous namespace still requires email."""
        self._log_in_test_user()

        from remarkbox.models import create_root_node
        regular_ns = get_or_create_namespace(self.dbsession, self.regular_namespace_name)
        user = get_or_create_user_by_email(self.dbsession, "anon-test@remarkbox.com")

        root = create_root_node()
        root.namespace = regular_ns
        root.user = user
        root.verified = True
        root.title = "Regular Thread"
        root.set_data("Regular content")
        self.dbsession.add(root)
        self.dbsession.flush()
        root_id = str(root.id)
        self.tm.commit()

        self.testapp.get("/log-out")

        # Try to post without email on regular namespace
        redirect_res = self.testapp.post(
            "/{}/reply".format(root_id),
            {
                "thread_data": "This should fail",
                "anonymous_name": "ShouldFail",
            },
            status=302,
        )

        res = redirect_res.follow()
        self.assertIn(b"Press the back button to fix your email address", res.body)

    def test_anonymous_comment_is_verified(self):
        """Test that anonymous comments are marked as verified."""
        self._log_in_test_user()

        from remarkbox.models import create_root_node
        anon_ns = get_or_create_namespace(self.dbsession, self.anon_namespace_name)
        user = get_or_create_user_by_email(self.dbsession, "anon-test@remarkbox.com")

        root = create_root_node()
        root.namespace = anon_ns
        root.user = user
        root.verified = True
        root.title = "Verified Test Thread"
        root.set_data("Verified test content")
        self.dbsession.add(root)
        self.dbsession.flush()
        root_id = root.id
        self.tm.commit()

        self.testapp.get("/log-out")

        self.testapp.post(
            "/{}/reply".format(root_id),
            {
                "thread_data": "Anonymous verified comment",
                "anonymous_name": "VerifiedAnon",
            },
            status=302,
        )

        # Check the node is verified
        child = self.dbsession.query(Node).filter(
            Node.parent_id == root_id
        ).first()
        self.assertIsNotNone(child)
        self.assertTrue(child.verified)
        self.assertIsNotNone(child.user_surrogate)
        self.assertIsNone(child.user)

    def test_namespace_settings_toggle(self):
        """Test that namespace owner can toggle allow_anonymous setting."""
        self._log_in_test_user()

        # Make user owner of namespace
        from remarkbox.models import Namespace
        anon_ns = get_or_create_namespace(self.dbsession, self.anon_namespace_name)
        user = get_or_create_user_by_email(self.dbsession, "anon-test@remarkbox.com")

        anon_ns.set_role_for_user(user, "owner")
        self.dbsession.add(anon_ns)
        self.dbsession.flush()
        self.tm.commit()

        # Toggle off
        self.testapp.post(
            "/ns/{}/settings".format(self.anon_namespace_name),
            {
                "csrf_token": self.csrf,
                # Not including allow-anonymous-checkbox means it's unchecked
            },
        )

        ns = self.dbsession.query(Namespace).filter(
            Namespace.id == self.anon_namespace_id
        ).first()
        self.assertFalse(ns.allow_anonymous)

        # Toggle on
        self.testapp.post(
            "/ns/{}/settings".format(self.anon_namespace_name),
            {
                "csrf_token": self.csrf,
                "allow-anonymous-checkbox": "on",
            },
        )

        self.dbsession.expire(ns)
        self.assertTrue(ns.allow_anonymous)


class EmailCaseInsensitivityTests(FunctionalTests):
    """
    Tests to prevent duplicate accounts from case-insensitive email addresses.

    Regression test for issue where users 'G' and 'Groupr' both had emails
    'grop3r@protonmail.com' and 'Grop3r@protonmail.com' causing duplicate notifications.
    """

    @classmethod
    def setUpClass(cls):
        try:
            FunctionalTests.setUpClass.im_func(cls)
        except AttributeError:
            FunctionalTests.setUpClass.__func__(cls)

    def tearDown(self):
        super(EmailCaseInsensitivityTests, self).tearDown()
        # Clean up any test users created
        for email in ["casetest@example.com", "CASETEST@EXAMPLE.COM", "CaseTest@Example.com"]:
            user = get_user_by_email(self.dbsession, email)
            if user:
                self.dbsession.delete(user)
        self.dbsession.flush()
        self.tm.commit()

    def test_get_user_by_email_case_insensitive(self):
        """get_user_by_email should find users regardless of email case."""
        # Create user with lowercase email
        user = get_or_create_user_by_email(self.dbsession, "casetest@example.com")
        self.dbsession.add(user)
        self.dbsession.flush()
        self.tm.commit()

        # Should find with different cases
        found_lower = get_user_by_email(self.dbsession, "casetest@example.com")
        found_upper = get_user_by_email(self.dbsession, "CASETEST@EXAMPLE.COM")
        found_mixed = get_user_by_email(self.dbsession, "CaseTest@Example.com")

        self.assertIsNotNone(found_lower)
        self.assertIsNotNone(found_upper)
        self.assertIsNotNone(found_mixed)
        self.assertEqual(found_lower.id, found_upper.id)
        self.assertEqual(found_lower.id, found_mixed.id)

    def test_get_or_create_returns_existing_regardless_of_case(self):
        """get_or_create_user_by_email should return existing user regardless of email case."""
        # Create user with lowercase email
        user1 = get_or_create_user_by_email(self.dbsession, "casetest@example.com")
        self.dbsession.add(user1)
        self.dbsession.flush()
        user1_id = user1.id
        self.tm.commit()

        # Try to get/create with uppercase - should return same user
        user2 = get_or_create_user_by_email(self.dbsession, "CASETEST@EXAMPLE.COM")
        self.assertEqual(user1_id, user2.id)

        # Try to get/create with mixed case - should return same user
        user3 = get_or_create_user_by_email(self.dbsession, "CaseTest@Example.com")
        self.assertEqual(user1_id, user3.id)

    def test_new_user_email_stored_lowercase(self):
        """New user emails should be normalized to lowercase."""
        user = get_or_create_user_by_email(self.dbsession, "CASETEST@EXAMPLE.COM")
        self.dbsession.add(user)
        self.dbsession.flush()
        user_id = user.id
        self.tm.commit()

        # Requery to avoid detached instance error
        user = get_user_by_email(self.dbsession, "casetest@example.com")
        # Email should be stored lowercase
        self.assertEqual(user.email, "casetest@example.com")

    def test_no_duplicate_accounts_from_case_variations(self):
        """Ensure case variations don't create duplicate accounts."""
        # Create first user
        user1 = get_or_create_user_by_email(self.dbsession, "casetest@example.com")
        self.dbsession.add(user1)
        self.dbsession.flush()
        user1_id = user1.id
        self.tm.commit()

        # Attempt to create with different cases - should all return same user
        user2 = get_or_create_user_by_email(self.dbsession, "CASETEST@EXAMPLE.COM")
        user3 = get_or_create_user_by_email(self.dbsession, "CaseTest@Example.com")
        user4 = get_or_create_user_by_email(self.dbsession, "casetest@EXAMPLE.COM")

        # All should be the same user
        self.assertEqual(user1_id, user2.id)
        self.assertEqual(user1_id, user3.id)
        self.assertEqual(user1_id, user4.id)

        # Verify only one user exists with this email (case-insensitive)
        from remarkbox.models.user import User
        from sqlalchemy import func
        count = self.dbsession.query(User).filter(
            func.lower(User.email) == "casetest@example.com"
        ).count()
        self.assertEqual(count, 1)


class UserProfileNamespaceIsolationTests(FunctionalTests):
    """
    Regression tests for T0: User profile leaks comments across namespaces.

    Verifies that User.page_nodes() and related methods filter by namespace,
    so a user's profile page on site A only shows comments from site A.
    """

    @classmethod
    def setUpClass(cls):
        try:
            FunctionalTests.setUpClass.im_func(cls)
        except AttributeError:
            FunctionalTests.setUpClass.__func__(cls)

    def setUp(self):
        from remarkbox.models import create_root_node

        # Create a user who comments on two different namespaces.
        self.user = get_or_create_user_by_email(
            self.dbsession, "crossns@example.com"
        )
        self.raw_otp = self.user.new_password()
        self.dbsession.add(self.user)
        self.dbsession.flush()

        # Create two namespaces.
        self.ns_a = get_or_create_namespace(self.dbsession, "site-a.example.com")
        self.ns_b = get_or_create_namespace(self.dbsession, "site-b.example.com")

        # Create root nodes in each namespace.
        root_a = create_root_node()
        root_a.namespace = self.ns_a
        root_a.user = self.user
        root_a.verified = True
        root_a.title = "Thread on Site A"
        root_a.set_data("Root content A")
        self.dbsession.add(root_a)

        root_b = create_root_node()
        root_b.namespace = self.ns_b
        root_b.user = self.user
        root_b.verified = True
        root_b.title = "Thread on Site B"
        root_b.set_data("Root content B")
        self.dbsession.add(root_b)
        self.dbsession.flush()

        # Create child comments in each namespace.
        child_a = root_a.new_child()
        child_a.user = self.user
        child_a.verified = True
        child_a.approved = True
        child_a.set_data("Comment on site A")
        self.dbsession.add(child_a)

        child_b = root_b.new_child()
        child_b.user = self.user
        child_b.verified = True
        child_b.approved = True
        child_b.set_data("Comment on site B")
        self.dbsession.add(child_b)

        self.dbsession.flush()

        self.root_a_id = root_a.id
        self.root_b_id = root_b.id
        self.child_a_id = child_a.id
        self.child_b_id = child_b.id
        self.ns_a_id = self.ns_a.id
        self.ns_b_id = self.ns_b.id

        self.tm.commit()

        # Re-query after commit to avoid detached instances.
        self.user = get_or_create_user_by_email(
            self.dbsession, "crossns@example.com"
        )
        self.ns_a = get_or_create_namespace(self.dbsession, "site-a.example.com")
        self.ns_b = get_or_create_namespace(self.dbsession, "site-b.example.com")

    def tearDown(self):
        super(UserProfileNamespaceIsolationTests, self).tearDown()
        # Clean up nodes.
        self.dbsession.query(Node).filter(
            Node.root_id.in_([self.root_a_id, self.root_b_id])
        ).delete(synchronize_session=False)
        self.dbsession.query(Node).filter(
            Node.id.in_([self.root_a_id, self.root_b_id])
        ).delete(synchronize_session=False)
        user = get_user_by_email(self.dbsession, "crossns@example.com")
        if user:
            self.dbsession.delete(user)
        self.dbsession.flush()
        self.tm.commit()

    def test_page_nodes_without_namespace_returns_all(self):
        """page_nodes() without namespace returns nodes from all namespaces."""
        nodes = self.user.page_nodes()
        if nodes:
            node_ids = [n.id for n in nodes]
            self.assertIn(self.child_a_id, node_ids)
            self.assertIn(self.child_b_id, node_ids)

    def test_page_nodes_with_namespace_filters(self):
        """page_nodes(namespace=ns_a) only returns nodes from ns_a."""
        nodes_a = list(self.user.page_nodes(namespace=self.ns_a))
        node_ids_a = [n.id for n in nodes_a]
        self.assertIn(self.child_a_id, node_ids_a)
        self.assertNotIn(self.child_b_id, node_ids_a)

        nodes_b = list(self.user.page_nodes(namespace=self.ns_b))
        node_ids_b = [n.id for n in nodes_b]
        self.assertIn(self.child_b_id, node_ids_b)
        self.assertNotIn(self.child_a_id, node_ids_b)

    def test_disabled_nodes_with_namespace_filters(self):
        """disabled_nodes(namespace) only returns disabled nodes from that namespace."""
        # Disable child_a only.
        child_a = self.dbsession.query(Node).filter(Node.id == self.child_a_id).one()
        child_a.disable()
        self.dbsession.add(child_a)
        self.dbsession.flush()

        disabled_a = list(self.user.disabled_nodes(namespace=self.ns_a))
        disabled_b = list(self.user.disabled_nodes(namespace=self.ns_b))

        self.assertEqual(len(disabled_a), 1)
        self.assertEqual(disabled_a[0].id, self.child_a_id)
        self.assertEqual(len(disabled_b), 0)

    def test_unverified_nodes_with_namespace_filters(self):
        """unverified_nodes(namespace) only returns unverified nodes from that namespace."""
        # Unverify child_b only.
        child_b = self.dbsession.query(Node).filter(Node.id == self.child_b_id).one()
        child_b.unverify()
        self.dbsession.add(child_b)
        self.dbsession.flush()

        unverified_a = list(self.user.unverified_nodes(namespace=self.ns_a))
        unverified_b = list(self.user.unverified_nodes(namespace=self.ns_b))

        self.assertEqual(len(unverified_a), 0)
        self.assertEqual(len(unverified_b), 1)
        self.assertEqual(unverified_b[0].id, self.child_b_id)

    def test_user_profile_view_filters_by_namespace(self):
        """The user profile HTTP endpoint only shows same-namespace comments."""
        user_name = self.user.name

        # Request user profile under namespace site-a.
        res_a = self.testapp.get(
            "/embed/ns/site-a.example.com/u/{}".format(user_name),
            status=200,
        )
        self.assertIn(b"Comment on site A", res_a.body)
        self.assertNotIn(b"Comment on site B", res_a.body)

        # Request user profile under namespace site-b.
        res_b = self.testapp.get(
            "/embed/ns/site-b.example.com/u/{}".format(user_name),
            status=200,
        )
        self.assertIn(b"Comment on site B", res_b.body)
        self.assertNotIn(b"Comment on site A", res_b.body)


# ---------------------------------------------------------------------------
# T4: Customizable button text and comment labels
# ---------------------------------------------------------------------------


class CustomButtonTextFunctionalTests(FunctionalTests):
    """Functional tests for T4: custom button text and comment labels."""

    @classmethod
    def setUpClass(cls):
        try:
            FunctionalTests.setUpClass.im_func(cls)
        except AttributeError:
            FunctionalTests.setUpClass.__func__(cls)

    def setUp(self):
        # Create a test user and namespace
        self.test_user = get_or_create_user_by_email(
            self.dbsession, "custom-text@remarkbox.com"
        )
        self.raw_otp = self.test_user.new_password()
        self.dbsession.add(self.test_user)
        self.dbsession.flush()

        # Create a namespace with custom text
        self.ns_custom = get_or_create_namespace(
            self.dbsession, "custom-text.example.com"
        )
        self.ns_custom.subscription_type = "production"
        self.ns_custom.submit_button_text = "Post Comment"
        self.ns_custom.comment_label_singular = "comment"
        self.ns_custom.comment_label_plural = "comments"
        self.dbsession.add(self.ns_custom)

        # Create a namespace with defaults (None)
        self.ns_default = get_or_create_namespace(
            self.dbsession, "default-text.example.com"
        )
        self.ns_default.subscription_type = "production"
        self.dbsession.add(self.ns_default)

        self.dbsession.flush()

        self.ns_custom_id = self.ns_custom.id
        self.ns_custom_name = str(self.ns_custom.name)
        self.ns_default_id = self.ns_default.id
        self.ns_default_name = str(self.ns_default.name)

        self.tm.commit()

        self.test_user = get_or_create_user_by_email(
            self.dbsession, "custom-text@remarkbox.com"
        )
        self.test_creds = ("custom-text@remarkbox.com", self.raw_otp)

    def tearDown(self):
        super(CustomButtonTextFunctionalTests, self).tearDown()
        # Clean up nodes in these namespaces
        self.dbsession.query(Node).filter(
            Node.namespace_id.in_([self.ns_custom_id, self.ns_default_id])
        ).delete(synchronize_session=False)
        user = get_user_by_email(self.dbsession, "custom-text@remarkbox.com")
        if user:
            self.dbsession.delete(user)
        self.dbsession.flush()
        self.tm.commit()

    def _log_in_test_user(self):
        res_login = self.testapp.post(
            "/verification-challenge?email={}&raw-otp={}&submit".format(*self.test_creds)
        )
        res_csrf = self.testapp.get("/")
        self.csrf = res_csrf.form.fields["csrf_token"][0].value
        return res_login

    def test_embed_renders_custom_button_text(self):
        """Embed page shows custom submit_button_text instead of 'save message'."""
        self._log_in_test_user()

        # Create a root node in the custom namespace
        from remarkbox.models import create_root_node
        ns = get_or_create_namespace(self.dbsession, self.ns_custom_name)
        user = get_or_create_user_by_email(self.dbsession, "custom-text@remarkbox.com")

        root = create_root_node()
        root.namespace = ns
        root.user = user
        root.verified = True
        root.title = "Custom Button Thread"
        root.set_data("Test content")
        self.dbsession.add(root)
        self.dbsession.flush()
        root_id = str(root.id)
        self.tm.commit()

        # Visit the thread page (follows redirect from /{id} to /{id}/{slug})
        redirect_res = self.testapp.get("/{}".format(root_id))
        res = redirect_res.follow()
        # Should contain the custom button text
        self.assertIn(b"Post Comment", res.body)

    def test_embed_renders_default_button_text_when_not_set(self):
        """Embed page shows 'save message' when no custom text is set."""
        self._log_in_test_user()

        from remarkbox.models import create_root_node
        ns = get_or_create_namespace(self.dbsession, self.ns_default_name)
        user = get_or_create_user_by_email(self.dbsession, "custom-text@remarkbox.com")

        root = create_root_node()
        root.namespace = ns
        root.user = user
        root.verified = True
        root.title = "Default Button Thread"
        root.set_data("Test content")
        self.dbsession.add(root)
        self.dbsession.flush()
        root_id = str(root.id)
        self.tm.commit()

        redirect_res = self.testapp.get("/{}".format(root_id))
        res = redirect_res.follow()
        # Should contain the default text
        self.assertIn(b"save message", res.body)

    @patch("remarkbox.models.NamespaceRequest.scrape_target", mock_always_true)
    def test_namespace_settings_saves_custom_button_text(self):
        """Namespace settings form saves custom button text."""
        self._log_in_test_user()

        # Make user owner of namespace
        ns = get_or_create_namespace(self.dbsession, self.ns_custom_name)
        user = get_or_create_user_by_email(self.dbsession, "custom-text@remarkbox.com")
        ns.set_role_for_user(user, "owner")
        self.dbsession.add(ns)
        self.dbsession.flush()
        self.tm.commit()

        # Post updated settings
        self.testapp.post(
            "/ns/{}/settings".format(self.ns_custom_name),
            {
                "csrf_token": self.csrf,
                "submit-button-text": "Submit Reply",
                "comment-label-singular": "reply",
                "comment-label-plural": "replies",
            },
        )

        # Verify changes were saved
        ns = get_or_create_namespace(self.dbsession, self.ns_custom_name)
        self.dbsession.expire(ns)
        self.assertEqual(ns.submit_button_text, "Submit Reply")
        self.assertEqual(ns.comment_label_singular, "reply")
        self.assertEqual(ns.comment_label_plural, "replies")


# ---------------------------------------------------------------------------
# T6: Mention notification integration test
# ---------------------------------------------------------------------------


class MentionNotificationFunctionalTests(FunctionalTests):
    """Functional tests for T6: @mention notifications."""

    @classmethod
    def setUpClass(cls):
        try:
            FunctionalTests.setUpClass.im_func(cls)
        except AttributeError:
            FunctionalTests.setUpClass.__func__(cls)

    def setUp(self):
        # Create two test users
        self.test_user1 = get_or_create_user_by_email(
            self.dbsession, "mention-poster@remarkbox.com"
        )
        self.raw_otp1 = self.test_user1.new_password()

        self.test_user2 = get_or_create_user_by_email(
            self.dbsession, "mention-target@remarkbox.com"
        )
        self.raw_otp2 = self.test_user2.new_password()
        # Store the name so we can @mention it
        self.test_user2_name = str(self.test_user2.name)

        self.dbsession.add(self.test_user1)
        self.dbsession.add(self.test_user2)
        self.dbsession.flush()
        self.tm.commit()

        # Re-query
        self.test_user1 = get_or_create_user_by_email(
            self.dbsession, "mention-poster@remarkbox.com"
        )
        self.test_user2 = get_or_create_user_by_email(
            self.dbsession, "mention-target@remarkbox.com"
        )

        self.test_creds1 = ("mention-poster@remarkbox.com", self.raw_otp1)
        self.test_creds2 = ("mention-target@remarkbox.com", self.raw_otp2)

    def tearDown(self):
        super(MentionNotificationFunctionalTests, self).tearDown()
        # Clean up notifications first
        self.dbsession.query(NodeEventNotification).delete()
        # Re-query users to avoid detached instance errors
        user1 = get_user_by_email(self.dbsession, "mention-poster@remarkbox.com")
        user2 = get_user_by_email(self.dbsession, "mention-target@remarkbox.com")
        if user1:
            self.dbsession.delete(user1)
        if user2:
            self.dbsession.delete(user2)
        self.dbsession.flush()
        self.tm.commit()

    def _log_in_test_user(self, test_creds):
        res_login = self.testapp.post(
            "/verification-challenge?email={}&raw-otp={}&submit".format(*test_creds)
        )
        res_csrf = self.testapp.get("/")
        self.csrf = res_csrf.form.fields["csrf_token"][0].value
        return res_login

    @patch("smtplib.SMTP")
    def test_mention_creates_notification(self, mock_smtp):
        """Posting a comment with @mention creates a notification for the mentioned user."""
        # Store user2 ID before any session operations
        user2_id = self.test_user2.id

        # First, log in as user2 to set up their notification preferences
        self._log_in_test_user(self.test_creds2)
        self.testapp.post(
            "/u/settings",
            {
                "csrf_token": self.csrf,
                "default-node-watcher-frequency": "immediately",
                "reply-watcher-frequency": "immediately",
            },
        )
        self.testapp.get("/log-out")

        # Log in as user1 and create a thread
        self._log_in_test_user(self.test_creds1)
        self.testapp.post(
            "/u/settings",
            {
                "csrf_token": self.csrf,
                "default-node-watcher-frequency": "immediately",
                "reply-watcher-frequency": "immediately",
            },
        )

        new_resp = self.testapp.post(
            "/new",
            {
                "thread_title": "Mention Test Thread",
                "thread_data": "Initial content",
                "csrf_token": self.csrf,
            },
        )

        thread_url = new_resp.headers["location"]
        root_id = re.search(r"\/([^/]*)\/[^/]*$", thread_url).group(1)

        # Clear notifications from thread creation
        self.dbsession.query(NodeEventNotification).delete()
        self.dbsession.flush()
        self.tm.commit()

        # Post a reply mentioning user2
        mention_text = "Hey @{} check this out!".format(self.test_user2_name)
        self.testapp.post(
            "/{}/reply".format(root_id),
            {"csrf_token": self.csrf, "thread_data": mention_text},
        )

        # Check that a notification was created for the mentioned user
        notifications = list(self.dbsession.query(NodeEventNotification).all())
        # There should be at least one notification for the mentioned user
        mentioned_user_notifs = [
            n for n in notifications if n.user_id == user2_id
        ]
        self.assertGreaterEqual(len(mentioned_user_notifs), 1,
            "Expected at least one notification for mentioned user @{}".format(
                self.test_user2_name
            ))


# ---------------------------------------------------------------------------
# T8: Nesting depth enforcement (web view)
# ---------------------------------------------------------------------------


class NestingDepthWebFunctionalTests(FunctionalTests):
    """Functional tests for T8: max nesting depth enforcement in web views."""

    @classmethod
    def setUpClass(cls):
        try:
            FunctionalTests.setUpClass.im_func(cls)
        except AttributeError:
            FunctionalTests.setUpClass.__func__(cls)

    def setUp(self):
        self.test_user = get_or_create_user_by_email(
            self.dbsession, "depth-web@remarkbox.com"
        )
        self.raw_otp = self.test_user.new_password()
        self.dbsession.add(self.test_user)
        self.dbsession.flush()

        # Create namespace with max nesting depth = 1
        self.ns = get_or_create_namespace(
            self.dbsession, "depth-web-test.example.com"
        )
        self.ns.subscription_type = "production"
        self.ns.max_nesting_depth = 1
        self.dbsession.add(self.ns)
        self.dbsession.flush()

        self.ns_id = self.ns.id
        self.ns_name = str(self.ns.name)
        self.tm.commit()

        self.test_user = get_or_create_user_by_email(
            self.dbsession, "depth-web@remarkbox.com"
        )
        self.test_creds = ("depth-web@remarkbox.com", self.raw_otp)

    def tearDown(self):
        super(NestingDepthWebFunctionalTests, self).tearDown()
        self.dbsession.query(Node).filter(
            Node.namespace_id == self.ns_id
        ).delete(synchronize_session=False)
        user = get_user_by_email(self.dbsession, "depth-web@remarkbox.com")
        if user:
            self.dbsession.delete(user)
        self.dbsession.flush()
        self.tm.commit()

    def _log_in_test_user(self):
        res_login = self.testapp.post(
            "/verification-challenge?email={}&raw-otp={}&submit".format(*self.test_creds)
        )
        res_csrf = self.testapp.get("/")
        self.csrf = res_csrf.form.fields["csrf_token"][0].value
        return res_login

    def test_reply_within_max_depth_succeeds(self):
        """Reply within max depth (root depth 0 < max_nesting_depth 1) succeeds."""
        self._log_in_test_user()

        from remarkbox.models import create_root_node
        ns = get_or_create_namespace(self.dbsession, self.ns_name)
        user = get_or_create_user_by_email(self.dbsession, "depth-web@remarkbox.com")

        root = create_root_node()
        root.namespace = ns
        root.user = user
        root.verified = True
        root.title = "Depth Web Thread"
        root.set_data("Test content")
        self.dbsession.add(root)
        self.dbsession.flush()
        root_id = str(root.id)
        self.tm.commit()

        # Reply to root (parent.depth=0 < max=1) - should succeed
        redirect_res = self.testapp.post(
            "/{}/reply".format(root_id),
            {"csrf_token": self.csrf, "thread_data": "Depth 1 reply"},
            status=302,
        )
        res = redirect_res.follow()
        self.assertIn(b"Your post was successful!", res.body)

    def test_reply_beyond_max_depth_is_rejected(self):
        """Reply beyond max depth (parent depth 1 >= max 1) is rejected via web."""
        self._log_in_test_user()

        from remarkbox.models import create_root_node
        ns = get_or_create_namespace(self.dbsession, self.ns_name)
        user = get_or_create_user_by_email(self.dbsession, "depth-web@remarkbox.com")

        root = create_root_node()
        root.namespace = ns
        root.user = user
        root.verified = True
        root.title = "Too Deep Web Thread"
        root.set_data("Root content")
        self.dbsession.add(root)
        self.dbsession.flush()
        root_id = str(root.id)

        # Create a child at depth 1
        child = root.new_child()
        child.user = user
        child.verified = True
        child.set_data("Depth 1 child")
        self.dbsession.add(child)
        self.dbsession.flush()
        child_id = str(child.id)
        self.tm.commit()

        # Try to reply to child (parent.depth=1 >= max=1) - should be rejected
        redirect_res = self.testapp.post(
            "/{}/reply".format(child_id),
            {"csrf_token": self.csrf, "thread_data": "Too deep reply"},
            status=302,
        )
        res = redirect_res.follow()
        self.assertIn(b"Maximum nesting depth reached", res.body)

    @patch("remarkbox.models.NamespaceRequest.scrape_target", mock_always_true)
    def test_namespace_settings_saves_nesting_depth(self):
        """Namespace settings form saves max_nesting_depth and collapse_depth."""
        self._log_in_test_user()

        ns = get_or_create_namespace(self.dbsession, self.ns_name)
        user = get_or_create_user_by_email(self.dbsession, "depth-web@remarkbox.com")
        ns.set_role_for_user(user, "owner")
        self.dbsession.add(ns)
        self.dbsession.flush()
        self.tm.commit()

        self.testapp.post(
            "/ns/{}/settings".format(self.ns_name),
            {
                "csrf_token": self.csrf,
                "max-nesting-depth": "5",
                "collapse-depth": "3",
            },
        )

        ns = get_or_create_namespace(self.dbsession, self.ns_name)
        self.dbsession.expire(ns)
        self.assertEqual(ns.max_nesting_depth, 5)
        self.assertEqual(ns.collapse_depth, 3)


# ---------------------------------------------------------------------------
# T0: Profile namespace isolation — moderation settings tests
# ---------------------------------------------------------------------------


class UserProfileModerationFilterTests(FunctionalTests):
    """
    Regression tests for T0: namespace moderation settings on profile page.

    Verifies that hide_unless_approved and hide_unverified settings are
    respected when filtering page_nodes with a namespace.
    """

    @classmethod
    def setUpClass(cls):
        try:
            FunctionalTests.setUpClass.im_func(cls)
        except AttributeError:
            FunctionalTests.setUpClass.__func__(cls)

    def setUp(self):
        from remarkbox.models import create_root_node

        self.user = get_or_create_user_by_email(
            self.dbsession, "mod-filter@example.com"
        )
        self.raw_otp = self.user.new_password()
        self.dbsession.add(self.user)
        self.dbsession.flush()

        # Namespace with hide_unless_approved enabled.
        self.ns_strict = get_or_create_namespace(
            self.dbsession, "strict-ns.example.com"
        )
        self.ns_strict.subscription_type = "production"
        self.ns_strict.hide_unless_approved = True

        # Create root and two children: one approved, one not.
        root = create_root_node()
        root.namespace = self.ns_strict
        root.user = self.user
        root.verified = True
        root.title = "Strict thread"
        root.set_data("Strict root content")
        self.dbsession.add(root)
        self.dbsession.flush()

        approved_child = root.new_child()
        approved_child.user = self.user
        approved_child.verified = True
        approved_child.approved = True
        approved_child.set_data("Approved comment")
        self.dbsession.add(approved_child)

        unapproved_child = root.new_child()
        unapproved_child.user = self.user
        unapproved_child.verified = True
        unapproved_child.approved = False
        unapproved_child.set_data("Unapproved comment")
        self.dbsession.add(unapproved_child)

        self.dbsession.flush()

        self.root_id = root.id
        self.approved_id = approved_child.id
        self.unapproved_id = unapproved_child.id
        self.ns_strict_id = self.ns_strict.id

        self.tm.commit()

        self.user = get_or_create_user_by_email(
            self.dbsession, "mod-filter@example.com"
        )
        self.ns_strict = get_or_create_namespace(
            self.dbsession, "strict-ns.example.com"
        )

    def tearDown(self):
        super(UserProfileModerationFilterTests, self).tearDown()
        self.dbsession.query(Node).filter(
            Node.root_id == self.root_id
        ).delete(synchronize_session=False)
        self.dbsession.query(Node).filter(
            Node.id == self.root_id
        ).delete(synchronize_session=False)
        user = get_user_by_email(self.dbsession, "mod-filter@example.com")
        if user:
            self.dbsession.delete(user)
        self.dbsession.flush()
        self.tm.commit()

    def test_page_nodes_respects_hide_unless_approved(self):
        """page_nodes with hide_unless_approved namespace filters out unapproved nodes."""
        nodes = list(self.user.page_nodes(namespace=self.ns_strict))
        node_ids = [n.id for n in nodes]
        self.assertIn(self.approved_id, node_ids)
        self.assertNotIn(self.unapproved_id, node_ids)

    def test_page_nodes_without_namespace_returns_all_approved(self):
        """page_nodes without namespace returns all approved/verified nodes."""
        nodes = list(self.user.page_nodes())
        node_ids = [n.id for n in nodes]
        self.assertIn(self.approved_id, node_ids)

    def test_unapproved_nodes_with_namespace(self):
        """unapproved_nodes(namespace) returns only unapproved nodes in that namespace."""
        unapproved = list(self.user.unapproved_nodes(namespace=self.ns_strict))
        unapproved_ids = [n.id for n in unapproved]
        self.assertIn(self.unapproved_id, unapproved_ids)
        self.assertNotIn(self.approved_id, unapproved_ids)


# ---------------------------------------------------------------------------
# T1: Case-insensitive namespace creation via setup (integration test)
# ---------------------------------------------------------------------------


class CaseInsensitiveNamespaceSetupTests(FunctionalTests):
    """
    Regression tests for T1: the setup_namespace view lowercases domain names.

    When a user creates a namespace via /setup, the domain is lowercased.
    """

    @classmethod
    def setUpClass(cls):
        try:
            FunctionalTests.setUpClass.im_func(cls)
        except AttributeError:
            FunctionalTests.setUpClass.__func__(cls)

    def setUp(self):
        self.test_user = get_or_create_user_by_email(
            self.dbsession, "case-ns-setup@remarkbox.com"
        )
        self.raw_otp = self.test_user.new_password()
        self.dbsession.add(self.test_user)
        self.dbsession.flush()
        self.tm.commit()

        self.test_user = get_or_create_user_by_email(
            self.dbsession, "case-ns-setup@remarkbox.com"
        )
        self.test_creds = ("case-ns-setup@remarkbox.com", self.raw_otp)

    def tearDown(self):
        super(CaseInsensitiveNamespaceSetupTests, self).tearDown()
        user = get_user_by_email(self.dbsession, "case-ns-setup@remarkbox.com")
        if user:
            self.dbsession.delete(user)
        self.dbsession.flush()
        self.tm.commit()

    def _log_in_test_user(self):
        res_login = self.testapp.post(
            "/verification-challenge?email={}&raw-otp={}&submit".format(*self.test_creds)
        )
        res_csrf = self.testapp.get("/")
        self.csrf = res_csrf.form.fields["csrf_token"][0].value
        return res_login

    @patch("remarkbox.models.NamespaceRequest.scrape_target", mock_always_true)
    def test_setup_lowercases_namespace_domain(self):
        """The /setup view lowercases the namespace domain name."""
        self._log_in_test_user()

        self.testapp.post(
            "/setup",
            {
                "namespace-domain": "MixedCase.Example.COM",
                "csrf_token": self.csrf,
            },
        )

        # The namespace should have been created with lowercase name.
        from remarkbox.models.namespace import get_namespace_by_name
        ns = get_namespace_by_name(self.dbsession, "mixedcase.example.com")
        self.assertIsNotNone(ns, "Namespace should be found with lowercase name")


# ---------------------------------------------------------------------------
# T3: GDPR — Delete account and Export data (functional tests)
# ---------------------------------------------------------------------------


class GDPRDeleteAccountFunctionalTests(FunctionalTests):
    """
    Functional tests for T3: delete account flow.

    Tests the /u/delete-account endpoint for account deletion and anonymization.
    """

    @classmethod
    def setUpClass(cls):
        try:
            FunctionalTests.setUpClass.im_func(cls)
        except AttributeError:
            FunctionalTests.setUpClass.__func__(cls)

    def setUp(self):
        from remarkbox.models import create_root_node

        self.test_user = get_or_create_user_by_email(
            self.dbsession, "gdpr-delete@remarkbox.com"
        )
        self.raw_otp = self.test_user.new_password()
        self.dbsession.add(self.test_user)
        self.dbsession.flush()

        # Create a root node owned by this user.
        root = create_root_node()
        root.namespace = get_or_create_namespace(self.dbsession, "gdpr.example.com")
        root.user = self.test_user
        root.verified = True
        root.title = "GDPR Test Thread"
        root.set_data("Root content")
        self.dbsession.add(root)
        self.dbsession.flush()

        # Create a child comment by this user.
        child = root.new_child()
        child.user = self.test_user
        child.verified = True
        child.approved = True
        child.set_data("User comment to be anonymized")
        self.dbsession.add(child)
        self.dbsession.flush()

        self.root_id = root.id
        self.child_id = child.id
        self.user_id = self.test_user.id

        self.tm.commit()

        self.test_user = get_or_create_user_by_email(
            self.dbsession, "gdpr-delete@remarkbox.com"
        )
        self.test_creds = ("gdpr-delete@remarkbox.com", self.raw_otp)

    def tearDown(self):
        super(GDPRDeleteAccountFunctionalTests, self).tearDown()
        try:
            self.dbsession.query(Node).filter(
                Node.root_id == self.root_id
            ).delete(synchronize_session=False)
            self.dbsession.query(Node).filter(
                Node.id == self.root_id
            ).delete(synchronize_session=False)
            from remarkbox.models.user import User
            user = self.dbsession.query(User).filter(User.id == self.user_id).one_or_none()
            if user:
                self.dbsession.delete(user)
            self.dbsession.flush()
            self.tm.commit()
        except Exception:
            self.tm.abort()

    def _log_in_test_user(self):
        res_login = self.testapp.post(
            "/verification-challenge?email={}&raw-otp={}&submit".format(*self.test_creds)
        )
        res_csrf = self.testapp.get("/")
        self.csrf = res_csrf.form.fields["csrf_token"][0].value
        return res_login

    def test_1_delete_account_page_loads(self):
        """GET /u/delete-account returns 200 for authenticated users."""
        self._log_in_test_user()
        res = self.testapp.get("/u/delete-account", status=200)
        self.assertIn(b"Delete My Account", res.body)

    def test_2_delete_account_requires_confirmation(self):
        """POST without typing DELETE does not delete account."""
        self._log_in_test_user()
        res = self.testapp.post(
            "/u/delete-account",
            {"csrf_token": self.csrf, "confirm-delete": "wrong"},
            status=200,
        )
        self.assertIn(b'You must type', res.body)

        from remarkbox.models.user import User
        user = self.dbsession.query(User).filter(User.id == self.user_id).one_or_none()
        self.assertIsNotNone(user)

    @patch("smtplib.SMTP")
    def test_3_delete_account_anonymizes_and_keeps_tombstone(self, mock_smtp):
        """POST with DELETE confirmation scrubs PII and keeps user as tombstone."""
        self._log_in_test_user()

        # Step 1: POST with DELETE triggers OTP generation, returns 200 with OTP form.
        otp_res = self.testapp.post(
            "/u/delete-account",
            {"csrf_token": self.csrf, "confirm-delete": "DELETE"},
            status=200,
        )
        self.assertIn(b"Confirmation code", otp_res.body)

        # Retrieve the OTP code from the database.
        from remarkbox.models.sudo_otp import SudoOtp
        action_key = "delete_account:gdpr-delete@remarkbox.com"
        otp_row = self.dbsession.query(SudoOtp).get(action_key)
        self.assertIsNotNone(otp_row, "OTP row should exist after step 1")
        code = otp_row.code

        # Step 2: POST with the OTP code completes deletion.
        redirect_res = self.testapp.post(
            "/u/delete-account",
            {"csrf_token": self.csrf, "sudo_otp": code},
            status=302,
        )
        res = redirect_res.follow()
        self.assertIn(b"Your account has been deleted", res.body)

        # Expire cached objects so we get fresh data after the app committed.
        self.dbsession.expire_all()

        from remarkbox.models.user import User
        user = self.dbsession.query(User).filter(User.id == self.user_id).one_or_none()
        self.assertIsNotNone(user, "User record should be kept as tombstone")
        self.assertTrue(user.name.startswith("deleted-"), "Name should be anonymized")
        self.assertTrue(user.email.startswith("deleted-"), "Email should be anonymized")
        self.assertTrue(user.disabled, "Tombstone user should be disabled")
        self.assertIsNone(user.password, "Password should be scrubbed")

        child = self.dbsession.query(Node).filter(Node.id == self.child_id).one_or_none()
        self.assertIsNotNone(child, "Comment should still exist after deletion")
        self.assertEqual(child.user_id, self.user_id, "user_id FK should still point to tombstone")
        self.assertIsNone(child.ip_address, "IP address should be scrubbed")


class GDPRExportDataFunctionalTests(FunctionalTests):
    """
    Functional tests for T3: export user data flow.

    Tests the /u/export-data endpoint for JSON data export.
    """

    @classmethod
    def setUpClass(cls):
        try:
            FunctionalTests.setUpClass.im_func(cls)
        except AttributeError:
            FunctionalTests.setUpClass.__func__(cls)

    def setUp(self):
        from remarkbox.models import create_root_node

        self.test_user = get_or_create_user_by_email(
            self.dbsession, "gdpr-export@remarkbox.com"
        )
        self.raw_otp = self.test_user.new_password()
        self.dbsession.add(self.test_user)
        self.dbsession.flush()

        root = create_root_node()
        root.namespace = get_or_create_namespace(self.dbsession, "export.example.com")
        root.user = self.test_user
        root.verified = True
        root.title = "Export Test Thread"
        root.set_data("Root content for export")
        self.dbsession.add(root)
        self.dbsession.flush()

        child = root.new_child()
        child.user = self.test_user
        child.verified = True
        child.approved = True
        child.set_data("Exportable comment")
        self.dbsession.add(child)
        self.dbsession.flush()

        self.root_id = root.id
        self.child_id = child.id

        self.tm.commit()

        self.test_user = get_or_create_user_by_email(
            self.dbsession, "gdpr-export@remarkbox.com"
        )
        self.test_creds = ("gdpr-export@remarkbox.com", self.raw_otp)

    def tearDown(self):
        super(GDPRExportDataFunctionalTests, self).tearDown()
        self.dbsession.query(Node).filter(
            Node.root_id == self.root_id
        ).delete(synchronize_session=False)
        self.dbsession.query(Node).filter(
            Node.id == self.root_id
        ).delete(synchronize_session=False)
        user = get_user_by_email(self.dbsession, "gdpr-export@remarkbox.com")
        if user:
            self.dbsession.delete(user)
        self.dbsession.flush()
        self.tm.commit()

    def _log_in_test_user(self):
        res_login = self.testapp.post(
            "/verification-challenge?email={}&raw-otp={}&submit".format(*self.test_creds)
        )
        res_csrf = self.testapp.get("/")
        self.csrf = res_csrf.form.fields["csrf_token"][0].value
        return res_login

    def test_export_data_returns_json(self):
        """GET /u/export-data returns JSON attachment with user's comments."""
        self._log_in_test_user()
        res = self.testapp.get("/u/export-data", status=200)
        self.assertIn("application/json", res.content_type)
        self.assertIn("attachment", res.content_disposition)

        import json
        data = json.loads(res.body)
        self.assertIn("profile", data)
        self.assertIn("comments", data)
        self.assertEqual(data["profile"]["email"], "gdpr-export@remarkbox.com")
        self.assertGreater(len(data["comments"]), 0)

    def test_export_data_requires_auth(self):
        """GET /u/export-data redirects when not authenticated."""
        redirect_res = self.testapp.get("/u/export-data", status=302)
        res = redirect_res.follow()
        self.assertIn(b"You must log in", res.body)


# ---------------------------------------------------------------------------
# T5: Self-service namespace deletion (functional tests)
# ---------------------------------------------------------------------------


class NamespaceDeletionFunctionalTests(FunctionalTests):
    """
    Functional tests for T5: self-service namespace deletion.

    Tests the /ns/{namespace}/delete endpoint.
    """

    @classmethod
    def setUpClass(cls):
        try:
            FunctionalTests.setUpClass.im_func(cls)
        except AttributeError:
            FunctionalTests.setUpClass.__func__(cls)

    def setUp(self):
        from remarkbox.models import create_root_node

        self.owner = get_or_create_user_by_email(
            self.dbsession, "ns-delete-owner@remarkbox.com"
        )
        self.owner_otp = self.owner.new_password()
        self.dbsession.add(self.owner)

        self.non_owner = get_or_create_user_by_email(
            self.dbsession, "ns-delete-notown@remarkbox.com"
        )
        self.non_owner_otp = self.non_owner.new_password()
        self.dbsession.add(self.non_owner)

        self.dbsession.flush()

        self.ns = get_or_create_namespace(
            self.dbsession, "deleteme.example.com"
        )
        self.ns.set_role_for_user(self.owner, "owner")
        self.dbsession.add(self.ns)
        self.dbsession.flush()

        root = create_root_node()
        root.namespace = self.ns
        root.user = self.owner
        root.verified = True
        root.title = "Delete NS Thread"
        root.set_data("Will be deleted")
        self.dbsession.add(root)
        self.dbsession.flush()

        child = root.new_child()
        child.user = self.owner
        child.verified = True
        child.approved = True
        child.set_data("Will also be deleted")
        self.dbsession.add(child)
        self.dbsession.flush()

        self.ns_id = self.ns.id
        self.ns_name = str(self.ns.name)
        self.root_id = root.id
        self.owner_id = self.owner.id
        self.non_owner_id = self.non_owner.id

        self.tm.commit()

        self.owner = get_or_create_user_by_email(
            self.dbsession, "ns-delete-owner@remarkbox.com"
        )
        self.non_owner = get_or_create_user_by_email(
            self.dbsession, "ns-delete-notown@remarkbox.com"
        )
        self.owner_creds = ("ns-delete-owner@remarkbox.com", self.owner_otp)
        self.non_owner_creds = ("ns-delete-notown@remarkbox.com", self.non_owner_otp)

    def tearDown(self):
        super(NamespaceDeletionFunctionalTests, self).tearDown()
        from remarkbox.models.namespace import Namespace
        ns = self.dbsession.query(Namespace).filter(
            Namespace.id == self.ns_id
        ).one_or_none()
        if ns:
            self.dbsession.query(Node).filter(
                Node.namespace_id == self.ns_id
            ).delete(synchronize_session=False)
            # Also remove namespace-user associations before deleting ns.
            ns.owners[:] = []
            ns.moderators[:] = []
            self.dbsession.delete(ns)
        for email in ["ns-delete-owner@remarkbox.com", "ns-delete-notown@remarkbox.com"]:
            user = get_user_by_email(self.dbsession, email)
            if user:
                self.dbsession.delete(user)
        self.dbsession.flush()
        self.tm.commit()

    def _log_in(self, creds):
        res_login = self.testapp.post(
            "/verification-challenge?email={}&raw-otp={}&submit".format(*creds)
        )
        res_csrf = self.testapp.get("/")
        self.csrf = res_csrf.form.fields["csrf_token"][0].value
        return res_login

    def test_non_owner_cannot_delete_namespace(self):
        """Non-owner gets redirected when trying to delete a namespace."""
        self._log_in(self.non_owner_creds)
        redirect_res = self.testapp.get(
            "/ns/{}/delete".format(self.ns_name), status=302
        )
        res = redirect_res.follow()
        self.assertIn(b"You do not own that Namespace", res.body)

    def test_delete_namespace_requires_typing_name(self):
        """POST without typing the namespace name does not delete it."""
        self._log_in(self.owner_creds)
        res = self.testapp.post(
            "/ns/{}/delete".format(self.ns_name),
            {"csrf_token": self.csrf, "confirm-delete": "wrong-name"},
            status=200,
        )
        self.assertIn(b"You must type the namespace name", res.body)

        from remarkbox.models.namespace import Namespace
        ns = self.dbsession.query(Namespace).filter(
            Namespace.id == self.ns_id
        ).one_or_none()
        self.assertIsNotNone(ns)

    def test_owner_can_delete_namespace(self):
        """Owner typing the namespace name deletes it and all associated data."""
        self._log_in(self.owner_creds)
        redirect_res = self.testapp.post(
            "/ns/{}/delete".format(self.ns_name),
            {"csrf_token": self.csrf, "confirm-delete": self.ns_name},
            status=302,
        )
        res = redirect_res.follow()
        self.assertIn(b"permanently deleted", res.body)

        from remarkbox.models.namespace import Namespace
        ns = self.dbsession.query(Namespace).filter(
            Namespace.id == self.ns_id
        ).one_or_none()
        self.assertIsNone(ns, "Namespace should be deleted")

        nodes = self.dbsession.query(Node).filter(
            Node.root_id == self.root_id
        ).all()
        self.assertEqual(len(nodes), 0, "All nodes in namespace should be deleted")


class AjaxReplyFunctionalTests(FunctionalTests):
    """Functional tests for AJAX comment submission (progressive enhancement).

    Tests verify that:
    - AJAX replies return JSON 201 for authenticated users
    - Non-AJAX replies still redirect (graceful fallback)
    - JSON response contains correct comment data
    - Unverified users get redirect even with AJAX header
    - Anonymous AJAX replies work
    """

    @classmethod
    def setUpClass(cls):
        try:
            FunctionalTests.setUpClass.im_func(cls)
        except AttributeError:
            FunctionalTests.setUpClass.__func__(cls)

    def setUp(self):
        from remarkbox.models import create_root_node

        # Create test user
        self.test_user = get_or_create_user_by_email(
            self.dbsession, "ajax-test@remarkbox.com"
        )
        self.raw_otp = self.test_user.new_password()
        self.dbsession.add(self.test_user)

        # Create namespace
        self.ns = get_or_create_namespace(
            self.dbsession, "ajax-test.example.com"
        )
        self.dbsession.add(self.ns)

        # Create root node
        self.root = create_root_node()
        self.root.namespace = self.ns
        self.root.user = self.test_user
        self.root.verified = True
        self.root.title = "AJAX Test Thread"
        self.root.set_data("Test thread for AJAX replies")
        self.dbsession.add(self.root)
        self.dbsession.flush()

        self.root_id = str(self.root.id)
        self.ns_id = self.ns.id

        self.tm.commit()

        self.test_creds = ("ajax-test@remarkbox.com", self.raw_otp)

    def _log_in_test_user(self):
        res_login = self.testapp.post(
            "/verification-challenge?email={}&raw-otp={}&submit".format(
                *self.test_creds
            )
        )
        res_csrf = self.testapp.get("/")
        self.csrf = res_csrf.form.fields["csrf_token"][0].value
        return res_login

    def tearDown(self):
        super(AjaxReplyFunctionalTests, self).tearDown()
        # Clean up nodes
        self.dbsession.query(Node).filter(
            Node.namespace_id == self.ns_id
        ).delete(synchronize_session=False)
        # Clean up surrogates
        self.dbsession.query(UserSurrogate).filter(
            UserSurrogate.namespace_id == self.ns_id
        ).delete(synchronize_session=False)
        # Clean up user
        user = get_user_by_email(self.dbsession, "ajax-test@remarkbox.com")
        if user:
            self.dbsession.delete(user)
        self.dbsession.flush()
        self.tm.commit()

    def test_ajax_reply_returns_json_201(self):
        """Authenticated AJAX reply returns JSON with status 201."""
        self._log_in_test_user()

        res = self.testapp.post(
            "/{}/reply".format(self.root_id),
            {
                "csrf_token": self.csrf,
                "thread_data": "AJAX reply content",
            },
            headers={"X-Requested-With": "XMLHttpRequest"},
            status=201,
        )

        body = res.json
        self.assertIn("id", body)
        self.assertIn("parent_id", body)
        self.assertIn("node_html", body)
        # Server-rendered HTML contains the comment content.
        self.assertIn("AJAX reply content", body["node_html"])

    def test_ajax_reply_json_contains_rendered_html(self):
        """AJAX response node_html contains server-rendered markdown."""
        self._log_in_test_user()

        res = self.testapp.post(
            "/{}/reply".format(self.root_id),
            {
                "csrf_token": self.csrf,
                "thread_data": "**bold text** and _italic_",
            },
            headers={"X-Requested-With": "XMLHttpRequest"},
            status=201,
        )

        body = res.json
        self.assertIn("<strong>bold text</strong>", body["node_html"])
        self.assertIn("<em>italic</em>", body["node_html"])

    def test_ajax_reply_json_has_correct_parent_id(self):
        """AJAX response parent_id matches the node replied to."""
        self._log_in_test_user()

        res = self.testapp.post(
            "/{}/reply".format(self.root_id),
            {
                "csrf_token": self.csrf,
                "thread_data": "Reply to root",
            },
            headers={"X-Requested-With": "XMLHttpRequest"},
            status=201,
        )

        body = res.json
        self.assertEqual(body["parent_id"], self.root_id)

    def test_ajax_reply_html_has_author_name(self):
        """AJAX response node_html includes the authenticated user's display name."""
        self._log_in_test_user()

        res = self.testapp.post(
            "/{}/reply".format(self.root_id),
            {
                "csrf_token": self.csrf,
                "thread_data": "Check author name",
            },
            headers={"X-Requested-With": "XMLHttpRequest"},
            status=201,
        )

        body = res.json
        # Server-rendered HTML should contain author-and-date span.
        self.assertIn("author-and-date", body["node_html"])

    def test_non_ajax_reply_still_redirects(self):
        """Non-AJAX reply (no X-Requested-With) returns 302 redirect."""
        self._log_in_test_user()

        redirect_res = self.testapp.post(
            "/{}/reply".format(self.root_id),
            {
                "csrf_token": self.csrf,
                "thread_data": "Normal reply without AJAX",
            },
            status=302,
        )

        res = redirect_res.follow()
        self.assertIn(b"Your post was successful!", res.body)

    def test_ajax_reply_creates_node_in_database(self):
        """AJAX reply actually creates a node in the database."""
        self._log_in_test_user()

        res = self.testapp.post(
            "/{}/reply".format(self.root_id),
            {
                "csrf_token": self.csrf,
                "thread_data": "Database persistence check",
            },
            headers={"X-Requested-With": "XMLHttpRequest"},
            status=201,
        )

        node_id = res.json["id"]
        from remarkbox.models import get_node_by_id
        node = get_node_by_id(self.dbsession, node_id)
        self.assertIsNotNone(node)
        self.assertEqual(node.data, "Database persistence check")

    def test_ajax_empty_reply_returns_redirect(self):
        """AJAX reply with empty data falls back to redirect (form error)."""
        self._log_in_test_user()

        redirect_res = self.testapp.post(
            "/{}/reply".format(self.root_id),
            {
                "csrf_token": self.csrf,
                "thread_data": "",
            },
            headers={"X-Requested-With": "XMLHttpRequest"},
            status=302,
        )

        res = redirect_res.follow()
        self.assertIn(b"Your message was empty", res.body)

    @patch("smtplib.SMTP")
    def test_ajax_unverified_user_gets_redirect(self, mock_smtp):
        """Unverified user gets redirect even with AJAX header (email flow)."""
        redirect_res = self.testapp.post(
            "/{}/reply".format(self.root_id),
            {
                "thread_data": "Unverified AJAX reply",
                "email": "unverified@example.com",
            },
            headers={"X-Requested-With": "XMLHttpRequest"},
            status=302,
        )

        # Should redirect to join-or-log-in (email verification)
        self.assertIn("join-or-log-in", redirect_res.headers["location"])


class AjaxAnonymousReplyFunctionalTests(FunctionalTests):
    """Tests for AJAX replies in anonymous mode."""

    @classmethod
    def setUpClass(cls):
        try:
            FunctionalTests.setUpClass.im_func(cls)
        except AttributeError:
            FunctionalTests.setUpClass.__func__(cls)

    def setUp(self):
        from remarkbox.models import create_root_node

        # Create test user for thread ownership
        self.test_user = get_or_create_user_by_email(
            self.dbsession, "ajax-anon-test@remarkbox.com"
        )
        self.raw_otp = self.test_user.new_password()
        self.dbsession.add(self.test_user)

        # Create anonymous namespace
        self.ns = get_or_create_namespace(
            self.dbsession, "ajax-anon-test.example.com"
        )
        self.ns.allow_anonymous = True
        self.dbsession.add(self.ns)

        # Create root node
        self.root = create_root_node()
        self.root.namespace = self.ns
        self.root.user = self.test_user
        self.root.verified = True
        self.root.title = "AJAX Anonymous Test Thread"
        self.root.set_data("Test thread for anonymous AJAX replies")
        self.dbsession.add(self.root)
        self.dbsession.flush()

        self.root_id = str(self.root.id)
        self.ns_id = self.ns.id

        self.tm.commit()

    def tearDown(self):
        super(AjaxAnonymousReplyFunctionalTests, self).tearDown()
        # Clean up nodes
        self.dbsession.query(Node).filter(
            Node.namespace_id == self.ns_id
        ).delete(synchronize_session=False)
        # Clean up surrogates
        self.dbsession.query(UserSurrogate).filter(
            UserSurrogate.namespace_id == self.ns_id
        ).delete(synchronize_session=False)
        # Clean up user
        user = get_user_by_email(self.dbsession, "ajax-anon-test@remarkbox.com")
        if user:
            self.dbsession.delete(user)
        self.dbsession.flush()
        self.tm.commit()

    def test_ajax_anonymous_reply_returns_json_201(self):
        """Anonymous AJAX reply returns JSON 201."""
        res = self.testapp.post(
            "/{}/reply".format(self.root_id),
            {
                "thread_data": "Anonymous AJAX reply",
                "anonymous_name": "AjaxAnon",
            },
            headers={"X-Requested-With": "XMLHttpRequest"},
            status=201,
        )

        body = res.json
        self.assertIn("node_html", body)
        self.assertIn("AjaxAnon", body["node_html"])

    def test_ajax_anonymous_reply_default_name(self):
        """Anonymous AJAX reply without name uses 'Anonymous'."""
        res = self.testapp.post(
            "/{}/reply".format(self.root_id),
            {
                "thread_data": "Anonymous AJAX reply no name",
            },
            headers={"X-Requested-With": "XMLHttpRequest"},
            status=201,
        )

        body = res.json
        self.assertIn("Anonymous", body["node_html"])

    def test_non_ajax_anonymous_reply_still_redirects(self):
        """Non-AJAX anonymous reply returns redirect (baseline behavior)."""
        redirect_res = self.testapp.post(
            "/{}/reply".format(self.root_id),
            {
                "thread_data": "Normal anonymous reply",
                "anonymous_name": "NormalAnon",
            },
            status=302,
        )

        res = redirect_res.follow()
        self.assertIn(b"Your post was successful!", res.body)
