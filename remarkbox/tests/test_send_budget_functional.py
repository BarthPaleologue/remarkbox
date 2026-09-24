"""First-contact send budget through remarkbox's web join, API login,
first verification & the drain script."""
import transaction
import unittest
import webtest

from unittest.mock import patch

from pyramid.paster import get_appsettings

from remarkbox.models import get_tm_session, get_or_create_user_by_email, get_user_by_email
from remarkbox.models.meta import Base
from remarkbox.models.send_budget import SendLedger, SendQueue


class TestSendBudget(unittest.TestCase):
    KEYS = ("app.send_budget.floor", "app.send_budget.per_conversion")
    EMAILS = ("first@example.com", "second@example.com", "web@example.com",
              "convert@example.com", "known@example.com", "5555550123@tmomail.net")

    @classmethod
    def setUpClass(cls):
        from remarkbox import main
        cls.settings = get_appsettings("test.ini")
        cls.app = main({}, **cls.settings)
        cls.session_factory = cls.app.registry["dbsession_factory"]
        cls.engine = cls.session_factory.kw["bind"]
        Base.metadata.create_all(bind=cls.engine)
        cls.tm = transaction.manager
        cls.dbsession = get_tm_session(cls.session_factory, cls.tm)

    @classmethod
    def tearDownClass(cls):
        cls.dbsession.close()
        Base.metadata.drop_all(bind=cls.engine)

    def _wipe(self):
        self.dbsession.query(SendLedger).delete()
        self.dbsession.query(SendQueue).delete()
        for email in self.EMAILS:
            user = get_user_by_email(self.dbsession, email)
            if user:
                self.dbsession.delete(user)
        self.dbsession.flush()
        self.tm.commit()

    def setUp(self):
        self.testapp = webtest.TestApp(self.app)
        self._wipe()
        self._saved = {k: self.app.registry.settings.get(k) for k in self.KEYS}
        self.app.registry.settings["app.send_budget.floor"] = "1"
        self.app.registry.settings["app.send_budget.per_conversion"] = "1"

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                self.app.registry.settings.pop(k, None)
            else:
                self.app.registry.settings[k] = v
        self.testapp.get("/log-out")
        self._wipe()

    def _api_login(self, email):
        with patch("smtplib.SMTP") as smtp:
            res = self.testapp.post_json("/api/v1/auth/login", {"email": email})
        return smtp.called, res.json

    def _queued(self):
        self.dbsession.expire_all()
        return [r.email for r in self.dbsession.query(SendQueue)]

    def _conversions(self):
        self.dbsession.expire_all()
        return self.dbsession.query(SendLedger).filter_by(kind="conversion").count()

    def _drain(self):
        from pyramid.scripting import prepare
        from remarkbox.scripts.drain_send_queue import run
        env = prepare(registry=self.app.registry)
        try:
            with patch("smtplib.SMTP") as smtp:
                sent = run(env["request"])
        finally:
            env["closer"]()
        return sent, smtp.call_count

    def _verify(self, email):
        user = get_or_create_user_by_email(self.dbsession, email)
        otp = user.new_password()
        self.dbsession.add(user)
        self.dbsession.flush()
        self.tm.commit()
        return self.testapp.post_json("/api/v1/auth/verify", {"email": email, "otp": otp}).json

    def test_api_over_budget_answers_sent_and_queues(self):
        sent, first = self._api_login("first@example.com")
        self.assertTrue(sent)
        sent, second = self._api_login("second@example.com")
        self.assertFalse(sent)
        self.assertEqual(second["status"], first["status"])
        self.assertEqual(self._queued(), ["second@example.com"])

    def test_web_join_over_budget_same_message(self):
        self._api_login("first@example.com")
        with patch("smtplib.SMTP") as smtp:
            res = self.testapp.post("/join-or-log-in", {"email": "web@example.com"}, status=302)
        self.assertFalse(smtp.called)
        self.assertIn(b"We just sent a link to web@example.com", res.follow().body)
        self.assertEqual(self._queued(), ["web@example.com"])

    def test_sms_gateway_gets_no_code(self):
        sent, body = self._api_login("5555550123@tmomail.net")
        self.assertFalse(sent)
        self.assertEqual(body["status"], "sent")
        self.assertEqual(self._queued(), [])

    def test_first_verification_grows_budget_and_drain_sends(self):
        self._api_login("first@example.com")
        self._api_login("second@example.com")
        self.assertEqual(self._drain(), (0, 0))
        self.assertEqual(self._verify("convert@example.com")["status"], "authenticated")
        self.assertEqual(self._conversions(), 1)
        self.assertEqual(self._drain(), (1, 1))
        self.assertEqual(self._queued(), [])

    def test_repeat_verification_is_not_a_conversion(self):
        self._verify("convert@example.com")
        self.testapp.get("/log-out")
        self._verify("convert@example.com")
        self.assertEqual(self._conversions(), 1)

    def test_failed_codes_never_raise_budget(self):
        self._api_login("first@example.com")
        for _ in range(3):
            self.testapp.post_json(
                "/api/v1/auth/verify", {"email": "first@example.com", "otp": "000000"},
                expect_errors=True,
            )
        self.assertEqual(self._conversions(), 0)

    def test_verified_login_ignores_budget(self):
        self._api_login("first@example.com")
        self._verify("known@example.com")
        self.testapp.get("/log-out")
        user = get_user_by_email(self.dbsession, "known@example.com")
        user.password_timestamp = 0
        self.dbsession.add(user)
        self.tm.commit()
        sent, _ = self._api_login("known@example.com")
        self.assertTrue(sent)
