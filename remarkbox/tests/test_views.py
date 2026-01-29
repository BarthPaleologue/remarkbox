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
