import transaction
import unittest
import webtest
import stripe

from remarkbox.models import (
    Node,
    get_tm_session,
    get_or_create_user_by_email,
    get_user_by_email,
    NodeEventNotification,
)

from remarkbox.models.meta import Base

from remarkbox.lib.notify import deliver_scheduled_notifications

from pyramid.paster import get_appsettings

import mock
from mock import patch, call
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
        self.assertTrue(b"Faq" in res.body)
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
        self.assertTrue(b"Thank you for helping us out, Please verify your email in the form below!" in res.body)

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

        stripe.api_key = cls.settings["app.stripe.secret"]

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
        if user.stripe_id:
            # delete remote test Customer object on Stripe's test API.
            stripe.Customer.retrieve(user.stripe_id).delete()
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
        res = self._log_in_test_user(self.test_creds1)
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

    # the only reason we need to patch is because of temporary operator email.
    @patch("smtplib.SMTP")
    def test_billing(self, mock_smtp):

        self._log_in_test_user(self.test_creds1)

        billing_response = self.testapp.post(
            "/billing/add-card",
            {
                "email": "test@remarkbox.com",
                "csrf_token": self.csrf,
                "stripeToken": "tok_visa",
            },
        )

        self.dbsession.refresh(self.test_user1)
        customer = stripe.Customer.retrieve(self.test_user1.stripe_id)
        self.assertEqual(
            customer.sources.retrieve(customer.default_source).brand, "Visa"
        )

        self.testapp.post(
            "/billing/add-card",
            {
                "email": "test@remarkbox.com",
                "csrf_token": self.csrf,
                "stripeToken": "tok_amex",
            },
        )

        for source in customer.sources.list():
            if source.brand == "Visa":
                visa = source
            if source.brand == "American Express":
                amex = source

        self.testapp.post(
            "/billing/update-card",
            {
                "email": "test@remarkbox.com",
                "csrf_token": self.csrf,
                "action": "make-card-active",
                "card_id": amex.id,
            },
        )

        customer = stripe.Customer.retrieve(self.test_user1.stripe_id)
        self.assertEqual(
            customer.sources.retrieve(customer.default_source).brand, "American Express"
        )

        self.testapp.post(
            "/billing/update-card",
            {
                "email": "test@remarkbox.com",
                "csrf_token": self.csrf,
                "action": "delete-card",
                "card_id": amex.id,
            },
        )

        customer = stripe.Customer.retrieve(self.test_user1.stripe_id)
        self.assertEqual(
            customer.sources.retrieve(customer.default_source).brand, "Visa"
        )

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
